"""专注模式状态机 + 系统状态管理 — M7 正式实现

状态转移图:
  IDLE ──[start_focus]──> WAITING_PHONE ──[phone_inserted]──> BOX_CLOSED
  BOX_CLOSED ──[自动]──> FOCUSING <──[phone_inserted]── PAUSED
  FOCUSING ──[phone_removed / request_pause]──> PAUSED
  FOCUSING ──[timer_expired / complete_focus]──> COMPLETED ──[自动]──> IDLE
  WAITING_PHONE ──[cancel_focus]──> IDLE
  FOCUSING ──[cancel_focus]──> IDLE
  PAUSED ──[cancel_focus]──> IDLE
  PAUSED ──[pause_timeout]──> IDLE
"""

import time
import threading
from enum import Enum, auto
from typing import Optional, Callable, Dict

from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger("state")


# ═══════════════════════════════════════════════════════════════
# 状态枚举
# ═══════════════════════════════════════════════════════════════

class FocusState(Enum):
    """专注模式状态枚举"""
    IDLE = auto()              # 空闲，未开启专注
    WAITING_PHONE = auto()     # 等待用户放入手机（IR传感器监听中）
    BOX_CLOSED = auto()        # 手机已放入，盒盖关闭中（短暂过渡态）
    FOCUSING = auto()          # 专注计时中
    PAUSED = auto()            # 暂停（临时开盒取手机）
    COMPLETED = auto()         # 专注完成（计时归零）


class SystemState(Enum):
    """系统级状态枚举 — 用于语音对话循环"""
    IDLE = auto()              # 等待唤醒词
    AWAKE = auto()             # 已唤醒，等待用户说话
    LISTENING = auto()         # 正在录音
    PROCESSING = auto()        # ASR/LLM/TTS 处理中
    WAITING = auto()           # 等待下一轮对话
    DEGRADED = auto()          # 降级模式（连续错误过多）


# ═══════════════════════════════════════════════════════════════
# 状态转移验证表 — 定义合法的状态转移
# ═══════════════════════════════════════════════════════════════

# 格式: { 当前状态: {允许转移到的目标状态} }
_ALLOWED_TRANSITIONS: Dict[FocusState, set] = {
    FocusState.IDLE:          {FocusState.WAITING_PHONE},
    FocusState.WAITING_PHONE: {FocusState.BOX_CLOSED, FocusState.IDLE},
    FocusState.BOX_CLOSED:    {FocusState.FOCUSING},
    FocusState.FOCUSING:      {FocusState.PAUSED, FocusState.COMPLETED, FocusState.IDLE},
    FocusState.PAUSED:        {FocusState.BOX_CLOSED, FocusState.IDLE},
    FocusState.COMPLETED:     {FocusState.IDLE},
}


# ═══════════════════════════════════════════════════════════════
# FocusTimer — 独立守护线程倒计时
# ═══════════════════════════════════════════════════════════════

class FocusTimer:
    """专注计时器：独立daemon线程每秒倒计时，到期触发回调"""

    def __init__(self, on_expire: Callable[[], None]):
        self._remaining: int = 0          # 剩余秒数
        self._paused: bool = False        # 是否暂停中
        self._running: bool = False       # 是否运行中
        self._expired: bool = False       # 是否已到期
        self._lock = threading.Lock()     # 保护 _remaining 的线程锁
        self._on_expire = on_expire       # 到期回调
        self._thread: Optional[threading.Thread] = None

    # ── 属性 ──────────────────────────────────────────────

    @property
    def remaining(self) -> int:
        """剩余秒数（线程安全）"""
        with self._lock:
            return self._remaining

    @property
    def expired(self) -> bool:
        """计时器是否已到期"""
        return self._expired

    @property
    def is_running(self) -> bool:
        """是否正在运行且未暂停"""
        return self._running and not self._paused

    @property
    def is_paused(self) -> bool:
        """是否处于暂停状态"""
        return self._paused

    # ── 控制方法 ──────────────────────────────────────────

    def start(self, duration_seconds: int):
        """启动倒计时（先停止旧计时器）"""
        self.stop()
        self._remaining = duration_seconds
        self._paused = False
        self._running = True
        self._expired = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(f"FocusTimer 启动: {duration_seconds}s ({duration_seconds // 60}分钟)")

    def pause(self):
        """暂停计时"""
        self._paused = True
        logger.info(f"FocusTimer 暂停 (剩余 {self._remaining}s)")

    def resume(self):
        """恢复计时"""
        self._paused = False
        logger.info(f"FocusTimer 恢复 (剩余 {self._remaining}s)")

    def stop(self):
        """停止计时并重置"""
        self._running = False
        self._paused = False
        self._expired = False
        with self._lock:
            self._remaining = 0
        logger.info("FocusTimer 已停止")

    # ── 内部 ──────────────────────────────────────────────

    def _run(self):
        """倒计时循环（在daemon线程中运行）"""
        while self._running and self._remaining > 0:
            time.sleep(1)
            if not self._paused and self._running:
                with self._lock:
                    self._remaining -= 1
                # 剩余时间检查点：到期触发回调
                if self._remaining <= 0:
                    self._expired = True
                    self._running = False
                    logger.info("FocusTimer 时间到！触发到期回调")
                    try:
                        self._on_expire()
                    except Exception as e:
                        logger.error(f"FocusTimer 到期回调异常: {e}")
                    break


