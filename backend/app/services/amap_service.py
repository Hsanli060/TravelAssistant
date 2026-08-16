"""高德地图基础服务类（供前端接口调用）"""

import requests
from ..config import get_settings
from typing import List,Optional
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


    def search_scenic_spot(self, spot_name: str, city: Optional[str] = None) -> dict:
        """
        高德官方景点综合检索：一步获取景点的精确经纬度与官方高清实景相册
        具备智能去括号、分段重试能力，泛用性极强。
        """
        import re
        # 提取核心关键词（去除 LLM 可能生成的括号修饰语，例如 "黄山风景区（前山段：迎客松）" -> "黄山风景区 迎客松"）
        clean_name = re.sub(r"[\(（][^()（）]*?[\)）]", " ", spot_name).strip()
        search_kw = clean_name or spot_name

        url = f"{self.base_url}/place/text"
        params = {
            "key": self.api_key,
            "keywords": search_kw,
            "city": city or "",
            "extensions": "all",
            "children": "1",
            "output": "json"
        }
        try:
            response = requests.get(url, params=params, timeout=5)
            data = response.json()
            pois = data.get("pois", [])
            
            # 若未搜到且包含连字符，尝试取前段关键词再搜
            if not pois and ("-" in search_kw or "·" in search_kw):
                first_seg = re.split(r"[-·/]", search_kw)[0].strip()
                if first_seg:
                    params["keywords"] = first_seg
                    res2 = requests.get(url, params=params, timeout=5)
                    pois = res2.json().get("pois", [])

            if data.get("status") == "1" and pois:
                poi = pois[0]
                loc_str = poi.get("location", "")
                loc = None
                if loc_str and "," in loc_str:
                    lng_s, lat_s = loc_str.split(",")
                    loc = Location(longitude=float(lng_s), latitude=float(lat_s))

                photo_url = None
                photos = poi.get("photos", [])
                if photos and isinstance(photos, list) and len(photos) > 0:
                    raw_url = photos[0].get("url")
                    if raw_url:
                        # 转换成 https 协议以防混合内容拦截
                        photo_url = raw_url.replace("http://", "https://")

                return {
                    "name": poi.get("name", spot_name),
                    "location": loc,
                    "photo_url": photo_url,
                    "address": poi.get("address") or "",
                    "type": poi.get("type") or "",
                    "rating": (poi.get("biz_ext") or {}).get("rating"),
                }
            return {}
        except Exception as e:
            print(f"高德景区检索异常: {e}")
            return {}


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

    def calculate_leg(self, origin_loc: Optional[Location], dest_loc: Optional[Location], from_name: str, to_name: str, city: Optional[str] = None) -> RouteLeg:
        """
        高德两点间真实交通距离与路程建议计算（毫秒级高德 Distance API）
        """
        # 若缺少坐标，尝试实时地理编码补全
        if (not origin_loc or origin_loc.longitude == 0) and from_name:
            clean_from = from_name.replace("(出发)", "").replace("(返程)", "").strip()
            origin_loc = self.geocode(f"{city or ''}{clean_from}", city)
        if (not dest_loc or dest_loc.longitude == 0) and to_name:
            clean_to = to_name.replace("(出发)", "").replace("(返程)", "").strip()
            dest_loc = self.geocode(f"{city or ''}{clean_to}", city)

        if not origin_loc or not dest_loc or origin_loc.longitude == 0 or dest_loc.longitude == 0:
            return RouteLeg(
                from_name=from_name,
                to_name=to_name,
                route_type="公共交通",
                distance_m=0,
                duration_min=15,
                description="市内交通便捷，建议乘公交/打车前往"
            )

        url = f"{self.base_url}/distance"
        params = {
            "key": self.api_key,
            "origins": f"{origin_loc.longitude},{origin_loc.latitude}",
            "destination": f"{dest_loc.longitude},{dest_loc.latitude}",
            "type": "1",  # 驾车/道路实际行驶距离
        }
        try:
            res = requests.get(url, params=params, timeout=3).json()
            if res.get("status") == "1" and res.get("results"):
                dist_m = float(res["results"][0].get("distance", 0))
                dur_s = int(res["results"][0].get("duration", 0))
                dist_km = round(dist_m / 1000, 1)

                if dist_m < 1200:
                    walk_min = max(2, int(dist_m / 75))
                    return RouteLeg(
                        from_name=from_name,
                        to_name=to_name,
                        route_type="步行",
                        distance_m=dist_m,
                        duration_min=walk_min,
                        description=f"🚶 步行约 {walk_min} 分钟（{int(dist_m)} 米）"
                    )
                elif dist_m < 15000:
                    transit_min = max(8, int(dur_s / 60) + 5)
                    taxi_cost = max(10, int(10 + max(0, dist_km - 3) * 2.4))
                    return RouteLeg(
                        from_name=from_name,
                        to_name=to_name,
                        route_type="公交/地铁/打车",
                        distance_m=dist_m,
                        duration_min=transit_min,
                        description=f"🚇 公交/地铁约 {transit_min} 分钟 · {dist_km} 公里（打车约 ¥{taxi_cost}）"
                    )
                else:
                    drive_min = max(15, int(dur_s / 60))
                    taxi_cost = int(10 + max(0, dist_km - 3) * 2.4)
                    return RouteLeg(
                        from_name=from_name,
                        to_name=to_name,
                        route_type="专线/打车",
                        distance_m=dist_m,
                        duration_min=drive_min,
                        description=f"🚖 专线大巴/打车约 {drive_min} 分钟 · {dist_km} 公里（打车约 ¥{taxi_cost}）"
                    )
        except Exception as e:
            print(f"高德距离计算异常: {e}")

        return RouteLeg(
            from_name=from_name,
            to_name=to_name,
            route_type="常规交通",
            distance_m=0,
            duration_min=20,
            description="建议使用公共交通或打车前往"
        )


def get_amap_service():
    """工厂函数：在其他文件里只需要调这个函数就能拿到服务实例"""
    return AmapService()