# BJTU 桌面学习助手（Amiya）

[English](README.md) | [中文](README_CN.md)

桌面学习助手"阿米娅（Amiya）"——面向学生的 AI 语音陪伴设备，以大模型语音交互为核心，集成手机收纳管理、坐姿监测、走神追踪等功能。

> 当前阶段：**里程碑10已完成**（硬件真实测试 — 全流程硬件联动、摄像头跟踪与走神检测、舵机限位与驱动调优）。PC Mock 模式开箱即用，无需任何硬件。目标部署平台：树莓派 5。

## 功能一览

| 模块 | 描述 |
|------|------|
| 语音助手 | 大模型多轮语音对话（中英双语），角色扮演 Amiya 性格 |
| 手机管理器 | 语音指令进入专注模式，红外检测手机放入，舵机控制盒盖开关 |
| 坐姿端正器 | TOF 距离传感器监测坐姿，过近时语音提醒 |
| 走神监测 | 二维云台+摄像头人脸追踪 + MediaPipe 面部网格检测闭眼/转头 |
| LED 指示 | 多彩 RGB LED 显示系统当前运行状态 |
| 上下文记忆 | 多轮对话历史管理、上下文压缩、会话与长期记忆 |

## 环境要求

- **Python 3.11**（推荐使用 [Anaconda3](https://www.anaconda.com/) 或 [Miniconda](https://docs.conda.io/en/latest/miniconda.html)）
- **Windows 11 / macOS / Linux**（PC Mock 模式无需硬件）
- **阿里云百炼 API Key** — [免费获取](https://bailian.console.aliyun.com/)
- **麦克风 + 扬声器**（仅在真实语音模式下需要；Mock 模式使用文本控制台交互）

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/lijiawei255/BJTU_Desktop-Learing-Assistant.git
cd BJTU_Desktop-Learing-Assistant
```

### 2. 配置 Python 环境

```bash
# 方式 A：使用 conda（推荐）
conda create -n amiya python=3.11 -y
conda activate amiya

# 方式 B：使用系统 Python 3.11 + venv
python3.11 -m venv amiya-env
source amiya-env/bin/activate   # Linux/macOS
# amiya-env\Scripts\activate    # Windows
```

### 3. 安装依赖

```bash
# 核心依赖（Mock 模式，PC 开发全部所需）
pip install -r requirements.txt

# 可选：开发工具（测试、代码格式化）
pip install -r requirements-dev.txt
```

**验证安装**：
```bash
python -c "import webrtcvad, pyaudio, dashscope, cv2; print('OK')"
```
预期输出：`OK`

### 4. 配置 API Key

```bash
cp .env.example .env
```

编辑 `.env`，填入你的百炼 API Key：
```
ALIBABA_API_KEY=sk-你的真实api-key
```

获取地址：https://bailian.console.aliyun.com/

> **重要**：`.env` 已加入 .gitignore，切勿提交到 Git 或泄露你的 API Key。

### 5. 运行

```bash
# Mock 模式（默认，无需麦克风或硬件）
python -m src.main
```

Mock 模式下通过**文本控制台**与 Amiya 交互：
- 输入任意唤醒词（`阿米娅`、`amiya`、`amia` 等）唤醒助手
- 在 `[You]` 提示符后输入你想说的话
- 输入 `exit`、`quit` 或按 Ctrl+Z（Windows）/ Ctrl+D（Linux）退出

### 6. 运行测试（可选）

```bash
python -m pytest tests/ -v
```

**预期**：全部测试通过（28 个 M5 设备测试 + 管道集成测试 + 音频设备测试）。

## Mock 模式说明

项目支持 **Mock/Real 双模式**，通过 `data/config.json` 中的 `mock` 字段逐设备控制：

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

| 设置项 | `true`（Mock 模拟） | `false`（真实驱动） |
|--------|---------------------|---------------------|
| `audio` | 控制台文本输入/输出（模拟 ASR/TTS） | 真实麦克风 + 扬声器（PyAudio） |
| `servo` | 仅日志输出 | PCA9685 I2C PWM 舵机控制 |
| `ir` | 模拟手机放入/取出 | GPIO 17 红外传感器轮询 |
| `tof` | 模拟距离数据 | VL53L0X I2C 距离传感器 |
| `led` | 仅日志输出 | GPIO 23/24/25 RGB LED PWM |
| `camera` | 模拟人脸位置 | OV5647 MIPI CSI + MediaPipe |
| `button` | 模拟按下 | GPIO 27 物理按钮 |

**PC 开发**：全部设为 `true`，无需任何硬件即可运行。  
**树莓派部署**：设置 `"enabled": false` 即可全部切换为真实驱动。

### PC 端真实语音模式

如需在 PC 上测试真实麦克风和语音交互，编辑 `data/config.json`，将 `mock` 下的 `"audio"` 改为 `false`。重启 `python -m src.main`，系统将使用 PyAudio 录音/播放，并通过阿里云百炼 API 进行真实语音识别和合成。

## 常见问题

| 问题 | 解决方法 |
|------|---------|
| `ModuleNotFoundError: No module named 'pkg_resources'` | 执行 `pip install "setuptools>=65.0,<70.0"` — 新版 setuptools 移除了 webrtcvad 依赖的该模块 |
| `Could not find PyAudio` | Windows：从 https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio 下载 wheel 安装。Linux：`sudo apt install portaudio19-dev && pip install pyaudio` |
| API 调用失败 / 连接错误 | 检查 `.env` 中 `ALIBABA_API_KEY` 是否正确，网络是否能访问 `dashscope.aliyuncs.com` |
| `python` 命令找不到 | 尝试使用 `python3`，或确保 Python 3.11 在系统 PATH 中 |
| conda 命令找不到 | 先安装 Anaconda3 或 Miniconda，再重启终端 |
| pip 安装速度慢 | 使用清华镜像：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple` |

## 技术栈

| 层级 | 技术 |
|------|------|
| 大模型 | 阿里云百炼 API — `qwen-plus` |
| 语音识别 | 百炼 Paraformer-Realtime-V2（流式语音识别） |
| 语音合成 | 百炼 cosyvoice-v3-flash（音色：`longanrou_v3`） |
| 语音前端 | webrtcvad + PyAudio + 流式 ASR 唤醒词检测 |
| 视觉处理 | OpenCV Haar Cascade + MediaPipe Face Mesh |
| 人脸跟踪 | PID 控制 + 云台舵机自动扫描 |
| 开发语言 | Python 3.11 |
| 包管理 | pip / conda（environment.yml） |
| 平台 | Windows 11（开发）→ 树莓派 5（部署） |

## 项目结构

```
├── src/
│   ├── main.py                  # 主入口：语音对话循环 + 工具调用集成
│   ├── config.py                # 全局配置（默认值 + config.json + .env 合并）
│   ├── tool_executor.py         # 工具执行器 + FocusTimer + 专注模式生命周期
│   ├── dialog_manager.py        # 多轮对话历史管理
│   ├── llm_client.py            # LLM 客户端（流式对话 + 5个工具声明）
│   ├── asr_client.py            # 百炼 ASR 语音识别
│   ├── tts_client.py            # 百炼 TTS 语音合成（支持 barge-in 打断）
│   ├── audio_handler.py         # PyAudio 音频采集 / 播放
│   ├── vad_handler.py           # WebRTC VAD 语音活动检测
│   ├── wake_word_detector.py    # VAD + ASR 唤醒词检测（20+个变体）
│   ├── text_sanitizer.py        # LLM 输出文本清洗
│   ├── message_bus.py           # 消息总线（IPC 通信 + 25 种消息类型）
│   ├── state_controller.py      # 专注模式状态机（FocusState / SystemState）
│   ├── memory_manager.py        # 跨会话记忆管理（摘要/昵称/偏好）
│   ├── sentence_splitter.py     # 流式句子分割（用于流式 TTS）
│   ├── devices/                 # 硬件驱动层
│   │   ├── __init__.py          # 设备管理器（Mock/Real 路由工厂函数，10个）
│   │   ├── servo_mock.py        # 舵机 Mock
│   │   ├── servo_controller.py  # PCA9685 SG90 舵机真实驱动
│   │   ├── ir_sensor_mock.py    # 红外传感器 Mock
│   │   ├── ir_sensor.py         # GPIO 红外避障真实驱动
│   │   ├── tof_sensor_mock.py   # TOF 距离传感器 Mock
│   │   ├── tof_sensor.py        # VL53L0X I2C 真实驱动
│   │   ├── led_mock.py          # RGB LED Mock
│   │   ├── led_controller.py    # GPIO PWM LED 真实驱动
│   │   ├── camera.py            # OV5647 摄像头（PID跟踪 + MediaPipe走神检测）
│   │   └── gpio_button.py       # GPIO 物理按钮 + Mock
│   ├── processes/               # 传感器/视觉/外设子进程
│   ├── utils/                   # 日志、重试工具
│   └── models/                  # 空包（预留给未来本地模型）
├── system_prompts/              # Amiya 角色人格提示词
├── tests/                       # 测试（包含 M2-M9 全链路测试：管道/设备/记忆/状态机/唤醒词/无头集成）
├── docs/                        # 开发文档
├── data/                        # 运行时数据（config.json 已 gitignore）
├── logs/                        # 日志（已 gitignore）
├── requirements.txt             # 核心 Python 依赖
├── requirements-dev.txt         # 开发依赖（pytest/black）
├── requirements-rpi.txt         # 树莓派专用依赖
├── environment.yml              # Conda 环境配置
├── CLAUDE.md                    # Claude Code 开发指南
└── .env.example                 # 环境变量模板
```

## 硬件清单（树莓派 5 部署）

| 硬件 | 型号 | 数量 | 接口 |
|------|------|------|------|
| 主控 | 树莓派 5 (4/8GB) | 1 | — |
| 舵机 | SG90 180° | 4 | PCA9685 I2C (0x40) |
| 舵机驱动板 | PCA9685 16通道 | 1 | I2C |
| 摄像头 | OV5647 | 1 | MIPI CSI |
| 红外传感器 | IR 避障模块 | 1 | GPIO 17 |
| TOF 传感器 | VL53L0X | 1 | I2C (0x29) |
| RGB LED | 共阴/共阳 | 1 | GPIO 23/24/25 |
| 按钮 | 轻触开关 | 1 | GPIO 27 |
| 麦克风+扬声器 | USB 即插即用 | 1 | USB |

> **树莓派环境搭建**：通过 `raspi-config` 启用 I2C 和 GPIO 后，安装 `requirements-rpi.txt`。详细部署说明参见 [docs/](docs/)。

## 开发路线图

| 里程碑 | 内容 | 状态 |
|--------|------|------|
| M1 | 项目骨架：目录结构、依赖、日志系统 | ✅ 完成 |
| M2-M4 | 音频管道 + LLM + ASR/TTS 语音交互全链路 | ✅ 完成 |
| M5 | 函数调用 + Mock 外设 + 真实硬件驱动 | ✅ 完成 |
| M6 | 上下文管理 + 记忆系统 | ✅ 完成 |
| M7 | 专注模式状态机 | ✅ 完成 |
| M8 | 多进程框架 + 传感器进程 | ✅ 完成 |
| M9 | 语音交互优化：缩短等待、唤醒词打断、模糊唤醒词检测 | ✅ 完成 |
| M10 | 硬件真实测试：全流程硬件联动、摄像头跟踪与走神检测、舵机限位与驱动调优 | ✅ 完成 |
| 阶段二 | 树莓派硬件联调与功能优化 | 🔄 进行中 |

## 开发协作

### 分支模型
`main`（稳定）← `feature/xxx`（功能分支）

### 提交前缀
`feat:` / `fix:` / `docs:` / `test:` / `mock:` / `refactor:`

### Git 注意事项
- `.env` **绝对不能提交**（已加入 .gitignore）
- `data/config.json` 已 gitignore（含用户本地配置）
- API Key 仅存储在 `.env`，`config.json` 不会持久化密钥
- 变更依赖后同步更新 `requirements*.txt`

完整协作指南见：[docs/协作者方法.md](docs/协作者方法.md)

### Claude Code 协作
项目根目录的 `CLAUDE.md` 包含完整的项目上下文和开发约定，Claude Code 会自动加载。每次修改代码后需同步更新相关文档。

## 文档

- [开发规格文档](docs/桌面学习助手_开发规格文档.md) — 主规格文档 v1.2
- [业务逻辑说明](docs/业务逻辑说明.md) — 已实现的业务逻辑参考
- [开发实操手册](docs/ClaudeCode_开发实操手册.md) — 分步骤搭建指南
- [协作者方法](docs/协作者方法.md) — 新人上手与协作流程

## 许可证

MIT — 详见 [LICENSE](LICENSE)
