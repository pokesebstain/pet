#!/usr/bin/env bash
# 应用容器入口：等待数据库就绪 → 执行数据库迁移 → 启动 uvicorn。
set -euo pipefail

echo "[entrypoint] 等待 PostgreSQL 就绪..."
python - <<'PY'
import sys, time
from sqlalchemy import create_engine, text
from app.core.config import get_settings

dsn = get_settings().database.dsn
last_err = None
for attempt in range(60):
    try:
        engine = create_engine(dsn)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        print(f"[entrypoint] 数据库已就绪（第 {attempt + 1} 次尝试）")
        break
    except Exception as exc:  # noqa: BLE001
        last_err = exc
        time.sleep(2)
else:
    sys.exit(f"[entrypoint] 数据库在超时内未就绪：{last_err}")
PY

echo "[entrypoint] 执行数据库迁移（幂等）..."
python -c "from app.db import init_database; print('[entrypoint] 已执行迁移:', init_database())"

echo "[entrypoint] 启动 uvicorn（workers=${UVICORN_WORKERS:-1}）..."
exec uvicorn app.api.app:create_app --factory \
    --host 0.0.0.0 --port 8000 \
    --workers "${UVICORN_WORKERS:-1}"
