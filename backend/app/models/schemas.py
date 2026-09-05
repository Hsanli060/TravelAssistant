"""数据模型定义"""
from typing import List,Optional,Any,Union
from pydantic import BaseModel,Field,field_validator,ConfigDict


# ============ 前端发来的请求模型 ============
class TripRequest(BaseModel):
    """旅行规划请求"""
    city: str = Field(..., description="目的地城市", examples=["北京"])
    start_date: str = Field(..., description="开始日期 YYYY-MM-DD", examples=["2025-06-01"])
    end_date: str = Field(..., description="结束日期 YYYY-MM-DD", examples=["2025-06-03"])
    travel_days: int = Field(..., description="旅行天数", ge=1, le=30, examples=[3])
    transportation: str = Field(default="公共交通", description="交通方式", examples=["公共交通"])
    accommodation: str = Field(default="舒适型酒店", description="住宿偏好", examples=["经济型酒店"])
    preferences: List[str] = Field(default=[], description="旅行偏好标签")
    free_text_input: Optional[str] = Field(default="", description="额外要求")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "city": "北京",
            "start_date": "2025-06-01",
            "end_date": "2025-06-03",
            "travel_days": 3,
            "transportation": "公共交通",
            "accommodation": "经济型酒店",
            "preferences": ["历史文化", "美食"],
            "free_text_input": ""
        }
    })

class RouteRequest(BaseModel):
    """路线规划请求"""
    origin_address: str = Field(..., description="起点地址", examples=["北京市朝阳区阜通东大街6号"])
    destination_address: str = Field(..., description="终点地址", examples=["北京市海淀区上地十街10号"])
    origin_city: Optional[str] = Field(default=None, description="起点城市")
    destination_city: Optional[str] = Field(default=None, description="终点城市")
    route_type: str = Field(default="walking", description="路线类型: walking/driving/transit")



# ============ 响应模型 ============
class Location(BaseModel):
    """地理位置"""
    longitude:float
    latitude:float

class Attraction(BaseModel):
    """景点信息"""
    name: str = Field(..., description="景点名称")
    address: str = Field(default="", description="地址")
    location: Optional[Location] = Field(default=None, description="经纬度坐标")
    visit_duration: int = Field(default=120, description="建议游览时间(分钟)")
    description: str = Field(default="", description="景点描述")
    category: Optional[str] = Field(default="景点", description="景点类别")
    rating: Optional[float] = Field(default=None, description="评分")
    photos: Optional[List[str]] = Field(default_factory=list, description="景点图片URL列表")
    poi_id: Optional[str] = Field(default="", description="POI ID")
    image_url: Optional[str] = Field(default=None, description="图片URL")
    ticket_price: Optional[int] = Field(default=None, description="门票价格(元)，None 表示数据未提供（区别于免费=0）")
    open_time: Optional[str] = Field(default=None, description="开放时间（高德真实营业/开放信息，含闭馆安排）")

class Meal(BaseModel):
    """餐饮信息"""
    type: str = Field(default="lunch", description="餐饮类型: breakfast/lunch/dinner/snack")
    name: str = Field(..., description="餐饮名称")
    address: Optional[str] = Field(default=None, description="地址")
    location: Optional[Location] = Field(default=None, description="经纬度坐标")
    description: Optional[str] = Field(default=None, description="描述")
    estimated_cost: int = Field(default=0, description="预估费用(元)")


class Hotel(BaseModel):
    """酒店信息"""
    name: str = Field(..., description="酒店名称")
    address: str = Field(default="", description="酒店地址")
    location: Optional[Location] = Field(default=None, description="酒店位置")
    price_range: Optional[str] = Field(default=None, description="价格范围")
    rating: Optional[Union[str, float]] = Field(default=None, description="评分，无数据为 None")
    distance: Optional[str] = Field(default=None, description="距离景点距离")
    type: Optional[str] = Field(default=None, description="酒店类型")
    estimated_cost: int = Field(default=0, description="预估费用(元/晚)")


class RouteLeg(BaseModel):
    """一段真实交通信息（由动线计算/距离矩阵填充，数据来自高德路线接口）"""
    from_name: str = Field(..., description="起点名称")
    to_name: str = Field(..., description="终点名称")
    route_type: str = Field(default="walking", description="交通方式: walking/driving/transit")
    distance_m: float = Field(default=0, description="距离(米)")
    duration_min: int = Field(default=0, description="耗时(分钟)")
    description: str = Field(default="", description="路线描述(如'全程约 2.5 公里，耗时约 30 分钟')")
    cost: Optional[int] = Field(default=None, description="该段估算费用(元/人)：步行0、公交地铁约5、打车按里程估算")


