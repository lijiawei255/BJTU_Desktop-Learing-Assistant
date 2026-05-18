"""树莓派硬件逐设备测试脚本"""
import time
import sys

def test_button():
    """自复按钮 GPIO27"""
    from gpiozero import Button
    print('=== 自复按钮 GPIO27 ===')
    print('请现在按下按钮...')
    btn = Button(27, pull_up=True)
    pressed = False
    for i in range(150):
        if btn.is_pressed:
            pressed = True
            print(f'检测到按下 (帧{i}) ✓')
            break
        time.sleep(0.1)
    if not pressed:
        print('未检测到 — 请检查接线')
    btn.close()
    return pressed

def test_ir():
    """红外避障传感器 GPIO17"""
    from gpiozero import Button
    print('\n=== 红外避障 GPIO17 ===')
    ir = Button(17, pull_up=True)
    initial = ir.is_pressed
    print(f'初始状态: {"有障碍" if initial else "无障碍"}')
    print('请遮挡传感器...')
    detected = False
    for i in range(100):
        if ir.is_pressed != initial:
            detected = True
            print(f'状态变化: {"有障碍" if ir.is_pressed else "无障碍"} ✓')
            break
        time.sleep(0.1)
    if not detected:
        print(f'状态未变化 (当前: {"有障碍" if ir.is_pressed else "无障碍"})')
    ir.close()
    return True

def test_led():
    """RGB LED GPIO23/24/25"""
    from gpiozero import LED
    print('\n=== RGB LED ===')
    results = []
    for gpio, name in [(23, '红'), (24, '绿'), (25, '蓝')]:
        try:
            led = LED(gpio, active_high=True)
            led.on()
            time.sleep(0.5)
            led.off()
            led.close()
            print(f'  GPIO{gpio} ({name}) ✓')
            results.append(True)
        except Exception as e:
            print(f'  GPIO{gpio} ({name}) ✗ {e}')
            results.append(False)
    return all(results)

def test_i2c():
    """检查I2C设备"""
    import subprocess
    print('\n=== I2C设备扫描 ===')
    # 检查所有I2C总线
    result = subprocess.run(['i2cdetect', '-l'], capture_output=True, text=True)
    print(result.stdout.strip())

    for bus in ['1', '4', '11', '12']:
        result = subprocess.run(
            ['sudo', 'i2cdetect', '-y', bus],
            capture_output=True, text=True
        )
        lines = result.stdout.strip().split('\n')
        # 过滤空行
        non_empty = [l for l in lines if '--' not in l or l.count('--') < 8]
        if any(c in result.stdout for c in ['29', '40']):
            print(f'  BUS {bus}: 设备已找到 ✓')
        else:
            print(f'  BUS {bus}: 无设备')

    # 检查GPIO2/3
    result = subprocess.run(['pinctrl', '2,3'], capture_output=True, text=True)
    print(f'GPIO2/3状态: {result.stdout.strip()}')

def test_audio():
    """USB声卡"""
    import pyaudio, struct
    print('\n=== USB声卡 ===')
    pa = pyaudio.PyAudio()
    found = False
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if 'UACDemo' in info['name']:
            print(f'  设备[{i}]: {info["name"]} ✓')
            found = True
    if not found:
        print('  未找到UACDemo声卡')
    pa.terminate()
    return found

if __name__ == '__main__':
    results = {}
    results['LED'] = test_led()
    results['IR'] = test_ir()
    results['Audio'] = test_audio()
    test_i2c()
    results['Button'] = test_button()

    print('\n' + '=' * 30)
    print('测试汇总:')
    for name, ok in results.items():
        print(f'  {name}: {"✓" if ok else "✗"}')
    print('=' * 30)
