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
```

## Architecture

```
Voice Pipeline:  AudioHandler → VAD → WakeWord → ASR → LLM → TTS
Tool System:     LLM function-calling → ToolExecutor → Devices
Hardware Layer:  Device Manager (__init__.py) → Mock or Real drivers
```

- **Entry point**: `src/main.py` → `AmiyaSystem.run_test()` (voice conversation loop)
- **Config**: `src/config.py` global `config` singleton, dot-path access `config.get("key.path")`
- **Devices**: `src/devices/__init__.py` factory functions route to Mock (PC) or Real (RPi) via `config.is_mock`
- **Focus mode**: `src/tool_executor.py` — `ToolExecutor` + `FocusTimer` manage full lifecycle
- **Camera**: `src/devices/camera.py` — PID face tracking + auto-scan + MediaPipe distraction detection

## Code Conventions

- Imports: `from src.xxx import YYY` (absolute from package root)
- Logging: `logger = setup_logger("name")` at module level
- Config: `config.get("section.key", default)` for all tunable values
- Mock/Real: check `config.is_mock and config.mock_devices.get("<device>")` before hardware access
- Real drivers: lazy-import hardware deps inside `__init__` (allows import on PC)
- Mock classes: same public interface as real drivers, plus `simulate_*` helpers for testing
- No abstract base classes — use duck-typing via factory functions

## Current Status (M5 Complete)

| Milestone | Status |
|-----------|--------|
| M1: Project skeleton | ✅ Done |
| M2-M4: Audio pipeline + LLM + ASR/TTS | ✅ Done |
| M5: Function calling + mock devices | ✅ Done |
| M6: Context management + memory | ❌ Next |
| M7: Focus state machine | ❌ Planned |
| M8: Multiprocess architecture | ❌ Planned |

## Key Files for M6+ Development

- `src/tool_executor.py` — Focus lifecycle (will be refactored into `state_controller.py` in M7)
- `src/dialog_manager.py` — Message history (will integrate `memory_manager.py` in M6)
- `src/devices/__init__.py` — Device factory (add new devices here)
- `src/devices/camera.py` — PID tracker + MediaPipe distraction detector
- `src/config.py` — All config keys defined here
- `src/llm_client.py` — `AVAILABLE_TOOLS` + `stream_chat` (add new tools here)
- `docs/ClaudeCode_开发实操手册.md` — Full development manual with M6-M8 specs

## Mock Mode

Default: all hardware mocked. Edit `data/config.json`:
```json
{"mock": {"enabled": true, "audio": true, "servo": true, ...}}
```
Per-device granularity: set individual flags to `false` for selective real hardware testing.

## API Key Setup

Copy `.env.example` → `.env`, fill in `ALIBABA_API_KEY` from https://bailian.console.aliyun.com/
`.env` is gitignored. API keys are NEVER saved to `config.json`.