class DayPlan(BaseModel):
    """单日行程"""
    date: str = Field(default="", description="日期 YYYY-MM-DD")
    day_index: int = Field(default=0, description="第几天(从0开始)")
    description: str = Field(default="", description="当日行程描述")
    transportation: str = Field(default="公共交通", description="交通方式")
    accommodation: str = Field(default="", description="住宿")
    hotel: Optional[Hotel] = Field(default=None, description="推荐酒店")
    attractions: List[Attraction] = Field(default=[], description="景点列表")
    meals: List[Meal] = Field(default=[], description="餐饮列表")
    legs: List[RouteLeg] = Field(default=[], description="当日各段真实交通(景点间)，数据未计算时为空")


class WeatherInfo(BaseModel):
    """天气信息"""
    date: str = Field(..., description="日期 YYYY-MM-DD")
    day_weather: Optional[str] = Field(default=None, description="白天天气")
    night_weather: Optional[str] = Field(default=None, description="夜间天气")
    day_temp: Optional[Union[int, str]] = Field(default=None, description="白天温度，无数据为 None")
    night_temp: Optional[Union[int, str]] = Field(default=None, description="夜间温度，无数据为 None")
    wind_direction: Optional[str] = Field(default=None, description="风向")
    wind_power: Optional[str] = Field(default=None, description="风力")

    @field_validator('day_temp', 'night_temp', mode='before')
    @classmethod
    def parse_temperature(cls, v):
        """解析温度,移除°C等单位"""
        if isinstance(v, str):
            # 移除°C, ℃等单位符号
            v = v.replace('°C', '').replace('℃', '').replace('°', '').strip()
            try:
                return int(v)
            except ValueError:
                return 0
        return v


# ============ 气象 Agent 结构化输出模型 ============
# 天气 Agent 用 with_structured_output(json_mode) 把高德原始天气转成这份紧凑 JSON，
# 存进 state.weather_data 供下游（景区分天 / 规划总监 weather_info / 质检）直接读字段，不再传原始 JSON。
class WeatherDaily(BaseModel):
    """单日天气（JSON 报告里的 daily 元素）"""
    date: str = Field(..., description="日期 YYYY-MM-DD")
    has_data: bool = Field(default=False, description="该日是否有预报数据")
    day_weather: Optional[str] = Field(default=None, description="白天天气，无数据为 None")
    night_weather: Optional[str] = Field(default=None, description="夜间天气，无数据为 None")
    day_temp: Optional[int] = Field(default=None, description="白天最高温，无数据为 None")
    night_temp: Optional[int] = Field(default=None, description="夜间最低温，无数据为 None")
    wind: Optional[str] = Field(default=None, description="风向风力，无数据为 None")
    is_rainy: Optional[bool] = Field(default=None, description="是否雨天(白天或夜间含雨)，无数据为 None")
    indoor_recommended: Optional[bool] = Field(default=None, description="是否建议室内活动，无数据为 None")


class WeatherCoverage(BaseModel):
    """天气数据覆盖情况（是否覆盖到出行日期）"""
    covers_travel_dates: bool = Field(default=False, description="预报是否覆盖出行日期")
    covered_dates: List[str] = Field(default_factory=list, description="有预报数据的日期")
    note: str = Field(default="", description="一句话覆盖说明")


class WeatherReport(BaseModel):
    """气象 Agent 的输出报告（紧凑 JSON，替代大段散文）"""
    coverage: WeatherCoverage = Field(default_factory=WeatherCoverage, description="数据覆盖情况")
    daily: List[WeatherDaily] = Field(default_factory=list, description="逐日天气(与出行日期对齐)")
    packing_tips: List[str] = Field(default_factory=list, description="必备物品建议，每条≤15字")
    safety_reminders: List[str] = Field(default_factory=list, description="安全提醒，每条≤15字")


class Budget(BaseModel):
    """预算信息"""
    total_attractions: int = Field(default=0, description="景点门票总费用")
    total_hotels: int = Field(default=0, description="酒店总费用")
    total_meals: int = Field(default=0, description="餐饮总费用")
    total_transportation: int = Field(default=0, description="交通总费用")
    total: int = Field(default=0, description="总费用")


