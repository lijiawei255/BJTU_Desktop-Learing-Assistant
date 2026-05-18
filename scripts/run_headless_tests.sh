#!/bin/bash
# run_headless_tests.sh — 树莓派/ Linux 无头集成测试运行器
# 用法: bash scripts/run_headless_tests.sh [--api] [-v]
#
# 阶段1: 运行已有测试套件（回归检查）
# 阶段2: 运行无头集成测试（跳过API依赖测试）
# 阶段3: 运行API依赖测试（需要ALIBABA_API_KEY）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# ── 激活虚拟环境 ──
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
elif [ -f "env/bin/activate" ]; then
    source env/bin/activate
else
    echo "WARNING: No virtualenv found, using system Python"
fi

# ── 确保 .env 存在 ──
if [ ! -f ".env" ]; then
    echo "ERROR: .env file not found. Copy .env.example to .env and fill in your API key."
    exit 1
fi

# ── 强制 Mock + 无头模式 ──
export ENABLE_MOCK=true

# ── 解析参数 ──
INCLUDE_API=false
VERBOSE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --api) INCLUDE_API=true ;;
        --verbose|-v) VERBOSE="-v" ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
    shift
done

echo "============================================"
echo "  Amiya 无头集成测试"
echo "  日期: $(date)"
echo "  主机: $(hostname)"
echo "  Python: $(python3 --version 2>/dev/null || python --version 2>/dev/null || echo 'unknown')"
echo "  Mock模式: ENABLED"
echo "============================================"

PASSED=0
FAILED=0

# ── 阶段1: 已有测试套件回归 ──
echo ""
echo "[1/3] 运行已有测试套件（回归检查）..."
if python -m pytest tests/test_m5_devices.py tests/test_m7_m8.py tests/test_m9_wake_word.py \
    $VERBOSE -x --tb=short -q 2>&1; then
    echo "  ✅ 已有测试: 通过"
    PASSED=$((PASSED + 1))
else
    echo "  ❌ 已有测试: 失败"
    FAILED=$((FAILED + 1))
fi

# ── 阶段2: 无头集成测试（无API） ──
echo ""
echo "[2/3] 运行无头集成测试（无需API）..."
if python -m pytest tests/test_headless_integration.py \
    $VERBOSE -x --tb=short -q -m "not api" 2>&1; then
    echo "  ✅ 无头集成测试: 通过"
    PASSED=$((PASSED + 1))
else
    echo "  ❌ 无头集成测试: 失败"
    FAILED=$((FAILED + 1))
fi

# ── 阶段3: API依赖测试 ──
echo ""
echo "[3/3] 运行API依赖测试..."
if [ "$INCLUDE_API" = true ]; then
    if grep -q "ALIBABA_API_KEY=sk-" .env 2>/dev/null || [ -n "${ALIBABA_API_KEY:-}" ]; then
        if python -m pytest tests/test_m2_m4_pipeline.py tests/test_headless_integration.py \
            $VERBOSE --tb=long -q -m "api" 2>&1; then
            echo "  ✅ API依赖测试: 通过"
            PASSED=$((PASSED + 1))
        else
            echo "  ⚠️  API依赖测试: 部分失败（检查网络/API Key）"
            FAILED=$((FAILED + 1))
        fi
    else
        echo "  ⏭️  跳过 — 未检测到API Key"
    fi
else
    echo "  ⏭️  跳过 — 使用 --api 参数以启用"
fi

# ── 结果汇总 ──
echo ""
echo "============================================"
echo "  测试完成: ${PASSED}通过, ${FAILED}失败"
if [ $FAILED -gt 0 ]; then
    echo "  ❌ 存在失败测试，请检查日志。"
    exit 1
else
    echo "  ✅ 所有测试通过！"
fi
echo "============================================"
