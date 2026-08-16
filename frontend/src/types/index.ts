// TypeScript 数据类型契约定义

export interface Location {
  longitude?: number
  latitude?: number
}

export interface Attraction {
  name: string
  address?: string
  location?: Location
  visit_duration?: number
  description?: string
  category?: string
  rating?: number | string
  image_url?: string
  ticket_price?: number
  poi_id?: string
  open_time?: string
}

export interface Meal {
  type: 'breakfast' | 'lunch' | 'dinner' | 'snack' | string
  name: string
  address?: string
  location?: Location
  description?: string
  estimated_cost?: number
  recommended_dishes?: string[]
}

export interface Hotel {
  name: string
  address?: string
  location?: Location
  price_range?: string
  rating?: number | string
  description?: string
  estimated_cost?: number
}

export interface RouteLeg {
  from_name: string
  to_name: string
  route_type?: string
  distance_m?: number
  duration_min?: number
  description?: string
  cost?: number
}

export interface DayPlan {
  day_index: number
  date: string
  description?: string
  attractions: Attraction[]
  meals: Meal[]
  hotel?: Hotel
  accommodation?: string
  transportation?: string
  legs?: RouteLeg[]
}

export interface Budget {
  total_attractions: number
  total_hotels: number
  total_meals: number
  total_transportation: number
  total: number
}

export interface WeatherInfo {
  date: string
  day_weather?: string
  night_weather?: string
  day_temp?: number | string
  night_temp?: number | string
  wind_direction?: string
  wind_power?: string
}

export interface TripPlan {
  city: string
  start_date: string
  end_date: string
  days: DayPlan[]
  overall_suggestions?: string
  budget?: Budget
  weather_info?: WeatherInfo[]
}

export interface TripRequest {
  city: string
  start_date: string
  end_date: string
  travel_days: number
  transportation?: string
  accommodation?: string
  preferences?: string[]
  free_text_input?: string
}

export interface ApiResponse<T> {
  success: boolean
  message: string
  data: T
}
