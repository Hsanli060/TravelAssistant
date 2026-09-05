# =====================================================================
# 基于 LangGraph + 高德 MCP 的多智能体旅行规划系统（fan-out / fan-in 并行拓扑）
# =====================================================================
#
# 拓扑：
#   START ──fan-out──→ weather_agent（气象顾问·ReAct）
#                   ├──→ hotel_agent（酒店餐厅专家）
#                   └──→ attraction_agent（景点专家）
#   三者 fan-in ──→ planner_agent（行程规划总监）──→ END
#
# 本文件只保留 LangGraph 逻辑：状态定义、节点函数、图组装、对外调用类。
# 所有确定性工具函数（MCP 解析 / 数据增强 / 兜底 / 后处理）位于 trip_planner_helpers.py。
#
# 设计要点：
#   - Agent 间传递结构化 Pydantic 对象（WeatherReport / HotelFoodResult / AttractionPool），不传散文。
#   - LLM 一律惰性创建（带缓存的函数），严禁模块级 get_llm() 调用，杜绝 import 期网络/密钥副作用。
#   - 预算完全由 Python 确定性计算，LLM 只出单价。
#   - 预算约束每日 480min 时间窗算法、晴雨编排、顺路聚类等硬性规则全部写在规划总监提示词里。

import asyncio
import operator
from typing import Annotated, List, Optional, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from ..models.schemas import (
    AttractionPool,
    Budget,
    HotelFoodResult,
    TripPlan,
    TripRequest,
    WeatherReport,
)
from ..services.mcp_service import get_mcp_manager
from .prompts import (
    ATTRACTION_PARAM_SYSTEM_PROMPT,
    HOTEL_FOOD_SELECT_SYSTEM_PROMPT,
    WEATHER_STRUCTURE_SYSTEM_PROMPT,
    build_attraction_param_prompt,
    build_hotel_food_selection_prompt,
)
from .trip_planner_helpers import (
    ATTRACTION_PREFERENCE_KEYWORDS,
    _backfill_attraction_details,
    _build_weather_info,
    _calculate_budget,
    _dedupe_candidates,
    _default_suggestions,
    _dedupe_pois,
    _enrich_attraction_detail,
    _enrich_hotel_price,
    _enrich_restaurant_cost,
    _extract_cuisine_keywords,
    _extract_last_ai_text,
    _extract_place_names,
    _fallback_attraction_pool,
    _fallback_hotel_food,
    _filter_pois_by_type,
    _format_pois_list,
    _get_fast_llm,
    _get_weather_react_agent,
    _is_hotel_poi,
    _is_restaurant_poi,
    _llm_orchestrate_plan,
    _naive_fallback_plan,
    _normalize_poi_name,
    _parse_pois,
    _parse_poi_location,
    _postprocess_plan,
)


# =====================================================================
# 1. 状态定义 (MultiAgentState)
# =====================================================================

class MultiAgentState(TypedDict):
    request: TripRequest                              # 用户初始需求（只读）
    weather_report: Optional[WeatherReport]           # ← 天气weather_agent 写
    hotel_food: Optional[HotelFoodResult]             # ← 酒店餐馆hotel_agent 写
    attraction_pool: Optional[AttractionPool]         # ← 景点attraction_agent 写
    errors: Annotated[List[str], operator.add]        # 三个并行分支都可能追加降级信息 → 必须用 reducer 合并
    final_plan: Optional[TripPlan]                    # ← planner_agent 写


# =====================================================================
# 2. 节点定义 (Nodes)
# =====================================================================

