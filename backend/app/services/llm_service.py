"""大模型工厂服务（统一管理 ChatOpenAI 实例的创建）"""

from langchain_openai import ChatOpenAI
from ..config import  get_settings

settings=get_settings()

def get_llm(temperature:float=0.7)->ChatOpenAI:
    """
    获取配置好的通用大模型实例
    通过读取 .env 里的 OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
    """

    return ChatOpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=settings.model,
        temperature=temperature,
        request_timeout=30.0,
        max_retries=2,
    )