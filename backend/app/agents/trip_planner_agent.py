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
# 设计要点：
#   - Agent 间传递结构化 Pydantic 对象（WeatherReport / HotelFoodResult / AttractionPool），不传散文。
#   - LLM 一律惰性创建（带缓存的函数），严禁模块级 get_llm() 调用，杜绝 import 期网络/密钥副作用。
#   - 预算完全由 Python 确定性计算，LLM 只出单价。
#   - 预算约束每日 480min 时间窗算法、晴雨编排、顺路聚类等硬性规则全部写在规划总监提示词里。

import asyncio
import json
import operator
import re
from datetime import date, timedelta
from typing import Annotated, Any, List, Optional, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import create_react_agent

from ..config import get_settings
from ..models.schemas import (
    Attraction,
    AttractionCandidate,
    AttractionPool,
    Budget,
    DayPlan,
    Hotel,
    HotelCandidate,
    HotelFoodResult,
    Location,
    Meal,
    RestaurantCandidate,
    RouteLeg,
    TripPlan,
    TripRequest,
    WeatherInfo,
    WeatherReport,
)
from ..services.amap_service import get_amap_service
from ..services.mcp_service import get_mcp_manager
from ..services.unsplash_service import get_unsplash_service
from .prompts import (
    ATTRACTION_PARAM_SYSTEM_PROMPT,
    HOTEL_FOOD_SELECT_SYSTEM_PROMPT,
    PLANNER_SYSTEM_PROMPT,
    WEATHER_REACT_SYSTEM_PROMPT,
    WEATHER_STRUCTURE_SYSTEM_PROMPT,
    build_attraction_param_prompt,
    build_hotel_food_selection_prompt,
    build_planner_human_prompt,
)


# =====================================================================
# 1. 状态定义 (MultiAgentState)
# =====================================================================

class MultiAgentState(TypedDict):
    request: TripRequest                              # 用户初始需求（只读）
    weather_report: Optional[WeatherReport]           # ← weather_agent 写
    hotel_food: Optional[HotelFoodResult]             # ← hotel_agent 写
    attraction_pool: Optional[AttractionPool]         # ← attraction_agent 写
    errors: Annotated[List[str], operator.add]        # 三个并行分支都可能追加降级信息 → 必须用 reducer 合并
    final_plan: Optional[TripPlan]                    # ← planner_agent 写


# =====================================================================
# 2. LLM 惰性工厂（带缓存的函数，严禁模块级调用）
# =====================================================================

_fast_llm_instance: Optional[ChatOpenAI] = None
_planner_llm_instance: Optional[ChatOpenAI] = None
_weather_react_agent_instance: Optional[Any] = None


def _get_fast_llm() -> ChatOpenAI:
    """惰性创建快速模型实例（温度 0.2、30s 超时），供三个数据 Agent 做结构化甄选/参数化"""
    global _fast_llm_instance
    if _fast_llm_instance is None:
        settings = get_settings()
        _fast_llm_instance = ChatOpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            model=settings.model,
            temperature=0.2,
            request_timeout=30.0,
            max_retries=2,
        )
    return _fast_llm_instance


def _get_planner_llm() -> ChatOpenAI:
    """惰性创建规划总监模型实例（温度 0.4、120s 超时，适配大规模结构化输出）"""
    global _planner_llm_instance
    if _planner_llm_instance is None:
        settings = get_settings()
        _planner_llm_instance = ChatOpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            model=settings.model,
            temperature=0.4,
            request_timeout=120.0,
            max_retries=2,
        )
    return _planner_llm_instance


def _get_weather_react_agent():
    """惰性构建天气 ReAct Agent（带缓存）：LLM + maps_weather 工具 + 系统提示词"""
    global _weather_react_agent_instance
    if _weather_react_agent_instance is None:
        _weather_react_agent_instance = create_react_agent(
            _get_fast_llm(),
            tools=[weather_tool],
            prompt=WEATHER_REACT_SYSTEM_PROMPT,
        )
    return _weather_react_agent_instance


# =====================================================================
# 3. 天气工具包装（关键安全措施）
# =====================================================================

@tool("maps_weather", description="查询中国城市未来4天天气预报。入参: city(城市名, 字符串)")
async def weather_tool(city: str) -> str:
    """查询指定城市的天气预报（含白天/夜间天气、温度、风力）

    MCPManager.call_tool_text 内有 _call_lock 保护 stdio 持久会话，
    用 @tool 包装后交给 ReAct Agent，锁语义不变，避免与并行分支产生读写竞争。
    """
    return await get_mcp_manager().call_tool_text("maps_weather", {"city": city})


# =====================================================================
# 4. MCP 结果解析 / 展示辅助函数
# =====================================================================

def _to_json_obj(text: str):
    """尝试把文本解析成 JSON；失败时截取首段 {...} / [...] 再试"""
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, (dict, list)) else None
    except json.JSONDecodeError:
        pass
    for start_ch, end_ch in (("[", "]"), ("{", "}")):
        s = text.find(start_ch)
        if s >= 0:
            e = text.rfind(end_ch)
            if e > s:
                try:
                    obj = json.loads(text[s:e + 1])
                    return obj if isinstance(obj, (dict, list)) else None
                except json.JSONDecodeError:
                    continue
    return None


def _find_pois(obj) -> List[dict]:
    """递归查找 POI 列表（兼容 pois 在顶层 / result.pois / data 等位置，或直接是 POI 列表）"""
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) and ("name" in x or "location" in x) for x in obj):
            return [x for x in obj if isinstance(x, dict)]
        for item in obj:
            found = _find_pois(item)
            if found:
                return found
    elif isinstance(obj, dict):
        if isinstance(obj.get("pois"), list):
            return [p for p in obj["pois"] if isinstance(p, dict)]
        for key in ("result", "data", "result_data", "data_list"):
            sub = obj.get(key)
            if isinstance(sub, dict) and isinstance(sub.get("pois"), list):
                return [p for p in sub["pois"] if isinstance(p, dict)]
        for sub in obj.values():
            found = _find_pois(sub)
            if found:
                return found
    return []


