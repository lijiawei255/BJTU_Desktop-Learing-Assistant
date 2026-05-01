# BJTU Desktop Learning Assistant (Amiya)

桌面学习助手"阿米娅（Amiya）"—— 面向学生的 AI 语音陪伴设备，以大模型语音交互为核心，集成手机收纳管理、坐姿监测、走神追踪等功能。

> 当前阶段：**阶段一（PC 模拟开发）**，所有硬件通过 Mock 层模拟，暂不依赖树莓派。

## 技术栈

| 层级 | 技术 |
|------|------|
| 大模型服务 | 阿里云百炼 API（qwen3.6-plus / 千问3-ASR-Flash-Realtime / CosyVoice-v3-Flash） |
| 语音前端 | webrtcvad + 流式 ASR 关键词唤醒 |
| 视觉处理 | OpenCV + YuNet 人脸检测 |
| 开发语言 | Python 3.11 |
| 包管理 | Anaconda3 + pip |
| 部署平台 | Windows 11（阶段一）→ 树莓派 5（阶段二） |

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/lijiawei255/BJTU_Desktop-Learing-Assistant.git
cd BJTU_Desktop-Learing-Assistant
```

### 2. 使用 Anaconda 创建环境（一键配置）

```bash
# 方法一：通过 environment.yml 创建（推荐，精确复现）
conda env create -f environment.yml
conda activate amiya

# 方法二：手动创建后安装依赖
conda create -n amiya python=3.11 -y
conda activate amiya
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 3. 配置 API Key

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，填入你的阿里云百炼 API Key
# 获取地址：https://bailian.console.aliyun.com/
```

### 4. 验证环境

```bash
python -c "import webrtcvad, pyaudio, numpy, cv2, dashscope, pydantic; print('OK')"
```

预期输出：`OK`

### 5. 运行项目

```bash
python -m src.main
```

## 项目结构

```
├── src/                       # 源代码
│   ├── main.py                # 程序入口
│   ├── config.py              # 配置管理
│   ├── dialog_manager.py      # 对话调度器
│   ├── state_controller.py    # 状态机控制器
│   ├── wake_word_detector.py  # VAD + ASR 唤醒检测
│   ├── vad_handler.py         # VAD 语音活动检测
│   ├── memory_manager.py      # 三层记忆管理
│   ├── llm_client.py          # LLM API 封装
│   ├── asr_client.py          # ASR 语音识别
│   ├── tts_client.py          # TTS 语音合成
│   ├── audio_handler.py       # 音频采集与播放
│   ├── message_bus.py         # 进程间通信
│   ├── tool_executor.py       # 工具函数执行
│   ├── processes/             # 子进程模块
│   │   ├── vision_process.py  # 视觉子进程
│   │   ├── sensor_process.py  # 传感器子进程
│   │   └── device_process.py  # 外设控制子进程
│   ├── devices/               # 硬件驱动（Mock + 真实）
│   ├── utils/                 # 工具函数
│   └── models/                # 本地 ONNX 模型
├── system_prompts/            # Amiya 人格提示词
├── data/                      # 运行时数据
│   ├── session_history/       # 会话存档
│   ├── longterm_memory.json   # 长期记忆
│   └── config.json            # 用户配置
├── logs/                      # 日志文件
├── scripts/                   # 辅助脚本
├── environment.yml            # Conda 环境配置（一键复现）
├── requirements.txt           # 核心 pip 依赖
├── requirements-dev.txt       # 开发依赖
├── requirements-rpi.txt       # 树莓派专用依赖
└── .env.example               # 环境变量模板
```

## 开发协作

### 环境同步

当依赖发生变更时，更新者需同步维护以下文件：

| 文件 | 用途 |
|------|------|
| `environment.yml` | Conda 环境完整描述，新成员一键 `conda env create -f environment.yml` |
| `requirements.txt` | 核心 pip 依赖，`pip install -r requirements.txt` |
| `requirements-dev.txt` | 开发工具（pytest/black），`pip install -r requirements-dev.txt` |
| `requirements-rpi.txt` | 树莓派专用包，阶段二使用 |

### 更新已有环境

```bash
# 当 environment.yml 变更后
conda env update -f environment.yml --prune

# 当 requirements.txt 变更后
pip install -r requirements.txt
```

### Git 注意事项

- `.env` **绝对不能提交**（已加入 .gitignore）
- API Key 等敏感信息仅存储在本地 `.env` 文件中
- 变更依赖后请同步更新 `environment.yml` 和 `requirements.txt`

## 里程碑

| 阶段 | 内容 | 状态 |
|------|------|------|
| 1.1 项目骨架搭建 | 目录结构、依赖配置、日志系统 | 🚧 进行中 |
| 1.2 音频管道 | PyAudio 采集/播放 | 待开始 |
| 1.3 唤醒 + ASR | VAD 语音检测 + 流式 ASR 唤醒 | 待开始 |
| 1.4 大模型链路 | ASR → LLM → TTS 全流程 | 待开始 |
| 1.5 函数调用 | 工具函数 + Mock 外设 | 待开始 |
| 1.6 上下文管理 | 滑动窗口、摘要压缩 | 待开始 |
| 1.7 长期记忆 | JSON 存储、记忆整理 | 待开始 |
| 1.8 状态机 | 专注模式完整流程 | 待开始 |
| 1.9 多进程框架 | 消息队列、子进程通信 | 待开始 |
| 阶段二 | 树莓派硬件联调 | 待开始 |

## 许可证

参见 [LICENSE](LICENSE)
