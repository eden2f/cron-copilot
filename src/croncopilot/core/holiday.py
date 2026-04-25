"""中国法定节假日检查模块。

基于 ``chinesecalendar`` 库提供工作日/节假日判断能力，用于在调度层面
根据 ``holiday_mode`` 决定任务是否应当执行。
"""

from __future__ import annotations

import datetime
from typing import Optional

from croncopilot.logging.logger import get_logger

logger = get_logger(__name__)

_holiday_lib = None


def _ensure_holiday_lib() -> None:
    """延迟加载 ``chinesecalendar`` 库。

    Raises:
        ImportError: 当 ``chinesecalendar`` 未安装时抛出。
    """
    global _holiday_lib
    if _holiday_lib is None:
        try:
            import chinese_calendar
            _holiday_lib = chinese_calendar
        except ImportError:
            logger.error("chinesecalendar not installed. Run: pip install chinesecalendar")
            raise


class HolidayChecker:
    """中国节假日检查器。

    Attributes:
        VALID_MODES: 所有合法的 ``holiday_mode`` 值。

    Parameters:
        enabled: 是否启用节假日检查。设为 ``False`` 时所有判断均返回
            "应该执行"。
    """

    VALID_MODES = ("none", "workday_only", "holiday_only", "skip_holiday", "skip_workday")

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        if enabled:
            _ensure_holiday_lib()

    def is_holiday(self, date: datetime.date) -> bool:
        """判断是否为法定节假日（含周末，不含调休工作日）。

        Parameters:
            date: 检查日期。

        Returns:
            ``True`` 表示当天为节假日。
        """
        if not self._enabled:
            return False
        _ensure_holiday_lib()
        return _holiday_lib.is_holiday(date)  # type: ignore[union-attr]

    def is_workday(self, date: datetime.date) -> bool:
        """判断是否为工作日（含调休工作日）。

        Parameters:
            date: 检查日期。

        Returns:
            ``True`` 表示当天为工作日。
        """
        if not self._enabled:
            return True
        _ensure_holiday_lib()
        return _holiday_lib.is_workday(date)  # type: ignore[union-attr]

    def should_execute(self, date: datetime.date, holiday_mode: str) -> bool:
        """根据 ``holiday_mode`` 判断任务在指定日期是否应执行。

        Parameters:
            date: 检查日期。
            holiday_mode: 节假日模式，取值为
                ``"none"`` | ``"workday_only"`` | ``"holiday_only"``
                | ``"skip_holiday"`` | ``"skip_workday"``。

        Returns:
            ``True`` 表示应执行，``False`` 表示应跳过。
        """
        if holiday_mode == "none" or not self._enabled:
            return True

        is_wd = self.is_workday(date)

        if holiday_mode == "workday_only":
            return is_wd
        elif holiday_mode == "holiday_only":
            return not is_wd
        elif holiday_mode == "skip_holiday":
            return is_wd  # 节假日跳过 = 只在工作日执行
        elif holiday_mode == "skip_workday":
            return not is_wd  # 工作日跳过 = 只在非工作日执行
        else:
            logger.warning("Unknown holiday_mode: %s, defaulting to execute", holiday_mode)
            return True


_global_checker: Optional[HolidayChecker] = None


def get_holiday_checker(enabled: bool = True) -> HolidayChecker:
    """获取全局节假日检查器单例。

    Parameters:
        enabled: 是否启用节假日检查（仅在首次创建时有效）。

    Returns:
        全局 ``HolidayChecker`` 实例。
    """
    global _global_checker
    if _global_checker is None:
        _global_checker = HolidayChecker(enabled=enabled)
    return _global_checker
