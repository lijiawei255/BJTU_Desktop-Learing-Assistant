"""OV5647 Camera Module — PID人脸跟踪 + 自动扫描 + MediaPipe走神检测"""

import time
import math
import threading
from typing import Optional, Tuple, Callable

from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("camera")


# ═══════════════════════════════════════════════════════════════
# PID Controller
# ═══════════════════════════════════════════════════════════════

class PIDController:
    """离散PID控制器"""

    def __init__(self, kp: float, ki: float, kd: float, setpoint: float = 0.0):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint = setpoint
        self._integral = 0.0
        self._prev_error = 0.0
        self._last_time = None

    def update(self, measured: float, dt: float = None) -> float:
        """计算控制输出"""
        now = time.time()
        if self._last_time is None:
            self._last_time = now
            return 0.0
        if dt is None:
            dt = now - self._last_time
        self._last_time = now

        error = self.setpoint - measured
        self._integral += error * dt
        derivative = (error - self._prev_error) / dt if dt > 0 else 0.0
        self._prev_error = error

        return self.kp * error + self.ki * self._integral + self.kd * derivative

    def reset(self):
        self._integral = 0.0
        self._prev_error = 0.0
        self._last_time = None


# ═══════════════════════════════════════════════════════════════
# Face Tracker — PID跟踪 + 自动扫描
# ═══════════════════════════════════════════════════════════════

class FaceTracker:
    """人脸跟踪器：PID控制云台舵机 + 丢失后自动扫描"""

    def __init__(self, pan_servo, tilt_servo):
        self.pan_servo = pan_servo
        self.tilt_servo = tilt_servo

        # PID
        pan_pid_cfg = config.get("vision.pan_pid", {})
        tilt_pid_cfg = config.get("vision.tilt_pid", {})
        self.pan_pid = PIDController(
            pan_pid_cfg.get("kp", 0.08), pan_pid_cfg.get("ki", 0.01), pan_pid_cfg.get("kd", 0.02)
        )
        self.tilt_pid = PIDController(
            tilt_pid_cfg.get("kp", 0.06), tilt_pid_cfg.get("ki", 0.008), tilt_pid_cfg.get("kd", 0.015)
        )

        # 范围与死区
        self.pan_range = config.get("vision.pan_range", [0, 180])
        self.tilt_range = config.get("vision.tilt_range", [0, 90])
        self.dead_x = config.get("vision.dead_zone_x", 40)
        self.dead_y = config.get("vision.dead_zone_y", 30)

        # 默认位置
        self.default_pan = config.get("vision.default_pan_angle", 90)
        self.default_tilt = config.get("vision.default_tilt_angle", 45)

        # 扫描状态
        self._scanning = False
        self._scan_direction = 1  # 1=右, -1=左
        self._scan_pan = self.default_pan
        self._scan_step = config.get("vision.scan_step_degrees", 5)
        self._scan_delay = config.get("vision.scan_delay_ms", 200) / 1000.0
        self._last_scan_time = 0.0

        # 丢脸计时
        self._face_lost_time = None
        self._face_lost_timeout = config.get("vision.face_lost_timeout", 10)

        # 当前角度
        self.current_pan = self.default_pan
        self.current_tilt = self.default_tilt

        # 移动到默认位置
        self.pan_servo.set_angle(self.default_pan)
        self.tilt_servo.set_angle(self.default_tilt)
        logger.info(
            f"FaceTracker ready: pan=[{self.pan_range}], tilt=[{self.tilt_range}], "
            f"dead=({self.dead_x},{self.dead_y}), default=({self.default_pan},{self.default_tilt})"
        )

    def update(self, face_rect: Optional[Tuple[int, int, int, int]],
               frame_width: int, frame_height: int) -> bool:
        """
        每帧调用。传入人脸矩形 (x, y, w, h) 或 None。
        返回 True=正在跟踪, False=人脸丢失。
        """
        frame_cx = frame_width / 2
        frame_cy = frame_height / 2

        if face_rect is not None:
            # ━━ 有人脸：PID跟踪 ━━
            self._scanning = False
            self._face_lost_time = None
            fx, fy, fw, fh = face_rect
            face_cx = fx + fw / 2
            face_cy = fy + fh / 2

            error_x = face_cx - frame_cx
            error_y = face_cy - frame_cy

            # 死区检查 — PID setpoint=画面中心, measured=人脸中心
            if abs(error_x) > self.dead_x:
                self.pan_pid.setpoint = frame_cx
                pan_correction = self.pan_pid.update(face_cx)
                self.current_pan = max(self.pan_range[0], min(self.pan_range[1],
                                         self.current_pan - pan_correction * 0.05))
                self.pan_servo.set_angle(self.current_pan)

            if abs(error_y) > self.dead_y:
                self.tilt_pid.setpoint = frame_cy
                tilt_correction = self.tilt_pid.update(face_cy)
                self.current_tilt = max(self.tilt_range[0], min(self.tilt_range[1],
                                          self.current_tilt - tilt_correction * 0.05))
                self.tilt_servo.set_angle(self.current_tilt)

            return True

        else:
            # ━━ 无人脸：倒计时 → 自动扫描 ━━
            now = time.time()
            if self._face_lost_time is None:
                self._face_lost_time = now

            if now - self._face_lost_time > self._face_lost_timeout:
                self._auto_scan()

            return False

    def _auto_scan(self):
        """水平循环扫描，直到重新捕捉到人脸"""
        if not self._scanning:
            self._scanning = True
            self._scan_pan = self.current_pan
            self._scan_direction = 1
            self.pan_pid.reset()
            self.tilt_pid.reset()
            logger.info("Face lost — starting auto-scan")

        now = time.time()
        if now - self._last_scan_time < self._scan_delay:
            return
        self._last_scan_time = now

        self._scan_pan += self._scan_step * self._scan_direction

        # 到达边界反向
        if self._scan_pan >= self.pan_range[1]:
            self._scan_pan = self.pan_range[1]
            self._scan_direction = -1
        elif self._scan_pan <= self.pan_range[0]:
            self._scan_pan = self.pan_range[0]
            self._scan_direction = 1

        self.current_pan = self._scan_pan
        self.pan_servo.set_angle(self.current_pan)

    def stop(self):
        """停止跟踪，回到默认位置"""
        self._scanning = False
        self.pan_pid.reset()
        self.tilt_pid.reset()
        self.pan_servo.set_angle(self.default_pan)
        self.tilt_servo.set_angle(self.default_tilt)
        self.current_pan = self.default_pan
        self.current_tilt = self.default_tilt
        logger.info(f"FaceTracker stopped → default position ({self.default_pan}, {self.default_tilt})")


