"""
上传限流测试

测试滑动窗口算法核心逻辑，不依赖真实 DB/Redis。
"""

import time
import pytest

from src.api.rate_limit import _reset_for_testing, _sliding_window_check
from fastapi import HTTPException


@pytest.fixture(autouse=True)
def reset_rate_limit_state():
    """每个用例前后清空限流状态，防止用例间污染。"""
    _reset_for_testing()
    yield
    _reset_for_testing()


class TestSlidingWindowCheck:
    """_sliding_window_check 核心算法"""

    def test_first_request_allowed(self):
        _sliding_window_check("stu_1", max_requests=3, window=60)

    def test_requests_within_limit_allowed(self):
        for _ in range(3):
            _sliding_window_check("stu_1", max_requests=3, window=60)

    def test_exceeding_limit_raises_429(self):
        for _ in range(3):
            _sliding_window_check("stu_1", max_requests=3, window=60)
        with pytest.raises(HTTPException) as exc_info:
            _sliding_window_check("stu_1", max_requests=3, window=60)
        assert exc_info.value.status_code == 429

    def test_429_response_has_retry_after_header(self):
        for _ in range(2):
            _sliding_window_check("stu_1", max_requests=2, window=60)
        with pytest.raises(HTTPException) as exc_info:
            _sliding_window_check("stu_1", max_requests=2, window=60)
        assert "Retry-After" in exc_info.value.headers

    def test_different_students_have_independent_buckets(self):
        for _ in range(3):
            _sliding_window_check("stu_a", max_requests=3, window=60)
        # stu_a 已满，stu_b 不受影响
        _sliding_window_check("stu_b", max_requests=3, window=60)

    def test_expired_entries_do_not_count(self):
        # 在极短窗口内写入记录，然后等窗口过期
        _sliding_window_check("stu_1", max_requests=1, window=1)
        time.sleep(1.05)
        # 窗口已过期，应允许新请求
        _sliding_window_check("stu_1", max_requests=1, window=1)

    def test_limit_1_allows_exactly_one(self):
        _sliding_window_check("stu_1", max_requests=1, window=60)
        with pytest.raises(HTTPException):
            _sliding_window_check("stu_1", max_requests=1, window=60)

    def test_detail_message_contains_window_and_max(self):
        _sliding_window_check("stu_1", max_requests=2, window=30)
        _sliding_window_check("stu_1", max_requests=2, window=30)
        with pytest.raises(HTTPException) as exc_info:
            _sliding_window_check("stu_1", max_requests=2, window=30)
        assert "30" in exc_info.value.detail
        assert "2" in exc_info.value.detail
