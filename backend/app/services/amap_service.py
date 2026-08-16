"""高德地图基础服务类（供前端接口调用）"""

import re
import requests
from ..config import get_settings
from typing import List,Optional,Tuple
from ..models.schemas import Location, POIInfo, WeatherInfo, RouteInfo, RouteLeg

settings=get_settings()

class AmapService:
    def __init__(self):
        #高德 API 密钥
        self.api_key=settings.amap_api_key
        self.base_url="https://restapi.amap.com/v3"

    def search_poi(self,keywords:str,city:str,citylimit:bool=True)->List[POIInfo]:
        """获取地点信息
        根据关键词和城市搜索地点（POI）
        比如：搜索“北京”的“故宫”
        """
        url=f"{self.base_url}/place/text"
        params={
            "key": self.api_key,
            "keywords": keywords,
            "city": city,
            "citylimit": str(citylimit).lower(),
            "output": "json"
        }
        try:
            # 向高德发送 GET 请求
            response=requests.get(url,params=params,timeout=10)
            data=response.json()
            # status == "1" 表示高德官方返回成功
            if data.get("status")=="1" and data.get("pois"):
                poi_list=[]
                for item in data["pois"]:
                    # 高德返回的经纬度格式是 "116.397128,39.916527"（经度在前，纬度在后）
                    location_str=item.get("location","")
                    #获取坐标
                    if location_str and "," in location_str:
                        lag_str,lat_str=location_str.split(",")
                        loc=Location(longitude=float(lag_str),latitude=float(lat_str))
                    else:
                        loc=Location(longitude=0.0,latitude=0.0)

                    poi_list.append(POIInfo(
                        id=item.get("id",""),
                        name=item.get("name",""),
                        type=item.get("type","景点"),
                        address=item.get("address","") if isinstance(item.get("address"),str) else "",
                        location=loc,
                        tel=item.get("tel") if isinstance(item.get("tel"),str) else None
                    ))
                return poi_list
            return []
        except Exception as e:
            print(f"搜索POI失败: {str(e)}")
            return []

    def get_weather(self,city:str)->List[WeatherInfo]:
        """
        查询指定城市未来几天的天气预报
        """
        url=f"{self.base_url}/weather/weatherInfo"
        params={
            "key":self.api_key,
            "city":city,
            "extensions":"all", # all 代表获取预报天气（包含未来多天）
            "output":"json"
        }
        try:
            response=requests.get(url,params=params,timeout=10)
            data=response.json()

            if data.get("status")=="1" and data.get("forecasts"):
                casts=data["forecasts"][0]["casts"]
                weather_list=[]
                for cast in casts:
                    weather_list.append(WeatherInfo(
                        date=cast.get("date",""),
                        day_weather=cast.get("dayweather","晴"),
                        night_weather=cast.get("nightweather","晴"),
                        day_temp=cast.get("daytemp",20),
                        night_temp=cast.get("nighttemp", 10),
                        wind_direction=cast.get("daywind", "南风"),
                        wind_power=cast.get("daypower", "1-3级")
                    ))
                return weather_list
            return []
        except Exception as e:
            print(f"❌ 查询天气失败: {str(e)}")
            return []


    def get_poi_detail(self, poi_id: str) -> dict:
        """
        根据高德 POI ID 查询景点深度详情（评分、营业时间、人均消费、官方图库等）
        """
        url = f"{self.base_url}/place/detail"
        params = {
            "key": self.api_key,
            "id": poi_id,
            "output": "json"
        }
        try:
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            if data.get("status") == "1" and data.get("pois"):
                poi = data["pois"][0]
                biz_ext = poi.get("biz_ext") or {}
                location = poi.get("location", "")
                return {
                    "id": poi.get("id", ""),
                    "name": poi.get("name", ""),
                    "address": poi.get("address", ""),
                    "type": poi.get("type", ""),
                    "location": location,
                    "tel": poi.get("tel", ""),
                    "rating": biz_ext.get("rating"),
                    "cost": biz_ext.get("cost"),
                    "open_time": biz_ext.get("open_time"),
                    "photos": [p.get("url") for p in poi.get("photos", []) if p.get("url")],
                }
            return {}
        except Exception as e:
            print(f"❌ 获取POI详情失败: {str(e)}")
            return {}

    def get_route(
            self,
            origin_address:str,#出发点
            destination_address:str,#目标点
            route_type:str="walking",#交通方式
            city:Optional[str]=None
    )->Optional[RouteInfo]:
        """
        计算路线（支持步行 walking、驾车 driving、公交 transit）
        """
        # 先把起点和终点文字地址转成经纬度
        origin_loc=self.geocode(origin_address,city)
        dest_loc=self.geocode(destination_address,city)

        if not origin_loc or not dest_loc:
            return None

        origin_str=f"{origin_loc.longitude},{origin_loc.latitude}"
        dest_str = f"{dest_loc.longitude},{dest_loc.latitude}"

        # 公交出行走专用的公交路径规划接口
        if route_type == "transit":
            return self._get_transit_route(origin_str, dest_str, city)

        # 决定使用驾车还是步行 API
        mode="driving" if route_type== "driving" else "walking"
        url =f"{self.base_url}/direction/{mode}"
        params={
            "key": self.api_key,
            "origin": origin_str,
            "destination": dest_str,
            "output": "json"
        }

        try:
            response=requests.get(url,params=params,timeout=10)
            data=response.json()

            if data.get("status")=="1" and data.get("route") and data["route"].get("paths"):
                path=data["route"]["paths"][0]
                distance=float(path.get("distance", 0))  # 距离（米）
                duration=int(path.get("duration",0))  # 耗时（秒）

                return RouteInfo(
                    distance=distance,
                    duration=duration,
                    route_type=route_type,
                    description=f"全程约 {round(distance / 1000, 1)} 公里，耗时约 {round(duration / 60)} 分钟"
                )
            return None
        except Exception as e:
            print(f"❌ 路线规划计算失败: {str(e)}")
            return None

    def _get_transit_route(self, origin_str: str, dest_str: str, city: Optional[str] = None) -> Optional[RouteInfo]:
        """调用高德公交路径规划接口（integrated）"""
        url = f"{self.base_url}/direction/transit/integrated"
        params = {
            "key": self.api_key,
            "origin": origin_str,
            "destination": dest_str,
            "city": city or "",
            "cityd": city or "",
            "output": "json"
        }
        try:
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            if data.get("status") == "1" and data.get("route") and data["route"].get("transits"):
                transit = data["route"]["transits"][0]
                distance = float(transit.get("distance", 0))
                duration = int(transit.get("duration", 0))
                return RouteInfo(
                    distance=distance,
                    duration=duration,
                    route_type="transit",
                    description=f"全程约 {round(distance / 1000, 1)} 公里，耗时约 {round(duration / 60)} 分钟（公共交通）"
                )
            return None
        except Exception as e:
            print(f"❌ 公交路线规划失败: {str(e)}")
            return None

    def geocode(self, address: str, city: Optional[str] = None) -> Optional[Location]:
        """地理编码：把文字地址/地点名转成经纬度坐标（GET /v3/geocode/geo），失败返回 None"""
        if not address:
            return None
        url = f"{self.base_url}/geocode/geo"
        params = {
            "key": self.api_key,
            "address": address,
            "output": "json",
        }
        if city:
            params["city"] = city
        try:
            response = requests.get(url, params=params, timeout=8)
            data = response.json()
            if data.get("status") == "1" and data.get("geocodes"):
                loc_str = data["geocodes"][0].get("location", "")
                if loc_str and "," in loc_str:
                    lng_s, lat_s = loc_str.split(",")
                    return Location(longitude=float(lng_s), latitude=float(lat_s))
            return None
        except Exception as e:
            print(f"❌ 地理编码失败: {str(e)}", flush=True)
            return None

    def search_scenic_spot(self, name: str, city: Optional[str] = None) -> dict:
        """搜索单个景点的深度信息（真实坐标/官方实景图/地址/类型/评分），供行程后处理补全坐标与图片。

        关键词去括号修饰，并按 "-·/" 分段重试一次；
        返回结构: {name, location, photo_url, address, type, rating}，找不到返回空字典。
        """
        if not name:
            return {}
        for kw in self._build_scenic_keywords(name):
            params = {
                "key": self.api_key,
                "keywords": kw,
                "output": "json",
                "extensions": "all",
            }
            if city:
                params["city"] = city
                params["citylimit"] = "true"
            try:
                response = requests.get(f"{self.base_url}/place/text", params=params, timeout=8)
                data = response.json()
                if data.get("status") == "1" and data.get("pois"):
                    poi = data["pois"][0]
                    # 坐标（经度,纬度）
                    location = poi.get("location", "")
                    # 官方实景图（http 统一转 https）
                    photos = poi.get("photos") or []
                    photo_url = ""
                    if photos and isinstance(photos[0], dict) and photos[0].get("url"):
                        photo_url = photos[0]["url"].replace("http://", "https://")
                    # 地址
                    address = poi.get("address", "")
                    if not isinstance(address, str):
                        address = ""
                    # 评分（可能数字或字符串）
                    biz_ext = poi.get("biz_ext") or {}
                    rating = biz_ext.get("rating")
                    try:
                        rating = float(rating) if rating is not None else None
                    except (TypeError, ValueError):
                        rating = None
                    return {
                        "name": name,
                        "location": location,
                        "photo_url": photo_url,
                        "address": address,
                        "type": poi.get("type", "") or "",
                        "rating": rating,
                    }
            except Exception as e:
                print(f"⚠️ 景点搜索失败({kw}): {str(e)}", flush=True)
        return {}

    def _build_scenic_keywords(self, name: str) -> List[str]:
        """生成景点检索候选关键词：先去括号修饰，再按 -·/ 分段"""
        cands = []
        clean = re.sub(r"[（(].*?[）)]", "", name).strip()
        if clean:
            cands.append(clean)
        for sep in ("-", "·", "/"):
            if sep in clean:
                for seg in clean.split(sep):
                    seg = seg.strip()
                    if seg and seg not in cands:
                        cands.append(seg)
        return cands

    def _get_distance(self, origin_loc: Location, dest_loc: Location) -> Tuple[float, int]:
        """调用高德 /v3/distance 接口获取两点间驾车里程(米)与耗时(秒)，失败返回 (0, 0)"""
        origin_str = f"{origin_loc.longitude},{origin_loc.latitude}"
        dest_str = f"{dest_loc.longitude},{dest_loc.latitude}"
        url = f"{self.base_url}/distance"
        params = {
            "key": self.api_key,
            "origins": origin_str,
            "destination": dest_str,
            "type": "1",
            "output": "json",
        }
        try:
            response = requests.get(url, params=params, timeout=8)
            data = response.json()
            if data.get("status") == "1" and data.get("results"):
                res = data["results"][0]
                return float(res.get("distance", 0)), int(res.get("duration", 0))
        except Exception as e:
            print(f"⚠️ 距离接口调用失败: {str(e)}", flush=True)
        return 0.0, 0

    @staticmethod
    def _pick_leg_mode(distance_km: float, transport_mode: str = "mixed") -> str:
        """按距离分档 + 用户交通方式偏好，决定推荐交通方式（walking/transit/driving）"""
        mode = (transport_mode or "mixed").strip()
        if mode in ("walking", "transit", "driving"):
            return mode
        # mixed 口径：按距离自动推荐
        if distance_km < 1.2:
            return "walking"
        if distance_km < 15:
            return "transit"
        return "driving"

    @staticmethod
    def _estimate_taxi_cost(distance_km: float) -> int:
        """按起步价 10 元(3 公里内) + 续程 2.4 元/公里 估算打车费用"""
        if distance_km <= 3:
            return 10
        return 10 + int(round(2.4 * (distance_km - 3)))

    def calculate_leg(
            self,
            origin_loc: Optional[Location],
            dest_loc: Optional[Location],
            from_name: str,
            to_name: str,
            city: Optional[str] = None,
            transport_mode: str = "mixed",
    ) -> RouteLeg:
        """
        计算两点间一段真实动线信息（高德 /v3/distance 真实里程 + 按距离分档生成方式/耗时/费用/描述）。

        transport_mode: mixed 按距离自动推荐；walking 全程步行；transit 公交/地铁；driving 打车/自驾。
        分档规则:
          - <1.2km   步行(75 米/分钟, ¥0)
          - <15km    公交/地铁(驾车时长+5min 缓冲, ¥5，附打车估价 10+2.4×超 3km 里程)
          - ≥15km    打车/专线(¥10+2.4/km)
        坐标缺失先 geocode 补全；彻底失败返回描述性占位 RouteLeg，绝不抛异常。
        """
        # 1. 坐标补全（缺坐标先 geocode）
        try:
            if origin_loc is None or (origin_loc.longitude == 0 and origin_loc.latitude == 0):
                origin_loc = self.geocode(f"{city or ''}{from_name}", city) or origin_loc
            if dest_loc is None or (dest_loc.longitude == 0 and dest_loc.latitude == 0):
                dest_loc = self.geocode(f"{city or ''}{to_name}", city) or dest_loc
        except Exception as e:
            print(f"⚠️ 动线坐标补全失败: {str(e)}", flush=True)
            origin_loc = None
            dest_loc = None

        # 2. 双方都有坐标 → 调 /v3/distance 拿真实里程与驾车耗时
        distance_m = 0.0
        driving_duration_s = 0
        if origin_loc and dest_loc:
            distance_m, driving_duration_s = self._get_distance(origin_loc, dest_loc)

        # 3. 彻底失败 → 返回描述性占位（不抛异常）
        if distance_m <= 0:
            return RouteLeg(
                from_name=from_name,
                to_name=to_name,
                route_type="mixed",
                distance_m=0,
                duration_min=15,
                cost=5,
                description=f"{from_name} → {to_name}（行程信息暂缺，预计乘车约 15 分钟 · 费用约 ¥5）",
            )

        distance_km = round(distance_m / 1000.0, 1)
        mode = self._pick_leg_mode(distance_km, transport_mode)

        if mode == "walking":
            duration_min = max(1, int(round(distance_m / 75.0)))
            cost = 0
            description = f"步行约 {duration_min} 分钟 · {distance_km} 公里"
        elif mode == "transit":
            if driving_duration_s:
                driving_min = max(1, int(driving_duration_s / 60))
            else:
                driving_min = max(5, int(round(distance_km * 3)))
            duration_min = driving_min + 5  # 公交等待/换乘缓冲
            cost = 5
            taxi_cost = self._estimate_taxi_cost(distance_km)
            description = f"公交/地铁约 {duration_min} 分钟 · {distance_km} 公里（打车约 ¥{taxi_cost}）"
        else:  # driving
            if driving_duration_s:
                duration_min = max(1, int(driving_duration_s / 60))
            else:
                duration_min = max(3, int(round(distance_km * 2)))
            cost = self._estimate_taxi_cost(distance_km)
            description = f"打车/自驾约 {duration_min} 分钟 · {distance_km} 公里（约 ¥{cost}）"

        return RouteLeg(
            from_name=from_name,
            to_name=to_name,
            route_type=mode,
            distance_m=int(distance_m),
            duration_min=duration_min,
            description=description,
            cost=cost,
        )


def get_amap_service():
    """工厂函数：在其他文件里只需要调这个函数就能拿到服务实例"""
    return AmapService()