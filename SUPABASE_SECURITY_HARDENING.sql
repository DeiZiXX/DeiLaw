-- DeiLaw SECURITY ROLLOUT (review before executing on production).
-- PREREQUISITES: enable Supabase Anonymous Sign-ins, deploy new client, take DB backup.
-- Run AFTER legacy SUPABASE_SETUP.sql and the admin/review setup migrations.
-- WARNING: old clients using installation headers will stop writing community data.
-- Do NOT re-run legacy SUPABASE_SETUP.sql after this migration.
begin;

create extension if not exists pgcrypto;

alter table public.reviews add column if not exists owner_uid uuid references auth.users(id);
alter table public.bug_reports add column if not exists owner_uid uuid references auth.users(id);
alter table public.bug_report_messages add column if not exists owner_uid uuid references auth.users(id);
alter table public.suggestions add column if not exists owner_uid uuid references auth.users(id);

alter table public.reviews alter column owner_uid set default auth.uid();
alter table public.bug_reports alter column owner_uid set default auth.uid();
alter table public.reviews alter column approved set default false;
alter table public.bug_report_messages alter column owner_uid set default auth.uid();
alter table public.suggestions alter column owner_uid set default auth.uid();

create index if not exists reviews_owner_uid_idx on public.reviews(owner_uid);
create unique index if not exists reviews_owner_uid_unique_idx
    on public.reviews(owner_uid) where owner_uid is not null;
create index if not exists bug_reports_owner_uid_idx on public.bug_reports(owner_uid);
create index if not exists bug_report_messages_owner_uid_idx on public.bug_report_messages(owner_uid);
create index if not exists suggestions_owner_uid_idx on public.suggestions(owner_uid);

-- Preserve the three existing approved reviews during the production transition.
-- New reviews remain unapproved by default and subject to server-side guards.

-- Clients can prove ownership of their own legacy data only once, by knowing
-- a long random installation secret. The raw secret is never stored in DB.
create or replace function public.deilaw_claim_legacy_ownership(
    p_installation_id text,
    p_installation_secret text
) returns jsonb
language plpgsql security definer set search_path = ''
as $$
declare
    v_uid uuid := auth.uid();
    v_hash text;
    v_reviews integer := 0;
    v_reports integer := 0;
begin
    if v_uid is null or length(coalesce(p_installation_id, '')) > 100
       or length(coalesce(p_installation_secret, '')) < 20
       or length(p_installation_secret) > 500 then
        raise exception 'Invalid owner claim';
    end if;
    v_hash := encode(extensions.digest(p_installation_secret, 'sha256'), 'hex');
    update public.reviews
       set owner_uid = v_uid
     where installation_id = p_installation_id
       and installation_secret_hash = v_hash
       and (owner_uid is null or owner_uid = v_uid);
    get diagnostics v_reviews = row_count;
    update public.bug_reports
       set owner_uid = v_uid
     where installation_id = p_installation_id
       and installation_secret_hash = v_hash
       and (owner_uid is null or owner_uid = v_uid);
    get diagnostics v_reports = row_count;
    update public.bug_report_messages msg
       set owner_uid = report.owner_uid
      from public.bug_reports report
     where msg.report_id = report.id
       and report.owner_uid = v_uid
       and (msg.owner_uid is null or msg.owner_uid = v_uid);
    update public.suggestions
       set owner_uid = v_uid
     where installation_id = p_installation_id
       and installation_secret_hash = v_hash
       and (owner_uid is null or owner_uid = v_uid);
    return jsonb_build_object('reviews', v_reviews, 'reports', v_reports);
end;
$$;
revoke all on function public.deilaw_claim_legacy_ownership(text, text) from public, anon;
grant execute on function public.deilaw_claim_legacy_ownership(text, text) to authenticated;

