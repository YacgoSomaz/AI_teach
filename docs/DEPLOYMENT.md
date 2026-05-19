# 部署指南

## 目录

1. [环境变量](#环境变量)
2. [Docker Compose 快速启动](#docker-compose-快速启动)
3. [数据库迁移](#数据库迁移)
4. [健康检查验证](#健康检查验证)
5. [本地裸机启动（不用 Docker）](#本地裸机启动)
6. [限流说明](#上传限流)
7. [测试分层](#测试分层)

---

## 环境变量

复制 `.env.example` 为 `.env`，按需填写。

### 必填（缺少则服务无法启动或核心功能失效）

| 变量 | 说明 | 示例 |
|------|------|------|
| `POSTGRES_PASSWORD` | PostgreSQL 密码（docker-compose 使用） | `change_me_in_prod` |
| `DATABASE_URL` | 完整连接串（裸机启动时使用） | `postgresql+asyncpg://user:pass@localhost:5432/ai_review_system` |
| `REDIS_URL` | Redis 连接串（Celery broker） | `redis://localhost:6379/0` |
| `PADDLEOCR_TOKEN` | PaddleOCR API Token | `your_token_here` |
| `DOUBAO_SEED_API_KEY` | 豆包 Seed1.8 API Key | `your_key_here` |
| `DOUBAO_SEED_MODEL` | 豆包模型 Endpoint ID | `ep-xxxxxxxxxxxxxxxx` |

> **注意：** docker-compose 启动时，`DATABASE_URL` 和 `REDIS_URL` 由 compose 文件自动注入
> （服务名替换 `localhost`），`.env` 里不需要重复设置这两项。

### 可选（有默认值）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `POSTGRES_DB` | `ai_review_system` | 数据库名 |
| `POSTGRES_USER` | `appuser` | 数据库用户名 |
| `API_PORT` | `8000` | 宿主机映射端口 |
| `CORS_ORIGINS` | `*` | 生产环境改为前端域名，逗号分隔 |
| `UPLOAD_DIR` | `uploads` | 文件存储目录 |
| `MAX_FILE_SIZE_MB` | `20` | 单文件最大体积（MB） |
| `UPLOAD_RATE_LIMIT_REQUESTS` | `10` | 每学生每窗口最多上传次数 |
| `UPLOAD_RATE_LIMIT_WINDOW` | `60` | 限流滑动窗口时长（秒） |
| `ENVIRONMENT` | `development` | 生产环境设为 `production` |
| `DEBUG` | `false` | 生产环境保持 `false` |

---

## Docker Compose 快速启动

### 前置条件

- Docker Engine 24+
- Docker Compose v2（`docker compose` 命令，非 `docker-compose`）

### 启动步骤

```bash
# 1. 复制并填写环境变量（至少设置 POSTGRES_PASSWORD 和 API Key）
cp .env.example .env
# 编辑 .env，填写 POSTGRES_PASSWORD、PADDLEOCR_TOKEN、DOUBAO_SEED_API_KEY 等

# 2. 构建镜像并启动所有服务
docker compose up -d --build

# 3. 查看启动日志（确认无报错）
docker compose logs -f api worker
```

`migrate` 服务会在 postgres 就绪后自动执行 `alembic upgrade head`，之后退出。  
`api` 和 `worker` 依赖 `migrate` 成功完成才会启动。

### 服务说明

| 服务 | 镜像 | 启动命令 | 说明 |
|------|------|----------|------|
| `postgres` | `postgres:16-alpine` | — | 主数据库，数据持久化到 `postgres_data` volume |
| `redis` | `redis:7-alpine` | — | Celery broker，数据持久化到 `redis_data` volume |
| `migrate` | `ai-review-system:latest` | `alembic upgrade head` | 一次性迁移任务，完成后自动退出 |
| `api` | `ai-review-system:latest` | `uvicorn src.main:app` | FastAPI，监听 `0.0.0.0:8000` |
| `worker` | `ai-review-system:latest` | `celery -A src.celery_app worker` | Celery 异步任务处理 |

> `api` 和 `worker` 使用**同一个镜像**，仅启动命令不同。

### 上传文件持久化

上传目录挂载到名为 `uploads_data` 的 Docker volume，容器重建后文件不会丢失：

```
容器内：/app/uploads  ←→  Docker volume: uploads_data
```

---

## 数据库迁移

### docker compose 中执行（推荐）

迁移由 `migrate` 服务自动处理。如需手动重跑：

```bash
docker compose run --rm migrate alembic upgrade head
```

回滚一个版本：

```bash
docker compose run --rm migrate alembic downgrade -1
```

查看当前版本：

```bash
docker compose run --rm migrate alembic current
```

### 裸机环境中执行

```bash
export DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/ai_review_system
alembic upgrade head
```

---

## 健康检查验证

### 接口说明

| 端点 | 用途 | 正常响应 | 异常响应 |
|------|------|----------|----------|
| `GET /health` | 进程存活（Liveness） | `200 {"status":"ok"}` | 进程挂掉时无响应 |
| `GET /health/ready` | 依赖就绪（Readiness） | `200 {"status":"ok","checks":{"db":"ok","redis":"ok"}}` | `503 {"status":"degraded",...}` |

### 验证命令

```bash
# 存活检查
curl -s http://localhost:8000/health | python -m json.tool

# 就绪检查（DB + Redis 都通时才返回 200）
curl -s http://localhost:8000/health/ready | python -m json.tool

# 查看所有服务健康状态
docker compose ps
```

### Kubernetes 探针配置参考

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 15

readinessProbe:
  httpGet:
    path: /health/ready
    port: 8000
  initialDelaySeconds: 15
  periodSeconds: 10
```

---

## 本地裸机启动

不使用 Docker，需自行准备 PostgreSQL 和 Redis。

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填写 DATABASE_URL / REDIS_URL / API Keys

# 3. 运行数据库迁移
alembic upgrade head

# 4. 启动 API
uvicorn src.main:app --host 0.0.0.0 --port 8000

# 5. 另开终端，启动 Celery Worker
celery -A src.celery_app worker --loglevel=info

# Windows 用户可使用批处理脚本：
# start_celery.bat
```

---

## 上传限流

上传接口内置滑动窗口限流，防止 OCR/AI 成本失控：

- 默认：每学生每 **60 秒**最多 **10 次**上传
- 超出时返回 `429 Too Many Requests`，响应头包含 `Retry-After: 60`
- 通过 `UPLOAD_RATE_LIMIT_REQUESTS` / `UPLOAD_RATE_LIMIT_WINDOW` 调整
- 当前为**单进程**内存实现；多实例部署时需替换为 Redis 实现

---

## 测试分层

```
tests/
├── api/          # 单元级 API 测试（无真实 DB/Redis，全部 mock）
│   └── 运行：python -m pytest tests/api -q
└── integration/  # 集成测试（SQLite 内存库，无需外部服务）
    └── 运行：python -m pytest tests/integration -q
```

CI 推荐命令：

```bash
python -m pytest tests/api tests/integration/test_report_flow.py -q
```

---

## 常见问题

**Q: `migrate` 服务一直重启？**  
A: postgres 健康检查还未通过。运行 `docker compose logs postgres` 查看原因，通常是磁盘空间不足或 `POSTGRES_PASSWORD` 未设置。

**Q: worker 启动后立即退出？**  
A: 检查 `REDIS_URL` 是否可达，以及 Celery 能否连接 broker：`docker compose logs worker`。

**Q: 上传文件重启后丢失？**  
A: 确认 `uploads_data` volume 存在：`docker volume ls | grep uploads`。若使用 `docker compose down -v` 会删除 volume，改用 `docker compose down` 即可。
