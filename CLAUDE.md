# CLAUDE.md — BJTU Desktop Learning Assistant (Amiya)

## Project Overview

桌面学习助手"阿米娅" — AI voice companion for students. LLM voice interaction + phone storage management + posture/distraction monitoring. Currently **Phase 1 (PC mock development)** with full hardware mock layer. Target platform: Raspberry Pi 5.

## Development Commands

```bash
# Run main app (mock mode — no hardware needed)
python -m src.main

# Run all tests
python -m pytest tests/ -v

# Run M5 device tests only
python -m pytest tests/test_m5_devices.py -v

# Run with real audio (edit data/config.json: mock.audio = false)
python -m src.main

# Code formatting
black src/ tests/

# Run headless mock integration tests (no hardware, no human)
python -m pytest tests/test_headless_integration.py -v -m "not api"

# Run headless tests on RPi via SSH
bash scripts/run_headless_tests.sh

# Run headless tests with API-dependent tests
bash scripts/run_headless_tests.sh --api
```

## Architecture

```
Voice Pipeline:  AudioHandler → VAD → WakeWord → ASR → LLM → TTS
Tool System:     LLM function-calling → ToolExecutor → Devices
Hardware Layer:  Device Manager (__init__.py) → Mock or Real drivers
```

- **Entry point**: `src/main.py` → `AmiyaSystem.run()` → `_run_voice_loop()` (multi-turn voice conversation loop)
- **Config**: `src/config.py` global `config` singleton, dot-path access `config.get("key.path")`
- **Devices**: `src/devices/__init__.py` factory functions route to Mock (PC) or Real (RPi) via `config.is_mock`
- **Focus mode**: `src/tool_executor.py` — `ToolExecutor` manages full lifecycle; `src/state_controller.py` — `StateController` + `FocusState` state machine (M7)
- **IPC**: `src/message_bus.py` — `MessageBus` + `IPCMessage` cross-process communication (M8)
- **Camera**: `src/devices/camera.py` — PID face tracking + auto-scan + MediaPipe distraction detection

---

## Rules & Requirements

以下规则在每次 Claude Code 会话中**必须遵守**。违反将导致代码库不一致或产生安全风险。

### 1. 文档同步（REQUIRED）

**每次修改代码后，必须同步更新受影响的文档文件**，以实际代码为唯一基准。

| 代码变更类型 | 需同步的文档 |
|-------------|-------------|
| 模型名、API 端点、默认配置值变更 | `README.md`、`README_CN.md`、`docs/桌面学习助手_开发规格文档.md`、`docs/ClaudeCode_开发实操手册.md`、`CLAUDE.md` |
| 新增/删除/重命名方法或类 | `CLAUDE.md`（架构部分）、`docs/业务逻辑说明.md` |
| 新增/删除/重命名文件 | `README.md`、`README_CN.md`（项目结构树）、`CLAUDE.md`（Key Files） |
| 工具函数（AVAILABLE_TOOLS）变更 | `docs/桌面学习助手_开发规格文档.md`（附录C）、`docs/业务逻辑说明.md`、`docs/ClaudeCode_开发实操手册.md` |
| 里程碑状态变更 | `README.md`、`README_CN.md`、`CLAUDE.md`、`docs/桌面学习助手_开发规格文档.md` |
| 依赖包变更 | `requirements.txt` / `requirements-dev.txt` / `requirements-rpi.txt` / `environment.yml`、`README.md` |

**检查方法**：修改完成后用 `git diff` 审视变更，确认所有受影响文档已更新。

### 2. 代码规范（REQUIRED）

- Imports: `from src.xxx import YYY`（绝对导入，从包根目录）
- Logging: `logger = setup_logger("name")` 放在模块级别
- Config: 所有可调参数通过 `config.get("section.key", default)` 读取，**禁止硬编码**
- Mock/Real: 通过 `config.is_mock and config.mock_devices.get("<device>")` 检查后再访问硬件
- Real drivers: 在 `__init__.py` 工厂函数中 lazy-import 硬件依赖（确保 PC 上可导入）
- Mock classes: 与真实驱动保持相同公开接口，额外提供 `simulate_*` 测试辅助方法
- 禁止抽象基类 — 通过工厂函数实现鸭子类型

