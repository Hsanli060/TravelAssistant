# 基于 LangGraph + 高德 MCP 的极简多智能体旅行规划系统

import json
import asyncio
from typing import TypedDict, Optional
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END

from ..services.llm_service import get_llm
from ..services.mcp_service import get_mcp_manager
from ..services.amap_service import get_amap_service
from ..services.unsplash_service import get_unsplash_service
from ..models.schemas import TripRequest, TripPlan, Budget, Location, Hotel, RouteLeg
from .prompts import (
    WEATHER_SUMMARY_SYSTEM_PROMPT,
    build_weather_prompt,
    ATTRACTION_PLANNER_SYSTEM_PROMPT,
    build_attraction_planner_prompt,
    PLANNER_SYSTEM_PROMPT,
    build_planner_prompt,
)


def _to_text(content) -> str:
    """把 LLM 返回的 content 统一转成纯文本"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item["text"] if isinstance(item, dict) and "text" in item else str(item)
            for item in content
        )
    return str(content)


def _format_pois_brief(raw_pois_text: str, max_count: int = 8) -> str:
    """把高德原始搜索 JSON 提炼为紧凑的文本清单，方便 LLM 快速阅读并节省 Token"""
    try:
        data = json.loads(raw_pois_text)
        pois = data.get("pois", [])
        if not pois:
            return raw_pois_text[:1000]
        
        lines = []
        for p in pois[:max_count]:
            name = p.get("name", "")
            address = p.get("address", "")
            typecode = p.get("typecode", "")
            location = p.get("location", "")
            lines.append(f"- 名称: {name} | 地址: {address} | 类别: {typecode} | 坐标: {location}")
        return "\n".join(lines)
    except Exception:
        return raw_pois_text[:1500]


# 通用大模型（用于天气精简与景点分天）
fast_llm = get_llm(temperature=0.3)

# 结构化输出模型（用于最终行程生成）
planner_structured_llm = get_llm(temperature=0.4).with_structured_output(TripPlan, method="json_mode")


# =====================================================================
# 1. 状态定义 (MultiAgentState)
# =====================================================================

class MultiAgentState(TypedDict):
    request: TripRequest                    # 用户初始需求
    weather_summary: str                    # [Agent 1 气象顾问] 极简逐日天气文本
    attraction_schedule: str                # [Agent 2 景点专家] 景点专家规划的分天日程表
    hotel_food_text: str                    # [Agent 3 酒店美食专家] 酒店和特色餐厅的真实文本推荐
    final_plan: Optional[TripPlan]          # [Agent 4 规划总监] 最终生成的完整结构化 TripPlan


# =====================================================================
# 2. 节点定义 (Nodes)
# =====================================================================

async def weather_agent_node(state: MultiAgentState) -> dict:
    """【智能体 1：气象顾问】
    直调高德 maps_weather 接口，提炼出极简的逐日天气与出行建议。
    """
    req = state["request"]
    mcp_mgr = get_mcp_manager()
    print(f"\n🌤️ [Agent 1 气象顾问] 上线！正在调取【{req.city}】天气数据...")

    try:
        raw_weather = await mcp_mgr.call_tool_text("maps_weather", {"city": req.city})
    except Exception as e:
        raw_weather = f"天气查询异常: {str(e)}"

    try:
        res = await fast_llm.ainvoke([
            SystemMessage(content=WEATHER_SUMMARY_SYSTEM_PROMPT),
            HumanMessage(content=build_weather_prompt(
                city=req.city,
                start_date=req.start_date,
                end_date=req.end_date,
                travel_days=req.travel_days,
                raw_weather=raw_weather,
            ))
        ])
        weather_summary = _to_text(res.content).strip()
    except Exception as e:
        print(f"  ⚠️ [Agent 1 气象顾问] 天气提炼失败，使用简单文本兜底: {e}")
        weather_summary = f"{req.city} 出行期间（{req.start_date}至{req.end_date}）常规天气出行，请注意防晒与携带雨具。"

    print(f"   ✅ [Agent 1 气象顾问] 极简天气摘要生成完毕：\n{weather_summary}", flush=True)
    return {"weather_summary": weather_summary}


async def hotel_agent_node(state: MultiAgentState) -> dict:
    """【智能体 2：酒店与美食专家】
    直接调用 1 次高德酒店搜索 + 1 次特色美食搜索，把原数据整理成简明清单。
    """
    req = state["request"]
    mcp_mgr = get_mcp_manager()
    print(f"\n🏨 [Agent 2 酒店美食专家] 上线！正在搜索【{req.city}】的精选酒店与特色美食...", flush=True)

    # 1. 搜索酒店（聚焦市中心与核心景区商圈，方便动线游览）
    hotel_kw = f"{req.city} 市中心 核心景区 {req.accommodation or '酒店'}"
    try:
        raw_hotels = await mcp_mgr.call_tool_text("maps_text_search", {
            "keywords": hotel_kw,
            "city": req.city
        })
        hotels_text = _format_pois_brief(raw_hotels, max_count=5)
    except Exception as e:
        hotels_text = f"- 查询酒店失败: {e}"

    # 2. 搜索当地美食
    food_kw = f"{req.city} 特色美食 老字号"
    try:
        raw_foods = await mcp_mgr.call_tool_text("maps_text_search", {
            "keywords": food_kw,
            "city": req.city
        })
        foods_text = _format_pois_brief(raw_foods, max_count=6)
    except Exception as e:
        foods_text = f"- 查询特色美食失败: {e}"

    hotel_food_text = f"""【精选酒店推荐】：
{hotels_text}

