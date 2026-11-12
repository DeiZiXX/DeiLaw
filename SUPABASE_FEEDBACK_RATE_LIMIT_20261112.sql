-- Abuse-resistant write limits. Do not rerun the legacy setup SQL files.
-- Rules apply only to user submissions, not developer replies.
-- The authenticated role includes Supabase anonymous users; each quota uses
-- the actual authenticated UID, not caller-provided device headers.

CREATE OR REPLACE FUNCTION deilaw_internal.rate_limit_reports()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $fn$
DECLARE v_uid uuid := auth.uid(); v_count integer;
BEGIN
  IF v_uid IS NULL THEN RETURN NEW; END IF;
  PERFORM pg_catalog.pg_advisory_xact_lock(120209, pg_catalog.hashtext(v_uid::text));
  SELECT COUNT(*) INTO v_count FROM public.bug_reports
   WHERE owner_uid=v_uid AND created_at >= pg_catalog.now()-INTERVAL '24 hours';
  IF v_count >= 10 THEN
    RAISE EXCEPTION 'Daily report limit reached. Try again later.' USING ERRCODE='P0001';
  END IF;
  NEW.created_at := pg_catalog.now();
  RETURN NEW;
END $fn$;
REVOKE ALL ON FUNCTION deilaw_internal.rate_limit_reports() FROM PUBLIC,anon,authenticated;
DROP TRIGGER IF EXISTS deilaw_rate_limit_reports ON public.bug_reports;
CREATE TRIGGER deilaw_rate_limit_reports
BEFORE INSERT ON public.bug_reports FOR EACH ROW
EXECUTE FUNCTION deilaw_internal.rate_limit_reports();

CREATE OR REPLACE FUNCTION deilaw_internal.rate_limit_messages()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $fn$
DECLARE v_uid uuid := auth.uid(); v_report_owner uuid; v_count integer;
BEGIN
  IF v_uid IS NULL OR NEW.sender IS DISTINCT FROM 'user' THEN
    RETURN NEW;
  END IF;
  -- Parent owner comes from the authenticated account and cannot be forged.
  SELECT owner_uid INTO v_report_owner FROM public.bug_reports WHERE id=NEW.report_id;
  IF v_report_owner IS DISTINCT FROM v_uid THEN
    RAISE EXCEPTION 'Report does not belong to this account';
  END IF;
  PERFORM pg_catalog.pg_advisory_xact_lock(120210, pg_catalog.hashtext(v_uid::text));
  SELECT COUNT(*) INTO v_count FROM public.bug_report_messages
  WHERE owner_uid=v_uid AND sender='user'
    AND created_at >= pg_catalog.now()-INTERVAL '24 hours';
  IF v_count >= 100 THEN
    RAISE EXCEPTION 'Daily message limit reached. Try again later.' USING ERRCODE='P0001';
  END IF;
  NEW.created_at := pg_catalog.now();
  RETURN NEW;
END $fn$;
REVOKE ALL ON FUNCTION deilaw_internal.rate_limit_messages() FROM PUBLIC,anon,authenticated;
DROP TRIGGER IF EXISTS deilaw_rate_limit_messages ON public.bug_report_messages;
CREATE TRIGGER deilaw_rate_limit_messages
BEFORE INSERT ON public.bug_report_messages FOR EACH ROW
EXECUTE FUNCTION deilaw_internal.rate_limit_messages();

CREATE OR REPLACE FUNCTION deilaw_internal.rate_limit_suggestions()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $fn$
DECLARE v_uid uuid := auth.uid(); v_count integer;
BEGIN
  IF v_uid IS NULL THEN RETURN NEW; END IF;
  PERFORM pg_catalog.pg_advisory_xact_lock(120211,pg_catalog.hashtext(v_uid::text));
  SELECT COUNT(*) INTO v_count FROM public.suggestions
   WHERE owner_uid=v_uid AND created_at >= pg_catalog.now()-INTERVAL '24 hours';
  IF v_count >= 10 THEN
    RAISE EXCEPTION 'Daily suggestion limit reached. Try again later.' USING ERRCODE='P0001';
  END IF;
  NEW.created_at := pg_catalog.now();
  RETURN NEW;
END $fn$;
REVOKE ALL ON FUNCTION deilaw_internal.rate_limit_suggestions() FROM PUBLIC,anon,authenticated;
DROP TRIGGER IF EXISTS deilaw_rate_limit_suggestions ON public.suggestions;
CREATE TRIGGER deilaw_rate_limit_suggestions
BEFORE INSERT ON public.suggestions FOR EACH ROW
EXECUTE FUNCTION deilaw_internal.rate_limit_suggestions();
