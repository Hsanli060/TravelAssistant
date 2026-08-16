import axios from 'axios'
import type { TripRequest, TripPlan, ApiResponse } from '../types'

const apiClient = axios.create({
  baseURL: '/api',
  timeout: 120000, // 2分钟超时，适应复杂大模型规划
  headers: {
    'Content-Type': 'application/json',
  },
})

export const tripApi = {
  // 生成旅行规划
  async planTrip(request: TripRequest): Promise<TripPlan> {
    const response = await apiClient.post<ApiResponse<TripPlan>>('/trip/plan', request)
    if (response.data.success && response.data.data) {
      return response.data.data
    }
    throw new Error(response.data.message || '生成旅行计划失败')
  },

  // 查询城市天气
  async getWeather(city: string) {
    const response = await apiClient.get<ApiResponse<any>>('/map/weather', {
      params: { city },
    })
    return response.data.data
  },

  // 搜索 POI
  async searchPOI(keywords: string, city: string) {
    const response = await apiClient.get<ApiResponse<any>>('/map/poi', {
      params: { keywords, city },
    })
    return response.data.data
  },

  // 计算路线
  async calculateRoute(params: {
    origin_address: string
    destination_address: string
    route_type?: string
    origin_city?: string
  }) {
    const response = await apiClient.post<ApiResponse<any>>('/map/route', params)
    return response.data.data
  },
}