class TripPlan(BaseModel):
    """旅行计划"""
    city: str = Field(..., description="目的地城市")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    days: List[DayPlan] = Field(..., description="每日行程")
    weather_info: List[WeatherInfo] = Field(default=[], description="天气信息")
    overall_suggestions: str = Field(default="", description="总体建议")
    budget: Optional[Budget] = Field(default=None, description="预算信息")


class TripPlanResponse(BaseModel):
    """旅行计划响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: Optional[TripPlan] = Field(default=None, description="旅行计划数据")


class POIInfo(BaseModel):
    """POI信息"""
    id: str = Field(..., description="POI ID")
    name: str = Field(..., description="名称")
    type: str = Field(..., description="类型")
    address: str = Field(..., description="地址")
    location: Location = Field(..., description="经纬度坐标")
    tel: Optional[str] = Field(default=None, description="电话")


class POISearchResponse(BaseModel):
    """POI搜索响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[POIInfo] = Field(default=[], description="POI列表")


class RouteInfo(BaseModel):
    """路线信息"""
    distance: float = Field(..., description="距离(米)")
    duration: int = Field(..., description="时间(秒)")
    route_type: str = Field(..., description="路线类型")
    description: str = Field(..., description="路线描述")


class RouteResponse(BaseModel):
    """路线规划响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: Optional[RouteInfo] = Field(default=None, description="路线信息")


class WeatherResponse(BaseModel):
    """天气查询响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[WeatherInfo] = Field(default=[], description="天气信息")


# ============ 多智能体 Agent 候选池模型 ============
# 三个数据 Agent（weather/hotel/attraction）先通过 MCP 检索真实 POI，
# 再让 LLM 从候选池中甄选/参数化，Agent 间传递的是结构化对象而不是散文文本。

class AttractionCandidate(BaseModel):
    """景点候选（景点 Agent 从真实 POI 中筛选 + LLM 补充游玩参数）"""
    name: str = Field(..., description="景点名称")
    address: str = Field(default="", description="地址")
    longitude: Optional[float] = Field(default=None, description="经度")
    latitude: Optional[float] = Field(default=None, description="纬度")
    category: str = Field(default="景点", description="景点类别")
    poi_id: str = Field(default="", description="POI ID")
    rating: Optional[float] = Field(default=None, description="评分")
    ticket_price: Optional[int] = Field(default=None, description="门票(元)，None=未知，0=免费")
    visit_duration: int = Field(default=120, description="LLM 预估游玩分钟数（规划总监按此排每日个数）")
    indoor: bool = Field(default=False, description="是否室内（规划总监按此做雨天编排）")
    open_time: Optional[str] = Field(default=None, description="真实开放时间（高德 detail）")
    level: Optional[str] = Field(default=None, description="景区等级，如 AAAAA（高德 detail）")
    reason: str = Field(default="", description="一句话推荐理由")


class AttractionPool(BaseModel):
    """景点候选池"""
    candidates: List[AttractionCandidate] = Field(default_factory=list)


class HotelCandidate(BaseModel):
    """酒店候选"""
    name: str = Field(..., description="酒店名称")
    address: str = Field(default="", description="地址")
    longitude: Optional[float] = Field(default=None, description="经度")
    latitude: Optional[float] = Field(default=None, description="纬度")
    poi_id: str = Field(default="", description="POI ID")
    price_per_night: int = Field(default=300, description="预估每晚价格")
    rating: Optional[float] = Field(default=None, description="评分")
    reason: str = Field(default="", description="推荐理由")


class RestaurantCandidate(BaseModel):
    """餐厅候选"""
    name: str = Field(..., description="餐厅名称")
    address: str = Field(default="", description="地址")
    longitude: Optional[float] = Field(default=None, description="经度")
    latitude: Optional[float] = Field(default=None, description="纬度")
    poi_id: str = Field(default="", description="POI ID")
    meal_types: List[str] = Field(default_factory=list, description="餐次类型: breakfast/lunch/dinner/snack")
    specialty: str = Field(default="", description="招牌特色")
    avg_cost: int = Field(default=50, description="人均")
    rating: Optional[float] = Field(default=None, description="评分")
    reason: str = Field(default="", description="推荐理由")


class HotelFoodResult(BaseModel):
    """酒店餐厅甄选结果"""
    hotels: List[HotelCandidate] = Field(default_factory=list, description="3~5 家酒店")
    restaurants: List[RestaurantCandidate] = Field(default_factory=list, description="含早餐店与正餐厅")