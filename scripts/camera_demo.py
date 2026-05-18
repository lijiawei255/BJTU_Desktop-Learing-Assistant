"""摄像头+云台演示录制 — 人脸跟踪框 + 走神检测可视化 + 舵机跟踪

用法: python scripts/camera_demo.py [--duration 30] [--output demos/demo.mp4]
"""
import argparse
import time
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import cv2
import numpy as np
from src.config import config

# 强制真实硬件模式
config.set('mock.enabled', False)
config.set('mock.camera', False)
config.set('mock.servo', False)

WIDTH = config.get('vision.camera_width', 640)
HEIGHT = config.get('vision.camera_height', 480)
FPS = config.get('vision.fps', 15)
FOURCC = cv2.VideoWriter_fourcc(*'mp4v')

LEFT_EYE_IDX  = [33, 160, 158, 133, 153, 144]
RIGHT_EYE_IDX = [362, 385, 387, 263, 373, 380]
IRIS_LEFT  = [468, 469, 470, 471, 472]
IRIS_RIGHT = [473, 474, 475, 476, 477]

def init_face_mesh():
    import mediapipe as mp
    return mp.solutions.face_mesh.FaceMesh(
        static_image_mode=False, max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.4, min_tracking_confidence=0.4,
    )

def init_face_detector():
    return None  # 使用Haar Cascade替代