async def weather_agent_node(state: MultiAgentState) -> dict:
    """气象顾问节点：ReAct 自主调用天气 MCP 工具，再结构化收口为 WeatherReport

    职责：
    1. 用 @tool 包装 maps_weather（保持 MCPManager._call_lock 锁语义，避免与并行分支竞争 stdio 会话）；
    2. create_react_agent 让 LLM 自主决定调用时机/参数/重试；
    3. ReAct 结束后用 with_structured_output(WeatherReport, json_mode) 收口；
    4. 整体 try/except 降级：失败返回 WeatherReport() + errors 追加，绝不向上抛。
    """
    request = state.get("request")
    if not request:
        return {"weather_report": WeatherReport(), "errors": ["缺少旅行请求，无法查询天气"]}

    errors = []
    weather_report = WeatherReport()
    try:
        # 1. ReAct 循环：LLM 自主调用 maps_weather 工具（单步超时保护）
        react_agent = _get_weather_react_agent()
        react_input = {
            "messages": [
                HumanMessage(content=(
                    f"请查询城市「{request.city}」在出行日期 {request.start_date} 至 {request.end_date}"
                    f"（共 {request.travel_days} 天）的逐日天气预报。"
                ))
            ]
        }
        #wait_for起保护作用，限制react_agent运行在90s内，防止死循环
        result = await asyncio.wait_for(react_agent.ainvoke(react_input), timeout=90.0)
        #将result进行字符串化处理：选择最后一条AI回答的信息（非空）。兜底：取最后一条非空文本
        final_text = _extract_last_ai_text(result)

        # 2. 结构化收口：把 ReAct 汇总文本转成结构化 WeatherReport
        structured = _get_fast_llm().with_structured_output(WeatherReport, method="json_mode")
        parsed = await structured.ainvoke([
            SystemMessage(content=WEATHER_STRUCTURE_SYSTEM_PROMPT),
            HumanMessage(content=(
                f"城市: {request.city}\n出行日期: {request.start_date} ~ {request.end_date}\n\n"
                f"天气原始信息:\n{final_text}"
            )),
        ])
        #parsed是空就新建一个WeatherReport空对象
        weather_report = parsed or WeatherReport()
        #每天天气列表为空
        if not any(d.has_data for d in weather_report.daily):
            errors.append("天气 Agent 未能获取到覆盖出行日期的预报数据，部分日期天气未知")
        print("✅ 天气 Agent 已完成结构化天气报告", flush=True)
    except Exception as e:
        print(f"⚠️ 天气 Agent 降级处理: {str(e)}", flush=True)
        errors.append(f"天气查询失败，已降级: {e}")

    return {"weather_report": weather_report, "errors": errors}


