"""
一键部署脚本：通过 SSH + docker cp 把本地文件推到服务器容器。
用法：python deploy.py
依赖：pip install paramiko
"""
import getpass
import os
import sys

try:
    import paramiko
except ImportError:
    sys.exit("缺少依赖，请先运行：pip install paramiko")

# ── 配置 ──────────────────────────────────────────────────────────
HOST = "106.53.77.14"
PORT = 22
USER = "ubuntu"
CONTAINER = "ai_review_system-api-1"
LOCAL_ROOT = os.path.dirname(os.path.abspath(__file__))

# 可选文件列表（本地路径 → 容器内路径）
DEPLOY_TARGETS = {
    "1": {
        "label": "前端 index.html",
        "local": "static/index.html",
        "remote": "/app/static/index.html",
    },
    "2": {
        "label": "AI 批改服务 ai_grading_service.py",
        "local": "src/services/ai_grading_service.py",
        "remote": "/app/src/services/ai_grading_service.py",
    },
    "3": {
        "label": "Grading API grading.py",
        "local": "src/api/grading.py",
        "remote": "/app/src/api/grading.py",
    },
    "4": {
        "label": "docker-compose.yml",
        "local": "docker-compose.yml",
        "remote": "/app/docker-compose.yml",
    },
    "5": {
        "label": "知识图谱模型 knowledge_graph.py",
        "local": "src/models/knowledge_graph.py",
        "remote": "/app/src/models/knowledge_graph.py",
    },
    "6": {
        "label": "Embedding 服务 embedding_service.py",
        "local": "src/services/embedding_service.py",
        "remote": "/app/src/services/embedding_service.py",
    },
    "7": {
        "label": "知识图谱服务 knowledge_graph_service.py",
        "local": "src/services/knowledge_graph_service.py",
        "remote": "/app/src/services/knowledge_graph_service.py",
    },
    "8": {
        "label": "知识图谱 API knowledge_graph.py",
        "local": "src/api/knowledge_graph.py",
        "remote": "/app/src/api/knowledge_graph.py",
    },
    "9": {
        "label": "聊天 API chat.py（含 RAG）",
        "local": "src/api/chat.py",
        "remote": "/app/src/api/chat.py",
    },
    "10": {
        "label": "模型索引 models/__init__.py",
        "local": "src/models/__init__.py",
        "remote": "/app/src/models/__init__.py",
    },
    "11": {
        "label": "主入口 main.py",
        "local": "src/main.py",
        "remote": "/app/src/main.py",
    },
    "12": {
        "label": "配置 config.py",
        "local": "src/config.py",
        "remote": "/app/src/config.py",
    },
    "13": {
        "label": "Alembic 迁移 kg_20260616（知识图谱表）",
        "local": "alembic/versions/kg_20260616_knowledge_graph_tables.py",
        "remote": "/app/alembic/versions/kg_20260616_knowledge_graph_tables.py",
    },
    "14": {
        "label": "Alembic 迁移 emb_20260616（embedding 列）",
        "local": "alembic/versions/emb_20260616_add_embedding_to_taxonomy.py",
        "remote": "/app/alembic/versions/emb_20260616_add_embedding_to_taxonomy.py",
    },
    "15": {
        "label": "初二物理知识点 seed 脚本 seed_physics_kp.py",
        "local": "scripts/seed_physics_kp.py",
        "remote": "/app/scripts/seed_physics_kp.py",
    },
    "16": {
        "label": "登录页 login.html（浅色主题）",
        "local": "static/login.html",
        "remote": "/app/static/login.html",
    },
    "17": {
        "label": "Nginx 反向代理配置 nginx.conf",
        "local": "nginx.conf",
        "remote": "/app/nginx.conf",
    },
    "18": {
        "label": "Auth Dockerfile",
        "local": "auth/Dockerfile",
        "remote": "/app/auth/Dockerfile",
    },
    "19": {
        "label": "Auth server.js（Node.js 认证服务）",
        "local": "auth/server.js",
        "remote": "/app/auth/server.js",
    },
    "20": {
        "label": "Auth database.js（SQLite 初始化）",
        "local": "auth/database.js",
        "remote": "/app/auth/database.js",
    },
    "21": {
        "label": "Auth mailer.js（QQ SMTP 邮件）",
        "local": "auth/mailer.js",
        "remote": "/app/auth/mailer.js",
    },
    "22": {
        "label": "Auth package.json",
        "local": "auth/package.json",
        "remote": "/app/auth/package.json",
    },
    "23": {
        "label": "Auth middleware/auth.js（JWT 中间件）",
        "local": "auth/middleware/auth.js",
        "remote": "/app/auth/middleware/auth.js",
    },
    "24": {
        "label": "Auth service.js（stub）",
        "local": "auth/service.js",
        "remote": "/app/auth/service.js",
    },
    "25": {
        "label": "Auth usage.js（stub）",
        "local": "auth/usage.js",
        "remote": "/app/auth/usage.js",
    },
}
# ─────────────────────────────────────────────────────────────────


def pick_files() -> list[dict]:
    print("\n可部署文件：")
    for k, v in DEPLOY_TARGETS.items():
        print(f"  [{k}] {v['label']}")
    print("  [a] 全部")
    raw = input("\n选择（逗号分隔，如 1,2 或 a）：").strip()
    if raw.lower() == "a":
        return list(DEPLOY_TARGETS.values())
    keys = [x.strip() for x in raw.split(",")]
    chosen = []
    for k in keys:
        if k in DEPLOY_TARGETS:
            chosen.append(DEPLOY_TARGETS[k])
        else:
            print(f"  忽略无效选项：{k}")
    return chosen


def deploy(targets: list[dict], password: str) -> None:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"\n连接 {USER}@{HOST}…")
    client.connect(HOST, port=PORT, username=USER, password=password, timeout=15)
    sftp = client.open_sftp()

    for t in targets:
        local_path = os.path.join(LOCAL_ROOT, t["local"])
        remote_tmp = f"/tmp/_deploy_{os.path.basename(t['local'])}"

        if not os.path.exists(local_path):
            print(f"  ✗ 本地文件不存在：{t['local']}")
            continue

        print(f"  上传 {t['label']}…", end=" ", flush=True)
        sftp.put(local_path, remote_tmp)

        cmd = f"docker cp {remote_tmp} {CONTAINER}:{t['remote']}"
        _, stdout, stderr = client.exec_command(cmd)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code == 0:
            print("✓")
        else:
            print(f"✗ docker cp 失败：{stderr.read().decode().strip()}")

    sftp.close()
    client.close()
    print("\n完成。")


def main() -> None:
    targets = pick_files()
    if not targets:
        sys.exit("没有选择任何文件，退出。")

    password = getpass.getpass(f"\n{USER}@{HOST} 密码：")
    deploy(targets, password)


if __name__ == "__main__":
    main()
