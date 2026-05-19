"""
上传接口内存限流

滑动窗口算法：每学生在 window 秒内最多 max_requests 次上传。
单进程有效；多实例部署时请替换为 Redis 实现。
"""

import time
from collections import defaultdict
from threading import Lock
from typing import List

from fastapi import Depends, HTTPException, status

from src.api.deps import get_current_student_id
from src.config import settings

_lock = Lock()
_timestamps: dict[str, List[float]] = defaultdict(list)


def _sliding_window_check(student_id: str, max_requests: int, window: int) -> None:
    now = time.monotonic()
    cutoff = now - window
    with _lock:
        _timestamps[student_id] = [t for t in _timestamps[student_id] if t > cutoff]
        if len(_timestamps[student_id]) >= max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"上传过于频繁，每 {window} 秒最多 {max_requests} 次，请稍后重试"
                ),
                headers={"Retry-After": str(window)},
            )
        _timestamps[student_id].append(now)


async def upload_rate_limit(
    student_id: str = Depends(get_current_student_id),
) -> str:
    """上传接口限流依赖：每学生每窗口期最多 N 次，超出返回 429。"""
    _sliding_window_check(
        student_id,
        max_requests=settings.upload_rate_limit_requests,
        window=settings.upload_rate_limit_window,
    )
    return student_id


def _reset_for_testing() -> None:
    """测试专用：清空限流状态，防止用例间污染。"""
    with _lock:
        _timestamps.clear()
