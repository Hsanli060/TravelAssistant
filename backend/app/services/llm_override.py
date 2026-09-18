# =====================================================================
# 用户自带 API Key (BYOK) 上下文重载服务
# =====================================================================
# 核心职责：
# 1) 请求级 ContextVar 隔离：实现请求生命周期内 API Key 与 Base URL 的安全注入与清理
# 2) SSRF 安全护栏：严密拦截内网/环回/保留地址（localhost, 127., 10., 192.168., 172.16-31., 169.254. 等）
# 3) 日志安全脱敏：提供 mask_key 工具，严防明文 Key 泄漏至服务端日志
# =====================================================================

import asyncio
import ipaddress
import socket
import urllib.parse
from dataclasses import dataclass
from contextlib import contextmanager
from typing import Optional, Tuple
import contextvars
import httpx


@dataclass
class LLMOverride:
    """用户请求级自带 LLM 配置"""
    api_key: str
    base_url: Optional[str] = None


# 请求级上下文变量：保证不同并发协程互不干扰、线程/协程安全
_llm_override_var: contextvars.ContextVar[Optional[LLMOverride]] = contextvars.ContextVar(
    "llm_override_var", default=None
)


def get_llm_override() -> Optional[LLMOverride]:
    """获取当前请求的 LLM 重载配置（未配置则返回 None）"""
    return _llm_override_var.get()


def set_llm_override(override: Optional[LLMOverride]) -> contextvars.Token:
    """设置当前请求的 LLM 重载配置并返回 token"""
    return _llm_override_var.set(override)


def reset_llm_override(token: contextvars.Token) -> None:
    """重置当前请求的 LLM 重载配置"""
    _llm_override_var.reset(token)


@contextmanager
def llm_override_context(override: Optional[LLMOverride]):
    """上下文管理器：安全注入并在退出时保证自动清理"""
    token = _llm_override_var.set(override)
    try:
        yield
    finally:
        _llm_override_var.reset(token)


def mask_key(api_key: str) -> str:
    """脱敏 API Key：只保留前 3 位和后 4 位，其余遮罩"""
    if not api_key or not api_key.strip():
        return ""
    clean = api_key.strip()
    if len(clean) <= 8:
        return "********"
    return f"{clean[:3]}...{clean[-4:]}"


def validate_base_url(url: str) -> Tuple[bool, str]:
    """SSRF 护栏校验：严格检查用户传入的 Base URL。
    
    返回: (是否合法: bool, 错误信息: str)
    
    安全规则：
    1. 必须使用 http:// 或 https:// 协议；
    2. 禁止 localhost、环回地址 (127.0.0.0/8, ::1)；
    3. 禁止私有内网地址 (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fc00::/7)；
    4. 禁止链路本地/云厂商元数据地址 (169.254.0.0/16, fe80::/10)；
    5. 禁止广播与保留地址 (0.0.0.0/8, 240.0.0.0/4)。
    """
    if not url:
        return True, ""

    url = url.strip()
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as e:
        return False, f"URL 解析失败: {e}"

    # 1. 协议白名单
    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"仅支持 http:// 或 https:// 协议，当前协议为: {parsed.scheme}"

    hostname = parsed.hostname
    if not hostname:
        return False, "URL 缺少有效主机名"

    lower_host = hostname.lower()

    # 2. 本地特殊主机名过滤
    blocked_hosts = {
        "localhost",
        "localhost.localdomain",
        "broadcasthost",
        "0.0.0.0",
        "local",
    }
    if lower_host in blocked_hosts or lower_host.endswith(".localhost") or lower_host.endswith(".local"):
        return False, f"禁止访问本地或内部主机名: {hostname}"

    # 3. IP 地址与内网段检测
    try:
        ip = ipaddress.ip_address(lower_host)
        if ip.is_loopback:
            return False, f"禁止访问环回地址: {hostname}"
        if ip.is_private:
            return False, f"禁止访问私有局域网地址: {hostname}"
        if ip.is_link_local:
            return False, f"禁止访问链路本地/云元数据地址: {hostname}"
        if ip.is_reserved:
            return False, f"禁止访问保留地址: {hostname}"
        if ip.is_multicast:
            return False, f"禁止访问多播地址: {hostname}"
        if ip.is_unspecified:
            return False, f"禁止访问未指定地址: {hostname}"
    except ValueError:
        # 非直接 IP 格式（普通域名），进行安全解析探测
        try:
            # 解析域名指向的 IP，防止域名被指向 127.0.0.1 等欺骗行为 (DNS Rebinding 防护)
            resolved_ip_str = socket.gethostbyname(lower_host)
            resolved_ip = ipaddress.ip_address(resolved_ip_str)
            if resolved_ip.is_loopback or resolved_ip.is_private or resolved_ip.is_link_local or resolved_ip.is_reserved:
                return False, f"域名解析指向内网受限地址 ({resolved_ip_str})"
        except socket.gaierror:
            # 域名无法解析时，允许通过或报错；为避免误杀未上线的合规域名，记录但放行或标记
            pass

    # 注：基于 DNS 解析的内网过滤属于 best-effort 降低风险防线，
    # 能够有效降低将域名解析到内网的风险，但无法杜绝动态 DNS 重绑定或外部 HTTP 重定向绕过。
    return True, ""