async def hotel_agent_node(state: MultiAgentState) -> dict:
    """酒店餐厅专家节点：MCP 多轮检索真实 POI → LLM 甄选 HotelFoodResult，双重降级保底

    检索关键词由用户输入驱动（住宿偏好 / 特色早餐 / 老字号正餐 / 菜系追加），
    MCP 失败 → 空池 + errors；LLM 失败 → 用解析出的原始 POI 前 N 条构造保底候选。
    """
    request = state.get("request")
    if not request:
        return {"hotel_food": HotelFoodResult(), "errors": ["缺少旅行请求，无法检索酒店餐厅"]}

    errors = []
    result = HotelFoodResult()

    # 1. 关键词矩阵
    keyword_rounds = [
        (f"{request.city} {request.accommodation}", "hotel"),
        (f"{request.city} {request.accommodation} 地铁口", "hotel"),
        (f"{request.city} 当地特色早餐 早点", "restaurant"),
        (f"{request.city} 当地特色美食 老字号餐厅", "restaurant"),
    ]
    #提起free_text_input（额外需求）的美食关键词，如："火锅", "烧烤", "小吃", "面", "烤鸭"等
    for kw in _extract_cuisine_keywords(request.free_text_input or ""):
        keyword_rounds.append((f"{request.city} {kw}", "restaurant"))

    # 2. 多轮 MCP 检索（内部串行即可），压缩成紧凑清单
    mcp = get_mcp_manager()
    hotel_pois: List[dict] = []
    restaurant_pois: List[dict] = []
    brief_chunks: List[str] = []
    for kw, kind in keyword_rounds:
        try:
            #调用MCP工具
            raw = await mcp.call_tool_text("maps_text_search", {"keywords": kw, "city": request.city})
            #数据清洗：拿到 key=pois 的值（list[dict]）
            #{"status":"1","pois":[{"name":"故宫博物院","address":"...","location":"116.397,39.918","type":"风景名胜",...}, {...}]}
            pois = _parse_pois(raw)
            if not pois:
                continue
            if kind == "hotel":
                #从pois筛选出酒店的poi，extend将酒店追加到hotel_pois
                hotel_pois.extend(_filter_pois_by_type(pois, _is_hotel_poi))
            else:
                #筛选出餐厅的poi
                restaurant_pois.extend(_filter_pois_by_type(pois, _is_restaurant_poi))
            brief = _format_pois_list(pois, max_items=12)
            if brief:
                brief_chunks.append(brief)
        except Exception as e:
            errors.append(f"MCP 检索「{kw}」失败: {e}")

    combined_brief = "\n".join(brief_chunks)
    if not hotel_pois and not restaurant_pois:
        errors.append("酒店/餐厅 MCP 检索结果为空，无法提供真实候选（候选池为空，酒店将为 None）")
        return {"hotel_food": result, "errors": errors}

    # 3. LLM 甄选（候选池只能来自真实 POI）
    try:
        structured = _get_fast_llm().with_structured_output(HotelFoodResult, method="json_mode")
        human = build_hotel_food_selection_prompt(
            request,
            combined_brief or _format_pois_list(hotel_pois + restaurant_pois, max_items=25),
        )
        parsed = await structured.ainvoke([
            SystemMessage(content=HOTEL_FOOD_SELECT_SYSTEM_PROMPT),
            HumanMessage(content=human),
        ])
        result = parsed or HotelFoodResult()
        if not result.hotels and not result.restaurants:
            raise ValueError("LLM 酒店餐厅甄选结果为空")
        # 确定性补丁：LLM正常运行但是漏选，返回有真实酒店餐厅数据但LLM没加上，选择手动添加
        #手动添加餐厅列表
        if not result.restaurants and restaurant_pois:
            print("⚠️ LLM 未选出餐厅，用真实检索池补齐餐厅候选", flush=True)
            result.restaurants = _fallback_hotel_food([], restaurant_pois).restaurants
        #手动添加酒店列表
        if not result.hotels and hotel_pois:
            print("⚠️ LLM 未选出酒店，用真实检索池补齐酒店候选", flush=True)
            result.hotels = _fallback_hotel_food(hotel_pois, []).hotels
    except Exception as e:
        print(f"⚠️ 酒店餐厅 Agent LLM 甄选失败，使用原始 POI 保底: {str(e)}", flush=True)
        errors.append(f"酒店餐厅甄选失败，已用原始 POI 保底: {e}")
        #LLM异常，同样选择手动添加
        result = _fallback_hotel_food(hotel_pois, restaurant_pois)

    # 3.6 候选去重（确定性）：同名同址合并，同名不同址保留并加分店后缀。
    #     连锁酒店常见同名分店，不去重会导致 poi_id 回填同名互相覆盖、
    #     以及规划总监逐日分配不同分店时动线出发点漂移（详见 _dedupe_candidates）。
    result.hotels = _dedupe_candidates(result.hotels)
    result.restaurants = _dedupe_candidates(result.restaurants)

    # 3.5 poi_id 确定性回填：LLM返回的地点可能没有poi_id，那就从高德返回的结果中获取填补
    #     键用「归一化名称|坐标」：同名分店若只按名称建映射，后面的 id 会覆盖前面的，
    #     导致两家分店拿到同一个 poi_id（回查详情张冠李戴）。
    _poi_id_map = {}
    for p in [*hotel_pois, *restaurant_pois]:
        pid = p.get("id")
        if not pid:
            continue
        lng, lat = _parse_poi_location(p.get("location", ""))
        #{ "如家酒店|116.397,39.899" : "B001" , ...}
        _poi_id_map.setdefault(f"{_normalize_poi_name(str(p.get('name', '')))}|{lng},{lat}", pid)
    #补全LLM候选出来没有id的选项
    for cand in [*result.hotels, *result.restaurants]:
        if cand.poi_id:
            continue
        lng, lat = (cand.longitude, cand.latitude)
        cand.poi_id = (
            _poi_id_map.get(f"{_normalize_poi_name(cand.name)}|{lng},{lat}")
            # 加了分店后缀的候选（"如家酒店(灯市口大街)"）先按全名试，再退回归一化名
            or _poi_id_map.get(f"{_normalize_poi_name(_normalize_poi_name(cand.name))}|{lng},{lat}")
            # 坐标缺失/检索池没对上时的最终退路：单名称映射（同名时保留首个，宁缺勿错）
            or _poi_id_map.get(f"{_normalize_poi_name(cand.name)}|None,None", "")
        )

    # 4. 真实数据增强：餐厅人均 cost / 酒店星级房价（并发回查 maps_search_detail，失败静默）
    try:
        #创建事件循环任务：通过酒店餐馆的poi_id调用高德MCP 的 maps_search_detai，返回这家店的详情（人均消费/评分；酒店再加星级）赋值到r/h中
        enrich_tasks = [asyncio.create_task(_enrich_restaurant_cost(r)) for r in result.restaurants[:8]]
        enrich_tasks += [asyncio.create_task(_enrich_hotel_price(h)) for h in result.hotels[:5]]
        if enrich_tasks:
            #执行并等待任务完成
            await asyncio.gather(*enrich_tasks, return_exceptions=True)
    except Exception as e:
        errors.append(f"酒店餐厅真实数据增强失败: {e}")

    print(f"✅ 酒店餐厅 Agent 已完成甄选（酒店 {len(result.hotels)} 家 · 餐厅 {len(result.restaurants)} 家，已回查真实价格）", flush=True)
    return {"hotel_food": result, "errors": errors}


