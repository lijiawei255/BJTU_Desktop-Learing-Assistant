"""工具函数执行器 - 执行LLM请求的函数调用，管理专注模式生命周期"""

import json
import threading
import time
from typing import Dict, Any, Optional
from src.config import config
from src.devices import (
    get_box_servo_left, get_box_servo_right, get_pan_servo, get_tilt_servo,
    get_ir_sensor, get_led, get_camera,
)
from src.utils.logger import setup_logger

logger = setup_logger("tools")


class FocusTimer:
    """轻量级专注计时器，独立daemon线程倒计时"""

    def __init__(self, on_expire: callable):
        self._remaining = 0
        self._paused = False
        self._running = False
        self._expired = False
        self._lock = threading.Lock()
        self._on_expire = on_expire
        self._thread: Optional[threading.Thread] = None

    def start(self, duration_seconds: int):
        self.stop()
        self._remaining = duration_seconds
        self._paused = False
        self._running = True
        self._expired = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(f"FocusTimer started: {duration_seconds}s")

    def pause(self):
        self._paused = True
        logger.info("FocusTimer paused")

    def resume(self):
        self._paused = False
        logger.info("FocusTimer resumed")

    def stop(self):
        self._running = False
        self._paused = False
        self._expired = False
        with self._lock:
            self._remaining = 0
        logger.info("FocusTimer stopped")

    @property
    def remaining(self) -> int:
        with self._lock:
            return self._remaining

    @property
    def expired(self) -> bool:
        return self._expired

    @property
    def is_running(self) -> bool:
        return self._running and not self._paused

    def _run(self):
        while self._running and self._remaining > 0:
            time.sleep(1)
            if not self._paused and self._running:
                with self._lock:
                    self._remaining -= 1
                if self._remaining <= 0:
                    self._expired = True
                    self._running = False
                    logger.info("FocusTimer EXPIRED!")
                    try:
                        self._on_expire()
                    except Exception as e:
                        logger.error(f"FocusTimer on_expire callback failed: {e}")
                    break