# ═══════════════════════════════════════════════════════════════
# Distraction Detector — MediaPipe Face Mesh
# ═══════════════════════════════════════════════════════════════

class DistractionDetector:
    """基于MediaPipe Face Mesh的走神/闭眼/转头检测"""

    # MediaPipe 眼部关键点索引
    LEFT_EYE  = [33, 160, 158, 133, 153, 144]    # 左眼外→内
    RIGHT_EYE = [362, 385, 387, 263, 373, 380]    # 右眼外→内

    # 头部姿态估算关键点
    NOSE_TIP       = 1
    CHIN           = 152
    LEFT_EYE_INNER = 133
    RIGHT_EYE_INNER = 362
    LEFT_MOUTH     = 61
    RIGHT_MOUTH    = 291

    def __init__(self):
        self.ear_threshold = config.get("vision.ear_threshold", 0.2)
        self.confirm_frames = config.get("vision.distraction_confirm_frames", 10)
        self.yaw_threshold = config.get("vision.head_yaw_threshold", 20)
        self.pitch_threshold = config.get("vision.head_pitch_threshold", 15)

        self._eyes_closed_count = 0
        self._looking_away_count = 0
        self._face_mesh = None  # 懒加载

        self.is_eyes_closed = False
        self.is_looking_away = False

        logger.info(
            f"DistractionDetector ready: ear<{self.ear_threshold}, "
            f"yaw>{self.yaw_threshold}°, confirm={self.confirm_frames}frames"
        )

    def _init_face_mesh(self) -> bool:
        """初始化MediaPipe，返回是否可用"""
        if self._face_mesh is None:
            try:
                import mediapipe as mp
                self._face_mesh = mp.solutions.face_mesh.FaceMesh(
                    static_image_mode=False,
                    max_num_faces=1,
                    refine_landmarks=True,
                    min_detection_confidence=0.4,
                    min_tracking_confidence=0.4,
                )
            except ImportError:
                logger.warning("MediaPipe not available — distraction detection disabled")
                self._face_mesh = False  # 标记为不可用
        return self._face_mesh is not False

    def analyze(self, frame) -> dict:
        """
        分析一帧，返回走神状态。
        frame: RGB numpy array (H, W, 3) 或 None
        返回: dict with eyes_closed, looking_away, ear, yaw, pitch, distracted
        """
        result = {
            "eyes_closed": False, "looking_away": False,
            "ear": 1.0, "yaw": 0.0, "pitch": 0.0, "distracted": False,
        }

        if frame is None:
            return result
        if not self._init_face_mesh():
            return result

        import numpy as np

        rgb = frame if frame.shape[-1] == 3 else frame
        h, w = rgb.shape[:2]

        mesh_result = self._face_mesh.process(rgb)
        if not mesh_result.multi_face_landmarks:
            return result

        landmarks = mesh_result.multi_face_landmarks[0]
        pts = np.array([(lm.x * w, lm.y * h, lm.z * w) for lm in landmarks.landmark])

        # ━━ Eye Aspect Ratio (EAR) ━━
        left_ear = self._calc_ear(pts, self.LEFT_EYE)
        right_ear = self._calc_ear(pts, self.RIGHT_EYE)
        ear = (left_ear + right_ear) / 2.0
        result["ear"] = ear

        if ear < self.ear_threshold:
            self._eyes_closed_count += 1
        else:
            self._eyes_closed_count = max(0, self._eyes_closed_count - 1)

        result["eyes_closed"] = self._eyes_closed_count >= self.confirm_frames
        self.is_eyes_closed = result["eyes_closed"]

        # ━━ Head Pose — 简化PnP估算 ━━
        yaw, pitch = self._estimate_head_pose(pts, w, h)
        result["yaw"] = yaw
        result["pitch"] = pitch

        if abs(yaw) > self.yaw_threshold or abs(pitch) > self.pitch_threshold:
            self._looking_away_count += 1
        else:
            self._looking_away_count = max(0, self._looking_away_count - 1)

        result["looking_away"] = self._looking_away_count >= self.confirm_frames
        self.is_looking_away = result["looking_away"]

        result["distracted"] = result["eyes_closed"] or result["looking_away"]
        return result

    def _calc_ear(self, pts, indices) -> float:
        """计算眼睛纵横比 (Eye Aspect Ratio)"""
        import numpy as np
        p = pts[indices]
        # EAR = (|p1-p5| + |p2-p4|) / (2 * |p0-p3|)
        vertical = np.linalg.norm(p[1] - p[5]) + np.linalg.norm(p[2] - p[4])
        horizontal = 2.0 * np.linalg.norm(p[0] - p[3])
        return vertical / horizontal if horizontal > 0 else 0.0

    def _estimate_head_pose(self, pts, w, h) -> Tuple[float, float]:
        """简化头部姿态估算，返回 (yaw_deg, pitch_deg)"""
        import numpy as np

        # 关键3D点（世界坐标，毫米）
        model_pts = np.array([
            (0.0, 0.0, 0.0),         # 鼻尖
            (0.0, -63.6, -12.5),      # 下巴
            (-34.0, 32.6, -24.2),     # 左眼内角
            (34.0, 32.6, -24.2),      # 右眼内角
            (-28.5, -28.0, -11.8),    # 左嘴角
            (28.5, -28.0, -11.8),     # 右嘴角
        ], dtype=np.float64)

        image_pts = np.array([
            pts[self.NOSE_TIP][:2],
            pts[self.CHIN][:2],
            pts[self.LEFT_EYE_INNER][:2],
            pts[self.RIGHT_EYE_INNER][:2],
            pts[self.LEFT_MOUTH][:2],
            pts[self.RIGHT_MOUTH][:2],
        ], dtype=np.float64)

        # 相机内参（简化）
        focal = w
        center = (w / 2, h / 2)
        camera_matrix = np.array([
            [focal, 0, center[0]],
            [0, focal, center[1]],
            [0, 0, 1],
        ], dtype=np.float64)

        dist_coeffs = np.zeros((4, 1))
        try:
            import cv2
            success, rvec, _ = cv2.solvePnP(
                model_pts, image_pts, camera_matrix, dist_coeffs,
                flags=cv2.SOLVEPNP_ITERATIVE
            )
            if success:
                rot_mat, _ = cv2.Rodrigues(rvec)
                sy = math.sqrt(rot_mat[0, 0] ** 2 + rot_mat[1, 0] ** 2)
                pitch = math.degrees(math.atan2(-rot_mat[2, 0], sy))
                yaw = math.degrees(math.atan2(rot_mat[1, 0], rot_mat[0, 0]))
                return yaw, pitch
        except Exception as e:
            logger.debug(f"Head pose estimation failed: {e}")

        return 0.0, 0.0

    def reset(self):
        self._eyes_closed_count = 0
        self._looking_away_count = 0
        self.is_eyes_closed = False
        self.is_looking_away = False


