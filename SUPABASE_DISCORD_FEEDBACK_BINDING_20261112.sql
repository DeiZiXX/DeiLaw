-- DeiLaw 0.3.5rc7 / Support Center 0.2.3
-- Run ONCE after the JWT owner_uid RLS migration; production deployment tracked
-- separately. Existing reviews/reports are intentionally preserved.
-- New feedback/report submission requires a Supabase Auth account with an
-- actual Discord identity in auth.identities; client-supplied nicknames are ignored.

CREATE SCHEMA IF NOT EXISTS deilaw_internal;
REVOKE ALL ON SCHEMA deilaw_internal FROM PUBLIC, anon, authenticated;

ALTER TABLE public.reviews ADD COLUMN IF NOT EXISTS discord_user_id text;
ALTER TABLE public.bug_reports ADD COLUMN IF NOT EXISTS discord_user_id text;
ALTER TABLE public.bug_reports ADD COLUMN IF NOT EXISTS discord_name text;

-- The same Discord account cannot create a second review with another auth UID.
CREATE UNIQUE INDEX IF NOT EXISTS reviews_discord_user_id_unique_idx
ON public.reviews (discord_user_id) WHERE discord_user_id IS NOT NULL;

CREATE OR REPLACE FUNCTION deilaw_internal.bind_discord_review()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = ''
AS $fn$
DECLARE
  v_uid uuid := auth.uid();
  v_name text;
  v_provider_id text;
BEGIN
  IF TG_OP = 'UPDATE' AND public.deilaw_is_admin() THEN
    -- Developer moderation (approval/reply) must not rewrite a different
    -- user's identity. But editing the developer's own review text/rating
    -- must still bind their verified Discord profile.
    IF OLD.owner_uid IS DISTINCT FROM auth.uid()
       OR (NEW.review_text IS NOT DISTINCT FROM OLD.review_text
           AND NEW.rating IS NOT DISTINCT FROM OLD.rating) THEN
      RETURN NEW;
    END IF;
  END IF;
  IF v_uid IS NULL THEN
    RAISE EXCEPTION 'Войдите через Discord для отправки отзыва';
  END IF;
  SELECT
    LEFT(BTRIM(REGEXP_REPLACE(
      COALESCE(NULLIF(BTRIM(i.identity_data->>'full_name'), ''),
               NULLIF(BTRIM(i.identity_data->>'name'), ''),
               'Discord'), '[[:cntrl:]]+', ' ', 'g')),
      40),
    i.provider_id
  INTO v_name, v_provider_id
  FROM auth.identities i
  WHERE i.user_id = v_uid AND i.provider = 'discord'
  ORDER BY i.updated_at DESC
  LIMIT 1;
  IF v_provider_id IS NULL OR BTRIM(v_provider_id) = '' THEN
    RAISE EXCEPTION 'Для отправки отзыва требуется подтверждённый Discord-аккаунт';
  END IF;
  IF TG_OP = 'INSERT' THEN
    NEW.owner_uid := v_uid;
    NEW.installation_id := 'discord:' || v_uid::text;
    NEW.installation_secret_hash := NULL;
    NEW.device_id := NULL;
    NEW.device_secret_hash := NULL;
  ELSIF OLD.owner_uid IS DISTINCT FROM v_uid THEN
    RAISE EXCEPTION 'Нельзя изменять чужой отзыв';
  END IF;
  NEW.author_name := v_name;
  NEW.discord_user_id := v_provider_id;
  RETURN NEW;
END
$fn$;
REVOKE ALL ON FUNCTION deilaw_internal.bind_discord_review() FROM PUBLIC, anon, authenticated;
DROP TRIGGER IF EXISTS deilaw_bind_discord_review_trigger ON public.reviews;
CREATE TRIGGER deilaw_bind_discord_review_trigger
BEFORE INSERT OR UPDATE ON public.reviews
FOR EACH ROW EXECUTE FUNCTION deilaw_internal.bind_discord_review();

CREATE OR REPLACE FUNCTION deilaw_internal.bind_discord_report()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = ''
AS $fn$
DECLARE
  v_uid uuid := auth.uid();
  v_name text;
  v_provider_id text;
