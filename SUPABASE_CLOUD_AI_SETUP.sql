-- DeiLaw Cloud AI — rate limiting storage and atomic quota claim.
-- Run this once in Supabase SQL Editor.

create table if not exists public.deilaw_ai_daily_usage (
    device_id text not null,
    usage_date date not null default current_date,
    request_count integer not null default 0 check (request_count >= 0),
    updated_at timestamptz not null default now(),
    primary key (device_id, usage_date)
);

alter table public.deilaw_ai_daily_usage enable row level security;

-- No client-side RLS policies are created. The table is used only by the
-- Edge Function through a server-side secret/service-role key.
revoke all on table public.deilaw_ai_daily_usage from anon, authenticated;

create or replace function public.deilaw_claim_ai_request(
    p_device_id text,
    p_daily_limit integer default 100
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_used integer;
    v_limit integer := greatest(1, least(coalesce(p_daily_limit, 100), 1000));
begin
    if p_device_id is null or p_device_id !~ '^[a-f0-9]{64}$' then
        return jsonb_build_object(
            'allowed', false,
            'used', 0,
            'remaining', 0,
            'error', 'invalid_device_id'
        );
    end if;

    insert into public.deilaw_ai_daily_usage (
        device_id,
        usage_date,
        request_count,
        updated_at
    ) values (
        p_device_id,
        current_date,
        0,
        now()
    )
    on conflict (device_id, usage_date) do nothing;

    select request_count
      into v_used
      from public.deilaw_ai_daily_usage
     where device_id = p_device_id
       and usage_date = current_date
     for update;

    if coalesce(v_used, 0) >= v_limit then
        return jsonb_build_object(
            'allowed', false,
            'used', coalesce(v_used, 0),
            'remaining', 0
        );
    end if;

    update public.deilaw_ai_daily_usage
       set request_count = request_count + 1,
           updated_at = now()
     where device_id = p_device_id
       and usage_date = current_date
     returning request_count into v_used;

    return jsonb_build_object(
        'allowed', true,
        'used', v_used,
        'remaining', greatest(0, v_limit - v_used)
    );
end;
$$;

revoke all on function public.deilaw_claim_ai_request(text, integer) from public, anon, authenticated;
grant execute on function public.deilaw_claim_ai_request(text, integer) to service_role;

-- v2 replaces the spoofable device-id limit. Deploy this BEFORE Edge v2.
-- Keep legacy storage for audit/history, but revoke the legacy RPC execute
-- permission so the old Edge implementation cannot spend more OpenAI credits.
revoke execute on function public.deilaw_claim_ai_request(text, integer) from service_role;

create table if not exists public.deilaw_ai_user_daily_usage (
    user_id uuid not null references auth.users(id) on delete cascade,
    usage_date date not null default (now() at time zone 'utc')::date,
    request_count integer not null default 0 check (request_count >= 0),
    updated_at timestamptz not null default now(),
    primary key (user_id, usage_date)
);
create table if not exists public.deilaw_ai_global_daily_usage (
    usage_date date primary key,
    request_count integer not null default 0 check (request_count >= 0),
    updated_at timestamptz not null default now()
);
alter table public.deilaw_ai_user_daily_usage enable row level security;
alter table public.deilaw_ai_global_daily_usage enable row level security;
revoke all on public.deilaw_ai_user_daily_usage, public.deilaw_ai_global_daily_usage
  from anon, authenticated;

-- Serialize claims across all users: both per-user and global counters move
-- in ONE transaction, with no race conditions at the daily cap.
create or replace function public.deilaw_claim_ai_request_v2(
    p_user_id uuid, p_user_limit integer default 12, p_global_limit integer default 250
) returns jsonb
language plpgsql security definer set search_path = ''
as $$
declare
    v_day date := (now() at time zone 'utc')::date;
    v_user_count integer;
    v_global_count integer;
    v_user_limit integer := greatest(1, least(coalesce(p_user_limit, 12), 50));
    v_global_limit integer := greatest(1, least(coalesce(p_global_limit, 250), 2000));
begin
    if p_user_id is null then
        return jsonb_build_object('allowed', false, 'remaining', 0);
    end if;
    perform pg_catalog.pg_advisory_xact_lock(73642, 1001);
    insert into public.deilaw_ai_global_daily_usage(usage_date)
        values (v_day) on conflict do nothing;
    insert into public.deilaw_ai_user_daily_usage(user_id, usage_date)
        values (p_user_id, v_day) on conflict do nothing;
    select request_count into v_user_count
      from public.deilaw_ai_user_daily_usage
     where user_id = p_user_id and usage_date = v_day;
    select request_count into v_global_count
      from public.deilaw_ai_global_daily_usage where usage_date = v_day;
    if v_user_count >= v_user_limit or v_global_count >= v_global_limit then
        return jsonb_build_object('allowed', false, 'remaining', 0,
          'global_exhausted', v_global_count >= v_global_limit);
    end if;
    update public.deilaw_ai_user_daily_usage
       set request_count = request_count + 1, updated_at = now()
     where user_id = p_user_id and usage_date = v_day;
    update public.deilaw_ai_global_daily_usage
       set request_count = request_count + 1, updated_at = now()
     where usage_date = v_day;
    return jsonb_build_object('allowed', true,
      'remaining', greatest(0, v_user_limit - v_user_count - 1),
      'global_remaining', greatest(0, v_global_limit - v_global_count - 1));
end;
$$;
revoke all on function public.deilaw_claim_ai_request_v2(uuid, integer, integer)
  from public, anon, authenticated;
grant execute on function public.deilaw_claim_ai_request_v2(uuid, integer, integer)
  to service_role;
