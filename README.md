# BJTU Desktop Learning Assistant (Amiya)

[English](README.md) | [中文](README_CN.md)

Amiya is an AI voice companion device for students, built around LLM voice interaction with integrated phone storage management, posture monitoring, and distraction tracking.

> **Status**: Milestone 9 complete — Voice interaction optimizations (shorter wait, wake-word-gated barge-in, fuzzy wake word detection). Runs out of the box on PC in mock mode (no hardware required). Target deployment: Raspberry Pi 5.

## Features

| Module | Description |
|--------|-------------|
| Voice Assistant | LLM-powered multi-turn voice conversation (CN/EN), Amiya character persona |
| Phone Manager | Voice-activated focus mode: IR sensor detects phone placement, servo-controlled box lid |
| Posture Corrector | TOF distance sensor monitors sitting posture, voice reminders when too close |
| Distraction Monitor | Pan-tilt camera with face tracking + MediaPipe face mesh for eyes-closed/head-turn detection |
| LED Indicator | Multi-color RGB LED displays system state |
| Context & Memory | Multi-turn dialog history, context compression, session & long-term memory |

## Prerequisites

- **Python 3.11** (recommended: [Anaconda3](https://www.anaconda.com/) or [Miniconda](https://docs.conda.io/en/latest/miniconda.html))
- **Windows 11 / macOS / Linux** (PC mock mode — no hardware needed)
- **Alibaba Cloud Bailian API Key** — [Get one free](https://bailian.console.aliyun.com/) (Mainland China accessible)
- **Microphone + Speaker** (only needed when running in real audio mode; mock mode uses text console)

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/lijiawei255/BJTU_Desktop-Learing-Assistant.git
cd BJTU_Desktop-Learing-Assistant
```

### 2. Set up Python environment

```bash
# Option A: Using conda (recommended)
conda create -n amiya python=3.11 -y
conda activate amiya

# Option B: Using system Python 3.11 + venv
python3.11 -m venv amiya-env
source amiya-env/bin/activate   # Linux/macOS
# amiya-env\Scripts\activate    # Windows
```

### 3. Install dependencies

```bash
# Core dependencies (mock mode — all you need for PC development)
pip install -r requirements.txt

# Optional: Development tools (testing, formatting)
pip install -r requirements-dev.txt
```

**Expected output**: All packages install without errors. Verify with:
```bash
python -c "import webrtcvad, pyaudio, dashscope, cv2; print('OK')"
```

### 4. Configure API Key

```bash
cp .env.example .env
```

Edit `.env` and set your Bailian API key:
```
ALIBABA_API_KEY=sk-your-real-api-key
```

Get your key at: https://bailian.console.aliyun.com/

> **Important**: `.env` is gitignored. Never commit it or expose your API key.

### 5. Run

```bash
# Mock mode (default — no hardware or microphone needed)
python -m src.main
```

In mock mode, you interact with Amiya through the **text console**:
- Type any wake word (`amiya`, `阿米娅`, `amia`) to wake up the assistant
- Type your message after the `[You]` prompt
- Type `exit`, `quit`, or send EOF (Ctrl+Z on Windows / Ctrl+D on Linux) to stop

### 6. Run tests (optional)

```bash
python -m pytest tests/ -v
```

**Expected**: All tests pass (28 M5 device tests + pipeline integration tests + audio device test).

## Mock Mode

The project supports **per-device mock/real switching** via `data/config.json`:

```json
{
  "mock": {
    "enabled": true,
    "audio": true,
    "servo": true,
    "ir": true,
    "tof": true,
    "led": true,
    "camera": true,
    "button": true
  }
}
```

| Setting | `true` (Mock) | `false` (Real) |
|---------|---------------|-----------------|
| `audio` | Console text I/O (ASR/TTS simulated) | Real microphone + speaker via PyAudio |
| `servo` | Log output only | PCA9685 I2C PWM servo control |
| `ir` | Simulated phone detect/remove | GPIO 17 IR sensor polling |
| `tof` | Simulated distance patterns | VL53L0X I2C ToF sensor |
| `led` | Log output only | GPIO 23/24/25 RGB LED PWM |
| `camera` | Simulated face position | OV5647 MIPI CSI + MediaPipe |
| `button` | Simulated press | GPIO 27 physical button |

**PC development**: All mocks `true` — runs anywhere with no hardware.  
**Raspberry Pi deployment**: Set `"enabled": false` to switch all devices to real drivers.

### Real Audio Mode (PC with microphone)

To test with a real microphone on PC, edit `data/config.json` and set `"audio": false` under `mock`. Restart `python -m src.main` — the system will use PyAudio for recording/playback and call cloud APIs for ASR/TTS.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError: No module named 'pkg_resources'` | Run `pip install "setuptools>=65.0,<70.0"` — newer setuptools removed this module required by webrtcvad |
| `Could not find PyAudio` | Windows: install PyAudio wheel from https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio. Linux: `sudo apt install portaudio19-dev && pip install pyaudio` |
| API error / connection failed | Verify ALIBABA_API_KEY in `.env` is correct and network can reach `dashscope.aliyuncs.com` |
| `python: command not found` | Use `python3` instead, or ensure Python 3.11 is in your PATH |
| Conda not found | Install Anaconda3 or Miniconda first, then restart your terminal |
| Slow pip installs in China | Use Tsinghua mirror: `pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple` |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| LLM | Alibaba Cloud Bailian API — `qwen-plus` |
| ASR | Bailian Paraformer-Realtime-V2 (streaming speech recognition) |
| TTS | Bailian cosyvoice-v3-flash (voice: `longanrou_v3`) |
| Voice Frontend | webrtcvad + PyAudio + streaming ASR wake word detection |
| Vision | OpenCV Haar Cascade + MediaPipe Face Mesh |
| Face Tracking | PID control + pan-tilt servo auto-scan |
| Language | Python 3.11 |
| Package Management | pip / conda (environment.yml) |
| Platforms | Windows 11 (dev) → Raspberry Pi 5 (deploy) |

## Project Structure

```
├── src/
│   ├── main.py                  # Entry point: voice conversation loop + tool integration
│   ├── config.py                # Global config (defaults + config.json + .env merge)
│   ├── tool_executor.py         # Tool executor + FocusTimer + focus mode lifecycle
│   ├── dialog_manager.py        # Multi-turn conversation history manager
│   ├── llm_client.py            # LLM client (streaming chat + tool declarations)
│   ├── asr_client.py            # Bailian ASR speech recognition
│   ├── tts_client.py            # Bailian TTS speech synthesis (with barge-in)
│   ├── audio_handler.py         # PyAudio recording / playback
│   ├── vad_handler.py           # WebRTC voice activity detection
│   ├── wake_word_detector.py    # VAD + ASR wake word detection (8 variants)
│   ├── text_sanitizer.py        # LLM output text cleaner
│   ├── sentence_splitter.py     # Streaming sentence segmentation (for streaming TTS)
│   ├── devices/                 # Hardware driver layer
│   │   ├── __init__.py          # Device factory (mock/real routing)
│   │   ├── servo_mock.py        # Servo mock (log-based)
│   │   ├── servo_controller.py  # PCA9685 SG90 servo real driver
│   │   ├── ir_sensor_mock.py    # IR sensor mock
│   │   ├── ir_sensor.py         # GPIO IR obstacle sensor real driver
│   │   ├── tof_sensor_mock.py   # ToF distance sensor mock
│   │   ├── tof_sensor.py        # VL53L0X I2C real driver
│   │   ├── led_mock.py          # RGB LED mock
│   │   ├── led_controller.py    # GPIO PWM LED real driver
│   │   ├── camera.py            # OV5647 camera (PID tracking + MediaPipe distraction)
│   │   └── gpio_button.py       # GPIO physical button + mock
│   ├── processes/               # Subprocess modules (reserved for M8)
│   ├── utils/                   # Logger, retry utilities
│   └── models/                  # Reserved for future local models
├── system_prompts/              # Amiya character persona prompt
├── tests/                       # Tests (28 M5 device tests + pipeline integration)
├── docs/                        # Development documentation (Chinese)
├── data/                        # Runtime data (config.json is gitignored)
├── logs/                        # Log files (gitignored)
├── requirements.txt             # Core Python dependencies
├── requirements-dev.txt         # Dev dependencies (pytest, black)
├── requirements-rpi.txt         # Raspberry Pi specific dependencies
├── environment.yml              # Conda environment specification
├── CLAUDE.md                    # Claude Code development guide
└── .env.example                 # Environment variable template
```

## Hardware (Raspberry Pi 5 Deployment)

| Component | Model | Qty | Interface |
|-----------|-------|-----|-----------|
| Main Board | Raspberry Pi 5 (4/8 GB) | 1 | — |
| Servo | SG90 180° | 4 | PCA9685 I2C (0x40) |
| Servo Driver | PCA9685 16-channel | 1 | I2C |
| Camera | OV5647 | 1 | MIPI CSI |
| IR Sensor | IR obstacle avoidance | 1 | GPIO 17 |
| ToF Sensor | VL53L0X | 1 | I2C (0x29) |
| RGB LED | Common cathode/anode | 1 | GPIO 23/24/25 |
| Button | Tactile switch | 1 | GPIO 27 |
| Microphone + Speaker | USB plug-and-play | 1 | USB |

> **Raspberry Pi setup**: Install `requirements-rpi.txt` after enabling I2C/GPIO via `raspi-config`. See [docs/](docs/) for detailed deployment instructions.

## Roadmap

| Milestone | Content | Status |
|-----------|---------|--------|
| M1 | Project skeleton: directory structure, dependencies, logging | ✅ Done |
| M2-M4 | Audio pipeline + LLM + ASR/TTS full voice interaction chain | ✅ Done |
| M5 | Function calling + mock peripherals + real hardware drivers | ✅ Done |
| M6 | Context management + memory system | ✅ Done |
| M7 | Focus mode state machine | ✅ Done |
| M8 | Multi-process framework + sensor process | ✅ Done |
| M9 | Voice interaction: shorter timeout, wake-word barge-in, fuzzy wake word | ✅ Done |
| Phase 2 | Raspberry Pi hardware integration | 📋 Planned |

## Contributing

- **Branch model**: `main` (stable) → `develop` (integration) → `feature/xxx` (feature branches)
- **Commit prefixes**: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`
- `.env` and `data/config.json` are gitignored — never commit them
- Update `requirements*.txt` when adding/removing dependencies
- See [docs/协作者方法.md](docs/协作者方法.md) for the full collaboration guide (Chinese)

For Claude Code users: the project root `CLAUDE.md` provides full project context and development conventions.

## Documentation

- [Development Specification](docs/桌面学习助手_开发规格文档.md) (Chinese) — Master spec v1.2
- [Business Logic](docs/业务逻辑说明.md) (Chinese) — Implemented business logic reference
- [Development Manual](docs/ClaudeCode_开发实操手册.md) (Chinese) — Step-by-step build guide
- [Collaborator Guide](docs/协作者方法.md) (Chinese) — Onboarding & workflow

## License

MIT — see [LICENSE](LICENSE)
