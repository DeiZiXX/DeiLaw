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
