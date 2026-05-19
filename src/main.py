"""
FastAPI 主应用

应用工厂模式：
- 便于测试（可创建多个 app 实例）
- 便于配置不同环境（dev / test / prod）
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.export import router as export_router
from src.api.health import router as health_router
from src.api.report import router as report_router
from src.api.review import router as review_router
from src.api.student import router as student_router
from src.api.upload import router as upload_router
from src.api.visualization import router as visualization_router


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例（工厂模式，便于测试和多环境部署）。"""
    app = FastAPI(
        title="AI 复习导航系统",
        description="拍作业 → OCR → AI 分析 → 知识点归档 → 复习任务生成",
        version="0.1.0",
    )

    cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins if cors_origins != ["*"] else ["*"],
        allow_credentials=cors_origins != ["*"],
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Student-Id"],
    )

    app.include_router(health_router)
    app.include_router(upload_router)
    app.include_router(student_router)
    app.include_router(review_router)
    app.include_router(report_router)
    app.include_router(export_router)
    app.include_router(visualization_router)

    return app


# 创建应用实例（uvicorn 启动时使用）
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # 开发模式热重载
    )

