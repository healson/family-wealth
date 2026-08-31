# ============================================
# 家庭财富管理 - 单容器多阶段构建
# Stage 1: 构建 React 前端
# Stage 2: Python 运行时托管 API + 静态文件
# ============================================

# ---------- Stage 1: 前端构建 ----------
FROM node:20-alpine AS frontend-builder
WORKDIR /build/frontend

# 先只拷贝依赖清单，利用 Docker 层缓存
COPY frontend/package.json ./
RUN npm install --registry=https://registry.npmmirror.com

COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: 后端运行时 ----------
FROM python:3.12-slim
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    STATIC_DIR=/app/static \
    TZ=Asia/Shanghai

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY backend/app ./app
COPY README.md ./
COPY --from=frontend-builder /build/frontend/dist ./static

# 数据目录（SQLite 数据库持久化）
VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
