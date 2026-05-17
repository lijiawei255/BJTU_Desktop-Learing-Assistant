@echo off
REM run_headless_tests.bat — Windows PC 无头集成测试运行器
REM 用法: scripts\run_headless_tests.bat [--api] [-v]
setlocal enabledelayedexpansion

cd /d "%~dp0\.."

set ENABLE_MOCK=true

echo ============================================
echo   Amiya 无头集成测试 (Windows)
echo   日期: %date% %time%
echo ============================================

REM ── 解析参数 ──
set INCLUDE_API=false
set VERBOSE=
:parse_args
if "%~1"=="" goto :done_parsing
if "%~1"=="--api" set INCLUDE_API=true
if "%~1"=="-v" set VERBOSE=-v
shift
goto :parse_args
:done_parsing

REM ── 阶段1: 已有测试套件回归 ──
echo.
echo [1/3] 运行已有测试套件（回归检查）...
python -m pytest tests/test_m5_devices.py tests/test_m7_m8.py tests/test_m9_wake_word.py %VERBOSE% -x --tb=short -q
if %ERRORLEVEL% NEQ 0 (
    echo   ❌ 已有测试: 失败
    set FAILED=1
) else (
    echo   ✅ 已有测试: 通过
)

REM ── 阶段2: 无头集成测试（无API） ──
echo.
echo [2/3] 运行无头集成测试（无需API）...
python -m pytest tests/test_headless_integration.py %VERBOSE% -x --tb=short -q -m "not api"
if %ERRORLEVEL% NEQ 0 (
    echo   ❌ 无头集成测试: 失败
    set FAILED=1
) else (
    echo   ✅ 无头集成测试: 通过
)

REM ── 阶段3: API依赖测试 ──
echo.
echo [3/3] 运行API依赖测试...
if "%INCLUDE_API%"=="true" (
    python -m pytest tests/test_m2_m4_pipeline.py tests/test_headless_integration.py %VERBOSE% --tb=long -q -m "api"
    if %ERRORLEVEL% NEQ 0 (
        echo   ⚠️ API依赖测试: 部分失败
    ) else (
        echo   ✅ API依赖测试: 通过
    )
) else (
    echo   ⏭️ 跳过 — 使用 --api 参数以启用
)

echo.
echo ============================================
echo   测试完成。
echo ============================================