# ═══════════════════════════════════════════════════════════════
# StateController — 专注模式状态机
# ═══════════════════════════════════════════════════════════════

class StateController:
    """
    专注模式状态机控制器

    职责:
    - 管理状态转移的合法性验证
    - 维护专注时长、剩余时间、暂停状态
    - 通过回调机制与硬件层解耦
    - 提供心跳 tick() 用于超时检测和提醒

    使用方式:
        sc = StateController()
        sc.on_state_change = lambda old, new: print(f"{old} -> {new}")
        sc.on_tts_speak = lambda text: tts.speak(text)
        sc.on_box_close = lambda: servo.set_angle(90)
        sc.start_focus(25)  # 开始25分钟专注
    """

    def __init__(self):
        # ── 当前状态 ──
        self._state: FocusState = FocusState.IDLE

        # ── 计时数据 ──
        self.focus_duration_sec: int = 0     # 总时长（秒）
        self.pause_start_time: float = 0.0   # 暂停开始时刻 (time.monotonic)
        self._waiting_start_time: float = 0.0 # 等待放手机开始时刻

        # ── 计时器 ──
        self.timer = FocusTimer(on_expire=self._on_timer_expire)
        self._timer_expired_flag: bool = False  # 供外部轮询

        # ── 回调函数（由外部设置） ──
        self.on_state_change: Optional[Callable[[str, str], None]] = None
        """状态变化回调: (旧状态名, 新状态名) -> None"""

        self.on_box_open: Optional[Callable[[], None]] = None
        """开盖回调: 打开手机盒盖"""

        self.on_box_close: Optional[Callable[[], None]] = None
        """关盖回调: 关闭手机盒盖"""

        self.on_tts_speak: Optional[Callable[[str], None]] = None
        """TTS播报回调: (文本) -> None"""

        self.on_led_change: Optional[Callable[[str, str], None]] = None
        """LED状态变化: (颜色, 模式) -> None"""

        self.on_camera_start: Optional[Callable[[], None]] = None
        """摄像头开始跟踪"""

        self.on_camera_stop: Optional[Callable[[], None]] = None
        """摄像头停止跟踪"""

        logger.info("StateController 初始化完成 (IDLE)")

    # ── 属性 ──────────────────────────────────────────────────

    @property
    def state(self) -> FocusState:
        """当前状态"""
        return self._state

    @property
    def state_name(self) -> str:
        """当前状态名称（字符串）"""
        return self._state.name

    @property
    def is_idle(self) -> bool:
        return self._state == FocusState.IDLE

    @property
    def is_focusing(self) -> bool:
        return self._state == FocusState.FOCUSING

    @property
    def is_paused(self) -> bool:
        return self._state == FocusState.PAUSED

    @property
    def is_active(self) -> bool:
        """专注模式是否处于活跃状态（FOCUSING 或 PAUSED 或 BOX_CLOSED）"""
        return self._state in (FocusState.FOCUSING, FocusState.PAUSED,
                                FocusState.BOX_CLOSED, FocusState.WAITING_PHONE)

    @property
    def timer_expired(self) -> bool:
        """计时器是否已到期（供外部轮询）"""
        return self._timer_expired_flag

    @timer_expired.setter
    def timer_expired(self, value: bool):
        self._timer_expired_flag = value

    @property
    def remaining_seconds(self) -> int:
        """剩余专注秒数"""
        return self.timer.remaining

    @property
    def elapsed_seconds(self) -> int:
        """已过秒数"""
        elapsed = self.focus_duration_sec - self.timer.remaining
        return max(0, elapsed)

    # ── 状态转移验证 ──────────────────────────────────────────

    def _can_transition(self, target: FocusState) -> bool:
        """检查从当前状态到目标状态的转移是否合法"""
        allowed = _ALLOWED_TRANSITIONS.get(self._state, set())
        return target in allowed

    def _transition_to(self, new_state: FocusState):
        """
        执行状态转移（带合法性检查）

        Args:
            new_state: 目标状态
        Raises:
            ValueError: 非法状态转移
        """
        if not self._can_transition(new_state):
            allowed_names = [s.name for s in _ALLOWED_TRANSITIONS.get(self._state, set())]
            raise ValueError(
                f"非法状态转移: {self._state.name} -> {new_state.name}。"
                f"允许的目标: {allowed_names}"
            )

        old_name = self._state.name
        self._state = new_state
        logger.info(f"状态转移: {old_name} -> {new_state.name}")

        # 触发回调
        if self.on_state_change:
            try:
                self.on_state_change(old_name, new_state.name)
            except Exception as e:
                logger.error(f"状态变化回调异常: {e}")

    # ── 公开状态转移方法（对应 LLM Function Calling） ──────────

    def start_focus(self, duration_minutes: int) -> Dict[str, object]:
        """
        请求开始专注模式: IDLE -> WAITING_PHONE

        Args:
            duration_minutes: 专注时长（分钟）

        Returns:
            {"success": bool, "result": str}
        """
        # 验证时长范围
        min_dur = config.get("focus_mode.min_duration_minutes", 5)
        max_dur = config.get("focus_mode.max_duration_minutes", 120)
        if duration_minutes < min_dur or duration_minutes > max_dur:
            return {
                "success": False,
                "result": f"专注时长需要在{min_dur}到{max_dur}分钟之间哦。",
            }

        # 状态冲突检查
        if not self.is_idle:
            if self.is_focusing:
                remaining_min = self.timer.remaining // 60
                return {
                    "success": False,
                    "result": f"当前专注模式还在进行中，还剩{remaining_min}分钟。请先结束当前专注模式，再说出你想要的新时长。",
                }
            elif self.is_paused:
                return {
                    "success": False,
                    "result": "专注模式正在暂停中，请先放回手机继续，或者结束当前专注。",
                }
            else:
                return {
                    "success": False,
                    "result": f"当前状态为{self._state.name}，无法开启新的专注。",
                }

        # 记录时长
        self.focus_duration_sec = duration_minutes * 60
        self._waiting_start_time = time.monotonic()

        # 状态转移: IDLE -> WAITING_PHONE
        self._transition_to(FocusState.WAITING_PHONE)

        return {
            "success": True,
            "result": f"专注模式已准备开启，时长{duration_minutes}分钟。请把手机放入盒子中。",
        }

    def phone_inserted(self) -> Dict[str, object]:
        """
        IR传感器检测到手机放入: WAITING_PHONE -> BOX_CLOSED -> FOCUSING
        或: PAUSED -> BOX_CLOSED -> FOCUSING (暂停中放回)

        Returns:
            {"success": bool, "result": str}
        """
        if self._state == FocusState.WAITING_PHONE:
            # 关盖 → 开始计时 → 进入专注
            self._transition_to(FocusState.BOX_CLOSED)
            if self.on_box_close:
                self.on_box_close()

            # BOX_CLOSED 是瞬时过渡态，立即转入 FOCUSING
            self._transition_to(FocusState.FOCUSING)

            # 启动计时器和摄像头跟踪
            self.timer.start(self.focus_duration_sec)
            if self.on_led_change:
                self.on_led_change("green", "solid")
            if self.on_camera_start:
                self.on_camera_start()

            msg = f"手机已锁好，专注模式正式开始，时长{self.focus_duration_sec // 60}分钟。加油哦！"
            if self.on_tts_speak:
                self.on_tts_speak(msg)
            return {"success": True, "result": msg}

        elif self._state == FocusState.PAUSED:
            # 暂停中放回手机 → 关盖 → 恢复专注
            self._transition_to(FocusState.BOX_CLOSED)
            if self.on_box_close:
                self.on_box_close()

            self._transition_to(FocusState.FOCUSING)

            self.timer.resume()
            if self.on_led_change:
                self.on_led_change("green", "solid")
            if self.on_camera_start:
                self.on_camera_start()

            remaining_min = self.timer.remaining // 60
            msg = f"手机已放回，继续专注。还剩{remaining_min}分钟，加油！"
            if self.on_tts_speak:
                self.on_tts_speak(msg)
            return {"success": True, "result": msg}

        else:
            return {"success": False, "result": f"当前状态({self._state.name})下不需要放入手机。"}

    def phone_removed(self) -> Dict[str, object]:
        """
        IR传感器检测到手机取出: FOCUSING -> PAUSED

        Returns:
            {"success": bool, "result": str}
        """
        if self._state == FocusState.FOCUSING:
            # 暂停计时 → 开盖 → 停止跟踪
            self.timer.pause()
            self.pause_start_time = time.monotonic()

            self._transition_to(FocusState.PAUSED)

            if self.on_box_open:
                self.on_box_open()
            if self.on_led_change:
                self.on_led_change("yellow", "solid")
            if self.on_camera_stop:
                self.on_camera_stop()

            msg = "盒盖已打开，专注计时暂停。用完手机后请放回来哦。"
            if self.on_tts_speak:
                self.on_tts_speak(msg)
            return {"success": True, "result": msg}

        return {"success": False, "result": "当前不在专注中，无需打开盒盖。"}

    def request_pause(self, reason: str = "temporary") -> Dict[str, object]:
        """
        用户语音请求暂停（如"我要接电话"）

        Returns:
            {"success": bool, "result": str}
        """
        if self._state == FocusState.FOCUSING:
            self.timer.pause()
            self.pause_start_time = time.monotonic()

            self._transition_to(FocusState.PAUSED)

            if self.on_box_open:
                self.on_box_open()
            if self.on_led_change:
                self.on_led_change("yellow", "solid")
            if self.on_camera_stop:
                self.on_camera_stop()

            msg = "好的，盒盖已打开，专注计时暂停。取走手机吧，记得放回来哦。"
            if self.on_tts_speak:
                self.on_tts_speak(msg)
            return {"success": True, "result": msg}

        return {"success": False, "result": "当前没有进行中的专注模式，无需暂停。"}

    def complete_focus(self, auto_expired: bool = False) -> Dict[str, object]:
        """
        完成专注: FOCUSING -> COMPLETED -> IDLE

        Args:
            auto_expired: True=计时器自然到期, False=用户主动结束

        Returns:
            {"success": bool, "result": str}
        """
        if self._state != FocusState.FOCUSING:
            return {"success": False, "result": "当前没有进行中的专注模式哦。"}

        # 停止计时和硬件
        self.timer.stop()
        self._timer_expired_flag = False

        self._transition_to(FocusState.COMPLETED)

        if self.on_box_open:
            self.on_box_open()
        if self.on_led_change:
            self.on_led_change("blue", "breath")
        if self.on_camera_stop:
            self.on_camera_stop()

        # 区分自然到期 vs 用户主动结束
        if auto_expired:
            msg = "专注时间到！辛苦啦，起来活动一下吧。"
        else:
            msg = "专注模式已结束，盒盖已打开。辛苦啦！"

        if self.on_tts_speak:
            self.on_tts_speak(msg)

        # COMPLETED -> IDLE（自动）
        self._transition_to(FocusState.IDLE)

        return {"success": True, "result": msg}

    def cancel_focus(self) -> Dict[str, object]:
        """
        取消专注模式（用户强制结束或超时取消）
        可以从 WAITING_PHONE / FOCUSING / PAUSED 取消

        Returns:
            {"success": bool, "result": str}
        """
        if self._state in (FocusState.WAITING_PHONE, FocusState.FOCUSING, FocusState.PAUSED):
            self.timer.stop()
            self._timer_expired_flag = False

            self._transition_to(FocusState.IDLE)

            if self.on_box_open:
                self.on_box_open()
            if self.on_led_change:
                self.on_led_change("blue", "breath")
            if self.on_camera_stop:
                self.on_camera_stop()

            return {"success": True, "result": "专注模式已取消。"}

        return {"success": False, "result": "当前没有可取消的专注模式。"}

    # ── Tick (心跳) ───────────────────────────────────────────

    def tick(self) -> Optional[str]:
        """
        状态机心跳 — 由主循环定期调用（或由 FocusTimer 内部处理）
        检查超时条件并触发相应转移

        Returns:
            需要TTS播报的提醒文本，或 None
        """
        now = time.monotonic()

        # 等待放手机超时检查
        if self._state == FocusState.WAITING_PHONE:
            timeout = config.get("focus_mode.waiting_phone_timeout_seconds", 60)
            if now - self._waiting_start_time > timeout:
                self.cancel_focus()
                return "等待超时，专注模式已取消。需要时再叫我哦。"

        # 暂停超时检查
        elif self._state == FocusState.PAUSED:
            pause_timeout = config.get("focus_mode.pause_timeout_minutes", 10) * 60
            if now - self.pause_start_time > pause_timeout:
                self.cancel_focus()
                return "暂停时间太长了，专注模式已自动结束。需要时再叫我哦。"

        # 专注中的提醒点检查（委托给 FocusTimer 的到期回调处理主要逻辑，
        # 这里仅做阶段性提醒）
        elif self._state == FocusState.FOCUSING:
            reminders = config.get("focus_mode.reminder_intervals", [600, 300, 60])
            remaining = self.timer.remaining
            for rem in reminders:
                if remaining == rem:
                    mins = rem // 60
                    return f"还剩{mins}分钟，继续加油哦！"

        return None

    def _on_timer_expire(self):
        """FocusTimer 到期回调（在计时器daemon线程中执行）"""
        self._timer_expired_flag = True
        logger.info("计时器到期标志已设置")

    def force_timer_expire(self):
        """测试钩子：立即触发计时器到期"""
        self.timer.stop()
        self._timer_expired_flag = True
        logger.info("计时器已强制到期 (测试钩子)")

    # ── 状态查询 ──────────────────────────────────────────────

    def get_status_text(self) -> str:
        """获取当前状态的用户可读描述（供LLM system prompt使用）"""
        if self._state == FocusState.IDLE:
            return "未开启专注模式"
        elif self._state == FocusState.WAITING_PHONE:
            return "等待放入手机"
        elif self._state == FocusState.BOX_CLOSED:
            return "盒盖关闭中"
        elif self._state == FocusState.FOCUSING:
            remaining = self.timer.remaining
            mins = remaining // 60
            secs = remaining % 60
            return f"专注模式进行中，剩余{mins}分{secs}秒"
        elif self._state == FocusState.PAUSED:
            elapsed_min = self.elapsed_seconds // 60
            remaining_min = self.timer.remaining // 60
            return f"专注模式暂停中（已完成{elapsed_min}分钟，剩余{remaining_min}分钟）"
        elif self._state == FocusState.COMPLETED:
            return "专注完成"
        return "未知状态"

    def get_status_for_llm(self) -> str:
        """获取状态摘要（注入LLM system prompt）"""
        if self._state == FocusState.FOCUSING:
            mins = self.timer.remaining // 60
            return f"专注模式进行中，剩余{mins}分钟"
        elif self._state == FocusState.PAUSED:
            mins = self.timer.remaining // 60
            return f"专注模式暂停中，剩余{mins}分钟"
        elif self._state == FocusState.WAITING_PHONE:
            return "等待用户放入手机以开启专注"
        elif self._state == FocusState.COMPLETED:
            return "专注模式已完成"
        return "未开启专注模式"

    def reset(self):
        """重置状态机到初始状态"""
        self.timer.stop()
        self._timer_expired_flag = False
        self._state = FocusState.IDLE
        self.focus_duration_sec = 0
        self.pause_start_time = 0.0
        self._waiting_start_time = 0.0
        logger.info("StateController 已重置")
