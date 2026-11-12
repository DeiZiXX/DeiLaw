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