BEGIN
  IF v_uid IS NULL THEN
    RAISE EXCEPTION 'Войдите через Discord для отправки репорта';
  END IF;
  SELECT
    LEFT(BTRIM(REGEXP_REPLACE(
      COALESCE(NULLIF(BTRIM(i.identity_data->>'full_name'), ''),
               NULLIF(BTRIM(i.identity_data->>'name'), ''),
               'Discord'), '[[:cntrl:]]+', ' ', 'g')),
      40),
    i.provider_id
  INTO v_name, v_provider_id
  FROM auth.identities i
  WHERE i.user_id = v_uid AND i.provider = 'discord'
  ORDER BY i.updated_at DESC
  LIMIT 1;
  IF v_provider_id IS NULL OR BTRIM(v_provider_id) = '' THEN
    RAISE EXCEPTION 'Для отправки репорта требуется подтверждённый Discord-аккаунт';
  END IF;
  NEW.owner_uid := v_uid;
  NEW.discord_name := v_name;
  NEW.discord_user_id := v_provider_id;
  NEW.installation_id := 'discord:' || v_uid::text;
  NEW.installation_secret_hash := NULL;
  RETURN NEW;
END
$fn$;
REVOKE ALL ON FUNCTION deilaw_internal.bind_discord_report() FROM PUBLIC, anon, authenticated;
DROP TRIGGER IF EXISTS deilaw_bind_discord_report_trigger ON public.bug_reports;
CREATE TRIGGER deilaw_bind_discord_report_trigger
BEFORE INSERT ON public.bug_reports
FOR EACH ROW EXECUTE FUNCTION deilaw_internal.bind_discord_report();

-- Server-only discord_user_id is set by our trigger. The existing ownership
-- guard must allow this trigger-generated field while rejecting all other
-- protected fields and user attempts to alter developer/moderation data.
CREATE OR REPLACE FUNCTION public.deilaw_guard_review_changes()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $fn$
BEGIN
  IF current_user = 'authenticated' AND NOT COALESCE(public.deilaw_is_admin(), false) THEN
    IF TG_OP = 'INSERT' THEN
      NEW.owner_uid := auth.uid();
      NEW.approved := false;
      NEW.helpful_count := 0;
      NEW.developer_reply := NULL;
      NEW.developer_reply_at := NULL;
    ELSIF (to_jsonb(NEW)-'author_name'-'discord_user_id'-'rating'-'review_text'-'app_version'-'updated_at')
      IS DISTINCT FROM
      (to_jsonb(OLD)-'author_name'-'discord_user_id'-'rating'-'review_text'-'app_version'-'updated_at') THEN
      RAISE EXCEPTION 'Protected review fields cannot be changed';
    END IF;
  END IF;
  RETURN NEW;
END
$fn$;
REVOKE EXECUTE ON FUNCTION public.deilaw_guard_review_changes() FROM PUBLIC, anon, authenticated;

-- Editing a published review sends the revised text back to moderation.
CREATE OR REPLACE FUNCTION public.deilaw_review_moderation_guard()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $fn$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF current_user IN ('anon','authenticated') AND NOT COALESCE(public.deilaw_is_admin(), false) THEN
      NEW.approved := false;
      NEW.helpful_count := 0;
      NEW.developer_reply := NULL;
      NEW.developer_reply_at := NULL;
    END IF;
  ELSE
    -- Even a developer updating their own review needs fresh moderation.
    IF NEW.review_text IS DISTINCT FROM OLD.review_text
       OR NEW.rating IS DISTINCT FROM OLD.rating THEN
      NEW.approved := false;
    END IF;
    IF current_user IN ('anon','authenticated') AND NOT COALESCE(public.deilaw_is_admin(), false) THEN
      IF NEW.review_text IS NOT DISTINCT FROM OLD.review_text
         AND NEW.rating IS NOT DISTINCT FROM OLD.rating THEN
        NEW.approved := OLD.approved;
      END IF;
      NEW.helpful_count := OLD.helpful_count;
      NEW.developer_reply := OLD.developer_reply;
      NEW.developer_reply_at := OLD.developer_reply_at;
    END IF;
  END IF;
  RETURN NEW;
END
$fn$;
REVOKE EXECUTE ON FUNCTION public.deilaw_review_moderation_guard() FROM PUBLIC, anon, authenticated;

-- No SELECT of reviews.discord_user_id is granted to anon/authenticated;
-- current table-level UPDATE grants are constrained by the server triggers.
-- The admin application displays the safe public nickname on reviews.

-- Do NOT drop old rows, nor change old approved status. Existing posts without
-- discord_user_id remain readable and can be claimed via prior secret-backed RPC.