### 3. 安全规则（REQUIRED）

- **绝对禁止**提交 `.env` 文件或任何包含 API Key 的文件
- **绝对禁止**将 API Key 写入 `data/config.json`
- **绝对禁止**在代码中硬编码 API Key、密钥或令牌
- API Key 仅存储在 `.env`（已 gitignore），通过 `config.api_key_alibaba` 属性读取

### 4. Git 操作规则（REQUIRED）

- **禁止**未经用户明确要求而执行 `git commit`、`git push`、`git push --force`
- **禁止**跳过 Git hooks（`--no-verify`、`--no-gpg-sign`）
- **禁止**对 `main` 分支执行 force push
- **禁止**使用 `git add -A` 或 `git add .` — 只暂存明确需要提交的文件
- **禁止**执行破坏性操作（`git reset --hard`、`git clean -f`、`git branch -D`）除非用户明确要求
- 始终创建**新提交**而非 amend（除非用户明确要求 amend）
- 提交前确认不包含 `.env`、`data/config.json`、`*.wav`、`*.pcm` 等 gitignored 文件

### 5. 代码修改原则（REQUIRED）

- **以实际代码为准**：如文档与代码冲突，代码是权威来源，修改文档以匹配代码
- **最小变更**：不做与当前任务无关的重构、格式化、或"顺手优化"
- **不添加未请求的功能**：不实现用户没有要求的功能，不设计假设性的未来需求
- **不引入不必要的抽象**：三行相似代码不值得提取一个 helper；不创建半成品实现
- **代码即文档**：命名清晰优先于写注释；仅在 WHY 不显而易见时添加注释
- **安全第一**：避免命令注入、XSS、SQL 注入等 OWASP Top 10 漏洞
- **只验证系统边界**：仅在用户输入和外部 API 边界做验证；不验证内部调用

### 6. PC与树莓派代码同步（REQUIRED）

**当运行环境同时涉及 PC（开发机）和树莓派（部署机）时，修改代码必须同时同步两端。**

- 通过 SSH 修改树莓派上的文件后，必须同步修改 PC 上对应的同一文件
- 反之，修改 PC 上的文件后，必须同步到树莓派
- 同步方式：优先使用 `scp` 或 `rsync` 传输；小型改动可直接通过 SSH 命令编辑
- **检查方法**：修改完成后确认两端的文件内容一致（可用 `diff` 或 `md5sum` 验证）
- **目的**：避免 GitHub 仓库代码与树莓派实际运行代码不一致，确保版本可追溯

### 7. 测试要求（REQUIRED）

- 修改代码后**必须运行相关测试**确认无回归：
  ```bash
  python -m pytest tests/ -v
  ```
- 新增功能应补充测试（在 `tests/` 目录中）
- 测试失败时修复代码或更新测试，**不允许**跳过测试提交

---

## Current Status (M7+M8+M9 Complete)

| Milestone | Status |
|-----------|--------|
| M1: Project skeleton | ✅ Done |
| M2-M4: Audio pipeline + LLM + ASR/TTS | ✅ Done |
| M5: Function calling + mock devices | ✅ Done |
| M6: Context management + memory | ✅ Done |
| M7: Focus state machine | ✅ Done |
| M8: Multiprocess architecture | ✅ Done |
| M9: Voice interaction optimizations | ✅ Done |

## Key Files for M6+ Development

