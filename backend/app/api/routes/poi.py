"""POI 兴趣点与图片相关 API 路由"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, Any
from ...services.unsplash_service import get_unsplash_service
from ...services.amap_service import get_amap_service

router = APIRouter(prefix="/poi", tags=["景点详情"])


class StandardResponse(BaseModel):
    """通用响应格式"""
    success: bool
    message: str
    data: Optional[Any] = None


@router.get("/detail/{poi_id}", response_model=StandardResponse, summary="获取POI详情",
            description="根据高德 POI ID 查询景点深度详情（评分、营业时间、人均消费、官方图库等）")
async def get_poi_detail(poi_id: str):
    """根据 POI ID 获取详情"""
    try:
        amap_service = get_amap_service()
        detail = amap_service.get_poi_detail(poi_id)
        if not detail:
            raise HTTPException(status_code=404, detail="未找到该 POI 详情，请检查 POI ID 是否正确")
        return StandardResponse(success=True, message="获取POI详情成功", data=detail)
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 获取POI详情失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取POI详情失败: {str(e)}")


@router.get("/photo", response_model=StandardResponse, summary="获取景点图片",
            description="根据景点名称从 Unsplash 获取一张风景图")
async def get_attraction_photo(name: str = Query(..., description="景点名称", examples=["故宫"])):
    """根据景点名称获取图片 URL"""
    try:
        unsplash_service = get_unsplash_service()
        photo_url = unsplash_service.get_photo_url(f"{name} China landmark")
        return StandardResponse(
            success=True,
            message="获取图片成功",
            data={"name": name, "photo_url": photo_url}
        )
    except Exception as e:
        print(f"❌ 获取景点图片失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取景点图片失败: {str(e)}")


@router.get("/search", response_model=StandardResponse, summary="搜索POI",
            description="根据关键词搜索 POI（与 /map/poi 等价，供景点详情页使用）")
async def search_poi(
    keywords: str = Query(..., description="搜索关键词", examples=["故宫"]),
    city: str = Query("北京", description="城市名称", examples=["北京"]),
):
    """根据关键词搜索 POI"""
    try:
        amap_service = get_amap_service()
        pois = amap_service.search_poi(keywords=keywords, city=city)
        return StandardResponse(success=True, message="搜索成功", data=pois)
    except Exception as e:
        print(f"❌ 搜索POI失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"搜索POI失败: {str(e)}")
