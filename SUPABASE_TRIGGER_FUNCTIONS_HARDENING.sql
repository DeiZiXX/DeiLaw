-- Non-breaking hardening for internal trigger helpers and admin lookup.
begin;
revoke execute on function public.deilaw_fill_bug_message_owner() from public, anon, authenticated;
revoke execute on function public.deilaw_touch_bug_report_from_message() from public, anon, authenticated;
revoke execute on function public.deilaw_bug_report_reply_to_chat() from public, anon, authenticated;
revoke execute on function public.deilaw_bug_report_status_to_chat() from public, anon, authenticated;

-- RLS references deilaw_is_admin() for authenticated admins. It must remain
-- executable by authenticated, but never by unauthenticated REST clients.
revoke execute on function public.deilaw_is_admin() from public, anon;
grant execute on function public.deilaw_is_admin() to authenticated;
-- Its only query selects public.deilaw_admins, whose RLS already limits
-- authenticated users to their own row. SECURITY DEFINER is unnecessary.
alter function public.deilaw_is_admin() security invoker;

alter function public.deilaw_touch_bug_report() set search_path = '';
commit;
