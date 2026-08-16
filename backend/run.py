import uvicorn
from app.config import get_settings

if __name__ =="__main__":
    settings = get_settings()
    print("=" * 60)
    print(f"🌟 正在启动 {settings.app_name} 后端服务...")
    print(f"🌐 监听地址: http://{settings.host}:{settings.port}")
    print(f"📖 接口文档: http://127.0.0.1:{settings.port}/docs")
    print("=" * 60)
    # 启动 uvicorn 服务器，支持代码热重载 (reload=True)
    uvicorn.run(
        "app.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        log_level=settings.log_level.lower()
    )