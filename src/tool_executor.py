"""工具函数执行器 — 执行LLM请求的函数调用，管理专注模式生命周期

M7重构: 状态管理委托给 StateController，ToolExecutor 专注于设备编排和回调绑定
"""

import json
from typing import Dict, Any

from src.config import config
from src.devices import (
    get_box_servo_left, get_box_servo_right, get_pan_servo, get_tilt_servo,
    get_ir_sensor, get_led, get_camera,
)
from src.state_controller import StateController, FocusState
from src.utils.logger import setup_logger

logger = setup_logger("tools")


class ToolExecutor:
    """
    工具函数执行器 + 专注模式设备编排

    M7 重构后:
    - 状态管理完全委托给 StateController（state_controller.py）
    - ToolExecutor 专注于: 设备控制 + 回调绑定 + LLM工具接口
    - 保留 focus_active / focus_paused 等旧属性以向后兼容（映射到 StateController）
    """

    def __init__(self):
        # ── 硬件设备（Mock 或 Real，由 config 决定） ──
        self.box_servo_left = get_box_servo_left()
        self.box_servo_right = get_box_servo_right()
        self.ir_sensor = get_ir_sensor()
        self.led = get_led()

        # 摄像头云台舵机 + 摄像头
        self.pan_servo = get_pan_servo()
        self.tilt_servo = get_tilt_servo()
        self.camera = get_camera(self.pan_servo, self.tilt_servo)
        self.camera.on_distracted = self._on_distraction

        # ── M7: 状态机控制器（替代旧的布尔标志） ──
        self.state = StateController()

        # ── 绑定状态机回调到设备操作 ──
        self._bind_state_callbacks()

        # ── 用户称呼 ──
        self.user_nickname = config.get("system.nickname", "博士")

        logger.info("ToolExecutor 初始化完成 (M7 StateController 集成)")

    # ═══════════════════════════════════════════════════════════
    # 回调绑定 — 将 StateController 事件连接到实际设备
    # ═══════════════════════════════════════════════════════════

    def _bind_state_callbacks(self):
        """绑定状态机的硬件操作回调"""
        # 盒盖控制
        self.state.on_box_open = self._hardware_open_box
        self.state.on_box_close = self._hardware_close_box

        # LED 控制
        self.state.on_led_change = lambda color, pattern: self.led.set_color(color, pattern)

        # 摄像头控制
        self.state.on_camera_start = lambda: self.camera.start_tracking()
        self.state.on_camera_stop = lambda: self.camera.stop_tracking()

        # 状态日志
        self.state.on_state_change = lambda old, new: logger.info(
            f"专注状态变化: {old} -> {new}"
        )

        logger.info("StateController 回调已绑定到设备层")

    def _hardware_open_box(self):
        """硬件操作：打开手机盒盖"""
        open_angle = config.get("servo.box_open_angle", 0)
        self.box_servo_left.set_angle(open_angle)
        self.box_servo_right.set_angle(open_angle)
        logger.info("硬件: 盒盖已打开")

    def _hardware_close_box(self):
        """硬件操作：关闭手机盒盖"""
        close_angle = config.get("servo.box_close_angle", 90)
        self.box_servo_left.set_angle(close_angle)
        self.box_servo_right.set_angle(close_angle)
        logger.info("硬件: 盒盖已关闭")

    # ═══════════════════════════════════════════════════════════
    # 向后兼容属性 — 映射到 StateController
    # ═══════════════════════════════════════════════════════════

    @property
    def focus_active(self) -> bool:
        """[兼容] 专注模式是否处于活跃状态"""
        return self.state.is_active

    @focus_active.setter
    def focus_active(self, value: bool):
        """[兼容] 设置活跃状态 — 仅用于测试"""
        if not value:
            self.state.reset()

    @property
    def focus_paused(self) -> bool:
        """[兼容] 是否暂停中"""
        return self.state.is_paused

    @focus_paused.setter
    def focus_paused(self, value: bool):
        """[兼容] 设置暂停状态 — 仅用于测试"""
        pass  # 状态由 StateController 内部管理

    @property
    def focus_duration(self) -> int:
        """[兼容] 专注总时长（秒）"""
        return self.state.focus_duration_sec

    @focus_duration.setter
    def focus_duration(self, value: int):
        """[兼容] 设置总时长"""
        self.state.focus_duration_sec = value

    @property
    def focus_remaining(self) -> int:
        """[兼容] 剩余秒数"""
        return self.state.remaining_seconds

    @focus_remaining.setter
    def focus_remaining(self, value: int):
        """[兼容] 设置剩余秒数 — 通过 timer"""
        pass  # 由 FocusTimer 管理

    @property
    def timer(self):
        """[兼容] 暴露 FocusTimer 供测试使用"""
        return self.state.timer

    @property
    def timer_expired(self) -> bool:
        """[兼容] 计时器是否到期"""
        return self.state.timer_expired

    @timer_expired.setter
    def timer_expired(self, value: bool):
        self.state.timer_expired = value

    def force_timer_expire(self):
        """[兼容] 测试钩子：立即触发计时器到期"""
        self.state.force_timer_expire()

    # ═══════════════════════════════════════════════════════════
    # 走神检测回调
    # ═══════════════════════════════════════════════════════════

    def _on_distraction(self, reason: str):
        """走神检测回调（由摄像头跟踪线程调用）"""
        if reason == "eyes_closed":
            logger.info("走神检测: 闭眼")
        elif reason == "looking_away":
            logger.info("走神检测: 视线偏离")

    # ═══════════════════════════════════════════════════════════
    # 工具调度器 — LLM Function Calling 入口
    # ═══════════════════════════════════════════════════════════

    def execute(self, function_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行 LLM 请求的工具函数

        Args:
            function_name: 函数名（对应 AVAILABLE_TOOLS 中的定义）
            arguments: 函数参数

        Returns:
            {"success": bool, "result": str}
        """
        logger.info(f"执行工具: {function_name}({arguments})")
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
                return {"success": False, "result": f"未知函数: {function_name}"}
        except Exception as e:
            logger.error(f"工具执行失败: {e}")
            return {"success": False, "result": f"执行出错: {str(e)}"}

    # ═══════════════════════════════════════════════════════════
    # 各工具实现 — 委托给 StateController
    # ═══════════════════════════════════════════════════════════

    def _set_focus_mode(self, args: Dict) -> Dict:
        """
        开启专注模式:
        1. StateController.start_focus() 验证并转移到 WAITING_PHONE
        2. 等待IR传感器检测手机放入
        3. 手机放入后 -> StateController.phone_inserted() 完成转移
        """
        duration = args.get("duration_minutes",
                            config.get("focus_mode.default_duration_minutes", 40))

        # 通过状态机验证并开始
        result = self.state.start_focus(duration)
        if not result["success"]:
            return result

        # 等待用户放入手机（阻塞，带超时）
        timeout = config.get("focus_mode.waiting_phone_timeout_seconds", 60)
        phone_detected = self.ir_sensor.wait_for_phone(timeout_seconds=timeout)

        if not phone_detected:
            # 超时：取消专注
            self.state.cancel_focus()
            return {
                "success": False,
                "result": "没有检测到手机放入盒子，请把手机放进去后再说一次。",
            }

        # 手机已放入 -> 关盖 -> 开始计时
        return self.state.phone_inserted()

    def _end_focus_mode(self, args: Dict) -> Dict:
        """
        结束专注模式: FOCUSING -> COMPLETED -> IDLE
        支持 _auto_expired 参数区分自然到期 vs 用户主动结束
        """
        auto_expired = args.get("_auto_expired", False)
        return self.state.complete_focus(auto_expired=auto_expired)

    def _open_phone_box(self, args: Dict) -> Dict:
        """
        临时暂停专注（打开手机盒）: FOCUSING -> PAUSED
        流程: 暂停计时 -> 开盖 -> 等取走 -> 等放回 -> 关盖恢复
        """
        reason = args.get("reason", "temporary")

        if reason == "temporary":
            if not self.state.is_focusing:
                return {"success": False, "result": "当前没有进行中的专注模式，无需暂停。"}

            # 通过状态机暂停
            result = self.state.request_pause(reason)
            if not result["success"]:
                return result

            # 等待用户取走手机
            self.ir_sensor.wait_for_phone_removed(timeout_seconds=30)

            # 等待用户放回手机
            phone_back = self.ir_sensor.wait_for_phone(timeout_seconds=120)
            if not phone_back:
                # 超时：自动结束专注
                self.state.cancel_focus()
                self.led.set_color("blue", "breath")
                return {
                    "success": True,
                    "result": "好像很久没有放回手机，专注模式已自动结束。需要时再叫我哦。",
                }

            # 手机放回 -> 关盖恢复
            return self.state.phone_inserted()

        else:
            # reason == "complete": 兼容旧的结束方式 -> 直接结束
            return self.state.complete_focus(auto_expired=False)

    def _get_focus_status(self) -> Dict:
        """查询专注模式状态"""
        if self.state.is_idle:
            return {"success": True, "result": "当前没有进行专注模式。"}

        remaining = self.state.timer.remaining
        minutes = remaining // 60
        seconds = remaining % 60

        if self.state.is_paused:
            return {
                "success": True,
                "result": f"专注模式暂停中，还剩{minutes}分{seconds}秒。",
            }
        elif self.state.is_focusing:
            return {
                "success": True,
                "result": f"专注模式进行中，还剩{minutes}分{seconds}秒。",
            }
        else:
            return {
                "success": True,
                "result": f"当前状态: {self.state.state_name}",
            }

    def _set_user_nickname(self, args: Dict) -> Dict:
        """设置用户称呼"""
        nickname = args.get("nickname", "博士")
        self.user_nickname = nickname
        config.set("system.nickname", nickname)
        return {"success": True, "result": f"好的，以后我就叫你{nickname}了。"}

    # ═══════════════════════════════════════════════════════════
    # LLM 状态查询
    # ═══════════════════════════════════════════════════════════

    def get_status_for_llm(self) -> str:
        """生成当前状态摘要，供LLM system prompt使用"""
        return self.state.get_status_for_llm()
