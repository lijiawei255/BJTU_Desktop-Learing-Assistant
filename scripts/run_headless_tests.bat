@echo off
REM Windows-only test runner. Production and RPi configuration is untouched.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0\.."
set "INCLUDE_API="
set "VERBOSE=-q"
set "PYTHONIOENCODING=utf-8"

:parse_args
if "%~1"=="" goto :run_tests
if "%~1"=="--api" goto :enable_api
if "%~1"=="-v" goto :verbose
if "%~1"=="--help" goto :help
echo Unknown option: %~1
exit /b 2

:enable_api
set "INCLUDE_API=--run-api"
shift
goto :parse_args

:verbose
set "VERBOSE=-v"
shift
goto :parse_args

:help
echo Usage: scripts\run_headless_tests.bat [--api] [-v]
echo Default: offline tests only. --api enables real cloud requests.
exit /b 0

:run_tests
if defined INCLUDE_API (
    echo Cloud API tests enabled. A real API key is required; calls may incur charges.
) else (
    echo Running offline PC tests. API and real hardware tests are not enabled.
)
call python -m pytest tests %VERBOSE% --tb=short -m "not hardware" %INCLUDE_API%
set "RESULT=%ERRORLEVEL%"
if "%RESULT%"=="0" (
    echo No unexpected test failures. Review the XFAIL and SKIP summary above.
) else (
    echo Test run failed with exit code %RESULT%.
)
exit /b %RESULT%
