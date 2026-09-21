import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import backup, health

from .database import SessionLocal, get_db

# 这两个常量必须定义在「导入 routers」之前：
# routers/system.py 会 `from ..main import VERSION`，若 VERSION 定义在导入之后，
# 那个导入会拿到一个尚未初始化的模块并抛 ImportError。
STATIC_DIR = os.environ.get("STATIC_DIR", "/app/static")
VERSION = "1.10.1"

from .routers import (  # noqa: E402  —— 必须在上面的常量之后导入
    accounts, admin, ai, assets, attachments, auth, bill_import, dashboard,
    data_io, docs, financial, insurance, loans, options, reminders, system,
    templates, transactions, transfers,
)
from .seed import init_db, seed_demo  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    db: Session = SessionLocal()
    try:
        is_fresh = init_db(db)
        if is_fresh and os.environ.get("SEED_DEMO_DATA", "true").lower() == "true":
            seed_demo(db)
        # 启动自检三件事，都写日志 —— 部署后一眼就能看到「schema 对不对、账平不平、备份在不在」
        health.startup(db)
    finally:
        db.close()
    # 启动定时交易后台线程 + 首次到期检查
    from .schedulers import run_due, start_scheduler

    try:
        sdb = SessionLocal()
        try:
            run_due(sdb)
        finally:
            sdb.close()
    except Exception:
        pass
    start_scheduler()
    # 对账缓存后台刷新：让 /api/health 永远只读缓存、永远快
    # （它被 Docker HEALTHCHECK 每 30 秒打一次，不能每次实时全量对账）
    threading.Thread(target=health.maintenance_loop, name="health-refresh", daemon=True).start()
    # 自动备份：每日一份，按日期判重，随附轮转
    backup.start_scheduler()
    yield


app = FastAPI(title="家庭财富管理", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")

# 允许跨域（开发模式下前端独立运行；生产环境前后端同源，此配置无副作用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(assets.router)
app.include_router(insurance.router)
app.include_router(accounts.router)
app.include_router(financial.router)
app.include_router(transactions.router)
app.include_router(transfers.router)
app.include_router(options.router)
app.include_router(loans.router)
app.include_router(templates.router)
app.include_router(data_io.router)
app.include_router(bill_import.router)
app.include_router(ai.router)
app.include_router(admin.router)
app.include_router(dashboard.router)
app.include_router(attachments.router)
app.include_router(reminders.router)
app.include_router(docs.router)
app.include_router(system.router)

# MCP Server（供外部 AI Agent 调用）
from .mcp_server import mcp_message_endpoint, mcp_post_endpoint, mcp_sse_endpoint

app.add_api_route("/mcp", mcp_sse_endpoint, methods=["GET"], include_in_schema=False)
app.add_api_route("/mcp", mcp_post_endpoint, methods=["POST"], include_in_schema=False)
app.add_api_route("/mcp/message", mcp_message_endpoint, methods=["POST"], include_in_schema=False)


@app.get("/api/health")
def health_check():
    """健康检查。

    ⚠️ 这个端点被三处 Docker HEALTHCHECK、登录页与设置页消费，
       所以有两条规定：
       1. **HTTP 状态码恒为 200** —— 它是「进程活着」的信号，不能因为
          「账不平」「备份过期」这类业务状态而变成非 2xx，否则一个财务差异
          会被误报成服务故障（容器显示 unhealthy、自查命令失败）。
       2. **只读缓存** —— 对账结果由后台线程按 TTL 刷新（见 app/health.py），
          这里绝不实时全量计算：HEALTHCHECK 每 30 秒打一次，实时算会变成重负载。
    业务状态放在返回体字段里：books_balanced / schema_ok / backup_ok。
    """
    payload = {"status": "ok", "version": VERSION}
    db = None
    try:
        db = SessionLocal()
        payload.update(health.fields(db))
    except Exception as exc:  # noqa: BLE001 —— 健康检查自己绝不能把服务拖垮
        payload["health_error"] = "%s: %s" % (type(exc).__name__, exc)
    finally:
        if db is not None:
            db.close()
    return payload


# 托管前端静态文件（生产模式：React 构建产物）
if os.path.isdir(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        # API 404 不落到 SPA
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        file_path = Path(STATIC_DIR) / full_path
        if full_path and file_path.is_file():
            return FileResponse(file_path)
        index = Path(STATIC_DIR) / "index.html"
        if index.is_file():
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="前端资源未构建，请先构建前端")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