def _parse_pois(raw_text: str) -> List[dict]:
    """解析 MCP 文本检索结果为 POI 字典列表（兼容多种返回结构，失败返回空列表）"""
    obj = _to_json_obj(raw_text)
    if obj is None:
        return []
    return _find_pois(obj)


def _format_pois_list(pois: List[dict], max_items: int = 15) -> str:
    """把 POI 字典列表压缩成 '名称|地址|类别|坐标' 紧凑清单，封顶 max_items 条"""
    lines = []
    for p in pois[:max_items]:
        name = str(p.get("name", "") or "未知地点")
        address = str(p.get("address", "") or "")
        ptype = str(p.get("type", "") or p.get("typecode", "") or "景点")
        loc_str = str(p.get("location", "") or "")
        lines.append(f"- {name} | {address} | {ptype} | {loc_str}")
    return "\n".join(lines)


def _format_pois_brief(raw_text: str, max_items: int = 15) -> str:
    """把 MCP 原始检索文本压缩成紧凑清单"""
    return _format_pois_list(_parse_pois(raw_text), max_items)


def _normalize_poi_name(name: str) -> str:
    """景点名称归一化去重：去括号修饰（如 'xx风景区(东门)' 与 'xx风景区' 视为同一处）"""
    return re.sub(r"[（(].*?[）)]", "", name or "").strip()


def _dedupe_pois(pois: List[dict]) -> List[dict]:
    """按 '归一化名称|坐标' 去重，保留首次出现的 POI"""
    seen = set()
    unique = []
    for p in pois:
        name = _normalize_poi_name(p.get("name", ""))
        if not name:
            continue
        key = f"{name}|{p.get('location', '')}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


def _parse_poi_location(location_str: str) -> tuple:
    """解析高德 '经度,纬度' 为 (longitude, latitude)，失败返回 (None, None)"""
    if not location_str or "," not in location_str:
        return (None, None)
    try:
        lng_s, lat_s = location_str.split(",", 1)
        return (float(lng_s.strip()), float(lat_s.strip()))
    except (ValueError, TypeError):
        return (None, None)


def _parse_location_str(location: str) -> Optional[Location]:
    """解析高德 '经度,纬度' 字符串为 Location，失败返回 None"""
    if not location or "," not in location:
        return None
    try:
        lng_s, lat_s = location.split(",", 1)
        lng, lat = float(lng_s.strip()), float(lat_s.strip())
        if abs(lng) > 0 or abs(lat) > 0:
            return Location(longitude=lng, latitude=lat)
    except (ValueError, TypeError):
        pass
    return None