def draw_face_box(frame, face_rect, tracking):
    if face_rect is None:
        return
    x, y, w, h = face_rect
    color = (0, 255, 0) if tracking else (0, 0, 255)
    thickness = 3 if tracking else 2
    cv2.rectangle(frame, (x, y), (x + w, y + h), color, thickness)
    label = 'FACE TRACKED' if tracking else 'FACE LOST'
    cv2.putText(frame, label, (x, y - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

def draw_eye_landmarks(frame, pts, ear):
    color = (0, 255, 0) if ear > 0.2 else (0, 0, 255)
    for idx in LEFT_EYE_IDX + RIGHT_EYE_IDX:
        if idx < len(pts):
            px, py = int(pts[idx][0]), int(pts[idx][1])
            cv2.circle(frame, (px, py), 2, color, -1)

def draw_eye_outline(frame, pts, indices, color):
    poly = np.array([[int(pts[i][0]), int(pts[i][1])] for i in indices if i < len(pts)], np.int32)
    if len(poly) >= 3:
        cv2.polylines(frame, [poly], True, color, 1)

def draw_iris(pts, frame):
    for idx in IRIS_LEFT + IRIS_RIGHT:
        if idx < len(pts):
            px, py = int(pts[idx][0]), int(pts[idx][1])
            cv2.circle(frame, (px, py), 2, (255, 255, 0), -1)

def draw_head_pose_gauge(frame, yaw, pitch, x, y, size=80):
    cx, cy = x + size // 2, y + size // 2
    cv2.circle(frame, (cx, cy), size // 2, (200, 200, 200), 1)
    cv2.circle(frame, (cx, cy), 3, (200, 200, 200), -1)
    cv2.line(frame, (cx - size // 2, cy), (cx + size // 2, cy), (150, 150, 150), 1)
    cv2.line(frame, (cx, cy - size // 2), (cx, cy + size // 2), (150, 150, 150), 1)
    dx = int(np.clip(yaw / 60 * size // 2, -size // 2, size // 2))
    dy = int(np.clip(-pitch / 40 * size // 2, -size // 2, size // 2))
    cv2.circle(frame, (cx + dx, cy + dy), 6, (0, 165, 255), -1)
    cv2.putText(frame, f'yaw:{yaw:.0f} pit:{pitch:.0f}',
                (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (200, 200, 200), 1)

def draw_status_bar(frame, ear, distracted, eyes_closed, looking_away, fps_val, servo_pan, servo_tilt):
    h, w = frame.shape[:2]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 55), (30, 30, 30), -1)
    # 只对顶栏区域做叠加，不影响人脸区域
    frame[0:55] = cv2.addWeighted(overlay[0:55], 0.85, frame[0:55], 0.15, 0)

    # EAR
    ear_color = (0, 255, 0) if ear > 0.2 else (0, 0, 255)
    cv2.putText(frame, f'EAR:{ear:.2f}', (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, ear_color, 2)

    # 状态
    if distracted:
        status = 'DISTRACTED!' if eyes_closed else 'LOOKING AWAY!'
        cv2.putText(frame, status, (150, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
    else:
        cv2.putText(frame, 'FOCUSED', (150, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

    # 舵机角度
    cv2.putText(frame, f'Pan:{servo_pan:.0f}Tilt:{servo_tilt:.0f}', (w - 160, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 200, 0), 1)

    # FPS
    cv2.putText(frame, f'FPS:{fps_val:.0f}', (w - 160, 50),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)

def draw_tracking_target(frame):
    """画画面中心十字准星（跟踪目标）"""
    h, w = frame.shape[:2]
    cx, cy = w // 2, h // 2
    cv2.line(frame, (cx - 20, cy), (cx + 20, cy), (0, 255, 255), 1)
    cv2.line(frame, (cx, cy - 20), (cx, cy + 20), (0, 255, 255), 1)
    cv2.circle(frame, (cx, cy), 30, (0, 255, 255), 1)

def get_face_rect_from_landmarks(pts, w, h):
    """从MediaPipe 478点人脸网格计算准确的人脸边界框"""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    margin = 20
    x1 = max(0, int(min(xs)) - margin)
    y1 = max(0, int(min(ys)) - margin)
    x2 = min(w, int(max(xs)) + margin)
    y2 = min(h, int(max(ys)) + margin)
    return (x1, y1, x2 - x1, y2 - y1)

def calc_ear(pts, indices):
    p = pts[indices]
    v1 = np.linalg.norm(p[1] - p[5])
    v2 = np.linalg.norm(p[2] - p[4])
    h = 2.0 * np.linalg.norm(p[0] - p[3])
    return (v1 + v2) / h if h > 0 else 0.0

def estimate_head_pose_simple(pts, w):
    left_eye_c = np.mean(pts[LEFT_EYE_IDX[:4]], axis=0)
    right_eye_c = np.mean(pts[RIGHT_EYE_IDX[:4]], axis=0)
    eye_center = (left_eye_c + right_eye_c) / 2.0
    nose = pts[1]
    dx = nose[0] - eye_center[0]
    dy = nose[1] - eye_center[1]
    yaw = np.degrees(np.arctan2(dx, w * 0.3))
    pitch = np.degrees(np.arctan2(dy, w * 0.3))
    return yaw, pitch

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=int, default=30)
    parser.add_argument('--output', type=str, default='demos/camera_demo.mp4')
    args = parser.parse_args()

    print('=' * 60)
    print('  阿米娅 摄像头+云台演示录制（舵机跟踪）')
    print(f'  {WIDTH}x{HEIGHT} @ {FPS}fps  时长: {args.duration}s')
    print('=' * 60)

    # 初始化摄像头
    from picamera2 import Picamera2
    picam2 = Picamera2()
    video_config = picam2.create_video_configuration(
        main={'size': (WIDTH, HEIGHT), 'format': 'RGB888'},
        controls={'FrameRate': FPS},
    )
    picam2.configure(video_config)
    picam2.start()
    time.sleep(1)

    # OpenCV人脸检测 + MediaPipe走神分析
    face_mesh = init_face_mesh()
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    )

    # 初始化舵机 + 人脸跟踪器
    from src.devices import get_pan_servo, get_tilt_servo
    from src.devices.camera import FaceTracker

    pan = get_pan_servo()
    tilt = get_tilt_servo()
    tilt.set_angle(80)
    pan.set_angle(90)

    tracker = FaceTracker(pan, tilt)
    print(f'云台就位: Pan=90 Tilt=80  限位: Pan[{tracker.pan_range}] Tilt[{tracker.tilt_range}]')

    # 输出路径
    out_path = os.path.join(PROJECT_ROOT, args.output)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    writer = cv2.VideoWriter(out_path, FOURCC, FPS, (WIDTH, HEIGHT))
    print(f'录制到: {out_path}\n')

    start_time = time.time()
    frame_count = 0
    detect_interval = 1  # 每帧检测
    last_face_rect = None
    prev_lost = False

    print(f'请做以下动作:')
    print(f'  正视 → 慢慢转头左右看 → 闭眼 → 离开画面 → 回来')
    print(f'  (舵机会跟随你的脸移动!)\n')

    try:
        while time.time() - start_time < args.duration:
            frame = picam2.capture_array()
            if frame is None:
                continue

            # 上下翻转（摄像头倒装校正）
            frame = cv2.flip(frame, 0)
            frame_count += 1
            annot = frame.copy()

            # ━━ 阶段1: 人脸检测 + MediaPipe分析 ━━
            ear = 1.0; yaw = 0.0; pitch = 0.0
            distracted = False; eyes_closed = False; looking_away = False
            pts = None
            face_rect = None

            # 1a. Haar Cascade粗检测
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            faces = face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=4, minSize=(60, 60)
            )
            face_rect = faces[0] if len(faces) > 0 else None

            # 1b. MediaPipe Face Mesh精确分析（每帧运行）
            mesh_result = face_mesh.process(frame)
            if mesh_result.multi_face_landmarks:
                    lm = mesh_result.multi_face_landmarks[0]
                    h, w = frame.shape[:2]
                    pts = np.array([(lm.x * w, lm.y * h, lm.z * w) for lm in lm.landmark])
                    # 用landmarks算精确人脸框（替代Haar粗糙框）
                    face_rect = get_face_rect_from_landmarks(pts, w, h)

                    left_ear = calc_ear(pts, LEFT_EYE_IDX)
                    right_ear = calc_ear(pts, RIGHT_EYE_IDX)
                    ear = (left_ear + right_ear) / 2.0
                    eyes_closed = ear < 0.2

                    yaw, pitch = estimate_head_pose_simple(pts, w)
                    looking_away = abs(yaw) > 20 or abs(pitch) > 15
                    distracted = eyes_closed or looking_away

            tracking = face_rect is not None

            # ━━ 阶段2: 舵机PID跟踪 ━━
            tracker.update(face_rect, WIDTH, HEIGHT)
            if tracking and prev_lost and tracker._face_lost_time is None:
                print(f'  [{frame_count}] 人脸重新捕捉!')
            prev_lost = not tracking

            # ━━ 阶段3: 绘制标注 ━━
            draw_tracking_target(annot)
            draw_face_box(annot, face_rect, tracking)

            if pts is not None:
                draw_eye_landmarks(annot, pts, ear)
                draw_eye_outline(annot, pts, LEFT_EYE_IDX,
                               (0, 255, 0) if ear > 0.2 else (0, 0, 255))
                draw_eye_outline(annot, pts, RIGHT_EYE_IDX,
                               (0, 255, 0) if ear > 0.2 else (0, 0, 255))
                draw_iris(pts, annot)
                cv2.circle(annot, (int(pts[1][0]), int(pts[1][1])), 4, (255, 200, 0), -1)

            draw_head_pose_gauge(annot, yaw, pitch, WIDTH - 120, 75)
            fps_val = frame_count / max(time.time() - start_time, 0.1)
            current_pan = pan.get_angle() if hasattr(pan, 'get_angle') else tracker.current_pan
            current_tilt = tilt.get_angle() if hasattr(tilt, 'get_angle') else tracker.current_tilt
            draw_status_bar(annot, ear, distracted, eyes_closed, looking_away,
                          fps_val, current_pan, current_tilt)

            writer.write(cv2.cvtColor(annot, cv2.COLOR_RGB2BGR))  # annot是RGB, writer要BGR

            elapsed = time.time() - start_time
            if frame_count % 30 == 0:
                print(f'  [{elapsed:.0f}s] 帧={frame_count}  '
                      f'EAR={ear:.2f} Pan={current_pan:.0f} Tilt={current_tilt:.0f} '
                      f'{"⚠走神" if distracted else "✓"}')

    except KeyboardInterrupt:
        print('\n用户中断')

    finally:
        duration = time.time() - start_time
        writer.release()
        picam2.close()
        tracker.stop()

        file_size = os.path.getsize(out_path) / 1024 / 1024
        print(f'\n录制完成: {out_path}')
        print(f'  时长: {duration:.1f}s  帧数: {frame_count}  大小: {file_size:.1f}MB')
        print(f'  限位: Pan={pan.get_angle():.0f} Tilt={tilt.get_angle():.0f}')
        print('=' * 60)

if __name__ == '__main__':
    main()
