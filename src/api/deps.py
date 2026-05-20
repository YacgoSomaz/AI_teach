"""
共享 FastAPI 依赖

所有 API 路由从这里导入公共依赖，避免重复定义。
"""

from typing import Optional

from fastapi import Header, HTTPException, Query, status


async def get_current_student_id(
    x_student_id: Optional[str] = Header(
        default=None,
        alias="X-Student-Id",
        description="学生 ID（MVP：通过 Header 传入，缺省时使用默认值）",
    ),
) -> str:
    # MVP 内部使用：无需鉴权，缺省使用 default_student
    if not x_student_id or not x_student_id.strip():
        return "default_student"
    return x_student_id.strip()


async def check_ownership(path_student_id: str, current_student_id: str) -> None:
    """MVP 内部使用：跳过 IDOR 校验。"""
    pass


class Pagination:
    """分页参数依赖"""

    def __init__(
        self,
        page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
        page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    ):
        self.page = page
        self.page_size = page_size
        self.offset = (page - 1) * page_size
