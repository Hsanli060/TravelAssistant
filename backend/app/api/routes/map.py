"""地图相关 HTTP 路由接口（供前端网页调用地点搜索、天气和路线规划）"""

from fastapi import APIRouter,Query,HTTPException
from typing import Optional
from ...models.schemas import (
    POISearchResponse,
    WeatherResponse,
    RouteRequest,
    RouteResponse
)
from ...services.amap_service import get_amap_service

router=APIRouter(prefix="/map", tags=["地图与天气服务"])

@router.get("/poi",response_model=POISearchResponse,summary="搜索地点(POI)")
async def search_poi(
        keywords:str=Query(...,description="搜索关键词，例如：故宫", examples=["故宫"]),
        city:str=Query(...,description="城市名称，例如：北京", examples=["北京"]),
        citylimit:bool=Query(True, description="是否限制在指定城市内")
):
    """
    【接口】前端在输入框搜索景点或酒店时调用
    """
    try:
        service=get_amap_service()
        pois=service.search_poi(keywords=keywords,city=city,citylimit=citylimit)
        return POISearchResponse(
            success=True,
            message="搜索成功",
            data=pois
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索地点报错: {str(e)}")


@router.get("/weather",response_model=WeatherResponse,summary="查询城市天气")
async def get_weather(city:str=Query(...,description="城市名称，例如：北京", examples=["北京"])):
    """
    【接口】前端展示目的地天气预报卡片时调用
    """
    try:
        service=get_amap_service()
        weather_data=service.get_weather(city=city)
        return WeatherResponse(
            success=True,
            message="获取天气成功",
            data=weather_data
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取天气报错: {str(e)}")

@router.post("/route",response_model=RouteResponse, summary="两点间路线规划")
async def calculate_route(request: RouteRequest):
    """
    【接口】前端计算从酒店到景点、或景点到景点的距离和预计耗时
    """
    try:
        service=get_amap_service()
        route_info=service.get_route(
            origin_address=request.origin_address,
            destination_address=request.destination_address,
            route_type=request.route_type,
            city=request.origin_city
        )
        if route_info:
            return RouteResponse(
                success=True,
                message="路线规划成功",
                data=route_info
            )
        else:
            return RouteResponse(
                success=False,
                message="未找到可行路线，请检查起点或终点地址",
                data=None
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算路线报错: {str(e)}")


@router.get("/health", summary="健康检查", description="检查地图与天气服务是否正常")
async def health_check():
    """健康检查"""
    try:
        service = get_amap_service()
        return {
            "status": "healthy",
            "service": "map-service",
            "amap_configured": bool(service.api_key)
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"服务不可用: {str(e)}")