async def attraction_agent_node(state: MultiAgentState) -> dict:
    """景点专家节点：多路检索真实景点 POI → 去重 → LLM 参数化 AttractionPool，双重降级保底

    关键词矩阵由基础轮 + 偏好映射 + 自由文本潜在地名组成，总检索轮数 2~4 轮封顶；
    LLM 失败时用原始 POI 直接转候选（visit_duration=120 默认）。
    """
    request = state.get("request")
    if not request:
        return {"attraction_pool": AttractionPool(), "errors": ["缺少旅行请求，无法检索景点"]}

    errors = []
    pool = AttractionPool()

    # 1. 关键词矩阵（基础 + 偏好映射 + 自由文本潜在地名 + 默认网红打卡），2~4 轮封顶
    keywords: List[str] = [f"{request.city} 热门景点", f"{request.city} 网红打卡地"]
    for pref in request.preferences or []:
        mapped = ATTRACTION_PREFERENCE_KEYWORDS.get(pref)
        if mapped:
            kw = f"{request.city} {mapped}"
            if kw not in keywords:
                keywords.append(kw)
    #从用户的free_text_input（额外需求）中提取景点关键字，如："故宫", "颐和园", "博物馆", "胡同"
    for place in _extract_place_names(request.free_text_input or ""):
        kw = f"{request.city} {place}"
        if kw not in keywords:
            keywords.append(kw)

    keywords = keywords[:5]

    # 2. 多轮 MCP 检索 + 压缩 + 去重
    mcp = get_mcp_manager()
    all_pois: List[dict] = []
    brief_chunks: List[str] = []
    for kw in keywords:
        try:
            raw = await mcp.call_tool_text("maps_text_search", {"keywords": kw, "city": request.city})
            # 数据清洗：拿到 key = pois 的值（list[dict]）
            pois = _parse_pois(raw)
            if pois:
                all_pois.extend(pois)
            brief = _format_pois_list(pois, max_items=15)
            if brief:
                brief_chunks.append(brief)
        except Exception as e:
            errors.append(f"MCP 检索景点「{kw}」失败: {e}")
    #按 '归一化名称|坐标' 去重，保留首次出现的 POI
    unique_pois = _dedupe_pois(all_pois)
    combined_brief = "\n".join(brief_chunks)
    if not unique_pois:
        errors.append("景点 MCP 检索结果为空，无法提供景点候选")
        return {"attraction_pool": pool, "errors": errors}

    # 3. LLM 参数化（只能从候选池挑选，禁止编造）
    try:
        structured = _get_fast_llm().with_structured_output(AttractionPool, method="json_mode")
        human = build_attraction_param_prompt(
            request,
            combined_brief or _format_pois_list(unique_pois[:30], max_items=30),
        )
        parsed = await structured.ainvoke([
            SystemMessage(content=ATTRACTION_PARAM_SYSTEM_PROMPT),
            HumanMessage(content=human),
        ])
        pool = parsed or AttractionPool()
        if not pool.candidates:
            raise ValueError("LLM 景点参数化结果为空")
    except Exception as e:
        print(f"⚠️ 景点 Agent LLM 参数化失败，使用原始 POI 保底: {str(e)}", flush=True)
        errors.append(f"景点参数化失败，已用原始 POI 保底: {e}")
        #手动添加景点信息
        pool = _fallback_attraction_pool(unique_pois)

    # 3.5 poi_id 确定性回填：紧凑清单刻意不含 id（省 token），导致 LLM 参数化结果可能漏填 poi_id。
    #     直接从去重后的检索池按「归一化名称 → id」映射补齐（归一化对齐"故宫"与"故宫(东门)"），
    #     避免 enrich 阶段为拿 id 再按名称搜索一次 MCP（绕路）。
    #_poi_id_map={"故宫博物院": "B000A8206C", "颐和园": "B000A8U608",...}
    _poi_id_map = {
        _normalize_poi_name(str(p.get("name", ""))): str(p.get("id", ""))
        for p in unique_pois
        if p.get("id")
    }
    #填充LLM返回内容缺少poi_id的部分数据
    for cand in pool.candidates:
        if not cand.poi_id:
            cand.poi_id = _poi_id_map.get(_normalize_poi_name(cand.name), "")

    # 4. 真实数据增强：景点开放时间/等级/评分（并发回查 maps_search_detail，失败静默）
    try:
        enrich_tasks = [asyncio.create_task(_enrich_attraction_detail(c)) for c in pool.candidates[:12]]
        if enrich_tasks:
            await asyncio.gather(*enrich_tasks, return_exceptions=True)
    except Exception as e:
        errors.append(f"景点真实数据增强失败: {e}")

    print(f"✅ 景点 Agent 已完成候选池（{len(pool.candidates)} 个候选，已回查真实开放时间）", flush=True)
    return {"attraction_pool": pool, "errors": errors}


