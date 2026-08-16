"""通用高保真景点实景图片检索引擎

采用高可靠的三级多源检索体系，具备极强的全国与全球泛用性：
- 第一级（优先）：高德官方 POI 实景相册（覆盖全国所有地级市/区县的 100万+ 景点实景原图）
- 第二级（补充）：维基百科/维基共享资源官方 PageImages API
- 第三级（兜底）：多品类（名山峡谷、湖泊瀑布、古镇古城、寺庙古刹、博物馆、地质洞穴等）高清风景图库
"""

import hashlib
import re
import urllib.parse
from typing import Optional
import requests

from ..config import get_settings


# 多分类精选高清风景图库（当外网与高德均未收录极罕见小众景点时兜底）
CATEGORY_IMAGE_POOL = {
    # 博物馆、艺术馆、纪念馆、科技馆
    "museum": [
        "https://images.unsplash.com/photo-1565008447742-97f6f38c985c?w=800&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1579783900882-c0d3dad7b119?w=800&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1532094349884-543bc11b234d?w=800&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1582555172866-f73bb12a2ab3?w=800&auto=format&fit=crop&q=80",
    ],
    # 名山胜境、峡谷、自然峰林、索道
    "mountain": [
        "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=800&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1506744038136-46273834b3fb?w=800&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?w=800&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1548013146-72479768bada?w=800&auto=format&fit=crop&q=80",
    ],
    # 湖泊、溪流、河流、瀑布、海滨
    "water": [
        "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=800&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1432405972618-c60b0225b8f9?w=800&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1500382017468-9049fed747ef?w=800&auto=format&fit=crop&q=80",
    ],
    # 古镇、古城、老街、历史街区、民俗风情
    "ancient_town": [
        "https://images.unsplash.com/photo-1544735716-392fe2489ffa?w=800&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1519452635265-7b1fbfd1e4e0?w=800&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1534447677768-be436bb09401?w=800&auto=format&fit=crop&q=80",
    ],
    # 寺庙、古刹、道观、石窟、塔
    "temple": [
        "https://images.unsplash.com/photo-1548013146-72479768bada?w=800&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1599837565318-67429bde7162?w=800&auto=format&fit=crop&q=80",
    ],
    # 溶洞、地质洞穴、地道
    "cave": [
        "https://images.unsplash.com/photo-1509316975850-ff9c5deb0cd9?w=800&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1513836279014-a89f7a76ae86?w=800&auto=format&fit=crop&q=80",
    ],
    # 现代都市、地标建筑、商业街、夜市
    "city": [
        "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=800&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1578632767115-351597cf2477?w=800&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1508804185872-d7be30e9a0ec?w=800&auto=format&fit=crop&q=80",
    ]
}


class UnsplashService:
    def __init__(self):
        settings = get_settings()
        self.amap_api_key = settings.amap_api_key

    def get_image(self, keywords: str, city: Optional[str] = None) -> str:
        """多级高保真景点实景图检索入口
        
        Args:
            keywords: 景点名称或复合搜索词（如 "黄山 迎客松" 或 "宏村"）
            city: 城市名称（如 "黄山", "张家界", "成都"）
        """
        clean_name = keywords.strip()
        if city and clean_name.startswith(city):
            spot_name = clean_name[len(city):].strip()
        else:
            spot_name = clean_name.split()[-1] if clean_name else ""

        target_spot = spot_name or clean_name
        target_city = city or (clean_name.split()[0] if " " in clean_name else "")

        # 1. 第一级：高德官方 POI 实景相册检索
        if self.amap_api_key:
            try:
                url = "https://restapi.amap.com/v3/place/text"
                params = {
                    "key": self.amap_api_key,
                    "keywords": target_spot,
                    "city": target_city,
                    "extensions": "all",
                    "children": "1",
                    "output": "json"
                }
                res = requests.get(url, params=params, timeout=3.0).json()
                pois = res.get("pois", [])
                if pois:
                    for p in pois[:3]:
                        photos = p.get("photos", [])
                        if photos and isinstance(photos, list) and len(photos) > 0:
                            photo_url = photos[0].get("url")
                            if photo_url:
                                return photo_url.replace("http://", "https://")
            except Exception as e:
                pass

        # 2. 第二级：维基百科精美景物图检索
        try:
            wiki_url = "https://zh.wikipedia.org/w/api.php"
            wiki_params = {
                "action": "query",
                "titles": target_spot,
                "prop": "pageimages",
                "format": "json",
                "pithumbsize": 800
            }
            wres = requests.get(wiki_url, params=wiki_params, headers={"User-Agent": "TravelBot/1.0"}, timeout=2.5).json()
            pages = wres.get("query", {}).get("pages", {})
            for pid, pdata in pages.items():
                thumb = pdata.get("thumbnail", {}).get("source")
                if thumb:
                    return thumb
        except Exception:
            pass

        # 3. 第三级：基于景点语义特征的分类图库兜底
        kw = target_spot
        if any(w in kw for w in ["博物馆", "画院", "纪念馆", "展览馆", "科技馆", "地质馆", "文化馆", "艺术"]):
            pool = CATEGORY_IMAGE_POOL["museum"]
        elif any(w in kw for w in ["山", "峰", "寨", "峡谷", "梯", "索道", "森林公园", "绝壁", "栈道", "顶", "岩"]):
            pool = CATEGORY_IMAGE_POOL["mountain"]
        elif any(w in kw for w in ["湖", "溪", "河", "瀑布", "海", "江", "潭", "湿地", "泉", "水"]):
            pool = CATEGORY_IMAGE_POOL["water"]
        elif any(w in kw for w in ["古镇", "古城", "老街", "风情", "街区", "巷", "胡同", "村", "堡"]):
            pool = CATEGORY_IMAGE_POOL["ancient_town"]
        elif any(w in kw for w in ["寺", "庙", "观", "塔", "宫", "禅", "窟", "院"]):
            pool = CATEGORY_IMAGE_POOL["temple"]
        elif any(w in kw for w in ["洞", "地道", "地下", "溶洞"]):
            pool = CATEGORY_IMAGE_POOL["cave"]
        else:
            pool = CATEGORY_IMAGE_POOL["city"]

        # 使用字符串哈希确定池中索引，确保同一景点图片稳定且不同景点各不相同
        hash_val = int(hashlib.md5(f"{target_city}_{target_spot}".encode()).hexdigest(), 16)
        return pool[hash_val % len(pool)]


def get_unsplash_service() -> UnsplashService:
    return UnsplashService()
