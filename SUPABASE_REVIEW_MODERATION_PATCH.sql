-- Safe interim moderation for existing (header-authenticated) client versions.
-- A malicious desktop client can never publish or vote itself. Existing
-- reviews retain their approval status; NEW reviews require admin approval.
begin;
alter table public.reviews alter column approved set default false;

create or replace function public.deilaw_review_moderation_guard()
returns trigger language plpgsql security invoker set search_path = ''
as $$
begin
    if current_user in ('anon', 'authenticated')
       and not coalesce(public.deilaw_is_admin(), false) then
        if tg_op = 'INSERT' then
            new.approved := false;
            new.helpful_count := 0;
            new.developer_reply := null;
            new.developer_reply_at := null;
        else
            -- Legacy clients upsert their review with approved=true;
            -- ignore these untrusted fields rather than breaking editing.
            new.approved := old.approved;
            new.helpful_count := old.helpful_count;
            new.developer_reply := old.developer_reply;
            new.developer_reply_at := old.developer_reply_at;
        end if;
    end if;
    return new;
end;
$$;
drop trigger if exists deilaw_review_moderation_guard_trigger on public.reviews;
create trigger deilaw_review_moderation_guard_trigger
before insert or update on public.reviews for each row
execute function public.deilaw_review_moderation_guard();
revoke execute on function public.deilaw_review_moderation_guard()
    from public, anon, authenticated;
commit;
