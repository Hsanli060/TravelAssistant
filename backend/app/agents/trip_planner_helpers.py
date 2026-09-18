# =====================================================================
# 旅行规划多智能体系统 —— 确定性工具函数层
# =====================================================================
#
# 本文件只包含纯工具函数（无 LangGraph 图结构）：
#   - LLM 惰性工厂（严禁模块级调用，杜绝 import 期网络/密钥副作用）
#   - 天气 ReAct 工具包装（MCP maps_weather）
#   - MCP 结果解析 / POI 清洗 / 紧凑清单
#   - 真实数据增强（maps_search_detail 回查 cost/rating/star/open_time）
#   - POI 类型识别 / 用户意图关键词提取
#   - 数据 Agent 兜底构造 / 行程确定性后处理
#
# LangGraph 的状态、节点、图结构在 trip_planner_agent.py 中组装。

import asyncio
import json
import re
from datetime import date, timedelta
from typing import Any, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from ..config import get_settings
from ..services.llm_override import get_llm_override
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
    PLANNER_SYSTEM_PROMPT,
    WEATHER_REACT_SYSTEM_PROMPT,
    build_planner_human_prompt,
)


# =====================================================================
# 1. LLM 惰性工厂（带缓存的函数，严禁模块级调用）
# =====================================================================

_fast_llm_instance: Optional[ChatOpenAI] = None
_planner_llm_instance: Optional[ChatOpenAI] = None
_weather_react_agent_instance: Optional[Any] = None


def _get_fast_llm() -> ChatOpenAI:
    """惰性创建快速模型实例（温度 0.2、30s 超时），供三个数据 Agent 做结构化甄选/参数化。
    若当前请求存在用户自带 Key (BYOK) 重载，则临时构造独立实例，不污染全局单例缓存。
    """
    override = get_llm_override()
    settings = get_settings()
    if override:
        return ChatOpenAI(
            api_key=override.api_key,
            base_url=override.base_url or settings.base_url,
            model=settings.model,
            temperature=0.2,
            request_timeout=30.0,
            max_retries=2,
        )

    global _fast_llm_instance
    if _fast_llm_instance is None:
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
    """惰性创建规划总监模型实例（温度 0.4、120s 超时，适配大规模结构化输出）。
    若当前请求存在用户自带 Key 重载，则临时构造独立实例。
    """
    override = get_llm_override()
    settings = get_settings()
    if override:
        return ChatOpenAI(
            api_key=override.api_key,
            base_url=override.base_url or settings.base_url,
            model=settings.model,
            temperature=0.4,
            request_timeout=120.0,
            max_retries=2,
        )

    global _planner_llm_instance
    if _planner_llm_instance is None:
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
    """惰性构建天气 ReAct Agent（带缓存）：LLM + maps_weather 工具 + 系统提示词。
    注意：ReAct Agent 内部直接绑定了 LLM 实例引用，若存在 override 必须动态重建，不可复用单例！
    """
    override = get_llm_override()
    if override:
        return create_react_agent(
            _get_fast_llm(),
            tools=[weather_tool],
            prompt=WEATHER_REACT_SYSTEM_PROMPT,
        )

    global _weather_react_agent_instance
    if _weather_react_agent_instance is None:
        _weather_react_agent_instance = create_react_agent(
            _get_fast_llm(),
            tools=[weather_tool],
            prompt=WEATHER_REACT_SYSTEM_PROMPT,
        )
    return _weather_react_agent_instance


# =====================================================================
# 2. 天气工具包装（关键安全措施）
# =====================================================================

@tool("maps_weather", description="查询中国城市未来4天天气预报。入参: city(城市名, 字符串)")
async def weather_tool(city: str) -> str:
    """查询指定城市的天气预报（含白天/夜间天气、温度、风力）

    MCPManager.call_tool_text 内有 _call_lock 保护 stdio 持久会话，
    用 @tool 包装后交给 ReAct Agent，锁语义不变，避免与并行分支产生读写竞争。
    """
    #调用天气查询工具并返回结果（str）
    return await get_mcp_manager().call_tool_text("maps_weather", {"city": city})


