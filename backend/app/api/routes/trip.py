"""旅行规划 API 路由（专门处理旅行相关的请求）"""

from fastapi import APIRouter, HTTPException
from ...models.schemas import TripRequest, TripPlanResponse
from ...agents.trip_planner_agent import get_trip_planner_agent

router = APIRouter(prefix="/trip", tags=["旅行规划业务"])


@router.post(
    "/plan",
    response_model=TripPlanResponse,
    summary="生成旅行计划",
    description="根据用户输入的旅行需求，由 LangGraph 多智能体通过 MCP 协同生成详细的旅行计划"
)
async def plan_trip(request: TripRequest):
    """
    当用户在前端点击“生成行程”时触发。
    request 里包含了用户填写的：城市、天数、偏好等。
    """
    try:
        # 1. 打印请求信息
        print(f"\n{'=' * 60}")
        print(f"📥 收到旅行规划请求:")
        print(f"   目的地: {request.city}")
        print(f"   日期: {request.start_date} - {request.end_date} ({request.travel_days}天)")
        print(f"   偏好: {request.preferences}")
        print(f"{'=' * 60}\n")

        # 2. 获取 AI 智能体实例
        print("🔄 正在获取 AI 智能体调度实例...")
        agent = get_trip_planner_agent()

        # 3. 异步启动多智能体图工作流
        print("🚀 多智能体系统正在思考、调用 MCP 并生成旅行计划...")
        trip_plan = await agent.aplan_trip(request)
        print("✅ 旅行计划生成成功！准备返回给前端...\n")

        # 4. 组装响应
        return TripPlanResponse(
            success=True,
            message="旅行计划生成成功",
            data=trip_plan
        )
    except Exception as e:
        print(f"❌ 生成旅行计划失败: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"后端生成旅行计划失败: {str(e)}"
        )


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