async def validate_base_url_async(url: str) -> Tuple[bool, str]:
    """异步包装版 SSRF 校验：避免在异步事件循环主线程中同步阻塞 gethostbyname"""
    return await asyncio.to_thread(validate_base_url, url)


async def probe_llm_credentials(
    api_key: str,
    base_url: Optional[str] = None,
    timeout: float = 5.0,
) -> Tuple[bool, str, str]:
    """端点预检探测 LLM 凭证与连接可用性 (0 token 消耗)。

    请求方式: GET {base_url}/models (带 Authorization: Bearer <api_key>)
    返回: (is_valid: bool, error_code: str, error_message: str)

    判定规则：
    1. HTTP 2xx -> 鉴权成功，模型服务连接正常
    2. HTTP 401 / 403 -> BAD_API_KEY，API Key 无效、过期或余额不足
    3. HTTP 429 -> RATE_LIMIT_OR_QUOTA，API Key 额度耗尽或请求过于频繁
    4. HTTP 404 / 405 -> 部分第三方兼容网关未实现 /models 接口，放行 (OK)
    5. HTTP 5xx -> UPSTREAM_ERROR，上游模型服务暂时异常
    6. 网络连接失败 / 超时 -> LLM_CONNECT_FAILED / LLM_TIMEOUT
    """
    if not api_key or not api_key.strip():
        return False, "BAD_API_KEY", "API Key 不能为空"

    # 若未指定 base_url，取服务端默认 base_url
    if not base_url or not base_url.strip():
        from ..config import get_settings
        base_url = get_settings().base_url

    # 1. 严格 SSRF 校验
    is_safe, ssrf_err = await validate_base_url_async(base_url)
    if not is_safe:
        return False, "BAD_BASE_URL", f"Base URL 非法: {ssrf_err}"

    clean_base = base_url.strip().rstrip("/")
    models_url = f"{clean_base}/models"

    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "User-Agent": "TravelAssistant-BYOK-Probe/1.0",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(models_url, headers=headers)

            if resp.status_code in (200, 201, 204):
                return True, "OK", "API Key 校验成功，模型连接正常"

            if resp.status_code in (401, 403):
                return False, "BAD_API_KEY", f"API Key 无效或余额不足 (上游返回 HTTP {resp.status_code})"

            if resp.status_code == 429:
                return False, "RATE_LIMIT_OR_QUOTA", "API Key 额度已用尽或并发超限 (上游返回 HTTP 429)"

            if resp.status_code in (404, 405):
                # 若 base_url 不含 /v1，尝试补充 /v1/models 探活
                if not clean_base.endswith("/v1"):
                    try:
                        v1_resp = await client.get(f"{clean_base}/v1/models", headers=headers)
                        if v1_resp.status_code in (200, 201, 204):
                            return True, "OK", "API Key 校验成功 (/v1/models)"
                        if v1_resp.status_code in (401, 403):
                            return False, "BAD_API_KEY", f"API Key 无效或余额不足 (上游返回 HTTP {v1_resp.status_code})"
                    except Exception:
                        pass
                # 部分第三方反向代理未实现 /models 端点，容错放行
                return True, "OK", "服务商未提供 /models 探活接口，已放行"

            if resp.status_code >= 500:
                return False, "UPSTREAM_ERROR", f"上游大模型服务暂时不可用 (HTTP {resp.status_code})"

            return True, "OK", f"探活状态码 {resp.status_code}，已放行"

    except httpx.ConnectTimeout:
        return False, "LLM_TIMEOUT", f"连接大模型服务超时 ({timeout}s)，请检查 Base URL 或网络状况"
    except httpx.ConnectError as e:
        return False, "LLM_CONNECT_FAILED", f"无法连接到大模型服务器 ({type(e).__name__})，请检查 Base URL 是否正确"
    except httpx.TimeoutException:
        return False, "LLM_TIMEOUT", f"请求大模型服务超时 ({timeout}s)，请检查网络状况"
    except Exception as e:
        return False, "LLM_PROBE_FAILED", f"探测大模型服务失败: {str(e)}"