- `src/memory_manager.py` — Cross-session memory, context compression, nickname/preferences
- `src/tool_executor.py` — `ToolExecutor` manages focus lifecycle (delegates state to `StateController`). IR sensor NOT owned — sensor process is exclusive GPIO owner.
- `src/state_controller.py` — `FocusState` enum + `StateController` formal state machine (M7)
- `src/message_bus.py` — `MessageBus` + `IPCMessage` cross-process communication (M8)
- `src/processes/device_process.py` — Peripheral control subprocess (servo + LED)
- `src/processes/sensor_process.py` — Sensor subprocess/thread (TOF + IR) via message bus (M8)
- `src/processes/vision_process.py` — Vision subprocess (camera tracking + distraction)
- `src/dialog_manager.py` — Message history
- `src/devices/__init__.py` — Device factory (add new devices here)
- `src/devices/camera.py` — PID tracker + MediaPipe distraction detector (`PIDController` 在此文件中，非独立 `utils/pid.py`)
- `src/config.py` — All config keys defined here
- `src/llm_client.py` — `AVAILABLE_TOOLS` + `stream_chat` (add new tools here)
- `src/wake_word_detector.py` — Wake word detection with fuzzy matching + barge-in gating (M9)
- `src/headless_input.py` — Headless mock input system for automated testing (queue-based, replaces stdin)
- `tests/test_headless_integration.py` — Comprehensive headless mock integration tests (32 non-API + 5 API)
- `scripts/run_headless_tests.sh` — Automated test runner for RPi/Linux
- `scripts/run_headless_tests.bat` — Automated test runner for Windows
- `.rpi_connection` — RPi connection info (gitignored, contains IP/user)
- `docs/ClaudeCode_开发实操手册.md` — Full development manual with M6-M9 specs

## Hardware Specifications (Raspberry Pi 5)

| Hardware | Model | Interface | GPIO | Config Key |
|----------|-------|-----------|------|------------|
| Servo ×4 | SG90 (180°, 500-2400μs) | PCA9685 I2C (0x40) | CH0/1=Box, CH2=Pan, CH3=Tilt | `servo.*` |
| IR Obstacle Sensor | Standard 3.3V, active-LOW | GPIO 17 (pull_up) | Pin 11 | `ir_sensor.pin` |
| Button | Self-reset, default-HIGH, press-LOW | GPIO 27 (pull_up) | Pin 13 | `button.pin` |
| RGB LED | Common cathode, active_high | GPIO 23/24/25 | Pins 16/18/22 | `led.pins.*` |
| TOF Distance | VL53L0X (GY-53) | I2C (0x29) | Bus共享 | `tof_sensor.*` |
| USB Sound Card | UACDemoV1.0 | USB 2.0 | — | `audio.*` |
| Camera | OV5647 | MIPI CSI-2 | — | `vision.*` |

Key config: `servo.min_pulse_us=500`, `servo.max_pulse_us=2400` (SG90 standard),
`servo.box_open_angle=0`, `servo.box_close_angle=90`.

**GPIO Ownership**: Sensor process (`sensor_process.py`) is the exclusive owner of IR (GPIO 17)
and TOF (I2C 0x29) hardware. Main process only receives PHONE_DETECTED/PHONE_REMOVED messages
via MessageBus — never reads GPIO directly. This avoids multi-process GPIO conflicts.

## Mock Mode

Default: all hardware mocked. Edit `data/config.json`:
```json
{"mock": {"enabled": true, "audio": true, "servo": true, ...}}
```
Per-device granularity: set individual flags to `false` for selective real hardware testing.

### Headless Mock Mode (Automated Testing)

When `mock.headless` is `null` (auto) or `true`, the system replaces all `input()` calls with a
thread-safe `queue.Queue`-based input feeder. Detection: config flag > `sys.stdin.isatty()`.

- **Auto-detect**: Pytest/SSH pipe → headless; Terminal → interactive
- **Force headless**: Set `"headless": true` in config.json
- **API tests**: Marked with `@pytest.mark.api`, use `-m "not api"` to skip
- **RPi safety**: Mock audio mode prevents PyAudio from being imported/initialized

## API Key Setup

Copy `.env.example` → `.env`, fill in `ALIBABA_API_KEY` from https://bailian.console.aliyun.com/
`.env` is gitignored. API keys are NEVER saved to `config.json`.