class ToolExecutor:
    """执行LLM调用的工具函数，管理专注模式生命周期"""

    def __init__(self):
        self.box_servo_left = get_box_servo_left()
        self.box_servo_right = get_box_servo_right()
        self.ir_sensor = get_ir_sensor()
        self.led = get_led()

        # 摄像头云台舵机 + 摄像头（含PID跟踪 + 走神检测）
        self.pan_servo = get_pan_servo()
        self.tilt_servo = get_tilt_servo()
        self.camera = get_camera(self.pan_servo, self.tilt_servo)
        self.camera.on_distracted = self._on_distraction

        self.focus_duration = 0
        self.focus_remaining = 0
        self.focus_active = False
        self.focus_paused = False
        self.user_nickname = config.get("system.nickname", "博士")

        self.timer = FocusTimer(on_expire=self._on_timer_expire)
        self._timer_expired_flag = False

        logger.info("ToolExecutor initialized")

    # ── Timer ──────────────────────────────────────────────

    def _on_timer_expire(self):
        self._timer_expired_flag = True
        logger.info("Timer expiry flag set")

    @property
    def timer_expired(self) -> bool:
        return self._timer_expired_flag

    @timer_expired.setter
    def timer_expired(self, value: bool):
        self._timer_expired_flag = value

    def force_timer_expire(self):
        """测试钩子：立即触发计时器到期（模拟时间到）"""
        self.timer.stop()
        self._timer_expired_flag = True
        logger.info("Timer forcibly expired (test hook)")

    # ── Distraction callback ────────────────────────────────

    def _on_distraction(self, reason: str):
        """走神检测回调（由摄像头跟踪线程调用）"""
        if reason == "eyes_closed":
            logger.info("Distraction: eyes closed detected")
        elif reason == "looking_away":
            logger.info("Distraction: looking away detected")

    # ── Tool dispatcher ────────────────────────────────────

    def execute(self, function_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Executing tool: {function_name}({arguments})")
        try:
            if function_name == "set_focus_mode":
                return self._set_focus_mode(arguments)
            elif function_name == "end_focus_mode":
                return self._end_focus_mode(arguments)
            elif function_name == "open_phone_box":
                return self._open_phone_box(arguments)
            elif function_name == "get_focus_status":
                return self._get_focus_status()
            elif function_name == "set_user_nickname":
                return self._set_user_nickname(arguments)
            else:
                return {"success": False, "result": f"Unknown function: {function_name}"}
        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            return {"success": False, "result": f"Error: {str(e)}"}

    # ── Focus mode handlers ────────────────────────────────

    def _set_focus_mode(self, args: Dict) -> Dict:
        """进入专注模式：冲突检测 → 提示放手机 → IR等待 → 关盖 → 开始计时"""
        if self.focus_active:
            remaining_min = self.timer.remaining // 60
            return {
                "success": False,
                "result": f"当前专注模式还在进行中，还剩{remaining_min}分钟。请先结束当前专注模式，再说出你想要的新时长。",
            }

        duration = args.get("duration_minutes", config.get("focus_mode.default_duration_minutes", 40))
        self.focus_duration = duration
        self.focus_remaining = duration * 60

        # 等待用户放手机
        phone_detected = self.ir_sensor.wait_for_phone(timeout_seconds=60)
        if not phone_detected:
            self.focus_active = False
            return {
                "success": False,
                "result": "没有检测到手机放入盒子，请把手机放进去后再说一次。",
            }

        # 手机已放入，关盖
        close_angle = config.get("servo.box_close_angle", 90)
        self.box_servo_left.set_angle(close_angle)
        self.box_servo_right.set_angle(close_angle)
        self.led.set_color("green", "solid")

        # 开始计时 + 启动摄像头跟踪
        self.focus_active = True
        self.focus_paused = False
        self.timer.start(duration * 60)
        self.camera.start_tracking()

        return {
            "success": True,
            "result": f"专注模式已开启，时长{duration}分钟。手机已锁好，加油哦！",
        }

    def _end_focus_mode(self, args: Dict) -> Dict:
        """结束专注模式：停止计时 → 开盖 → 恢复硬件"""
        if not self.focus_active:
            return {"success": False, "result": "当前没有进行中的专注模式哦。"}

        self.timer.stop()
        self._timer_expired_flag = False
        self.focus_active = False
        self.focus_paused = False
        self.focus_remaining = 0

        self.camera.stop_tracking()

        open_angle = config.get("servo.box_open_angle", 0)
        self.box_servo_left.set_angle(open_angle)
        self.box_servo_right.set_angle(open_angle)
        self.led.set_color("blue", "breath")

        # 区分自然到期 vs 用户主动结束
        if args.get("_auto_expired"):
            return {"success": True, "result": "专注时间到！辛苦啦，起来活动一下吧。"}
        return {"success": True, "result": "专注模式已结束，盒盖已打开。辛苦啦！"}

    def _open_phone_box(self, args: Dict) -> Dict:
        """暂停专注：暂停计时 → 开盖 → 等取走 → 等放回 → 恢复"""
        reason = args.get("reason", "temporary")

        if reason == "temporary":
            if not self.focus_active:
                return {"success": False, "result": "当前没有进行中的专注模式，无需暂停。"}

            # 暂停计时 + 停止跟踪
            self.timer.pause()
            self.focus_paused = True
            self.camera.stop_tracking()

            # 开盖
            open_angle = config.get("servo.box_open_angle", 0)
            self.box_servo_left.set_angle(open_angle)
            self.box_servo_right.set_angle(open_angle)
            self.led.set_color("yellow", "solid")

            # 等待用户取走手机（确认离开）
            self.ir_sensor.wait_for_phone_removed(timeout_seconds=30)

            # 等待用户放回手机
            phone_back = self.ir_sensor.wait_for_phone(timeout_seconds=120)
            if not phone_back:
                # 超时：自动结束专注
                self.timer.stop()
                self.focus_active = False
                self.focus_paused = False
                self.led.set_color("blue", "breath")
                return {
                    "success": True,
                    "result": "好像很久没有放回手机，专注模式已自动结束。需要时再叫我哦。",
                }

            # 手机放回，关盖恢复
            close_angle = config.get("servo.box_close_angle", 90)
            self.box_servo_left.set_angle(close_angle)
            self.box_servo_right.set_angle(close_angle)
            self.led.set_color("green", "solid")

            self.timer.resume()
            self.focus_paused = False
            self.camera.start_tracking()

            return {
                "success": True,
                "result": "欢迎回来，手机已锁好，继续专注吧。",
            }
        else:
            # reason == "complete"：兼容旧的结束方式
            return self._end_focus_mode({})

    # ── Status tools ───────────────────────────────────────

    def _get_focus_status(self) -> Dict:
        if not self.focus_active:
            return {"success": True, "result": "当前没有进行专注模式。"}

        remaining = self.timer.remaining
        minutes = remaining // 60
        seconds = remaining % 60
        status = "暂停中" if self.focus_paused else "进行中"
        return {
            "success": True,
            "result": f"专注模式{status}，还剩{minutes}分{seconds}秒。",
        }

    def _set_user_nickname(self, args: Dict) -> Dict:
        nickname = args.get("nickname", "博士")
        self.user_nickname = nickname
        config.set("system.nickname", nickname)
        return {"success": True, "result": f"好的，以后我就叫你{nickname}了。"}

    def get_status_for_llm(self) -> str:
        if self.focus_active:
            remaining = self.timer.remaining
            mins = remaining // 60
            state = "暂停中" if self.focus_paused else "进行中"
            return f"专注模式{state}，剩余{mins}分钟"
        return "未开启专注模式"
