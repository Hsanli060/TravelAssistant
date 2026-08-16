"""FastAPI主应用（后端的总入口）"""
import sys
from contextlib import asynccontextmanager

# 修复 Windows 控制台（GBK）打印 emoji 时抛 UnicodeEncodeError 的问题
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ..config import get_settings, validate_config, print_config
from .routes import trip, poi, map as map_routes
from ..services.mcp_service import get_mcp_manager

# 1. 获取配置信息
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期管理器：启动时加载配置与 MCP，停止时释放资源"""
    print("\n" + "=" * 60)
    print(f"🚀 {settings.app_name} 正在启动...")
    print("=" * 60)
    print_config()

    try:
        validate_config()
        print("\n✅ 配置验证通过")
    except ValueError as e:
        print(f"\n❌ 配置验证失败: {e}")
        print("请检查 .env 文件后重启服务")
        raise

    # 启动 MCP 服务（失败不阻断应用：前端地图/POI 直连路由仍可用）
    mcp_mgr = get_mcp_manager()
    try:
        await mcp_mgr.initialize()
    except Exception as e:
        print(f"⚠️ MCP 初始化失败（行程规划将不可用，但地图/POI 直连接口仍可用）: {str(e)}")

    print(f"\n👉 接口文档地址: http://127.0.0.1:{settings.port}/docs")
    print("=" * 60 + "\n")

    yield

    # 停止时安全释放 MCP 子进程
    await mcp_mgr.close()


# 2. 实例化 FastAPI 应用
app = FastAPI(
    title=settings.app_name,
    description="基于 LangGraph + MCP 架构的智能旅行规划助手 API",
    lifespan=lifespan,
    docs_url="/docs"
)

# 3. 配置 CORS 跨域资源共享
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. 注册路由
app.include_router(trip.router, prefix="/api")        # 旅行规划主路由: /api/trip/...
app.include_router(poi.router, prefix="/api")         # 景点详情路由: /api/poi/...
app.include_router(map_routes.router, prefix="/api")   # 地图天气路由: /api/map/...


@app.get("/")
async def root():
    """根路径：返回服务基础信息"""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get("/health")
async def health():
    """健康检查：供前端启动时探测后端是否可用"""
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version
    }