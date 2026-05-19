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
        description="学生 ID（MVP stub：通过 Header 传入，生产环境替换为 JWT 解析）",
    ),
) -> str:
    # TODO: 接入真实 JWT 鉴权，从 token 中提取 student_id
    if not x_student_id or not x_student_id.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 X-Student-Id Header，请提供学生身份标识",
        )
    return x_student_id.strip()


async def check_ownership(path_student_id: str, current_student_id: str) -> None:
    """校验路径中的 student_id 与当前认证身份一致，防止 IDOR。不一致时返回 404。"""
    if path_student_id != current_student_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该学生的数据")


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
