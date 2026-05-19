# 部署指南

## 必须配置的环境变量

复制 `.env.example` 为 `.env`，填写以下变量后才能启动服务。

### 核心（缺少则启动失败或功能不可用）

| 变量 | 说明 | 示例 |
|------|------|------|
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql://user:pass@localhost:5432/ai_review` |
| `REDIS_URL` | Redis 连接串（Celery broker） | `redis://localhost:6379/0` |
| `PADDLEOCR_TOKEN` | PaddleOCR API Token | `your_token_here` |
| `DOUBAO_SEED_API_KEY` | 豆包 Seed1.8 API Key | `your_key_here` |
| `DOUBAO_SEED_MODEL` | 豆包模型 Endpoint ID | `ep-xxxxxxxxxxxxxxxx` |

### 可选（有默认值）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CORS_ORIGINS` | `*` | 生产环境改为前端域名，逗号分隔 |
| `UPLOAD_DIR` | `uploads` | 文件存储目录 |
| `MAX_FILE_SIZE_MB` | `20` | 单文件最大体积（MB） |
| `UPLOAD_RATE_LIMIT_REQUESTS` | `10` | 每学生每窗口最多上传次数 |
| `UPLOAD_RATE_LIMIT_WINDOW` | `60` | 限流滑动窗口时长（秒） |
| `ENVIRONMENT` | `development` | 生产环境设为 `production` |
| `DEBUG` | `false` | 生产环境保持 `false` |

---

## 健康检查

| 端点 | 用途 | 何时返回非 ok |
|------|------|---------------|
| `GET /health` | 进程存活（Liveness Probe） | 进程挂掉时无响应 |
| `GET /health/ready` | 依赖就绪（Readiness Probe） | DB 或 Redis 不可达时返回 **HTTP 503** + `status=degraded` |

K8s 配置示例：

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
└── integration/  # 集成测试（使用 SQLite 内存库，无需外部服务）
    └── 运行：python -m pytest tests/integration -q
```

CI 中建议两层都跑：

```bash
python -m pytest tests/api tests/integration/test_report_flow.py -q
```

---

## 快速启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填写 DATABASE_URL / REDIS_URL / API Keys

# 3. 运行数据库迁移
alembic upgrade head

# 4. 启动服务
uvicorn src.main:app --host 0.0.0.0 --port 8000

# 5. 验证
curl http://localhost:8000/health
curl http://localhost:8000/health/ready
```
