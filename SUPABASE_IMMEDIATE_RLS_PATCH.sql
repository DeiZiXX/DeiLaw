-- Interim protection while existing Windows clients move to JWT owner binding.
-- Strong installation/device secret verification remains temporarily supported.
-- Permanently removes the unsafe "installation_secret_hash IS NULL" escape hatch.
begin;
do $deilaw$
declare
    r record;
    v_new text;
    v_count integer := 0;
begin
    if exists (
        select 1 from public.reviews where installation_secret_hash is null
    ) or exists (
        select 1 from public.bug_reports where installation_secret_hash is null
    ) or exists (
        select 1 from public.bug_report_messages where installation_secret_hash is null
    ) then
        raise exception 'Cannot lock down legacy NULL owners without migration';
    end if;
    for r in
        select schemaname,tablename,policyname,qual,with_check
          from pg_catalog.pg_policies
         where schemaname='public'
           and tablename in ('reviews','bug_reports','bug_report_messages')
           and (
             coalesce(qual,'') like '%installation_secret_hash IS NULL%'
             or coalesce(with_check,'') like '%installation_secret_hash IS NULL%'
           )
    loop
        if r.qual like '%installation_secret_hash IS NULL%' then
            v_new := replace(r.qual,'(installation_secret_hash IS NULL) OR ','');
            if v_new = r.qual then raise exception 'Unrecognized legacy expression'; end if;
            execute format('alter policy %I on %I.%I using (%s)',
               r.policyname,r.schemaname,r.tablename,v_new);
        end if;
        if r.with_check like '%installation_secret_hash IS NULL%' then
            v_new := replace(r.with_check,'(installation_secret_hash IS NULL) OR ','');
            if v_new = r.with_check then raise exception 'Unrecognized legacy CHECK'; end if;
            execute format('alter policy %I on %I.%I with check (%s)',
               r.policyname,r.schemaname,r.tablename,v_new);
        end if;
        v_count := v_count + 1;
    end loop;
    if v_count < 4 then
        raise exception 'Expected at least four vulnerable legacy policies, found %',v_count;
    end if;
end;
$deilaw$;
commit;
