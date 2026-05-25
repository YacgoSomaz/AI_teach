"""
Celery 应用配置

负责异步任务处理：
- OCR 任务
- AI 分析任务
- 报告生成任务

使用 Redis 作为消息队列和结果后端。
"""

from celery import Celery

from src.config import settings

# 创建 Celery 应用
app = Celery(
    "ai_review_system",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "src.tasks.ocr_tasks",
        "src.tasks.ai_tasks",
        "src.tasks.grading_tasks",
    ],
)

# Celery 配置
app.conf.update(
    # 任务序列化
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    
    # 任务结果过期时间（1天）
    result_expires=86400,
    
    # 任务超时配置（从统一配置读取）
    task_soft_time_limit=settings.celery_task_soft_time_limit,
    task_time_limit=settings.celery_task_time_limit,
    
    # 任务重试配置
    task_acks_late=True,       # 任务执行完才确认
    task_reject_on_worker_lost=True,
    
    # Worker 配置
    worker_prefetch_multiplier=1,  # 每次只取一个任务
    worker_max_tasks_per_child=1000,  # 每个 worker 执行 1000 个任务后重启
    
    # 任务路由（可选，用于任务分发到不同队列）
    task_routes={
        "src.tasks.ocr_tasks.*": {"queue": "ocr"},
        "src.tasks.ai_tasks.*": {"queue": "ai"},
        "src.tasks.grading_tasks.*": {"queue": "ai"},
    },
)

if __name__ == "__main__":
    app.start()