async def planner_agent_node(state: MultiAgentState) -> dict:
    """行程规划总监节点：LLM 编排 → Python 确定性后处理（坐标图片补全/动线计算/预算精算）

    LLM 编排失败时按候选池朴素分天兜底；budget 一律用 Python 计算值覆盖，禁止信任 LLM 算账。
    """
    request = state.get("request")
    if not request:
        return {"final_plan": None, "errors": ["缺少旅行请求，无法编排行程"]}

    weather_report = state.get("weather_report") or WeatherReport()
    hotel_food = state.get("hotel_food") or HotelFoodResult()
    attraction_pool = state.get("attraction_pool") or AttractionPool()
    new_errors: List[str] = []

    # 第一步：LLM 编排（失败进入朴素分天兜底）
    trip_plan: Optional[TripPlan] = None
    try:
        trip_plan = await _llm_orchestrate_plan(request, weather_report, hotel_food, attraction_pool)
        if trip_plan is None:
            raise ValueError("LLM 编排无有效结果")
    except Exception as e:
        print(f"⚠️ 规划总监 LLM 编排失败，进入朴素分天兜底: {str(e)}", flush=True)
        new_errors.append(f"LLM 编排行程失败，已用确定性算法兜底: {e}")
        trip_plan = _naive_fallback_plan(request, attraction_pool, hotel_food, weather_report)

    # 第二步：Python 确定性后处理
    try:
        #补充LLM回答信息：补天、补日期、补酒店、补餐厅、补坐标、算路线，让行程“结构完整”
        trip_plan = await _postprocess_plan(trip_plan, request, hotel_food)
    except Exception as e:
        print(f"⚠️ 行程确定性后处理失败: {str(e)}", flush=True)
        new_errors.append(f"行程后处理失败，返回原始编排结果: {e}")

    # 真实详情回填：LLM 常漏抄候选池的开放时间/评分，按景点名确定性补齐
    try:
        #补充信息：开放时间、评分
        _backfill_attraction_details(trip_plan, attraction_pool)
    except Exception as e:
        print(f"⚠️ 景点真实详情回填失败: {str(e)}", flush=True)

    # 预算精算（LLM 的 budget 一律覆盖）
    try:
        trip_plan.budget = _calculate_budget(trip_plan, request.transportation)
    except Exception as e:
        print(f"⚠️ 预算精算失败: {str(e)}", flush=True)
        trip_plan.budget = Budget()

    #LLM返回的天气报告，转换成前端要的展示格式
    trip_plan.weather_info = _build_weather_info(weather_report)

    # 总体建议兜底：LLM 偶发漏写时用确定性文案补上
    if not (trip_plan.overall_suggestions or "").strip():
        trip_plan.overall_suggestions = _default_suggestions(request, weather_report, trip_plan)

    return {"final_plan": trip_plan, "errors": new_errors}


