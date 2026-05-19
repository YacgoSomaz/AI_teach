"""
共享 FastAPI 依赖

所有 API 路由从这里导入公共依赖，避免重复定义。
"""

from fastapi import Header, Query


async def get_current_student_id(
    x_student_id: str = Header(
        default="test_student",
        alias="X-Student-Id",
        description="学生 ID（MVP stub：通过 Header 传入，生产环境替换为 JWT 解析）",
    ),
) -> str:
    # TODO: 接入真实 JWT 鉴权，从 token 中提取 student_id
    return x_student_id


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
