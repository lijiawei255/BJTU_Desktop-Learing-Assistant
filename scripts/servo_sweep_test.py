"""云台舵机全角度范围扫测 — 限位后验证"""
import time
import os
from src.devices import get_pan_servo, get_tilt_servo

STOP_FILE = '/tmp/stop_servo_test'

# 清除之前的停止标记
if os.path.exists(STOP_FILE):
    os.remove(STOP_FILE)

pan = get_pan_servo()
tilt = get_tilt_servo()

print('=' * 40)
print('  云台舵机全角度扫测')
print('  Pan: 30° → 180° (限位验证)')
print('  Tilt: 0° → 140° (限位验证)')
print('  执行: echo stop > /tmp/stop_servo_test 可紧急停止')
print('=' * 40)

def check_stop():
    return os.path.exists(STOP_FILE)

try:
    # ━━ Pan 水平扫测：30→180→90 ━━
    print('\n[Pan] 从30°扫到180°...')
    for angle in range(30, 181, 10):
        if check_stop():
            print('⚠ 收到停止信号!')
            break
        pan.set_angle(angle)
        print(f'  Pan → {angle}°')
        time.sleep(0.4)

    print('\n[Pan] 从180°回到90°...')
    for angle in range(180, 79, -10):
        if check_stop():
            break
        pan.set_angle(angle)
        time.sleep(0.3)

    # ━━ Tilt 俯仰扫测：0→140→45 ━━
    print('\n[Tilt] 从0°扫到140°...')
    for angle in range(0, 141, 10):
        if check_stop():
            print('⚠ 收到停止信号!')
            break
        tilt.set_angle(angle)
        print(f'  Tilt → {angle}°')
        time.sleep(0.4)

    print('\n[Tilt] 从140°回到45°...')
    for angle in range(140, 34, -10):
        if check_stop():
            break
        tilt.set_angle(angle)
        time.sleep(0.3)

finally:
    # 恢复初始角度
    print('\n恢复初始位置...')
    pan.set_angle(90)
    tilt.set_angle(45)
    print('Pan=90° Tilt=45°')
    # 清理
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
    print('扫测结束')