def _safe_float(value: Any) -> Optional[float]:
    """安全转 float，失败返回 None"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _poi_rating(poi: dict) -> Optional[float]:
    """安全提取 POI 评分（biz_ext.rating 可能是数字或字符串）"""
    biz_ext = poi.get("biz_ext")
    if not isinstance(biz_ext, dict):
        return None
    return _safe_float(biz_ext.get("rating"))


# ------------------------------------------------------------------
# 真实数据增强：maps_search_detail 回查（cost/rating/star/opentime2/level）
# 仅高德 detail 接口带真实价格与属性：餐厅人均 cost、酒店星级 star、景点开放时间 opentime2
# ------------------------------------------------------------------

async def _mcp_poi_detail(poi_id: str) -> dict:
    """调用 MCP maps_search_detail 获取 POI 真实详情，失败返回 {}"""
    if not poi_id:
        return {}
    try:
        raw = await get_mcp_manager().call_tool_text("maps_search_detail", {"id": poi_id})
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


async def _resolve_poi_id(name: str, city: str) -> str:
    """按名称回查首个 POI 的 id（候选缺 poi_id 时用）"""
    try:
        raw = await get_mcp_manager().call_tool_text("maps_text_search", {"keywords": name, "city": city})
        obj = json.loads(raw)
        pois = obj.get("pois", []) or []
        return str(pois[0].get("id", "")) if pois else ""
    except Exception:
        return ""


def _star_to_price_band(star) -> int:
    """真实星级 → 确定性房价档位（元/晚）；未知返回 0 表示保持原值"""
    try:
        s = int(str(star).strip())
        if s >= 5:
            return 800
        if s == 4:
            return 550
        if s == 3:
            return 350
        if s == 2:
            return 250
        return 200
    except (TypeError, ValueError):
        return 0


async def _enrich_restaurant_cost(cand: RestaurantCandidate, city: str) -> None:
    """餐厅真实化：maps_search_detail 的 cost 覆盖人均消费，rating 覆盖评分"""
    if not cand.poi_id:
        cand.poi_id = await _resolve_poi_id(cand.name, city)
    d = await _mcp_poi_detail(cand.poi_id)
    if not d:
        return
    cost = d.get("cost")
    if cost:
        try:
            cand.avg_cost = int(float(str(cost).strip()))
        except (TypeError, ValueError):
            pass
    if d.get("rating"):
        try:
            cand.rating = float(str(d["rating"]).strip())
        except (TypeError, ValueError):
            pass


async def _enrich_hotel_price(cand: HotelCandidate, city: str) -> None:
    """酒店真实化：maps_search_detail 的 star 映射确定性房价档位，rating 覆盖评分"""
    if not cand.poi_id:
        cand.poi_id = await _resolve_poi_id(cand.name, city)
    d = await _mcp_poi_detail(cand.poi_id)
    if not d:
        return
    star = d.get("star")
    if star:
        band = _star_to_price_band(star)
        if band:
            cand.price_per_night = band
    if d.get("rating"):
        try:
            cand.rating = float(str(d["rating"]).strip())
        except (TypeError, ValueError):
            pass


async def _enrich_attraction_detail(cand: AttractionCandidate, city: str = "") -> None:
    """景点真实化：maps_search_detail 的开放时间/等级/评分写入候选（高德无门票价格，保持 LLM 参考价）"""
    if not cand.poi_id:
        cand.poi_id = await _resolve_poi_id(cand.name, city) if city else ""
    d = await _mcp_poi_detail(cand.poi_id)
    if not d:
        return
    cand.open_time = d.get("opentime2") or d.get("open_time") or cand.open_time
    cand.level = d.get("level") or cand.level
    if d.get("rating"):
        try:
            cand.rating = float(str(d["rating"]).strip())
        except (TypeError, ValueError):
            pass


HOTEL_TYPE_HINTS = ("住宿", "酒店", "宾馆", "旅馆", "客栈", "公寓")
RESTAURANT_TYPE_HINTS = ("餐饮", "美食", "餐厅", "饭店", "小吃", "火锅", "烧烤")


def _is_hotel_poi(poi: dict) -> bool:
    """根据 POI 类型/名称粗判是否为酒店类"""
    text = f'{poi.get("type", "")} {poi.get("name", "")}'
    return any(hint in text for hint in HOTEL_TYPE_HINTS)


def _is_restaurant_poi(poi: dict) -> bool:
    """根据 POI 类型/名称粗判是否为餐饮类"""
    text = f'{poi.get("type", "")} {poi.get("name", "")}'
    return any(hint in text for hint in RESTAURANT_TYPE_HINTS)


def _filter_pois_by_type(pois: List[dict], is_target) -> List[dict]:
    """按类型关键字过滤 POI；过滤结果为空时不强过滤（保底保留）"""
    matched = [p for p in pois if is_target(p)]
    return matched if matched else pois


CUISINE_KW_HINTS = ("火锅", "烧烤", "小吃", "面", "烤鸭", "海鲜", "川菜", "粤菜", "湘菜",
                    "本帮菜", "东北菜", "西餐", "咖啡", "奶茶", "甜点", "粥", "饺子", "包子")


def _extract_cuisine_keywords(text: str) -> List[str]:
    """从自由文本中提取菜系/美食关键词"""
    if not text:
        return []
    return [kw for kw in CUISINE_KW_HINTS if kw in text]


PLACE_SUFFIX_TUPLE = ("寺", "园", "楼", "馆", "山", "湖", "城", "街", "村", "塔",
                      "庙", "宫", "岛", "桥", "林", "谷", "屿", "湾", "滩",
                      "广场", "古镇", "保护区")


PLACE_CUE_PREFIX = ("一定去", "想去", "到", "去", "逛", "看", "玩", "在", "推荐", "参观")


def _strip_place_cue(seg: str) -> str:
    """去掉地名前的语气/动词助词前缀（如 '一定去故宫' → '故宫'）"""
    s = seg
    while True:
        hit = False
        for cue in PLACE_CUE_PREFIX:
            if s.startswith(cue):
                s = s[len(cue):]
                hit = True
                break
        if not hit:
            break
    return s


def _extract_place_names(text: str) -> List[str]:
    """从自由文本中提取潜在地名（启发式），用于景点检索轮

    偏好整段短词；长段内优先复合后缀词（博物馆/景区…），再回溯单字后缀避免上下文粘连。
    """
    if not text:
        return []
    names: List[str] = []
    segments = re.split(r"[，。,.\s、；;：:！!？?()（）“”\"' ]", text)
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        # 1) 去语气前缀后 2~8 字且以地名后缀结尾 → 直接采用（如 "故宫"、"颐和园"）
        stripped = _strip_place_cue(seg)
        if 2 <= len(stripped) <= 8 and stripped.endswith(PLACE_SUFFIX_TUPLE):
            if stripped not in names:
                names.append(stripped)
            continue
        # 2) 复合后缀词本身作为关键词（博物馆/科技馆/公园/景区/古镇/广场/老街/美食街/夜市）
        for kw in ("博物馆", "科技馆", "公园", "景区", "古镇", "广场", "老街", "美食街", "夜市"):
            if kw in seg and kw not in names:
                names.append(kw)
        # 3) 长段内回溯单字后缀（最多往前 3 字），如 "希望多安排一些博物馆和颐和园" → "颐和园"
        for suffix in (s for s in PLACE_SUFFIX_TUPLE if len(s) == 1):
            idx = seg.rfind(suffix)
            if idx > 0:
                cand = seg[max(0, idx - 2):idx + len(suffix)]
                if 2 <= len(cand) <= 8 and cand not in names:
                    names.append(cand)
    return names


# =====================================================================
# 5. 数据 Agent 兜底构造
# =====================================================================

def _fallback_hotel_food(hotel_pois: List[dict], restaurant_pois: List[dict]) -> HotelFoodResult:
    """LLM 甄选失败时：用真实 POI 前 N 条构造保底候选（名称/地址/坐标为真，价格用默认值）"""
    result = HotelFoodResult()
    seen_h = set()
    for p in hotel_pois[:6]:
        name = _normalize_poi_name(p.get("name", ""))
        if not name or name in seen_h:
            continue
        seen_h.add(name)
        lng, lat = _parse_poi_location(p.get("location", ""))
        result.hotels.append(HotelCandidate(
            name=name,
            address=str(p.get("address", "") or ""),
            longitude=lng,
            latitude=lat,
            poi_id=str(p.get("id", "") or ""),
            price_per_night=300,
            rating=_poi_rating(p),
            reason="真实 POI 检索结果（LLM 甄选失败，保底候选）",
        ))
    seen_r = set()
    for p in restaurant_pois[:8]:
        name = _normalize_poi_name(p.get("name", ""))
        if not name or name in seen_r:
            continue
        seen_r.add(name)
        lng, lat = _parse_poi_location(p.get("location", ""))
        result.restaurants.append(RestaurantCandidate(
            name=name,
            address=str(p.get("address", "") or ""),
            longitude=lng,
            latitude=lat,
            poi_id=str(p.get("id", "") or ""),
            meal_types=["breakfast", "lunch", "dinner"],
            specialty="在线检索到的真实门店",
            avg_cost=50,
            rating=_poi_rating(p),
            reason="真实 POI 检索结果（LLM 甄选失败，保底候选）",
        ))
    return result


def _fallback_attraction_pool(raw_pois: List[dict]) -> AttractionPool:
    """LLM 参数化失败时：原始 POI 直接转候选（visit_duration=120 默认），并剔除明显的酒店/餐厅"""
    pool = AttractionPool()
    seen = set()
    for p in raw_pois:
        # 排除明显非景点 POI（酒店/餐厅混入检索结果时兜底不受污染）
        if _is_hotel_poi(p) or _is_restaurant_poi(p):
            continue
        name = _normalize_poi_name(p.get("name", ""))
        if not name or name in seen:
            continue
        seen.add(name)
        lng, lat = _parse_poi_location(p.get("location", ""))
        pool.candidates.append(AttractionCandidate(
            name=name,
            address=str(p.get("address", "") or ""),
            longitude=lng,
            latitude=lat,
            category=str(p.get("type", "") or "景点")[:10],
            poi_id=str(p.get("id", "") or ""),
            rating=_poi_rating(p),
            visit_duration=120,
            indoor=False,
            reason="真实 POI 检索结果（LLM 参数化失败，保底候选）",
        ))
        if len(pool.candidates) >= 20:
            break
    return pool


def _candidate_to_attraction(c: AttractionCandidate) -> Attraction:
    """把景点候选转成最终 Attraction"""
    loc = None
    if c.longitude is not None and c.latitude is not None:
        loc = Location(longitude=c.longitude, latitude=c.latitude)
    return Attraction(
        name=c.name,
        address=c.address,
        location=loc,
        visit_duration=c.visit_duration or 120,
        description=c.reason,
        category=c.category or "景点",
        rating=c.rating,
        poi_id=c.poi_id,
        ticket_price=c.ticket_price,
        open_time=c.open_time,
    )


def _restaurant_to_meal(r: RestaurantCandidate, meal_type: str) -> Meal:
    """把餐厅候选转成最终 Meal"""
    loc = None
    if r.longitude is not None and r.latitude is not None:
        loc = Location(longitude=r.longitude, latitude=r.latitude)
    return Meal(
        type=meal_type,
        name=r.name,
        address=r.address or None,
        location=loc,
        description=r.specialty or r.reason,
        estimated_cost=r.avg_cost,
    )


def _ensure_daily_meals(trip_plan: TripPlan, hotel_food: Optional[HotelFoodResult]) -> None:
    """餐饮保底：为每个缺失早餐/晚餐的 DayPlan 从真实餐厅候选池补齐（按天轮换避免重复）"""
    if not hotel_food or not hotel_food.restaurants:
        return
    breakfasts = [r for r in hotel_food.restaurants if "breakfast" in (r.meal_types or [])]
    dinners = [r for r in hotel_food.restaurants if any(t in (r.meal_types or []) for t in ("lunch", "dinner"))]
    for i, day in enumerate(trip_plan.days):
        existing = {m.type for m in (day.meals or [])}
        if "breakfast" not in existing and breakfasts:
            day.meals.append(_restaurant_to_meal(breakfasts[i % len(breakfasts)], "breakfast"))
        if "dinner" not in existing and "lunch" not in existing and dinners:
            # 早/晚餐错开一家，避免同一天推荐同一家
            offset = i if len(dinners) > 1 else 0
            day.meals.append(_restaurant_to_meal(dinners[(offset + 1) % len(dinners)], "dinner"))

    # 去重：LLM 把早晚餐排成同一家时，晚餐替换为候选池另一家
    for day in trip_plan.days:
        bf = next((m for m in day.meals if m.type == "breakfast"), None)
        df = next((m for m in day.meals if m.type == "dinner"), None)
        if bf and df and bf.name == df.name and dinners:
            alt = next((r for r in dinners if r.name != bf.name), None)
            if alt:
                for k, m in enumerate(day.meals):
                    if m is df:
                        day.meals[k] = _restaurant_to_meal(alt, "dinner")
                        break


def _ensure_hotel_cost(trip_plan: TripPlan, hotel_food: Optional[HotelFoodResult]) -> None:
    """酒店价格/缺省兜底：LLM 常把候选池的 price_per_night 漏填到 Hotel.estimated_cost，
    按酒店名回填候选价格；某天缺 hotel 且候选池非空时用首选候选补建，绝不伪造"""
    if not hotel_food or not hotel_food.hotels:
        return
    price_map = {h.name: h.price_per_night for h in hotel_food.hotels if h.price_per_night}
    first = hotel_food.hotels[0]
    for day in trip_plan.days:
        if day.hotel is None:
            loc = None
            if first.longitude is not None and first.latitude is not None:
                loc = Location(longitude=first.longitude, latitude=first.latitude)
            day.hotel = Hotel(
                name=first.name,
                address=first.address,
                location=loc,
                price_range=f"约¥{first.price_per_night}/晚",
                rating=first.rating,
                estimated_cost=first.price_per_night,
            )
            continue
        if not (day.hotel.estimated_cost and day.hotel.estimated_cost > 0):
            day.hotel.estimated_cost = price_map.get(day.hotel.name) or 300


def _day_time_cost(attractions: List[Attraction]) -> int:
    """单日时间窗成本：Σ游玩耗时 + 景点数×30min 移动缓冲 + 60min 午餐"""
    if not attractions:
        return 0
    return sum((a.visit_duration or 120) for a in attractions) + len(attractions) * 30 + 60


def _rebalance_days(trip_plan: TripPlan) -> None:
    """确定性日均景点均衡：把超标天(>480min)的景点移到有富余的后继天，尽力逼近 480 分钟时间窗。
    多天总容量不足时保持原编排并打印告警（不丢景点、不伪造）。"""
    for i in range(len(trip_plan.days)):
        day = trip_plan.days[i]
        guard = 0
        while _day_time_cost(day.attractions) > 480 and len(day.attractions) > 1 and guard < 10:
            guard += 1
            # 移出候选：优先末尾景点；若末尾是大景点且当天有更小景点，优先移更小者
            candidates = [day.attractions[-1]]
            min_attr = min(day.attractions, key=lambda a: a.visit_duration or 120)
            if min_attr is not day.attractions[-1]:
                candidates.insert(0, min_attr)
            moved = False
            for attr in candidates:
                if attr not in day.attractions:
                    continue
                for j in range(i + 1, len(trip_plan.days)):
                    target = trip_plan.days[j]
                    if _day_time_cost(target.attractions) + (attr.visit_duration or 120) + 30 <= 480:
                        day.attractions.remove(attr)
                        target.attractions.append(attr)
                        moved = True
                        break
                if moved:
                    break
            if not moved:
                break
        if _day_time_cost(day.attractions) > 480:
            print(f"⚠️ Day{i + 1} 时间窗 {_day_time_cost(day.attractions)}min 超出 480min 且无法均衡"
                  f"（可能多天总容量不足），保持原编排", flush=True)


# =====================================================================
# 6. 节点定义 (Nodes)
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
        result = await asyncio.wait_for(react_agent.ainvoke(react_input), timeout=90.0)
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
        weather_report = parsed or WeatherReport()
        if not weather_report.daily:
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
        (f"{request.city} 特色早餐 早点", "restaurant"),
        (f"{request.city} 特色美食 老字号餐厅", "restaurant"),
    ]
    for kw in _extract_cuisine_keywords(request.free_text_input or ""):
        keyword_rounds.append((f"{request.city} {kw}", "restaurant"))

    # 2. 多轮 MCP 检索（内部串行即可），压缩成紧凑清单
    mcp = get_mcp_manager()
    hotel_pois: List[dict] = []
    restaurant_pois: List[dict] = []
    brief_chunks: List[str] = []
    for kw, kind in keyword_rounds:
        try:
            raw = await mcp.call_tool_text("maps_text_search", {"keywords": kw, "city": request.city})
            pois = _parse_pois(raw)
            if not pois:
                continue
            if kind == "hotel":
                hotel_pois.extend(_filter_pois_by_type(pois, _is_hotel_poi))
            else:
                restaurant_pois.extend(_filter_pois_by_type(pois, _is_restaurant_poi))
            brief = _format_pois_brief(raw, max_items=12)
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
        # 确定性补丁：LLM 漏选某类但检索池有真实数据时，用真实 POI 补齐（早晚餐是前端硬性契约）
        if not result.restaurants and restaurant_pois:
            print("⚠️ LLM 未选出餐厅，用真实检索池补齐餐厅候选", flush=True)
            result.restaurants = _fallback_hotel_food([], restaurant_pois).restaurants
        if not result.hotels and hotel_pois:
            print("⚠️ LLM 未选出酒店，用真实检索池补齐酒店候选", flush=True)
            result.hotels = _fallback_hotel_food(hotel_pois, []).hotels
    except Exception as e:
        print(f"⚠️ 酒店餐厅 Agent LLM 甄选失败，使用原始 POI 保底: {str(e)}", flush=True)
        errors.append(f"酒店餐厅甄选失败，已用原始 POI 保底: {e}")
        result = _fallback_hotel_food(hotel_pois, restaurant_pois)

    # 4. 真实数据增强：餐厅人均 cost / 酒店星级房价（并发回查 maps_search_detail，失败静默）
    try:
        enrich_tasks = [asyncio.create_task(_enrich_restaurant_cost(r, request.city)) for r in result.restaurants[:8]]
        enrich_tasks += [asyncio.create_task(_enrich_hotel_price(h, request.city)) for h in result.hotels[:5]]
        if enrich_tasks:
            await asyncio.gather(*enrich_tasks, return_exceptions=True)
    except Exception as e:
        errors.append(f"酒店餐厅真实数据增强失败: {e}")

    print(f"✅ 酒店餐厅 Agent 已完成甄选（酒店 {len(result.hotels)} 家 · 餐厅 {len(result.restaurants)} 家，已回查真实价格）", flush=True)
    return {"hotel_food": result, "errors": errors}


# 偏好标签 → 检索词映射（attraction_agent 用）
ATTRACTION_PREFERENCE_KEYWORDS = {
    "历史文化": "博物馆 古迹",
    "自然风光": "公园 山 湖",
    "美食": "美食街 夜市",
    "亲子": "动物园 科技馆",
    "购物": "商业街 步行街",
}


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
    keywords: List[str] = [f"{request.city} 热门景点", f"{request.city} 5A景区 博物馆"]
    for pref in request.preferences or []:
        mapped = ATTRACTION_PREFERENCE_KEYWORDS.get(pref)
        if mapped:
            kw = f"{request.city} {mapped}"
            if kw not in keywords:
                keywords.append(kw)
    for place in _extract_place_names(request.free_text_input or ""):
        kw = f"{request.city} {place}"
        if kw not in keywords:
            keywords.append(kw)
    if f"{request.city} 网红打卡" not in keywords:
        keywords.append(f"{request.city} 网红打卡")
    keywords = keywords[:4]

    # 2. 多轮 MCP 检索 + 压缩 + 去重
    mcp = get_mcp_manager()
    all_pois: List[dict] = []
    brief_chunks: List[str] = []
    for kw in keywords:
        try:
            raw = await mcp.call_tool_text("maps_text_search", {"keywords": kw, "city": request.city})
            pois = _parse_pois(raw)
            if pois:
                all_pois.extend(pois)
            brief = _format_pois_brief(raw, max_items=15)
            if brief:
                brief_chunks.append(brief)
        except Exception as e:
            errors.append(f"MCP 检索景点「{kw}」失败: {e}")

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
        pool = _fallback_attraction_pool(unique_pois)

    # 4. 真实数据增强：景点开放时间/等级/评分（并发回查 maps_search_detail，失败静默）
    try:
        enrich_tasks = [asyncio.create_task(_enrich_attraction_detail(c, request.city)) for c in pool.candidates[:12]]
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
        trip_plan = await _postprocess_plan(trip_plan, request, hotel_food)
    except Exception as e:
        print(f"⚠️ 行程确定性后处理失败: {str(e)}", flush=True)
        new_errors.append(f"行程后处理失败，返回原始编排结果: {e}")

    # 真实详情回填：LLM 常漏抄候选池的开放时间/评分，按景点名确定性补齐
    try:
        _backfill_attraction_details(trip_plan, attraction_pool)
    except Exception as e:
        print(f"⚠️ 景点真实详情回填失败: {str(e)}", flush=True)

    # 预算精算（LLM 的 budget 一律覆盖）
    try:
        trip_plan.budget = _calculate_budget(trip_plan, request.transportation)
    except Exception as e:
        print(f"⚠️ 预算精算失败: {str(e)}", flush=True)
        trip_plan.budget = Budget()

    # 天气信息逐日映射（有数据的日期才输出）
    trip_plan.weather_info = _build_weather_info(weather_report)

    # 总体建议兜底：LLM 偶发漏写时用确定性文案补上
    if not (trip_plan.overall_suggestions or "").strip():
        trip_plan.overall_suggestions = _default_suggestions(request, weather_report, trip_plan)

    return {"final_plan": trip_plan, "errors": new_errors}


# =====================================================================
# 7. 规划总监内部实现（LLM 编排 + 确定性后处理）
# =====================================================================

async def _llm_orchestrate_plan(request: TripRequest, weather_report: WeatherReport,
                                hotel_food: HotelFoodResult, attraction_pool: AttractionPool) -> Optional[TripPlan]:
    """调用规划总监 LLM 生成 TripPlan（json_mode 结构化输出），无有效结果返回 None"""
    try:
        structured = _get_planner_llm().with_structured_output(TripPlan, method="json_mode")
        payload = {
            "request": request.model_dump(),
            "weather_report": weather_report.model_dump(),
            "hotel_food": hotel_food.model_dump(),
            "attraction_pool": attraction_pool.model_dump(),
        }
        response = await structured.ainvoke([
            SystemMessage(content=PLANNER_SYSTEM_PROMPT),
            HumanMessage(content=build_planner_human_prompt(payload)),
        ])
        if response is None or not response.days:
            return None
        if len(response.days) != request.travel_days:
            print(f"⚠️ LLM 输出天数({len(response.days)})与请求天数({request.travel_days})不符，放弃该结果", flush=True)
            return None
        return response
    except Exception as e:
        print(f"⚠️ LLM 编排规划失败: {str(e)}", flush=True)
        return None


def _naive_fallback_plan(request: TripRequest, attraction_pool: AttractionPool,
                         hotel_food: HotelFoodResult, weather_report: WeatherReport) -> TripPlan:
    """LLM 编排失败时按候选池顺序朴素分天（每天 3 个、晴雨不敏感），保证接口永不 500"""
    day_count = max(1, request.travel_days)
    candidates = list((attraction_pool or AttractionPool()).candidates or [])

    # 酒店：全程固定一家（候选池首选），候选池为空则 hotel=None + 不伪造
    hotel = None
    if hotel_food and hotel_food.hotels:
        h0 = hotel_food.hotels[0]
        loc = None
        if h0.longitude is not None and h0.latitude is not None:
            loc = Location(longitude=h0.longitude, latitude=h0.latitude)
        hotel = Hotel(
            name=h0.name,
            address=h0.address,
            location=loc,
            price_range=f"约¥{h0.price_per_night}/晚",
            rating=h0.rating or "",
            estimated_cost=h0.price_per_night,
        )

    # 餐饮：每天一条早餐 + 一条正餐（从候选池选，早/晚餐不重复，选不到则当天无该餐）
    breakfast = next((r for r in hotel_food.restaurants if "breakfast" in r.meal_types), None)
    dinner = next((r for r in hotel_food.restaurants
                   if r is not breakfast and any(t in r.meal_types for t in ("lunch", "dinner"))), None)

    # 分天打包：与规划总监同一套 480 分钟时间窗算法（Σ游玩耗时 + 个数×30min 移动缓冲 + 60min 午餐 ≤ 480，每天最多 4 个）
    day_chunks: List[List] = []
    current: List = []
    for cand in candidates:
        trial = current + [cand]
        time_cost = sum(c.visit_duration or 120 for c in trial) + len(trial) * 30 + 60
        if len(trial) <= 4 and time_cost <= 480:
            current = trial
        else:
            if current:
                day_chunks.append(current)
            current = [cand]  # 单个超大景点（如主题乐园）独占一天
    if current:
        day_chunks.append(current)
    if not day_chunks:
        day_chunks = [[]]
    # 候选多于可编排天数时，把剩余候选依次塞进尚有余量的天；不足时循环复用已有打包结果
    while len(day_chunks) < day_count:
        day_chunks.append(list(day_chunks[len(day_chunks) % len(day_chunks)]))

    days: List[DayPlan] = []
    for i in range(day_count):
        chunk = day_chunks[i]
        attractions = [_candidate_to_attraction(c) for c in chunk]
        meals: List[Meal] = []
        if breakfast:
            meals.append(_restaurant_to_meal(breakfast, "breakfast"))
        if dinner:
            meals.append(_restaurant_to_meal(dinner, "dinner"))
        days.append(DayPlan(
            date=_date_from_start(request.start_date, i),
            day_index=i,
            description=f"第{i + 1}天：游览{len(attractions)}个景点（算法兜底编排，未使用 AI 生成）",
            transportation=request.transportation,
            accommodation=request.accommodation,
            hotel=hotel.model_copy(deep=True) if hotel else None,
            attractions=attractions,
            meals=meals,
            legs=[],
        ))

    return TripPlan(
        city=request.city,
        start_date=request.start_date,
        end_date=request.end_date,
        days=days,
        weather_info=_build_weather_info(weather_report),
        overall_suggestions=(
            "本次行程由确定性算法兜底生成（AI 编排失败）。建议以各景点官方信息为准，"
            "出行前确认开放时间、预约政策与当日天气。"
        ),
        budget=None,
    )


async def _postprocess_plan(trip_plan: TripPlan, request: TripRequest, hotel_food: Optional[HotelFoodResult] = None) -> TripPlan:
    """Python 确定性后处理：规整日期 → 餐饮保底 → 坐标/图片并发补全 → 每日动线计算"""
    # 0. 规整基础字段
    trip_plan.city = request.city
    trip_plan.start_date = request.start_date or trip_plan.start_date
    trip_plan.end_date = request.end_date or trip_plan.end_date
    transport_mode = _map_transport_mode(request.transportation)
    for i, day in enumerate(trip_plan.days):
        day.day_index = i
        if not day.date:
            day.date = _date_from_start(request.start_date, i)
        day.transportation = request.transportation
        day.accommodation = request.accommodation

    # 0.5 餐饮保底：LLM 漏排早/晚餐时从真实餐厅候选池补齐（前端契约：每天有早晚餐推荐）
    _ensure_daily_meals(trip_plan, hotel_food)

    # 0.6 酒店保底：LLM 漏填 estimated_cost 或缺 hotel 时按候选池回填
    _ensure_hotel_cost(trip_plan, hotel_food)

    # 0.7 日均景点时长均衡：确定性执行 480 分钟时间窗规则，尽力把超标天景点挪到有富余的天
    _rebalance_days(trip_plan)

    amap_svc = get_amap_service()
    unsplash_svc = get_unsplash_service()

    # 1. 坐标与图片补全（并发 asyncio.gather + to_thread，单点异常静默跳过）
    tasks: List[asyncio.Task] = []
    for day in trip_plan.days:
        for attr in day.attractions:
            tasks.append(asyncio.create_task(_complete_attraction(attr, request.city, amap_svc, unsplash_svc)))
        if day.hotel is not None:
            tasks.append(asyncio.create_task(_complete_hotel(day.hotel, request.city, amap_svc)))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    # 2. 每日动线计算：酒店 → 景点1 → ... → 酒店
    for day in trip_plan.days:
        day.legs = await _compute_day_legs(day, request, transport_mode)

    return trip_plan


async def _complete_attraction(attr: Attraction, city: str, amap_svc, unsplash_svc) -> None:
    """补全单个景点的坐标/实景图/地址（search_scenic_spot → unsplash → geocode 逐级兜底），异常静默跳过"""
    try:
        needs_coord = attr.location is None or (attr.location.longitude == 0 and attr.location.latitude == 0)
        info = await asyncio.to_thread(amap_svc.search_scenic_spot, attr.name, city)
        if info:
            loc = _parse_location_str(info.get("location", ""))
            if needs_coord and loc:
                attr.location = loc
            if not attr.image_url and info.get("photo_url"):
                attr.image_url = info["photo_url"]
                if info["photo_url"] not in attr.photos:
                    attr.photos.append(info["photo_url"])
            if not attr.address and info.get("address"):
                attr.address = info["address"]
            if attr.rating is None and info.get("rating"):
                attr.rating = info["rating"]
        # 图片仍缺 → Unsplash 兜底
        if not attr.image_url:
            img = await asyncio.to_thread(unsplash_svc.get_image, attr.name, city)
            if img:
                attr.image_url = img
        # 坐标仍缺 → geocode 兜底
        if needs_coord and (attr.location is None or (attr.location.longitude == 0 and attr.location.latitude == 0)):
            loc = await asyncio.to_thread(amap_svc.geocode, f"{city}{attr.name}", city)
            if loc:
                attr.location = loc
    except Exception:
        pass


async def _complete_hotel(hotel: Hotel, city: str, amap_svc) -> None:
    """补全酒店坐标/地址（search_scenic_spot → geocode 兜底），异常静默跳过"""
    try:
        needs_coord = hotel.location is None or (hotel.location.longitude == 0 and hotel.location.latitude == 0)
        info = await asyncio.to_thread(amap_svc.search_scenic_spot, hotel.name, city)
        if info:
            loc = _parse_location_str(info.get("location", ""))
            if needs_coord and loc:
                hotel.location = loc
            if not hotel.address and info.get("address"):
                hotel.address = info["address"]
        if needs_coord and (hotel.location is None or (hotel.location.longitude == 0 and hotel.location.latitude == 0)):
            loc = await asyncio.to_thread(amap_svc.geocode, f"{city}{hotel.name}", city)
            if loc:
                hotel.location = loc
    except Exception:
        pass


async def _compute_day_legs(day: DayPlan, request: TripRequest, transport_mode: str) -> List[RouteLeg]:
    """计算单日动线：酒店(出发) → 景点1 → 景点2 → … → 酒店(返程)，逐段调用 calculate_leg"""
    if not day.attractions:
        return []
    amap_svc = get_amap_service()
    legs: List[RouteLeg] = []

    prev_loc = None
    prev_name = None
    if day.hotel is not None:
        prev_loc = day.hotel.location
        prev_name = day.hotel.name
        if prev_loc is None:
            loc = await asyncio.to_thread(amap_svc.geocode, f"{request.city}{day.hotel.name}", request.city)
            if loc:
                day.hotel.location = loc
                prev_loc = loc

    for attr in day.attractions:
        if prev_name is not None:
            leg = await asyncio.to_thread(
                amap_svc.calculate_leg,
                prev_loc,
                attr.location,
                prev_name,
                attr.name,
                request.city,
                transport_mode,
            )
            legs.append(leg)
        prev_loc = attr.location
        prev_name = attr.name

    # 返程回酒店
    if day.hotel is not None and prev_name is not None:
        back = await asyncio.to_thread(
            amap_svc.calculate_leg,
            prev_loc,
            day.hotel.location,
            prev_name,
            day.hotel.name,
            request.city,
            transport_mode,
        )
        legs.append(back)

    return legs


def _calculate_budget(trip_plan: TripPlan, transportation: str) -> Budget:
    """纯 Python 预算精算：门票 + 酒店 + 餐饮 + 交通，LLM 的 budget 一律覆盖"""
    total_attractions = sum(a.ticket_price or 0 for day in trip_plan.days for a in day.attractions)
    total_hotels = sum((day.hotel.estimated_cost or 0) for day in trip_plan.days if day.hotel)
    total_meals = sum(m.estimated_cost or 0 for day in trip_plan.days for m in day.meals)

    # 交通：优先用每段 leg.cost 之和；某天无 cost 数据时按交通方式日定额兜底
    daily_allowance = 80 if ("打车" in transportation or "自驾" in transportation) else 30
    total_transportation = 0
    for day in trip_plan.days:
        day_cost = sum(leg.cost or 0 for leg in day.legs)
        if day_cost == 0:
            day_cost = daily_allowance
        total_transportation += day_cost

    total = total_attractions + total_hotels + total_meals + total_transportation
    print(
        f"💰 预算精算: 门票¥{total_attractions} 酒店¥{total_hotels} 餐饮¥{total_meals} "
        f"交通¥{total_transportation} 合计¥{total}",
        flush=True,
    )
    return Budget(
        total_attractions=total_attractions,
        total_hotels=total_hotels,
        total_meals=total_meals,
        total_transportation=total_transportation,
        total=total,
    )


def _build_weather_info(weather_report: WeatherReport) -> List[WeatherInfo]:
    """把天气 Agent 的逐日报告映射成 WeatherInfo 列表（只有 has_data 的日期才输出）"""
    infos: List[WeatherInfo] = []
    for daily in (weather_report.daily or []):
        if not daily.has_data:
            continue
        wind_parts = (daily.wind or "").split()
        infos.append(WeatherInfo(
            date=daily.date or "",
            day_weather=daily.day_weather or "",
            night_weather=daily.night_weather or "",
            day_temp=daily.day_temp or 0,
            night_temp=daily.night_temp or 0,
            wind_direction=wind_parts[0] if wind_parts else "",
            wind_power=wind_parts[-1] if wind_parts else "",
        ))
    return infos


def _backfill_attraction_details(trip_plan: TripPlan, pool: Optional[AttractionPool]) -> None:
    """景点真实详情回填：LLM 常漏抄候选池的开放时间/评分，按景点名确定性补齐"""
    if not pool or not pool.candidates:
        return
    cand_map = {c.name: c for c in pool.candidates}
    for day in trip_plan.days:
        for attr in day.attractions:
            c = cand_map.get(attr.name)
            if not c:
                continue
            if not attr.open_time and c.open_time:
                attr.open_time = c.open_time
            if attr.rating is None and c.rating:
                attr.rating = c.rating


def _default_suggestions(request: TripRequest, weather_report: WeatherReport, trip_plan: TripPlan) -> str:
    """总体建议确定性兜底：结合天气与酒店给出实用提示"""
    parts = []
    rainy_dates = [d.date for d in (weather_report.daily or []) if d.is_rainy]
    if rainy_dates:
        parts.append(f"{'、'.join(rainy_dates)}有雨，请携带雨具并优先安排室内场馆，及时关注天气预报。")
    hotels = {d.hotel.name for d in trip_plan.days if d.hotel}
    if hotels:
        parts.append(f"全程推荐入住「{next(iter(hotels))}」，位置便于游览。")
    parts.append("各博物馆/热门景点需提前在官方渠道预约门票，出行前确认开放时间与周一闭馆安排。")
    parts.append("市内出行建议优先地铁/公交，避开早晚高峰，注意防晒补水。")
    return " ".join(parts)


def _date_from_start(start_date: str, offset: int) -> str:
    """从开始日期推算第 offset 天的日期（YYYY-MM-DD），无法解析时原样返回"""
    if not start_date:
        return ""
    try:
        d = date.fromisoformat(start_date)
        return (d + timedelta(days=offset)).isoformat()
    except ValueError:
        return start_date


def _map_transport_mode(transportation: str) -> str:
    """把用户交通方式偏好映射为动线计算口径（mixed 按距离自动推荐）"""
    if not transportation:
        return "mixed"
    if "步行" in transportation:
        return "walking"
    if ("公交" in transportation) or ("地铁" in transportation) or ("公共交通" in transportation):
        return "transit"
    if ("打车" in transportation) or ("自驾" in transportation) or ("出租" in transportation):
        return "driving"
    return "mixed"


def _extract_last_ai_text(result) -> str:
    """从 ReAct 结果中提取最后一条非空的 AI 消息文本"""
    if not isinstance(result, dict):
        return str(result)
    messages = result.get("messages", [])
    # 优先取最后一条 AI 消息
    for msg in reversed(messages):
        content = getattr(msg, "content", "")
        if not content:
            continue
        if getattr(msg, "type", "") != "ai":
            continue
        if isinstance(content, list):
            merged = "".join(
                str(b.get("text", "") or b.get("content", "") or "") if isinstance(b, dict) else str(b)
                for b in content
            ).strip()
        else:
            merged = str(content).strip()
        if merged:
            return merged
    # 兜底：取最后一条非空文本
    for msg in reversed(messages):
        content = getattr(msg, "content", "")
        if isinstance(content, list):
            merged = "".join(
                str(b.get("text", "") if isinstance(b, dict) else b)
                for b in content
            ).strip()
        else:
            merged = str(content).strip()
        if merged:
            return merged
    return ""


# =====================================================================
# 8. 组装 LangGraph 工作流
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
# 9. 对外调用类
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