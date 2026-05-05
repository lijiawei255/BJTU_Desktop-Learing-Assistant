"""真实音频设备测试 - 录音+播放验证"""

import sys
import io
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def test_real_audio():
    """测试真实麦克风录音和音箱播放"""
    import pyaudio

    pa = pyaudio.PyAudio()

    # 查找输入设备
    print("=== 查找音频设备 ===")
    input_idx = None
    output_idx = None

    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info['maxInputChannels'] > 0 and input_idx is None:
            input_idx = i
            print(f"输入设备[{i}]: {info['name']}")
        if info['maxOutputChannels'] > 0 and output_idx is None:
            output_idx = i
            print(f"输出设备[{i}]: {info['name']}")

    if input_idx is None:
        print("未找到输入设备！")
        pa.terminate()
        return False

    if output_idx is None:
        print("未找到输出设备！")
        pa.terminate()
        return False

    # 录音测试 (3秒)
    SAMPLE_RATE = 16000
    CHUNK = 480
    DURATION = 3

    print(f"\n=== 录音测试 ({DURATION}秒) ===")
    print("请对着麦克风说话...")

    stream_in = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=SAMPLE_RATE,
        input=True,
        input_device_index=input_idx,
        frames_per_buffer=CHUNK,
    )

    frames = []
    for _ in range(0, int(SAMPLE_RATE / CHUNK * DURATION)):
        data = stream_in.read(CHUNK, exception_on_overflow=False)
        frames.append(data)

    stream_in.stop_stream()
    stream_in.close()

    audio_data = b"".join(frames)
    print(f"录制完成: {len(audio_data)} bytes")

    # 计算实际音量（简单的RMS）
    import struct
    samples = struct.unpack('h' * (len(audio_data) // 2), audio_data)
    rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
    print(f"音量RMS: {rms:.1f}")

    if rms < 50:
        print("警告: 录音音量很低，请检查麦克风")
    else:
        print("录音正常!")

    # 保存录音
    import wave
    with wave.open("logs/test_recording_real.wav", "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_data)
    print("已保存到 logs/test_recording_real.wav")

    # 播放测试
    print(f"\n=== 播放测试 ===")
    print("播放刚才的录音...")

    stream_out = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=SAMPLE_RATE,
        output=True,
        output_device_index=output_idx,
    )

    stream_out.write(audio_data)
    stream_out.stop_stream()
    stream_out.close()

    print("播放完成!")

    pa.terminate()
    print("\n真实音频测试通过!")
    return True


if __name__ == "__main__":
    success = test_real_audio()
    sys.exit(0 if success else 1)