-- Retain admin RLS policies, replace all vulnerable owner/public policies.
drop policy if exists "deilaw_reviews_public_read" on public.reviews;
drop policy if exists "deilaw_reviews_public_projection_read" on public.reviews;
drop policy if exists "deilaw_reviews_owner_insert" on public.reviews;
drop policy if exists "deilaw_reviews_owner_update" on public.reviews;
drop policy if exists "deilaw_reviews_owner_select" on public.reviews;
drop policy if exists "deilaw_bug_owner_insert" on public.bug_reports;
drop policy if exists "deilaw_bug_owner_read" on public.bug_reports;
drop policy if exists "deilaw_bug_messages_owner_read" on public.bug_report_messages;
drop policy if exists "deilaw_bug_messages_owner_insert" on public.bug_report_messages;

create policy "deilaw_reviews_public_projection_read" on public.reviews
  for select to anon, authenticated using (approved = true);
create policy "deilaw_reviews_owner_select" on public.reviews
  for select to authenticated using (owner_uid = (select auth.uid()));
create policy "deilaw_reviews_owner_insert" on public.reviews
  for insert to authenticated with check (
    owner_uid = (select auth.uid()) and approved = false
    and helpful_count = 0 and rating between 1 and 5
    and char_length(author_name) between 1 and 40
    and char_length(review_text) between 3 and 2000
  );
create policy "deilaw_reviews_owner_update" on public.reviews
  for update to authenticated
  using (owner_uid = (select auth.uid()))
  with check (owner_uid = (select auth.uid()));
create policy "deilaw_bug_owner_insert" on public.bug_reports
  for insert to authenticated with check (
    owner_uid = (select auth.uid()) and status = 'new'
    and developer_reply is null and char_length(category) between 1 and 50
    and char_length(title) between 3 and 150
    and char_length(description) between 3 and 5000
  );
create policy "deilaw_bug_owner_read" on public.bug_reports
  for select to authenticated using (owner_uid = (select auth.uid()));
create policy "deilaw_bug_messages_owner_read" on public.bug_report_messages
  for select to authenticated using (owner_uid = (select auth.uid()));
create policy "deilaw_bug_messages_owner_insert" on public.bug_report_messages
  for insert to authenticated with check (
    sender = 'user' and owner_uid = (select auth.uid())
  );

-- Replace legacy header-based suggestion policies with JWT ownership.
-- Reserve status/developer fields for administrators.
drop policy if exists "deilaw_suggestions_owner_read" on public.suggestions;
drop policy if exists "deilaw_suggestions_owner_insert" on public.suggestions;
drop policy if exists "deilaw_suggestions_admin_read" on public.suggestions;
drop policy if exists "deilaw_suggestions_admin_update" on public.suggestions;
drop policy if exists "deilaw_admin_suggestions_read" on public.suggestions;
drop policy if exists "deilaw_admin_suggestions_update" on public.suggestions;
create policy "deilaw_suggestions_owner_read" on public.suggestions
  for select to authenticated using (owner_uid = (select auth.uid()));
create policy "deilaw_suggestions_owner_insert" on public.suggestions
  for insert to authenticated with check (
    owner_uid = (select auth.uid()) and status = 'new'
    and developer_reply is null
    and char_length(author_name) between 1 and 40
    and char_length(title) between 3 and 150
    and char_length(suggestion_text) between 5 and 5000
  );
create policy "deilaw_suggestions_admin_read" on public.suggestions
  for select to authenticated using (public.deilaw_is_admin());
create policy "deilaw_suggestions_admin_update" on public.suggestions
  for update to authenticated using (public.deilaw_is_admin())
  with check (public.deilaw_is_admin());

create or replace function public.deilaw_guard_suggestion_changes()
returns trigger language plpgsql set search_path = ''
as $$
begin
    if current_user = 'authenticated'
       and not coalesce(public.deilaw_is_admin(), false) then
        if tg_op = 'INSERT' then
            new.owner_uid := auth.uid();
            new.status := 'new';
            new.developer_reply := null;
            new.developer_reply_at := null;
        else
            raise exception 'Only developers can update suggestions';
        end if;
    end if;
    return new;
end;
$$;
drop trigger if exists deilaw_guard_suggestion_changes_trigger on public.suggestions;
create trigger deilaw_guard_suggestion_changes_trigger
before insert or update on public.suggestions for each row
execute function public.deilaw_guard_suggestion_changes();

