# ── 构建阶段 ─────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# 只复制生产依赖清单，充分利用层缓存（测试/格式化工具不进镜像）
COPY requirements-prod.txt .

# 安装生产依赖到独立目录，便于多阶段复制
RUN pip install --no-cache-dir --prefix=/install -r requirements-prod.txt


# ── 运行阶段 ─────────────────────────────────────────────────────────────────
FROM python:3.12-slim

# 时区 + 不生成 .pyc + 不缓冲 stdout/stderr
ENV TZ=Asia/Shanghai \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 从构建阶段复制已安装的包
COPY --from=builder /install /usr/local

# 复制源码（.dockerignore 负责排除无关文件）
COPY src/       ./src/
COPY alembic/   ./alembic/
COPY alembic.ini .
COPY static/    ./static/

# 创建上传目录（容器内默认落盘位置，docker-compose 会挂载 volume 覆盖）
RUN mkdir -p /app/uploads

# 非 root 用户运行，降低容器逃逸风险
RUN useradd -r -u 1001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# 默认启动 API；worker 在 docker-compose 里用 command 覆盖
# 单进程启动：上传限流为内存实现，多 worker 会导致各进程独立计数，限流失效。
# 如需水平扩展，请先将限流实现迁移至 Redis，再改回 --workers N。
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
