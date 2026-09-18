import os
import sys
from pathlib import Path
from typing import List
from  pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# 统一 stdout/stderr 为 UTF-8，避免 Windows GBK 控制台打印 emoji 时抛 UnicodeEncodeError。
# 这里放在 config（所有模块的公共依赖）里，保证任意入口（uvicorn / 脚本直跑）都生效。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 优先加载 backend/.env，其次当前目录 .env
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()

class Settings(BaseSettings):
    """应用配置"""

    #应用基础配置
    app_name:str="Langgraph智能旅行助手"
    app_version:str="1.0.0"
    debug:bool=False

    # 服务器配置
    host:str="0.0.0.0"
    port:int=8000
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    # CORS配置 - 使用字符串,在代码中分割
    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000"

    # 高德地图API配置
    amap_api_key: str = os.getenv("AMAP_API_KEY","")

    # Unsplash 图片服务配置（未配置时自动回退到默认图片）
    unsplash_access_key: str = os.getenv("UNSPLASH_ACCESS_KEY", "")
    unsplash_secret_key: str = os.getenv("UNSPLASH_SECRET_KEY", "")

    #大模型配置
    api_key:str=os.getenv("OPENAI_API_KEY","")
    base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model: str = os.getenv("OPENAI_MODEL", "gpt-4")
    # 是否允许使用服务端默认 API Key（默认 False 严格模式；本地 .env 配置 true 保持现状）
    allow_default_key: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,  # 环境变量大小写不敏感
        extra="ignore",        # 忽略额外的环境变量
    )

    # 把逗号分隔的 cors_origins 字符串转成列表。
    # 原因：.env 里只能写字符串，而 CORSMiddleware 需要的是列表，
    # 所以这里按逗号切开，逐个去掉首尾空格，并跳过空项（如结尾多余逗号）。
    def get_cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

# 创建全局配置实例
settings = Settings()

def get_settings() -> Settings:
    """获取配置实例"""
    return settings


def validate_config() -> None:
    """校验必要配置项，缺失时抛出异常（通常在应用启动时调用）"""
    missing = []
    # 仅当允许默认 Key 时，OPENAI_API_KEY 才是启动硬依赖
    if settings.allow_default_key and not settings.api_key:
        missing.append("OPENAI_API_KEY")
    if not settings.amap_api_key:
        missing.append("AMAP_API_KEY")
    if missing:
        raise ValueError(f"缺少必要的配置项: {', '.join(missing)}，请检查 .env 文件")


def print_config() -> None:
    """打印当前配置摘要（不打印密钥明文）"""
    print(f"  应用: {settings.app_name} v{settings.app_version}")
    print(f"  大模型: {settings.model} ({settings.base_url})")
    print(f"  默认Key回退: {'✅ 允许 (ALLOW_DEFAULT_KEY=true)' if settings.allow_default_key else '🔒 严格模式 (要求自带 Key)'}")
    print(f"  高德地图: {'✅ 已配置' if settings.amap_api_key else '❌ 未配置'}")
    print(f"  Unsplash: {'✅ 已配置' if settings.unsplash_access_key else '⚠️ 未配置（使用默认图片）'}")
    print(f"  日志级别: {settings.log_level}")