# =====================================================================
# 3. MCP 结果解析 / 展示辅助函数
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
    #将字符串转换成JSON格式
    obj = _to_json_obj(raw_text)
    if obj is None:
        return []
    #再从JSON对象中拿到POI字典列表
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


def _normalize_poi_name(name: str) -> str:
    """景点名称归一化去重：去括号修饰（如 'xx风景区(东门)' 与 'xx风景区' 视为同一处）"""
    return re.sub(r"[（(].*?[）)]", "", name or "").strip()


def _dedupe_pois(pois: List[dict]) -> List[dict]:
    """按 '归一化名称|坐标' 去重，保留首次出现的 POI"""
    #根据坐标去除重复景点名称
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


def _dedupe_candidates(cands: List) -> List:
    """候选去重（酒店/餐厅通用）：同名同址合并，同名不同址保留但名称加分店后缀区分。

    背景 bug：连锁酒店常有多家同名分店（如家/汉庭各 N 家），若不去重：
    1) LLM 可能把两家同名分店都选进候选池，规划总监逐日分配时出现
       「第1天从分店A出发、第2天从同名分店B出发」的动线错乱；
    2) poi_id 回填按名称建映射，同名会互相覆盖导致 id 错配。
    区分策略：坐标不同 → 名称追加「(地址关键字)」后缀，既保住真实分店
    又让名称可区分；坐标相同/均缺 → 视为同一家，保留首个。
    """
    seen_norms = set()   # 已出现的归一化名称
    used_names = set()   # 已使用的最终名称（含加后缀的），保证输出名称互异
    result: List = []
    for c in cands:
        norm = _normalize_poi_name(c.name)
        if not norm:
            continue
        coord = (c.longitude, c.latitude)
        if norm not in seen_norms:
            seen_norms.add(norm)
            used_names.add(c.name)
            result.append(c)
            continue
        prev = result[0]
        for r in result:
            if _normalize_poi_name(r.name) == norm:
                prev = r
                break
        # 同名：坐标一致（或都缺失）→ 同一家，丢弃后来者
        same_spot = (coord == (prev.longitude, prev.latitude)) or (
            coord[0] is None and coord[1] is None
        ) or (prev.longitude is None and prev.latitude is None)
        if same_spot:
            continue
        # 同名不同址：给后来者名称加分店后缀（取地址尾部有辨识度的段），确保最终名称互异
        addr = (c.address or "").strip()
        base_suffix = addr[-8:] if addr else "门店"
        new_name = f"{c.name}({base_suffix})"
        n = 2
        while new_name in used_names:
            new_name = f"{c.name}({base_suffix}{n})"
            n += 1
        c.name = new_name
        used_names.add(new_name)
        result.append(c)
    return result


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


# =====================================================================
# 4. 真实数据增强：maps_search_detail 回查（cost/rating/star/opentime2/level）
#    仅高德 detail 接口带真实价格与属性：餐厅人均 cost、酒店星级 star、景点开放时间 opentime2
# =====================================================================

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


async def _enrich_restaurant_cost(cand: RestaurantCandidate) -> None:
    """餐厅真实化：maps_search_detail 的 cost 覆盖人均消费，rating 覆盖评分。
    poi_id 须由调用方确定性回填提供；缺 id 直接返回，不回查（宁缺勿伪造）。"""
    if not cand.poi_id:
        return
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


async def _enrich_hotel_price(cand: HotelCandidate) -> None:
    """酒店真实化：maps_search_detail 的 star 映射确定性房价档位，rating 覆盖评分。
    poi_id 须由调用方确定性回填提供；缺 id 直接返回，不回查（宁缺勿伪造）。"""
    if not cand.poi_id:
        return
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


