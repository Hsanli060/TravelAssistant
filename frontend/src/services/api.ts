import axios from 'axios'
import type { TripRequest, TripPlan, ApiResponse } from '../types'

const apiClient = axios.create({
  baseURL: '/api',
  timeout: 120000, // 2分钟超时，适应复杂大模型规划
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器：当请求 /trip/plan 时，若本地配置了 API Key / Base URL，自动附带在请求头中
apiClient.interceptors.request.use((config) => {
  if (config.url && config.url.includes('/trip/plan')) {
    const customKey = localStorage.getItem('ta_llm_api_key')
    const customBaseUrl = localStorage.getItem('ta_llm_base_url')

    if (customKey && customKey.trim()) {
      config.headers['X-LLM-API-Key'] = customKey.trim()
    }
    if (customBaseUrl && customBaseUrl.trim()) {
      config.headers['X-LLM-Base-URL'] = customBaseUrl.trim()
    }
  }
  return config
})

// 响应拦截器：捕获 409 (NO_API_KEY) 或 400 (BAD_API_KEY / BAD_BASE_URL 等) 并转化为业务易读错误
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    // 若为主动取消，直接向下传递 CancelError，不干扰前端取消流程
    if (axios.isCancel(error) || error?.code === 'ERR_CANCELED' || error?.name === 'CanceledError') {
      return Promise.reject(error)
    }
    const detail = error.response?.data?.detail
    if (detail?.code) {
      const err = new Error(detail.message || '大模型请求鉴权或连接失败')
      ;(err as any).code = detail.code
      return Promise.reject(err)
    }
    return Promise.reject(error)
  }
)

export const tripApi = {
  // 生成旅行规划（支持传入唯一请求 ID 与 AbortSignal 用于随时中断）
  async planTrip(
    request: TripRequest,
    options?: { requestId?: string; signal?: AbortSignal }
  ): Promise<TripPlan> {
    const headers: Record<string, string> = {}
    if (options?.requestId) {
      headers['X-Plan-Request-Id'] = options.requestId
    }
    const response = await apiClient.post<ApiResponse<TripPlan>>('/trip/plan', request, {
      headers,
      signal: options?.signal,
    })
    if (response.data.success && response.data.data) {
      return response.data.data
    }
    throw new Error(response.data.message || '生成旅行计划失败')
  },

  // 显式取消正在进行的旅行规划
  async cancelPlan(requestId: string): Promise<boolean> {
    try {
      const response = await apiClient.post<{ success: boolean; message: string }>('/trip/cancel', {
        request_id: requestId,
      })
      return !!response.data.success
    } catch {
      return false
    }
  },

  // 校验/测试 API Key 与连接有效性 (0 token 探活)
  async verifyApiKey(apiKey: string, baseUrl?: string): Promise<{ success: boolean; code: string; message: string }> {
    const response = await apiClient.post<{ success: boolean; code: string; message: string }>('/trip/verify-key', {
      api_key: apiKey,
      base_url: baseUrl,
    })
    return response.data
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
