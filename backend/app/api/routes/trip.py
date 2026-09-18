import asyncio
import uuid
from typing import Optional, Dict
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from ...models.schemas import TripRequest, TripPlanResponse
from ...agents.trip_planner_agent import get_trip_planner_agent
from ...services.llm_override import (
    LLMOverride,
    llm_override_context,
    validate_base_url,
    validate_base_url_async,
    probe_llm_credentials,
    mask_key,
)
from ...config import get_settings

router = APIRouter(prefix="/trip", tags=["旅行规划业务"])


class VerifyKeyRequest(BaseModel):
    """验证用户 API Key 请求参数"""
    api_key: str
    base_url: Optional[str] = None


class CancelPlanRequest(BaseModel):
    """取消旅行规划请求参数"""
    request_id: str


# 活跃规划任务注册表：{request_id: asyncio.Task}，用于在用户取消或断开时立即中断任务
_active_plan_tasks: Dict[str, asyncio.Task] = {}


@router.post(
    "/plan",
    response_model=TripPlanResponse,
    summary="生成旅行计划",
    description="根据用户输入的旅行需求，由 LangGraph 多智能体通过 MCP 协同生成详细的旅行计划"
)
async def plan_trip(request: TripRequest, http_request: Request):
    """
    当用户在前端点击“生成行程”时触发。
    request 里包含了用户填写的：城市、天数、偏好等。
    支持用户自带 API Key (BYOK) 与自定义 Base URL（通过请求头透传）。
    """
    settings = get_settings()

    # 1. 提取请求头中的自带 Key 与 Base URL (不落日志)
    raw_api_key = http_request.headers.get("x-llm-api-key") or ""
    raw_base_url = http_request.headers.get("x-llm-base-url") or ""
    user_api_key = raw_api_key.strip()
    user_base_url = raw_base_url.strip()

    # 2. SSRF 护栏校验用户传入的 Base URL (异步线程执行，避免阻塞主循环)
    if user_base_url:
        is_valid, err_msg = await validate_base_url_async(user_base_url)
        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail={"code": "BAD_BASE_URL", "message": f"Base URL 非法: {err_msg}"}
            )

    # 3. 严格模式鉴权：若未带 Key 且服务端禁止默认 Key，返回 409 引导配置
    if not user_api_key:
        if not settings.allow_default_key:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "NO_API_KEY",
                    "message": "当前服务处于严格模式，请在右上角「API 设置」中配置您的 API Key 后继续"
                }
            )
    else:
        # 3.1 端点预检 (0 token 消耗，~0.3s)
        # 预先探测 {base_url}/models，拦截假 Key、过期 Key、欠费 Key，防止静默降级为低质计划
        is_valid, probe_code, probe_msg = await probe_llm_credentials(
            api_key=user_api_key,
            base_url=user_base_url or settings.base_url
        )
        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail={"code": probe_code, "message": probe_msg}
            )

    # 4. 提取规划请求 ID（用于前端取消时精准命中任务）
    plan_request_id = (
        http_request.headers.get("x-plan-request-id")
        or http_request.query_params.get("request_id")
        or str(uuid.uuid4())
    )

    # 5. 构建 override 对象并打印脱敏日志
    override = None
    if user_api_key:
        override = LLMOverride(api_key=user_api_key, base_url=user_base_url or None)
        print(f"🔑 [BYOK] 使用用户自带 API Key (尾号: {mask_key(user_api_key)}, BaseURL: {user_base_url or '默认'})")
    else:
        print("🔑 [默认] 使用服务端配置的默认 API Key (ALLOW_DEFAULT_KEY=true)")

    # 6. 在请求级 ContextVar 上下文中执行 LangGraph 工作流
    with llm_override_context(override):
        agent = get_trip_planner_agent()
        plan_task = asyncio.create_task(agent.aplan_trip(request))
        _active_plan_tasks[plan_request_id] = plan_task

        # 启动客户端连接断开实时监听器（TCP 级别断开检测，响应 Esc 键）
        async def _watch_client_disconnect() -> bool:
            while not plan_task.done():
                try:
                    if await http_request.is_disconnected():
                        return True
                except Exception:
                    return True
                await asyncio.sleep(0.25)
            return False

        disconnect_watcher = asyncio.create_task(_watch_client_disconnect())

        try:
            # 打印请求信息
            print(f"\n{'=' * 60}")
            print(f"📥 收到旅行规划请求 (ID: {plan_request_id}):")
            print(f"   目的地: {request.city}")
            print(f"   日期: {request.start_date} - {request.end_date} ({request.travel_days}天)")
            print(f"   偏好: {request.preferences}")
            print(f"{'=' * 60}\n")
            print("🚀 多智能体系统正在思考、调用 MCP 并生成旅行计划...")

            done, pending = await asyncio.wait(
                [plan_task, disconnect_watcher],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # 场景 1：检测到客户端主动断开连接（如 Esc 取消或关闭标签页）
            if disconnect_watcher in done and disconnect_watcher.result():
                print(f"\n🛑 [连接断开] 检测到客户端已主动断开 (ID: {plan_request_id})，立即终止 Agent 规划并阻断后续 LLM 请求，节省 Token！", flush=True)
                plan_task.cancel()
                try:
                    await plan_task
                except asyncio.CancelledError:
                    pass
                except Exception as ex:
                    print(f"取消任务清理: {ex}", flush=True)

                raise HTTPException(
                    status_code=499,
                    detail="Client closed request: 用户已取消旅行规划"
                )

            # 场景 2：规划任务正常完成或抛出异常
            disconnect_watcher.cancel()
            trip_plan = await plan_task
            print("✅ 旅行计划生成成功！准备返回给前端...\n")

            return TripPlanResponse(
                success=True,
                message="旅行计划生成成功",
                data=trip_plan
            )
        except asyncio.CancelledError:
            # 场景 3：通过显式 /cancel 接口触发了 plan_task.cancel()
            print(f"\n🛑 [显式取消] 规划任务已接收到取消指令 (ID: {plan_request_id})，立即终止 LLM 生成并释放资源！", flush=True)
            disconnect_watcher.cancel()
            if not plan_task.done():
                plan_task.cancel()
                try:
                    await plan_task
                except asyncio.CancelledError:
                    pass
            raise HTTPException(
                status_code=499,
                detail="Plan request cancelled by user: 旅行规划已取消"
            )
        except HTTPException:
            raise
        except Exception as e:
            print(f"❌ 生成旅行计划失败: {str(e)}")
            import traceback
            traceback.print_exc()
            raise HTTPException(
                status_code=500,
                detail=f"后端生成旅行计划失败: {str(e)}"
            )
        finally:
            _active_plan_tasks.pop(plan_request_id, None)


@router.get(
    "/health",
    summary="健康检查",
    description="检查旅行规划 Agent 状态与可用 MCP 工具数量"
)
async def health_check():
    """健康检查接口（返回 Agent 状态与可用 MCP 工具数量）"""
    try:
        agent = get_trip_planner_agent()
        tools = agent.list_tools()

        return {
            "status": "healthy",
            "service": "trip-planner",
            "agent_name": getattr(agent, "name", "LangGraph-Multi-Agent-TripPlanner"),
            "tools_count": len(tools),
            "available_tools": [t.name for t in tools]
        }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"服务不可用: {str(e)}"
        )


