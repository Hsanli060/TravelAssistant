# =====================================================================
# TravelAssistant · 后端容器化配置 (Dockerfile)
# =====================================================================

# 1. 基础镜像：选用轻量级官方 Python 3.11 slim 镜像
FROM python:3.11-slim

# 2. 设置容器内工作目录
WORKDIR /app

# 3. 设置 Python 环境变量：
# - PYTHONDONTWRITEBYTECODE=1: 不写入 .pyc 缓存文件，保持镜像纯净
# - PYTHONUNBUFFERED=1: 强制标准流无缓冲，确保日志能被 docker logs 实时捕获
# - PYTHONIOENCODING / PYTHONUTF8: 强制 UTF-8 编码，杜绝中文/Emoji 日志乱码
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONUTF8=1 \
    PATH="/root/.local/bin:${PATH}"

# 4. 安装基础系统依赖（curl 用于健康检查）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 5. 安装 Astral uv（提供 uv 和 uvx 命令，高德 MCP 服务需要通过 uvx 运行 amap-mcp-server）
RUN pip install --no-cache-dir uv

# 6. 利用 Docker 缓存层机制：先复制依赖清单并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 7. 预先通过 uv 安装高德 MCP 服务，避免冷启动时临时拉取
RUN uv tool install amap-mcp-server || true

# 8. 复制应用源码
COPY app ./app
COPY run.py .

# 9. 声明容器内部监听端口
EXPOSE 8000

# 10. 生产环境启动命令：使用 uvicorn 直接运行主应用，关闭 reload 以保证生产稳定性
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
