-- DeiLaw 0.3.5rc8: automatically and safely claim old local feedback on Discord login.
-- This migration replaces only the legacy claim RPC and its Discord-review binder.
-- Install through migrations after the Discord feedback schema, not the old setup SQL.

CREATE OR REPLACE FUNCTION deilaw_internal.bind_discord_review()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = ''
AS $fn$
DECLARE
    v_uid uuid := auth.uid();
    v_name text;
    v_provider_id text;
BEGIN
    -- Admin moderation may modify another author's review without changing
    -- the author's verified Discord identity. This is NOT a legacy claim.
    IF TG_OP='UPDATE' AND public.deilaw_is_admin()
       AND NEW.owner_uid IS NOT DISTINCT FROM OLD.owner_uid
       AND (OLD.owner_uid IS DISTINCT FROM v_uid OR
            (NEW.review_text IS NOT DISTINCT FROM OLD.review_text
             AND NEW.rating IS NOT DISTINCT FROM OLD.rating)) THEN
        RETURN NEW;
    END IF;

    IF v_uid IS NULL THEN
        RAISE EXCEPTION 'Войдите через Discord для отправки отзыва';
    END IF;
    SELECT LEFT(BTRIM(REGEXP_REPLACE(
                 COALESCE(NULLIF(BTRIM(i.identity_data->>'full_name'),''),
                          NULLIF(BTRIM(i.identity_data->>'name'),''), 'Discord'),
                 '[[:cntrl:]]+',' ','g')),40),
           i.provider_id
      INTO v_name,v_provider_id
      FROM auth.identities i
     WHERE i.user_id=v_uid AND i.provider='discord'
     ORDER BY i.updated_at DESC LIMIT 1;
    IF v_provider_id IS NULL OR BTRIM(v_provider_id)='' THEN
        RAISE EXCEPTION 'Для отправки отзыва требуется Discord-аккаунт';
    END IF;

    IF TG_OP='INSERT' THEN
        NEW.owner_uid := v_uid;
        NEW.installation_id := 'discord:' || v_uid::text;
        NEW.installation_secret_hash := NULL;
        NEW.device_id := NULL;
        NEW.device_secret_hash := NULL;
    ELSIF OLD.owner_uid IS DISTINCT FROM v_uid THEN
        -- A normal user cannot update unowned/other-owned rows under RLS.
        -- This branch supports the privileged, secret-verified claim RPC.
        IF NEW.owner_uid IS DISTINCT FROM v_uid OR
           (OLD.owner_uid IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM auth.users u
                 WHERE u.id=OLD.owner_uid AND u.is_anonymous
           )) THEN
            RAISE EXCEPTION 'Нельзя изменять чужой отзыв';
        END IF;
    END IF;
    NEW.author_name := v_name;
    NEW.discord_user_id := v_provider_id;
    RETURN NEW;
END
$fn$;
REVOKE ALL ON FUNCTION deilaw_internal.bind_discord_review() FROM PUBLIC,anon,authenticated;