# ═══════════════════════════════════════════════════════════════
# Camera Controller — 集成跟踪 + 走神检测
# ═══════════════════════════════════════════════════════════════

class CameraController:
    """OV5647摄像头：PID跟踪 + 自动扫描 + MediaPipe走神检测"""

    def __init__(self, pan_servo=None, tilt_servo=None):
        self.width = config.get("vision.camera_width", 640)
        self.height = config.get("vision.camera_height", 480)
        self.fps = config.get("vision.fps", 15)
        self._running = False
        self._camera = None
        self._face_cascade = None
        self._tracking_thread: Optional[threading.Thread] = None

        # 跟踪与检测
        self.tracker = FaceTracker(pan_servo, tilt_servo) if pan_servo and tilt_servo else None
        self.detector = DistractionDetector()

        # 回调
        self.on_distracted: Optional[Callable[[str], None]] = None  # 走神回调
        self.on_face_found: Optional[Callable[[], None]] = None     # 重新捕捉回调

        logger.info("CameraController created (OV5647 + MediaPipe)")

    def start(self):
        from picamera2 import Picamera2

        self._camera = Picamera2()
        video_config = self._camera.create_video_configuration(
            main={"size": (self.width, self.height), "format": "RGB888"},
            controls={"FrameRate": self.fps},
        )
        self._camera.configure(video_config)
        self._camera.start()
        self._running = True
        logger.info(f"Camera started: {self.width}x{self.height} @ {self.fps}fps")

    def stop(self):
        self.stop_tracking()
        self._running = False
        if self._camera:
            self._camera.stop()
            self._camera = None
        if self.tracker:
            self.tracker.stop()
        logger.info("Camera stopped")

    def capture_frame(self):
        if not self._running or not self._camera:
            return None
        return self._camera.capture_array()

    def detect_faces(self, frame):
        """Haar Cascade人脸检测"""
        import cv2
        if frame is None:
            return []
        if self._face_cascade is None:
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self._face_cascade = cv2.CascadeClassifier(cascade_path)
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        faces = self._face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=4, minSize=(60, 60)
        )
        return faces

    # ── Tracking Loop ──────────────────────────────────────

    def start_tracking(self):
        """启动后台跟踪线程（专注模式开始时调用）"""
        if self._tracking_thread and self._tracking_thread.is_alive():
            return
        if self.tracker is None:
            logger.warning("Cannot track: no pan/tilt servos available")
            return

        self.detector.reset()
        self._running = True
        self._tracking_thread = threading.Thread(target=self._tracking_loop, daemon=True)
        self._tracking_thread.start()
        logger.info("Tracking loop started")

    def stop_tracking(self):
        """停止跟踪线程（专注模式结束时调用）"""
        if self.tracker:
            self.tracker.stop()
        self.detector.reset()

    def _tracking_loop(self):
        """后台跟踪循环：间隔检测人脸 → PID跟踪 → 跳帧走神检测"""
        logger.info("Tracking loop running...")
        prev_lost = False
        frame_count = 0
        detect_interval = config.get("vision.face_detection_interval", 2)
        distract_interval = config.get("vision.distraction_interval_frames", 5)
        last_face_rect = None

        while self._running:
            frame = self.capture_frame()
            if frame is None:
                time.sleep(0.05)
                continue

            frame_count += 1

            # ━━ 跳帧人脸检测（每 detect_interval 帧一次） ━━
            if frame_count % detect_interval == 0:
                faces = self.detect_faces(frame)
                last_face_rect = faces[0] if len(faces) > 0 else None
            face_rect = last_face_rect

            # ━━ PID跟踪 / 扫描（每帧执行，保证平滑） ━━
            if self.tracker:
                tracking = self.tracker.update(
                    face_rect, self.width, self.height
                )
                if tracking and prev_lost:
                    logger.info("Face re-acquired!")
                    if self.on_face_found:
                        self.on_face_found()
                prev_lost = not tracking

            # ━━ 走神检测（跳帧降低CPU，每 distract_interval 帧一次） ━━
            if face_rect is not None and frame_count % distract_interval == 0:
                dist = self.detector.analyze(frame)
                if dist["distracted"] and self.on_distracted:
                    if dist["eyes_closed"]:
                        self.on_distracted("eyes_closed")
                    elif dist["looking_away"]:
                        self.on_distracted("looking_away")

            time.sleep(1.0 / self.fps)

    def close(self):
        self.stop()