# =====================================================================
# 3. 组装 LangGraph 工作流
# =====================================================================

workflow = StateGraph(MultiAgentState)
workflow.add_node("weather_agent", weather_agent_node)
workflow.add_node("hotel_agent", hotel_agent_node)
workflow.add_node("attraction_agent", attraction_agent_node)
workflow.add_node("planner_agent", planner_agent_node)

# fan-out：三个数据 Agent 各自从 START 出发，同一 super-step 并行调度
workflow.add_edge(START, "weather_agent")
workflow.add_edge(START, "hotel_agent")
workflow.add_edge(START, "attraction_agent")

# fan-in：planner 有 3 条入边，LangGraph 会等全部上游完成后才执行一次（天然 join 屏障）
workflow.add_edge("weather_agent", "planner_agent")
workflow.add_edge("hotel_agent", "planner_agent")
workflow.add_edge("attraction_agent", "planner_agent")
workflow.add_edge("planner_agent", END)

# 编译图应用
multi_agent_app = workflow.compile()


# =====================================================================
# 4. 对外调用类
# =====================================================================

class TripPlannerAgent:
    """旅行规划多智能体系统调用入口"""
    name = "LangGraph-Multi-Agent-TripPlanner"

    def list_tools(self) -> list:
        """列出多智能体系统中当前可用的 MCP 工具（未初始化/初始化失败时返回空列表）"""
        mcp = get_mcp_manager()
        tools_map = getattr(mcp, "tools_map", None) or {}
        if tools_map:
            return list(tools_map.values())
        return []

    async def aplan_trip(self, request: TripRequest) -> TripPlan:
        """异步生成旅行计划（先初始化 MCP，再并行调度四个 Agent）"""
        mcp = get_mcp_manager()
        try:
            await mcp.initialize()
        except Exception as e:
            print(f"⚠️ MCP 初始化失败，数据 Agent 将整体降级: {str(e)}", flush=True)

        # 初始 state 所有 key 都给默认值
        initial_state: MultiAgentState = {
            "request": request,
            "weather_report": WeatherReport(),
            "hotel_food": HotelFoodResult(),
            "attraction_pool": AttractionPool(),
            "errors": [],
            "final_plan": None,
        }
        result = await multi_agent_app.ainvoke(initial_state)

        # 打印执行过程中的降级信息
        errs = result.get("errors") or []
        if errs:
            print("⚠️ 多智能体执行中的降级信息:", flush=True)
            for e in errs:
                print(f"  - {e}", flush=True)

        plan = result.get("final_plan")
        if plan is None:
            # 兜底：保证接口永不 500
            print("⚠️ 未拿到 final_plan，返回极简兜底计划", flush=True)
            plan = _naive_fallback_plan(request, AttractionPool(), HotelFoodResult(), WeatherReport())
            plan.budget = _calculate_budget(plan, request.transportation)
        return plan

    def plan_trip(self, request: TripRequest) -> TripPlan:
        """同步生成旅行计划：无事件循环时用 asyncio.run；有事件循环时提示改用异步版"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # 当前没有运行中的事件循环 → 直接跑
            return asyncio.run(self.aplan_trip(request))
        # 有运行中的事件循环 → 说明调用方在异步环境里，提醒用异步版，避免嵌套事件循环崩溃
        raise RuntimeError("检测到正在运行的异步事件循环，请改用异步方法: await agent.aplan_trip(request)")


def get_trip_planner_agent() -> TripPlannerAgent:
    """工厂函数：获取智能体调度实例"""
    return TripPlannerAgent()