CREATE OR REPLACE FUNCTION public.deilaw_claim_legacy_ownership(
    p_installation_id text,p_installation_secret text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = ''
AS $fn$
DECLARE
    v_uid uuid := auth.uid();
    v_hash text;
    v_discord_name text;
    v_discord_id text;
    v_reviews int := 0;
    v_reports int := 0;
    v_messages int := 0;
    v_suggestions int := 0;
    v_review_conflicts int := 0;
BEGIN
    IF v_uid IS NULL OR LENGTH(COALESCE(p_installation_id,'')) < 1
       OR LENGTH(p_installation_id) > 100
       OR LENGTH(COALESCE(p_installation_secret,'')) < 20
       OR LENGTH(p_installation_secret) > 500 THEN
        RAISE EXCEPTION 'Invalid legacy ownership proof';
    END IF;
    -- Anonymous users are authenticated in Supabase; enforce Discord
    -- *identity* rather than checking the Postgres role or editable metadata.
    SELECT i.provider_id,
           LEFT(BTRIM(REGEXP_REPLACE(
             COALESCE(NULLIF(BTRIM(i.identity_data->>'full_name'),''),
                      NULLIF(BTRIM(i.identity_data->>'name'),''), 'Discord'),
             '[[:cntrl:]]+', ' ', 'g')),40)
      INTO v_discord_id,v_discord_name
      FROM auth.identities i JOIN auth.users u ON u.id=i.user_id
     WHERE i.user_id=v_uid AND i.provider='discord' AND NOT u.is_anonymous
     ORDER BY i.updated_at DESC LIMIT 1;
    IF v_discord_id IS NULL OR BTRIM(v_discord_id)='' THEN
        RAISE EXCEPTION 'Discord authorization required for ownership recovery';
    END IF;
    v_hash := ENCODE(extensions.digest(p_installation_secret,'sha256'),'hex');

    -- Never replace an existing account review with an older installation
    -- review. Keep the legacy record intact and report a conflict instead.
    SELECT COUNT(*) INTO v_review_conflicts
      FROM public.reviews r
     WHERE r.installation_id=p_installation_id
       AND r.installation_secret_hash=v_hash
       AND r.owner_uid IS DISTINCT FROM v_uid
       AND (r.owner_uid IS NULL OR EXISTS (
           SELECT 1 FROM auth.users u
           WHERE u.id=r.owner_uid AND u.is_anonymous))
       AND EXISTS (
           SELECT 1 FROM public.reviews other
           WHERE other.owner_uid=v_uid AND other.id<>r.id);

    UPDATE public.reviews r SET owner_uid=v_uid
     WHERE r.installation_id=p_installation_id
       AND r.installation_secret_hash=v_hash
       AND r.owner_uid IS DISTINCT FROM v_uid
       AND (r.owner_uid IS NULL OR EXISTS (
            SELECT 1 FROM auth.users u
            WHERE u.id=r.owner_uid AND u.is_anonymous))
       AND NOT EXISTS (
            SELECT 1 FROM public.reviews other
            WHERE other.owner_uid=v_uid AND other.id<>r.id);
    GET DIAGNOSTICS v_reviews=ROW_COUNT;

    -- Transfer reports previously unclaimed or claimed by an anonymous
    -- session from the same installation. Never steal a Discord-owned row.
    UPDATE public.bug_reports r SET owner_uid=v_uid, discord_name=v_discord_name, discord_user_id=v_discord_id
     WHERE r.installation_id=p_installation_id
       AND r.installation_secret_hash=v_hash
       AND r.owner_uid IS DISTINCT FROM v_uid
       AND (r.owner_uid IS NULL OR EXISTS (
            SELECT 1 FROM auth.users u
            WHERE u.id=r.owner_uid AND u.is_anonymous));
    GET DIAGNOSTICS v_reports=ROW_COUNT;

    UPDATE public.bug_report_messages m SET owner_uid=v_uid
      FROM public.bug_reports r
     WHERE m.report_id=r.id
       AND r.owner_uid=v_uid
       AND r.installation_id=p_installation_id
       AND r.installation_secret_hash=v_hash
       AND m.owner_uid IS DISTINCT FROM v_uid
       AND (m.owner_uid IS NULL OR EXISTS (
            SELECT 1 FROM auth.users u
            WHERE u.id=m.owner_uid AND u.is_anonymous));
    GET DIAGNOSTICS v_messages=ROW_COUNT;

    UPDATE public.suggestions s SET owner_uid=v_uid
     WHERE s.installation_id=p_installation_id
       AND s.installation_secret_hash=v_hash
       AND s.owner_uid IS DISTINCT FROM v_uid
       AND (s.owner_uid IS NULL OR EXISTS (
            SELECT 1 FROM auth.users u
            WHERE u.id=s.owner_uid AND u.is_anonymous));
    GET DIAGNOSTICS v_suggestions=ROW_COUNT;

    RETURN jsonb_build_object(
        'reviews',v_reviews,'reports',v_reports,
        'messages',v_messages,'suggestions',v_suggestions,
        'review_conflicts',v_review_conflicts);
END
$fn$;
REVOKE ALL ON FUNCTION public.deilaw_claim_legacy_ownership(text,text)
    FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.deilaw_claim_legacy_ownership(text,text)
    TO authenticated;