# ═══════════════════════════════════════════════════════════════
# Camera Mock — PC模拟
# ═══════════════════════════════════════════════════════════════

class CameraMock:
    """模拟摄像头（PC测试用）"""

    def __init__(self, pan_servo=None, tilt_servo=None):
        self._running = False
        self.width = config.get("vision.camera_width", 640)
        self.height = config.get("vision.camera_height", 480)
        self.fps = config.get("vision.fps", 15)
        self.tracker = FaceTracker(pan_servo, tilt_servo) if pan_servo and tilt_servo else None
        self.detector = DistractionDetector()

        # 模拟状态
        self._sim_face_present = True
        self._sim_face_x = self.width // 2
        self._sim_face_y = self.height // 2
        self._sim_eyes_closed = False
        self._sim_looking_away = False
        self._tracking_thread: Optional[threading.Thread] = None

        self.on_distracted: Optional[Callable[[str], None]] = None
        self.on_face_found: Optional[Callable[[], None]] = None

        logger.info("[MOCK] Camera initialized")

    @staticmethod
    def _mediapipe_available():
        try:
            import mediapipe
            return True
        except ImportError:
            return False

    def start(self):
        self._running = True
        logger.info("[MOCK CAMERA] Started")

    def stop(self):
        self.stop_tracking()
        self._running = False
        logger.info("[MOCK CAMERA] Stopped")

    def capture_frame(self):
        return None if not self._running else None

    def detect_faces(self, frame):
        """模拟人脸检测"""
        if not self._sim_face_present:
            return []
        return [(self._sim_face_x - 50, self._sim_face_y - 60, 100, 120)]

    # ── Simulation helpers ──────────────────────────────────

    def simulate_face_moved(self, x: int, y: int):
        self._sim_face_x = x
        self._sim_face_y = y

    def simulate_face_lost(self):
        self._sim_face_present = False

    def simulate_face_found(self):
        self._sim_face_present = True

    def simulate_eyes_closed(self, closed: bool = True):
        self._sim_eyes_closed = closed

    def simulate_looking_away(self, away: bool = True):
        self._sim_looking_away = away

    # ── Tracking ────────────────────────────────────────────

    def start_tracking(self):
        if self._tracking_thread and self._tracking_thread.is_alive():
            return
        self._running = True
        self._tracking_thread = threading.Thread(target=self._mock_tracking_loop, daemon=True)
        self._tracking_thread.start()
        logger.info("[MOCK] Tracking loop started")

    def stop_tracking(self):
        if self.tracker:
            self.tracker.stop()
        if self.detector:
            self.detector.reset()

    def _mock_tracking_loop(self):
        logger.info("[MOCK] Tracking loop running...")
        prev_lost = False
        while self._running:
            face = self.detect_faces(None)
            face_rect = face[0] if face else None
            if self.tracker:
                tracking = self.tracker.update(face_rect, self.width, self.height)
                if tracking and prev_lost:
                    logger.info("[MOCK] Face re-acquired!")
                    if self.on_face_found:
                        self.on_face_found()
                prev_lost = not tracking
            # 模拟走神回调
            if self._sim_eyes_closed and self.on_distracted:
                self.on_distracted("eyes_closed")
            if self._sim_looking_away and self.on_distracted:
                self.on_distracted("looking_away")
            time.sleep(1.0 / self.fps)

    def close(self):
        pass