-- Existing trigger fills message owner from parent, including admin replies.
create or replace function public.deilaw_fill_bug_message_owner()
returns trigger language plpgsql security definer set search_path = ''
as $$
declare v_owner uuid;
begin
    select owner_uid into v_owner from public.bug_reports where id = new.report_id;
    if not found then raise exception 'Bug report not found'; end if;
    new.owner_uid := v_owner;
    return new;
end;
$$;

-- Authenticated users must not mutate review moderation or identity columns.
-- Admins keep their privileges through existing deilaw_is_admin() policies.
create or replace function public.deilaw_guard_review_changes()
returns trigger language plpgsql set search_path = ''
as $$
begin
    if current_user = 'authenticated'
       and not coalesce(public.deilaw_is_admin(), false) then
        if tg_op = 'INSERT' then
            new.owner_uid := auth.uid();
            new.approved := false;
            new.helpful_count := 0;
        elsif (
            to_jsonb(new) - 'author_name' - 'rating' - 'review_text' -
            'app_version' - 'updated_at'
        ) is distinct from (
            to_jsonb(old) - 'author_name' - 'rating' - 'review_text' -
            'app_version' - 'updated_at'
        ) then
            raise exception 'Review owner cannot modify protected fields';
        end if;
    end if;
    return new;
end;
$$;
drop trigger if exists deilaw_guard_review_changes_trigger on public.reviews;
create trigger deilaw_guard_review_changes_trigger
before insert or update on public.reviews for each row
execute function public.deilaw_guard_review_changes();

create or replace function public.deilaw_guard_bug_report_changes()
returns trigger language plpgsql set search_path = ''
as $$
begin
    if current_user = 'authenticated' and not coalesce(public.deilaw_is_admin(), false) then
        if tg_op = 'INSERT' then
            new.owner_uid := auth.uid();
            new.status := 'new';
            new.developer_reply := null;
            new.internal_notes := null;
            new.fixed_in_version := null;
        else
            raise exception 'Only developers can update bug reports';
        end if;
    end if;
    return new;
end;
$$;
drop trigger if exists deilaw_guard_bug_report_changes_trigger on public.bug_reports;
create trigger deilaw_guard_bug_report_changes_trigger
before insert or update on public.bug_reports for each row
execute function public.deilaw_guard_bug_report_changes();

revoke all on public.reviews, public.bug_reports, public.bug_report_messages
  from anon, authenticated;
revoke all on public.suggestions from anon, authenticated;
grant select, insert, update on public.reviews to authenticated;
grant select, insert, update on public.bug_reports to authenticated;
grant select, insert on public.bug_report_messages to authenticated;
grant select, insert, update on public.suggestions to authenticated;

-- Expose approved reviews through a restricted view, never raw private columns.
create or replace view public.deilaw_public_reviews
with (security_barrier = true, security_invoker = true)
as select id, author_name, rating, review_text, app_version,
          helpful_count, developer_reply, developer_reply_at,
          created_at, updated_at
from public.reviews where approved = true;
revoke all on public.deilaw_public_reviews from public;
grant select on public.deilaw_public_reviews to anon, authenticated;

-- Invoker view requires a SELECT policy on the underlying table. Grant only
-- non-private columns; never grant installation IDs / secret hashes to users.
revoke select on public.reviews from anon, authenticated;
grant select (id,author_name,rating,review_text,app_version,helpful_count,
  developer_reply,developer_reply_at,created_at,updated_at,approved)
  on public.reviews to anon;
grant select (id,author_name,rating,review_text,app_version,helpful_count,
  developer_reply,developer_reply_at,created_at,updated_at,approved,owner_uid)
  on public.reviews to authenticated;

-- Treat old SECURITY DEFINER trigger helpers as triggers only.
revoke execute on function public.deilaw_fill_bug_message_owner() from public, anon, authenticated;
revoke execute on function public.deilaw_touch_bug_report_from_message() from public, anon, authenticated;
revoke execute on function public.deilaw_bug_report_reply_to_chat() from public, anon, authenticated;
revoke execute on function public.deilaw_bug_report_status_to_chat() from public, anon, authenticated;
alter function public.deilaw_touch_bug_report() set search_path = '';

commit;