@router.post(
    "/verify-key",
    summary="测试 API Key 连接与有效性",
    description="对用户填写的 API Key 和 Base URL 进行 0 Token 探活验证"
)
async def verify_key(req: VerifyKeyRequest):
    """测试用户填写的 API Key 是否可用（供前端「测试连接」按钮调用）"""
    settings = get_settings()
    target_base_url = req.base_url.strip() if req.base_url else settings.base_url

    is_valid, code, message = await probe_llm_credentials(
        api_key=req.api_key.strip(),
        base_url=target_base_url
    )
    return {
        "success": is_valid,
        "code": code,
        "message": message
    }


@router.post(
    "/cancel",
    summary="取消正在进行的旅行规划",
    description="当用户在前端按 Esc 或点击取消按钮时调用，立即终止大模型后台生成以节约 Token"
)
async def cancel_plan(body: CancelPlanRequest):
    """主动取消规划任务，终止当前正在调用的大模型与 Agent 流程"""
    request_id = body.request_id.strip()
    task = _active_plan_tasks.get(request_id)
    if task and not task.done():
        print(f"🛑 [显式取消请求] 收到前端取消指令 (ID: {request_id})，正在中断任务与 LLM 调用...", flush=True)
        task.cancel()
        return {"success": True, "message": "旅行规划任务已成功终止"}
    return {"success": True, "message": "任务已完成或未找到"}

