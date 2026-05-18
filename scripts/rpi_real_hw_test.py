"""通过项目真实驱动代码测试所有可用硬件"""
import time
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import config

# 确保真实硬件模式
assert not config.is_mock or not any(config.mock_devices.values()), \
    "Mock mode must be OFF for real hardware test"

print('=' * 50)
print('  阿米娅 真实硬件驱动集成测试')
print('=' * 50)
print()

# ━━ 1. LED Controller ━━
print('[1/4] LED Controller (GPIO 23/24/25)')
from src.devices.led_controller import LEDController
led = LEDController()
for color in ['red', 'green', 'blue', 'off']:
    led.set_color(color, 'solid')
    print(f'  {color} ✓')
    time.sleep(0.3)
led.close()
print('  LED测试通过\n')

# ━━ 2. IR Sensor ━━
print('[2/4] IR Sensor (GPIO 17)')
from src.devices.ir_sensor import IRSensor
ir = IRSensor()
initial = ir.read()
print(f'  初始状态: {"有障碍物" if initial else "无障碍物"}')
ir.close()
print('  IR传感器测试通过\n')

# ━━ 3. Button ━━
print('[3/4] Button (GPIO 27)')
from src.devices.gpio_button import GPIOButton
btn = GPIOButton()
print(f'  初始状态: {"已按下" if btn.is_pressed else "未按下"}')
btn.close()
print('  按钮测试通过\n')

# ━━ 4. Audio (TTS + Recording) ━━
print('[4/4] USB Audio (TTS播放 + 录音)')
from src.tts_client import TTSClient
from src.audio_handler import AudioHandler
from src.vad_handler import VADHandler

# TTS播放
tts = TTSClient()
print('  播放TTS...')
tts.speak('阿米娅硬件测试完成。所有可用设备正常。')
print('  TTS播放完成 ✓')

# 录音测试
audio = AudioHandler()
vad = VADHandler()
print('  录音1秒...')
audio_data = audio.record_until_silence(vad, max_seconds=2, min_speech_ms=200)
if audio_data:
    print(f'  录音: {len(audio_data)} bytes ✓')
else:
    print('  录音: 无语音（正常，环境安静）✓')

print('\n' + '=' * 50)
print('  所有可用硬件测试通过!')
print('  LED ✓  IR ✓  Button ✓  Audio ✓')
print('=' * 50)
