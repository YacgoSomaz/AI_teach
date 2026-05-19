#!/usr/bin/env bash
# AI 复习导航系统 — 部署前自检脚本（Linux / macOS）
#
# 用法：
#   bash scripts/deploy_check.sh              # 含健康检查
#   bash scripts/deploy_check.sh --skip-health  # 跳过健康检查（服务未启动时）
#   DEPLOY_CHECK_API=http://host:8000 bash scripts/deploy_check.sh
#
# 脚本不会打印 .env 中的任何敏感值。

set -euo pipefail

# ── 参数 ──────────────────────────────────────────────────────────────────────
SKIP_HEALTH=0
API_BASE_URL="${DEPLOY_CHECK_API:-http://localhost:8000}"

for arg in "$@"; do
    case "$arg" in
        --skip-health) SKIP_HEALTH=1 ;;
        *) echo "未知参数：$arg" >&2; exit 1 ;;
    esac
done

# ── 颜色 ──────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; GRAY='\033[0;37m'; RESET='\033[0m'

PASS_COUNT=0; FAIL_COUNT=0; WARN_COUNT=0

pass() { echo -e "  ${GREEN}[PASS]${RESET} $1"; PASS_COUNT=$((PASS_COUNT+1)); }
fail() { echo -e "  ${RED}[FAIL]${RESET} $1"; FAIL_COUNT=$((FAIL_COUNT+1)); }
warn() { echo -e "  ${YELLOW}[WARN]${RESET} $1"; WARN_COUNT=$((WARN_COUNT+1)); }
section() { echo -e "\n${CYAN}── $1${RESET}"; }

# ── 项目根目录（脚本所在目录的上一级）────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── 1. docker 是否可用 ────────────────────────────────────────────────────────
section "Docker 可用性"

if command -v docker &>/dev/null; then
    VERSION=$(docker --version 2>&1)
    pass "docker 已安装：$VERSION"
else
    fail "docker 未安装或不在 PATH 中"
fi

if docker info &>/dev/null; then
    pass "Docker daemon 正在运行"
else
    fail "Docker daemon 未启动（请启动 Docker Desktop 或 dockerd）"
fi

# ── 2. docker compose 是否可用 ───────────────────────────────────────────────
section "Docker Compose 可用性"

if docker compose version &>/dev/null; then
    COMPOSE_VER=$(docker compose version 2>&1)
    pass "docker compose 已安装：$COMPOSE_VER"
else
    fail "docker compose 不可用（需要 Docker Compose v2，即 'docker compose'）"
fi

# ── 3. .env 文件是否存在 ──────────────────────────────────────────────────────
section ".env 配置"

ENV_FILE="$PROJECT_ROOT/.env"

if [[ -f "$ENV_FILE" ]]; then
    pass ".env 文件存在：$ENV_FILE"

    # 只检查 key 是否存在且非空，不打印 value
    REQUIRED_KEYS=(
        POSTGRES_PASSWORD
        PADDLEOCR_TOKEN
        DOUBAO_SEED_API_KEY
        DOUBAO_SEED_MODEL
    )

    for key in "${REQUIRED_KEYS[@]}"; do
        # grep 匹配 KEY=非空值（忽略注释行）
        if grep -qE "^${key}\s*=\s*.+" "$ENV_FILE"; then
            pass "  必填项已设置：$key"
        else
            fail "  必填项缺失或为空：$key"
        fi
    done
else
    fail ".env 文件不存在（请执行：cp .env.example .env 并填写必填项）"
fi

# ── 4. docker compose config 语法验证 ────────────────────────────────────────
section "docker-compose.yml 语法验证"

cd "$PROJECT_ROOT"
if docker compose config --quiet &>/dev/null; then
    pass "docker compose config 语法正确"
else
    # 重新运行以捕获错误输出（不静默）
    ERR=$(docker compose config 2>&1 || true)
    fail "docker compose config 报错：
$ERR"
fi

# ── 5. docker compose ps ──────────────────────────────────────────────────────
section "服务状态（docker compose ps）"

