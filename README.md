# BJTU Desktop Learning Assistant (Amiya)

桌面学习助手"阿米娅（Amiya）"——面向学生的 AI 语音陪伴设备，以大模型语音交互为核心，集成手机收纳管理、坐姿监测、走神追踪等功能。

> 当前阶段：**里程碑5已完成**（函数调用 + Mock外设层 + 真实硬件驱动）。PC Mock模式开箱即用，无需硬件。

## 技术栈

| 层级 | 技术 |
|------|------|
| 大模型服务 | 阿里云百炼 API（qwen-plus / Paraformer-Realtime / CosyVoice-v3-Flash） |
| 语音前端 | webrtcvad + PyAudio + 流式 ASR 唤醒词检测 |
| 视觉处理 | OpenCV Haar Cascade + MediaPipe Face Mesh（闭眼/转头走神检测） |
| 人脸跟踪 | PID 控制 + 云台舵机自动扫描 |
| 开发语言 | Python 3.11 |
| 包管理 | Anaconda3 + pip |
| 部署平台 | Windows 11（PC Mock 开发）→ 树莓派 5（真实硬件部署） |

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/lijiawei255/BJTU_Desktop-Learing-Assistant.git
cd BJTU_Desktop-Learing-Assistant
```

### 2. 安装依赖

```bash
# PC 开发只需核心依赖（Mock 模式无需硬件）
pip install -r requirements.txt

# 可选：安装开发工具（测试/格式化）
pip install -r requirements-dev.txt

# 树莓派部署时才需要（含 gpiozero / MediaPipe / PCA9685 等）
# pip install -r requirements-rpi.txt
```

### 3. 配置 API Key

```bash
cp .env.example .env
# 编辑 .env，填入阿里云百炼 API Key
# 获取地址：https://bailian.console.aliyun.com/
```

### 4. 运行

```bash
# Mock 模式（默认，无需麦克风/硬件）
python -m src.main

# 真实语音交互模式：编辑 data/config.json → mock.audio 改为 false
```

### 5. 运行测试

```bash
python -m pytest tests/ -v
```

## Mock 模式说明

项目支持 **Mock/Real 双模式**，通过 `data/config.json` 中的 `mock` 字段逐设备控制：

```json
{
  "mock": {
    "enabled": true,    // 总开关：false 则全部使用真实驱动
    "audio": true,      // true=模拟ASR/TTS，false=真实麦克风/扬声器
    "servo": true,      // true=日志模拟，false=PCA9685 I2C 驱动
    "ir": true,         // true=模拟红外，false=GPIO 轮询
    "tof": true,        // true=模拟距离，false=VL53L0X I2C
    "led": true,        // true=日志模拟，false=GPIO PWM
    "camera": true,     // true=模拟跟踪，false=OV5647 + MediaPipe
    "button": true
  }
}
```

PC 开发默认全部 Mock；树莓派部署时设置 `"enabled": false` 即可切换到真实驱动。

---

## 项目结构

```
├── src/
│   ├── main.py                  # 主入口：语音对话循环 + 工具调用集成
│   ├── config.py                # 全局配置（默认值 + config.json + .env 合并）
│   ├── tool_executor.py         # 工具执行器 + FocusTimer + 专注模式生命周期
│   ├── dialog_manager.py        # 多轮对话历史管理
│   ├── llm_client.py            # LLM 客户端（流式对话 + 工具声明）
│   ├── asr_client.py            # 阿里云百炼 ASR 语音识别
│   ├── tts_client.py            # 阿里云百炼 TTS 语音合成
│   ├── audio_handler.py         # PyAudio 音频采集 / 播放
│   ├── vad_handler.py           # WebRTC VAD 语音活动检测
│   ├── wake_word_detector.py    # VAD + ASR 唤醒词检测
│   ├── text_sanitizer.py        # LLM 输出文本清洗
│   ├── sentence_splitter.py     # 流式句子分割（用于流式 TTS）
│   ├── devices/                 # 硬件驱动层
│   │   ├── __init__.py          # 设备管理器（Mock/Real 路由工厂函数）
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
│   ├── processes/               # 子进程模块（M8 实现）
│   ├── utils/                   # 日志、重试工具
│   └── models/                  # 本地 ONNX 模型目录（预留）
├── system_prompts/              # Amiya 角色人格提示词
├── tests/                       # 测试（38个M5设备测试 + pipeline集成测试）
├── docs/                        # 开发文档
├── data/                        # 运行时数据（config.json 已 gitignore）
├── logs/                        # 日志（已 gitignore）
├── requirements.txt             # 核心依赖
├── requirements-dev.txt         # 开发依赖（pytest/black）
├── requirements-rpi.txt         # 树莓派专用依赖
├── environment.yml              # Conda 环境
├── CLAUDE.md                    # Claude Code 开发指南
└── .env.example                 # 环境变量模板
```

## 硬件清单（树莓派5部署）

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

## 里程碑

| 里程碑 | 内容 | 状态 |
|--------|------|------|
| M1 | 项目骨架：目录结构、依赖、日志系统 | ✅ 完成 |
| M2-M4 | 音频管道 + LLM + ASR/TTS 语音交互全链路 | ✅ 完成 |
| M5 | 函数调用 + Mock 外设 + 真实硬件驱动 | ✅ 完成 |
| M6 | 上下文管理 + 记忆系统 | 🔜 下一步 |
| M7 | 专注模式状态机 | 📋 计划中 |
| M8 | 多进程框架 + 传感器进程 | 📋 计划中 |
| 阶段二 | 树莓派硬件联调 | 📋 计划中 |

## 开发协作

### Git 注意事项

- `.env` **绝对不能提交**（已加入 .gitignore）
- `data/config.json` 已 gitignore（含用户本地配置）
- API Key 仅存储在 `.env`，`config.json` 不会持久化密钥
- 变更依赖后同步更新 `requirements*.txt`

### Claude Code 协作

项目根目录的 `CLAUDE.md` 包含完整的项目上下文和开发约定，Claude Code 会自动加载。

## 许可证

参见 [LICENSE](LICENSE)
