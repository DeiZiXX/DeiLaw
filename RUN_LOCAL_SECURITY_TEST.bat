@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

where docker >nul 2>&1
if errorlevel 1 (
    echo Docker Desktop is not installed. See docs\LOCAL_SECURITY_TEST.md
    goto failed
)
docker info >nul 2>&1
if errorlevel 1 (
    echo Please launch Docker Desktop and wait until it is ready.
    goto failed
)
where supabase >nul 2>&1
if errorlevel 1 (
    echo Supabase CLI is not installed. See docs\LOCAL_SECURITY_TEST.md
    goto failed
)
where python >nul 2>&1
if errorlevel 1 (
    echo Python is not available in PATH.
    goto failed
)

echo Starting ISOLATED local Supabase. Production will NOT be changed.
supabase start
if errorlevel 1 goto failed

echo Applying LEGACY setup to LOCAL database only...
supabase db query --local --file SUPABASE_SETUP.sql
if errorlevel 1 goto failed

echo Applying synthetic LOCAL compatibility fixture...
supabase db query --local --file supabase/tests/local_compat.sql
if errorlevel 1 goto failed

echo Applying proposed RLS hardening to LOCAL database only...
supabase db query --local --file SUPABASE_SECURITY_HARDENING.sql
if errorlevel 1 goto failed

echo.
echo Copy the LOCAL Publishable key from the following output:
supabase status
if errorlevel 1 goto failed

echo.
python scripts/test_local_rls.py
if errorlevel 1 goto failed

echo.
echo Local security regression checks PASSED.
echo The next run must use a fresh local test database; do not use remote reset.
pause
exit /b 0

:failed
echo.
echo Test setup STOPPED or tests FAILED. No production changes were requested.
echo Read docs\LOCAL_SECURITY_TEST.md for details.
pause
exit /b 1