PS_OUT=$(docker compose ps --format "table {{.Name}}\t{{.Status}}" 2>&1 || true)
if echo "$PS_OUT" | grep -qE "NAME|name"; then
    pass "docker compose ps 执行成功"
    echo -e "${GRAY}${PS_OUT}${RESET}"
elif [[ -z "$PS_OUT" || "$PS_OUT" =~ "no configuration file" ]]; then
    fail "docker compose ps 失败：$PS_OUT"
else
    warn "服务尚未启动（执行 docker compose up -d --build 启动）"
fi

# ── 6. 健康检查（可选）────────────────────────────────────────────────────────
if [[ "$SKIP_HEALTH" -eq 0 ]]; then
    section "健康检查（$API_BASE_URL）"

    # 优先用 curl，其次用 wget
    if command -v curl &>/dev/null; then
        HTTP_TOOL="curl"
    elif command -v wget &>/dev/null; then
        HTTP_TOOL="wget"
    else
        warn "curl 和 wget 均不可用，跳过健康检查"
        HTTP_TOOL=""
    fi

    if [[ -n "$HTTP_TOOL" ]]; then
        # /health — liveness
        if [[ "$HTTP_TOOL" == "curl" ]]; then
            STATUS=$(curl -s -o /tmp/_hc_body.txt -w "%{http_code}" \
                     --max-time 5 "$API_BASE_URL/health" 2>/dev/null || echo "000")
        else
            STATUS=$(wget -q -O /tmp/_hc_body.txt --timeout=5 \
                     "$API_BASE_URL/health" 2>/dev/null && echo "200" || echo "000")
        fi
        BODY=$(cat /tmp/_hc_body.txt 2>/dev/null || echo "")
        if [[ "$STATUS" == "200" ]]; then
            pass "/health → $STATUS  $BODY"
        elif [[ "$STATUS" == "000" ]]; then
            warn "/health 无响应（服务未启动？）使用 --skip-health 可静默此警告。"
        else
            fail "/health → 非预期状态码 $STATUS  $BODY"
        fi

        # /health/ready — readiness
        if [[ "$HTTP_TOOL" == "curl" ]]; then
            STATUS=$(curl -s -o /tmp/_hc_body.txt -w "%{http_code}" \
                     --max-time 5 "$API_BASE_URL/health/ready" 2>/dev/null || echo "000")
        else
            STATUS=$(wget -q -O /tmp/_hc_body.txt --timeout=5 \
                     "$API_BASE_URL/health/ready" 2>/dev/null && echo "200" || echo "503")
        fi
        BODY=$(cat /tmp/_hc_body.txt 2>/dev/null || echo "")
        if [[ "$STATUS" == "200" ]]; then
            pass "/health/ready → $STATUS  $BODY"
        elif [[ "$STATUS" == "503" ]]; then
            fail "/health/ready → 503 degraded（DB 或 Redis 不可达）：$BODY"
        elif [[ "$STATUS" == "000" ]]; then
            warn "/health/ready 无响应（服务未启动？）"
        else
            fail "/health/ready → 非预期状态码 $STATUS  $BODY"
        fi

        rm -f /tmp/_hc_body.txt
    fi
else
    echo -e "\n  ${GRAY}[跳过] 健康检查（--skip-health 已设置）${RESET}"
fi

# ── 汇总 ──────────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  结果汇总：PASS=${PASS_COUNT}  FAIL=${FAIL_COUNT}  WARN=${WARN_COUNT}"

if [[ "$FAIL_COUNT" -gt 0 ]]; then
    echo -e "  ${RED}✗ 自检未通过，请修复上述 FAIL 项后再部署。${RESET}"
    exit 1
elif [[ "$WARN_COUNT" -gt 0 ]]; then
    echo -e "  ${YELLOW}⚠ 自检通过（有警告），确认后可部署。${RESET}"
    exit 0
else
    echo -e "  ${GREEN}✓ 所有检查通过，可以部署。${RESET}"
    exit 0
fi