async def _enrich_attraction_detail(cand: AttractionCandidate) -> None:
    """景点真实化：maps_search_detail 的开放时间/等级/评分写入候选（高德无门票价格，保持 LLM 参考价）。
    poi_id 须由调用方确定性回填提供；缺 id 直接返回，不回查（宁缺勿伪造）。"""
    if not cand.poi_id:
        return
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


# =====================================================================
# 5. POI 类型识别 / 用户意图关键词提取
# =====================================================================

HOTEL_TYPE_HINTS = ("住宿", "酒店", "宾馆", "旅馆", "客栈", "公寓","民宿")
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


# 偏好标签 → 检索词映射（attraction_agent 用）
ATTRACTION_PREFERENCE_KEYWORDS = {
    "历史文化": "博物馆 古迹",
    "自然风光": "公园 山 湖",
    "美食": "美食街 夜市",
    "亲子": "动物园 科技馆",
    "购物": "商业街 步行街",
}


# =====================================================================
# 6. 数据 Agent 兜底构造
# =====================================================================

def _fallback_hotel_food(hotel_pois: List[dict], restaurant_pois: List[dict]) -> HotelFoodResult:
    """LLM 甄选失败时：用真实 POI 前 N 条构造保底候选（名称/地址/坐标为真，价格用默认值）"""
    result = HotelFoodResult()
    #先建一个空的集合，等下装poi名称
    seen_h = set()
    for p in hotel_pois[:6]:
        #归一化名称：景区名南门、景区名北门->景区名
        name = _normalize_poi_name(p.get("name", ""))
        if not name:
            continue
        #获取当前poi的经纬度
        lng, lat = _parse_poi_location(p.get("location", ""))
        # 去重键用「归一化名称|坐标」：同名不同址的分店是两家真店，都保留；
        # 只按名称去重会把第二家分店的坐标错并到第一家的名称上（动线算到错误分店）。
        key = f"{name}|{lng},{lat}"
        if key in seen_h:
            continue
        seen_h.add(key)
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
        if not name:
            continue
        #获取当前poi的经纬度
        lng, lat = _parse_poi_location(p.get("location", ""))
        key = f"{name}|{lng},{lat}"
        if key in seen_r:
            continue
        seen_r.add(key)
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


def _unify_plan_hotel(trip_plan: TripPlan, hotel_food: Optional[HotelFoodResult]) -> None:
    """酒店统一（确定性）：全程强制固定酒店候选池首选一家，覆盖 LLM 的逐日分配。

    设计意图（PLANNER_SYSTEM_PROMPT）本就是「全程固定一家（候选池首选）」，
    但 json_mode 无法强制 LLM 守规则：LLM 偶发把不同分店（尤其同名连锁）分配到
    不同天，同名时用户看不出差异，动线却按 day.hotel 坐标出发，出现
    「每天从不同门店出发」。这里用代码兜底强制执行；候选池为空时保持原样不伪造。
    """
    if not hotel_food or not hotel_food.hotels:
        return
    first = hotel_food.hotels[0]
    loc = None
    if first.longitude is not None and first.latitude is not None:
        loc = Location(longitude=first.longitude, latitude=first.latitude)
    template = Hotel(
        name=first.name,
        address=first.address,
        location=loc,
        price_range=f"约¥{first.price_per_night}/晚",
        rating=first.rating or "",
        estimated_cost=first.price_per_night,
    )
    for day in trip_plan.days:
        day.hotel = template.model_copy(deep=True)


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

    # 早餐 = 候选里第一个能卖早餐的店
    # 晚餐 = 候选里第一个能卖午餐或晚餐、又不是早餐那家店的店
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

    # 0.55 酒店统一：全程强制固定候选池首选一家（同名分店不再导致每日动线出发点漂移）
    _unify_plan_hotel(trip_plan, hotel_food)

    # 0.6 酒店价格兜底：LLM 漏填 estimated_cost 时按候选池回填（酒店本体已由上一步统一）
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
        #查询meg.content是否有数据
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