【特色美食/老字号推荐】：
{foods_text}"""

    print("   ✅ [Agent 2 酒店美食专家] 住宿与餐厅推荐数据整理完成！", flush=True)
    return {"hotel_food_text": hotel_food_text}


async def attraction_agent_node(state: MultiAgentState) -> dict:
    """【智能体 3：景点规划专家】
    搜索真实景点 -> 结合气象顾问的天气情况 -> 输出清晰的每日分天动线表。
    """
    req = state["request"]
    weather_summary = state.get("weather_summary", "")
    mcp_mgr = get_mcp_manager()
    print(f"\n🏛️ [Agent 3 景点规划专家] 上线！正在调取【{req.city}】热门景点并结合天气进行分天动线编排...", flush=True)

    # 搜索 1~2 次景点
    search_terms = [f"{req.city} 热门景点 5A 博物馆"]
    if req.preferences:
        search_terms.append(f"{req.city} {' '.join(req.preferences)}")

    raw_attraction_list = []
    for kw in search_terms:
        try:
            raw_res = await mcp_mgr.call_tool_text("maps_text_search", {
                "keywords": kw,
                "city": req.city
            })
            raw_attraction_list.append(_format_pois_brief(raw_res, max_count=6))
        except Exception as e:
            raw_attraction_list.append(f"- 搜索关键词 '{kw}' 异常: {e}")

    attractions_text = "\n".join(raw_attraction_list)

    # 由 LLM 结合天气进行分天动线规划
    try:
        res = await fast_llm.ainvoke([
            SystemMessage(content=ATTRACTION_PLANNER_SYSTEM_PROMPT),
            HumanMessage(content=build_attraction_planner_prompt(
                city=req.city,
                travel_days=req.travel_days,
                preferences=req.preferences,
                free_text_input=req.free_text_input or "",
                weather_summary=weather_summary,
                raw_attractions_text=attractions_text,
            ))
        ])
        attraction_schedule = _to_text(res.content).strip()
    except Exception as e:
        print(f"  ⚠️ [Agent 3 景点规划专家] 分天规划异常: {e}", flush=True)
        attraction_schedule = "【每日景点动线推荐】\n- 按常规热门景点顺路游览。"

    print(f"   ✅ [Agent 3 景点规划专家] 景点分天动线规划完成：\n{attraction_schedule}\n", flush=True)
    return {"attraction_schedule": attraction_schedule}


async def planner_agent_node(state: MultiAgentState) -> dict:
    """【智能体 4：行程规划总监】
    汇总天气、景点分天动线表、酒店美食清单，一步输出最终结构化 TripPlan。
    """
    req = state["request"]
    weather = state["weather_summary"]
    attractions = state["attraction_schedule"]
    hotels_food = state["hotel_food_text"]

    print("\n🧠 [Agent 4 行程规划总监] 上线！正在汇集各环节情报，一次性构建完整旅行方案...", flush=True)

    schema_json = json.dumps(TripPlan.model_json_schema(), ensure_ascii=False)

    try:
        final_plan: TripPlan = await planner_structured_llm.ainvoke([
            SystemMessage(content=PLANNER_SYSTEM_PROMPT),
            HumanMessage(content=build_planner_prompt(
                request_json=req.model_dump_json(indent=2),
                weather_summary=weather,
                attraction_schedule=attractions,
                hotel_food_text=hotels_food,
                schema_json=schema_json,
            ))
        ])
    except Exception as e:
        print(f"  ⚠️ [Agent 4 行程规划总监] 结构化生成失败，尝试兜底构建: {e}")
        # 基础兜底构建，确保接口不抛 500
        final_plan = TripPlan(
            city=req.city,
            start_date=req.start_date,
            end_date=req.end_date,
            days=[],
            overall_suggestions=f"旅行规划生成异常，请重试。错误信息: {str(e)}",
        )

    # 1. 并发为每个景点配上真实实景照片与真实高德经纬度坐标，并补齐住宿酒店精确位置
    unsplash = get_unsplash_service()
    amap_svc = get_amap_service()

    if final_plan and final_plan.days:
        async def _enrich_attr(attr):
            try:
                # 1. 优先调用高德综合景区检索获取真实坐标与实景照片
                spot_info = await asyncio.to_thread(amap_svc.search_scenic_spot, attr.name, req.city)
                if spot_info:
                    if not attr.location or not attr.location.longitude or attr.location.longitude == 0:
                        if spot_info.get("location"):
                            attr.location = spot_info["location"]
                    if not attr.image_url and spot_info.get("photo_url"):
                        attr.image_url = spot_info["photo_url"]
                    if not attr.address and spot_info.get("address"):
                        attr.address = spot_info["address"]
            except Exception:
                pass

            # 2. 若仍缺照片，走通用多级图库检索
            if not attr.image_url:
                try:
                    attr.image_url = await asyncio.to_thread(unsplash.get_image, attr.name, req.city)
                except Exception:
                    attr.image_url = None

            # 3. 若仍缺坐标，尝试普通地理编码
            if not attr.location or not attr.location.longitude or attr.location.longitude == 0:
                try:
                    geo_loc = await asyncio.to_thread(amap_svc.geocode, f"{req.city}{attr.name}", req.city)
                    if geo_loc and geo_loc.longitude and geo_loc.latitude:
                        attr.location = geo_loc
                except Exception:
                    pass

        async def _enrich_hotel(day):
            if day.hotel and day.hotel.name:
                try:
                    h_info = await asyncio.to_thread(amap_svc.search_scenic_spot, day.hotel.name, req.city)
                    if h_info:
                        if not day.hotel.location and h_info.get("location"):
                            day.hotel.location = h_info["location"]
                        if not day.hotel.address and h_info.get("address"):
                            day.hotel.address = h_info["address"]
                except Exception:
                    pass
            elif not day.hotel:
                # 如果缺少酒店对象，根据城市和住宿偏好自动创建候选酒店
                h_name = f"{req.city}中心亚朵酒店"
                h_info = await asyncio.to_thread(amap_svc.search_scenic_spot, h_name, req.city)
                day.hotel = Hotel(
                    name=h_name,
                    address=h_info.get("address", f"{req.city}核心商圈"),
                    location=h_info.get("location"),
                    estimated_cost=380,
                    type=req.accommodation or "舒适型酒店"
                )

        # 并发执行景点与酒店信息补全
        tasks = []
        for day in final_plan.days:
            tasks.append(_enrich_hotel(day))
            for attr in day.attractions:
                tasks.append(_enrich_attr(attr))

        if tasks:
            await asyncio.gather(*tasks)

        # 2. 计算每日由“住宿 -> 景点1 -> 景点2 -> ... -> 住宿”的真实交通距离与路程建议 (legs)
        for day in final_plan.days:
            day.legs = []
            waypoints = []

            # 出发点：当日酒店
            if day.hotel and day.hotel.location and day.hotel.location.longitude != 0:
                waypoints.append((f"{day.hotel.name}(出发)", day.hotel.location))

            # 途径景点
            for attr in day.attractions:
                if attr.location and attr.location.longitude != 0:
                    waypoints.append((attr.name, attr.location))

            # 返程：回到当日酒店
            if len(day.attractions) > 0 and day.hotel and day.hotel.location and day.hotel.location.longitude != 0:
                waypoints.append((f"{day.hotel.name}(返程)", day.hotel.location))

            # 逐段计算交通
            for i in range(len(waypoints) - 1):
                from_name, from_loc = waypoints[i]
                to_name, to_loc = waypoints[i + 1]
                leg = amap_svc.calculate_leg(from_loc, to_loc, from_name, to_name)
                day.legs.append(leg)

    # 3. 计算/校验各维度预算及总预算，确保前端拿到精确的预算明细
    if final_plan and final_plan.days:
        total_attractions = sum(
            (attr.ticket_price if attr.ticket_price is not None else 0)
            for day in final_plan.days
            for attr in day.attractions
        )
        total_hotels = sum(
            (day.hotel.estimated_cost if (day.hotel and day.hotel.estimated_cost) else 300)
            for day in final_plan.days
        )
        total_meals = sum(
            (meal.estimated_cost if meal.estimated_cost else 60)
            for day in final_plan.days
            for meal in day.meals
        )
        # 市内交通按天数估算（公共交通约 30元/天，自驾/打车约 80元/天）
        daily_transport = 80 if ("打车" in (req.transportation or "") or "自驾" in (req.transportation or "")) else 30
        total_transport = daily_transport * len(final_plan.days)

        if not final_plan.budget or final_plan.budget.total == 0:
            final_plan.budget = Budget(
                total_attractions=total_attractions,
                total_hotels=total_hotels,
                total_meals=total_meals,
                total_transportation=total_transport,
                total=total_attractions + total_hotels + total_meals + total_transport,
            )
        else:
            b = final_plan.budget
            # 若 LLM 遗漏了部分项则用计算值补齐
            if b.total_attractions == 0 and total_attractions > 0:
                b.total_attractions = total_attractions
            if b.total_hotels == 0 and total_hotels > 0:
                b.total_hotels = total_hotels
            if b.total_meals == 0 and total_meals > 0:
                b.total_meals = total_meals
            if b.total_transportation == 0 and total_transport > 0:
                b.total_transportation = total_transport
            b.total = b.total_attractions + b.total_hotels + b.total_meals + b.total_transportation

    print("   ✅ [Agent 4 行程规划总监] 最终旅行计划交付完毕！🎉\n", flush=True)
    return {"final_plan": final_plan}


# =====================================================================
# 3. 组装 LangGraph 工作流
# =====================================================================

workflow = StateGraph(MultiAgentState)

# 注册 4 个节点
workflow.add_node("weather_agent", weather_agent_node)
workflow.add_node("attraction_agent", attraction_agent_node)
workflow.add_node("hotel_agent", hotel_agent_node)
workflow.add_node("planner_agent", planner_agent_node)

# 极简流水线拓扑连线：
# START -> 天气顾问 -> 景点专家 (根据天气编排动线) -> 酒店美食专家 -> 规划总监 -> END
workflow.add_edge(START, "weather_agent")
workflow.add_edge("weather_agent", "attraction_agent")
workflow.add_edge("attraction_agent", "hotel_agent")
workflow.add_edge("hotel_agent", "planner_agent")
workflow.add_edge("planner_agent", END)

# 编译图应用
multi_agent_app = workflow.compile()


# =====================================================================
# 4. 对外调用类
# =====================================================================

class TripPlannerAgent:
    """旅行规划多智能体系统调用入口"""
    def __init__(self):
        self.name = "LangGraph-Multi-Agent-TripPlanner"

    def list_tools(self) -> list:
        """获取当前挂载的 MCP 工具列表"""
        return get_mcp_manager().get_all_tools()

    async def aplan_trip(self, request: TripRequest) -> TripPlan:
        """异步执行多智能体协同旅行规划"""
        # 确保 MCP 服务已就绪
        await get_mcp_manager().initialize()

        initial_state: MultiAgentState = {
            "request": request,
            "weather_summary": "",
            "attraction_schedule": "",
            "hotel_food_text": "",
            "final_plan": None,
        }

        # 启动异步多智能体图工作流
        final_state = await multi_agent_app.ainvoke(initial_state)
        return final_state["final_plan"]

    def plan_trip(self, request: TripRequest) -> TripPlan:
        """同步执行多智能体协同旅行规划（只能在无事件循环的线程中调用）"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.aplan_trip(request))
        raise RuntimeError(
            "plan_trip() 是同步方法，不能在 asyncio 事件循环内调用。"
            "请使用 await agent.aplan_trip(request)"
        )


def get_trip_planner_agent() -> TripPlannerAgent:
    """工厂函数：获取智能体调度实例"""
    return TripPlannerAgent()
