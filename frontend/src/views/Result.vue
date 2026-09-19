<template>
  <div class="result-container" id="printable-area">
    <!-- 旅行艺术与空间氛围背景 (克制质感，不干扰行程动线) -->
    <TravelBackground variant="result" />

    <!-- 顶部极简吸顶导航栏 -->
    <header class="top-nav-bar">
      <div class="nav-left">
        <button class="back-btn" @click="handleBackToHome">
          <ArrowLeftOutlined class="btn-arrow" />
          <span>返回重新规划</span>
        </button>
        <div class="trip-main-title">
          <span class="city-badge"><EnvironmentOutlined class="badge-icon" /> {{ tripPlan.city }}</span>
          <span class="days-badge">{{ tripPlan.start_date }} ~ {{ tripPlan.end_date }} · 共 {{ tripPlan.days?.length || 0 }} 天</span>
        </div>
      </div>

      <div class="nav-right no-print">
        <button class="copy-text-btn" @click="copyPlanToClipboard" title="一键复制行程文本">
          <CopyOutlined class="btn-icon" />
          <span>复制行程</span>
        </button>

        <a-dropdown :trigger="['click']">
          <template #overlay>
            <a-menu @click="handleExportMenu">
              <a-menu-item key="markdown">
                <FileMarkdownOutlined class="menu-icon" />
                <span>导出 Markdown (.md)</span>
              </a-menu-item>
              <a-menu-item key="image">
                <PictureOutlined class="menu-icon" />
                <span>导出长图 (PNG)</span>
              </a-menu-item>
              <a-menu-item key="print">
                <PrinterOutlined class="menu-icon" />
                <span>打印 / 另存为 PDF</span>
              </a-menu-item>
            </a-menu>
          </template>
          <button class="export-dropdown-btn">
            <ExportOutlined class="btn-icon" />
            <span>导出与分享</span>
            <DownOutlined class="arrow-down" />
          </button>
        </a-dropdown>
      </div>
    </header>

    <main class="result-body">
      <!-- 顶部信息看板：左侧概览与预算，右侧高德交互地图 -->
      <section class="dashboard-grid">
        <!-- 左侧面板：总体建议 + 天气（如有） + 预算明细看板 -->
        <div class="summary-column">
          <!-- 总体建议卡片 -->
          <div class="clean-card overview-panel">
            <div class="panel-header">
              <BulbOutlined class="panel-icon" />
              <h3 class="panel-title">规划总监出行锦囊</h3>
            </div>
            <div class="suggestions-text">
              {{ tripPlan.overall_suggestions || '祝您旅途愉快，探索美好风景！' }}
            </div>
          </div>

          <!-- 天气概况卡片 (如果有返回 weather_info) -->
          <div v-if="tripPlan.weather_info && tripPlan.weather_info.length > 0" class="clean-card weather-panel">
            <div class="panel-header">
              <CloudOutlined class="panel-icon" />
              <h3 class="panel-title">目的地气象预报</h3>
            </div>
            <div class="weather-grid">
              <div v-for="(w, wIdx) in tripPlan.weather_info" :key="wIdx" class="weather-item">
                <div class="w-date">{{ w.date }}</div>
                <div class="w-cond">{{ w.day_weather || '晴' }}</div>
                <div class="w-temp">{{ w.night_temp }}°C ~ {{ w.day_temp }}°C</div>
                <div class="w-wind" v-if="w.wind_direction">{{ w.wind_direction }}风</div>
              </div>
            </div>
          </div>

          <!-- 预算全景卡片 -->
          <div v-if="tripPlan.budget" class="clean-card budget-panel">
            <div class="panel-header">
              <WalletOutlined class="panel-icon" />
              <h3 class="panel-title">全程预算精算明细</h3>
              <span class="budget-subtitle">AI 精算 + 空间真实数据校验</span>
            </div>

            <div class="budget-grid-cards">
              <div class="budget-card-mini is-attractions">
                <div class="b-icon"><TagOutlined /></div>
                <div class="b-info">
                  <div class="b-label">景点门票</div>
                  <div class="b-value">¥{{ tripPlan.budget.total_attractions }}</div>
                </div>
              </div>

              <div class="budget-card-mini is-hotels">
                <div class="b-icon"><HomeOutlined /></div>
                <div class="b-info">
                  <div class="b-label">酒店住宿</div>
                  <div class="b-value">¥{{ tripPlan.budget.total_hotels }}</div>
                </div>
              </div>

              <div class="budget-card-mini is-meals">
                <div class="b-icon"><CoffeeOutlined /></div>
                <div class="b-info">
                  <div class="b-label">餐饮美食</div>
                  <div class="b-value">¥{{ tripPlan.budget.total_meals }}</div>
                </div>
              </div>

              <div class="budget-card-mini is-transport">
                <div class="b-icon"><CarOutlined /></div>
                <div class="b-info">
                  <div class="b-label">市内交通</div>
                  <div class="b-value">¥{{ tripPlan.budget.total_transportation }}</div>
                </div>
              </div>
            </div>

            <div class="budget-total-bar">
              <div class="total-left">
                <span class="total-label">全程预估总费用：</span>
                <span class="total-hint">（含门票、住宿、餐饮与交通）</span>
              </div>
              <div class="total-amount">
                <span class="currency">¥</span>
                <span class="amount-num">{{ tripPlan.budget.total }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 右侧面板：高德交互式地图 -->
        <div class="map-column">
          <div class="clean-card map-panel">
            <div class="map-header">
              <div class="map-title-wrap">
                <CompassOutlined class="panel-icon" />
                <h3 class="panel-title">高德地图动线轨迹</h3>
              </div>

              <!-- 天数切换过滤 Tab -->
              <div class="map-day-tabs">
                <button
                  type="button"
                  class="day-tab-btn"
                  :class="{ active: currentMapDay === -1 }"
                  @click="switchMapDay(-1)"
                >
                  全部
                </button>
                <button
                  type="button"
                  v-for="(day, idx) in tripPlan.days"
                  :key="idx"
                  class="day-tab-btn"
                  :class="{ active: currentMapDay === idx }"
                  @click="switchMapDay(idx)"
                >
                  第{{ day.day_index + 1 }}天
                </button>
              </div>
            </div>

            <!-- 地图渲染容器 -->
            <div class="map-container-wrapper">
              <div id="amap-container" class="amap-instance"></div>
              <div v-if="mapLoading" class="map-loading-mask">
                <a-spin tip="正在载入高德地图..." />
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 逐日详细行程安排列表 -->
      <section class="days-itinerary-section">
        <div class="section-title-wrap">
          <CalendarOutlined class="sec-icon" />
          <h2 class="sec-title">每日游玩详细安排</h2>
        </div>

        <div class="days-list">
          <div
            v-for="(day, dayIdx) in tripPlan.days"
            :key="dayIdx"
            class="day-card clean-card"
            :id="`day-section-${dayIdx}`"
          >
            <!-- 每日卡片头部 -->
            <div class="day-card-header">
              <div class="day-badge-wrap">
                <span class="day-index-badge">Day {{ day.day_index + 1 }}</span>
                <span class="day-date-text">{{ day.date }}</span>
              </div>
            </div>

            <!-- 当日精选住宿卡片（含地址与价格，支持点击定位地图） -->
            <div class="day-hotel-card" v-if="day.hotel" @click="focusOnHotel(day.hotel)">
              <div class="hotel-card-left">
                <div class="hotel-name-row">
                  <span class="hotel-pill"><HomeOutlined /> 住宿安排</span>
                  <span class="hotel-title">{{ day.hotel.name }}</span>
                </div>
                <div class="hotel-addr-row" v-if="day.hotel.address">
                  <EnvironmentOutlined class="addr-icon" />
                  <span class="addr-text">{{ day.hotel.address }}</span>
                </div>
              </div>
              <div class="hotel-card-right">
                <div class="hotel-cost-val">预估 ¥{{ day.hotel.estimated_cost || 350 }}<span class="cost-unit">/晚</span></div>
                <span class="hotel-loc-btn">在地图查看</span>
              </div>
            </div>

            <!-- 每日概述 -->
            <div class="day-desc-box" v-if="day.description">
              {{ day.description }}
            </div>

            <!-- 每日完整点对点动线与路程明细 (住宿 -> 景点 -> 景点 -> 住宿) -->
            <div class="transit-flow-box" v-if="day.legs && day.legs.length > 0">
              <div class="sub-sec-header">
                <span class="sub-sec-title"><NodeIndexOutlined class="sub-title-icon" /> 每日完整动线与路程交通明细</span>
                <span class="sub-sec-hint">（高德地图实时距离与耗时精算）</span>
              </div>

              <div class="transit-timeline-list">
                <div
                  v-for="(leg, legIdx) in day.legs"
                  :key="legIdx"
                  class="transit-step-item"
                >
                  <div class="step-point-node">
                    <div class="point-badge" :class="{ 'is-hotel': leg.from_name.includes('酒店') }">
                      <HomeOutlined v-if="leg.from_name.includes('酒店')" />
                      <span v-else>{{ legIdx + 1 }}</span>
                    </div>
                    <span class="point-name">{{ leg.from_name }}</span>
                  </div>

                  <div class="step-route-leg">
                    <div class="leg-dash-line"></div>
                    <div class="leg-pill-badge">
                      <span class="leg-type-badge">{{ getLegTypeName(leg.route_type || '') }}</span>
                      <span class="leg-desc-text">{{ getLegDesc(leg) }}</span>
                    </div>
                  </div>

                  <!-- 最后一个终点节点 -->
                  <div class="step-point-node" v-if="legIdx === day.legs.length - 1">
                    <div class="point-badge is-hotel"><HomeOutlined /></div>
                    <span class="point-name">{{ leg.to_name }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 每日景点动线与图文介绍 -->
            <div class="timeline-attractions" v-if="day.attractions && day.attractions.length > 0">
              <div class="sub-sec-header">
                <span class="sub-sec-title"><CameraOutlined class="sub-title-icon" /> 游览景点详情与门票</span>
                <span class="sub-sec-hint">（点击卡片可在右上方地图快速定位）</span>
              </div>

              <div class="attractions-grid">
                <div
                  v-for="(attr, attrIdx) in day.attractions"
                  :key="attrIdx"
                  class="attraction-card"
                  @click="focusOnMap(attr)"
                  title="点击在地图中定位该景点"
                >
                  <!-- 景点图片 -->
                  <div class="attr-image-wrap">
                    <img
                      :src="attr.image_url || defaultAttractionImage"
                      :alt="attr.name"
                      class="attr-img"
                      loading="lazy"
                      @error="handleImageError"
                    />
                    <div class="attr-order-badge">{{ attrIdx + 1 }}</div>
                    <div class="attr-price-tag">
                      {{ attr.ticket_price ? `¥${attr.ticket_price}` : '免费' }}
                    </div>
                  </div>

                  <!-- 景点详情 -->
                  <div class="attr-info">
                    <div class="attr-header-row">
                      <h4 class="attr-name">{{ attr.name }}</h4>
                      <span class="attr-duration" v-if="attr.visit_duration">
                        <ClockCircleOutlined class="attr-meta-icon" /> {{ attr.visit_duration }} 分钟
                      </span>
                    </div>
                    <p class="attr-desc">{{ attr.description || '知名景点，推荐细细游览感受当地风情。' }}</p>
                    <div class="attr-address" v-if="attr.address">
                      <EnvironmentOutlined class="addr-icon" />
                      <span class="addr-text">{{ attr.address }}</span>
                    </div>
                    <div class="attr-address" v-if="attr.open_time" :title="attr.open_time">
                      <ClockCircleOutlined class="addr-icon" />
                      <span class="addr-text">{{ attr.open_time }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 每日餐饮推荐 -->
            <div class="meals-section" v-if="day.meals && day.meals.length > 0">
              <div class="sub-sec-header">
                <span class="sub-sec-title"><CoffeeOutlined class="sub-title-icon" /> 特色餐饮推荐</span>
              </div>
              <div class="meals-grid">
                <div
                  v-for="(meal, mealIdx) in sortedMeals(day.meals)"
                  :key="mealIdx"
                  class="meal-card"
                >
                  <div class="meal-type-tag" :class="meal.type">
                    {{ getMealTypeName(meal.type) }}
                  </div>
                  <div class="meal-details">
                    <div class="meal-name">{{ meal.name }}</div>
                    <div class="meal-cost" v-if="meal.estimated_cost">
                      人均约 ¥{{ meal.estimated_cost }}
                    </div>
                    <div class="meal-address" v-if="meal.address">{{ meal.address }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { message } from 'ant-design-vue'
import {
  ArrowLeftOutlined,
  EnvironmentOutlined,
  CopyOutlined,
  FileMarkdownOutlined,
  PictureOutlined,
  PrinterOutlined,
  ExportOutlined,
  DownOutlined,
  BulbOutlined,
  CloudOutlined,
  WalletOutlined,
  TagOutlined,
  HomeOutlined,
  CoffeeOutlined,
  CarOutlined,
  CompassOutlined,
  CalendarOutlined,
  NodeIndexOutlined,
  CameraOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons-vue'
import AMapLoader from '@amap/amap-jsapi-loader'
import html2canvas from 'html2canvas'
import TravelBackground from '../components/TravelBackground.vue'
import type { TripPlan, Attraction, RouteLeg, Meal } from '../types'

const props = defineProps<{
  planData?: TripPlan | null
}>()

const emit = defineEmits<{
  (e: 'backToHome'): void
}>()

// 默认兜底示例数据
const defaultPlan: TripPlan = {
  city: '北京',
  start_date: '2026-08-20',
  end_date: '2026-08-22',
  days: [],
  overall_suggestions: '尽情享受旅途！',
  budget: {
    total_attractions: 0,
    total_hotels: 0,
    total_meals: 0,
    total_transportation: 0,
    total: 0
  }
}

// 获取当前 plan
const storedPlanStr = sessionStorage.getItem('current_trip_plan')
const tripPlan = ref<TripPlan>(
  props.planData || (storedPlanStr ? JSON.parse(storedPlanStr) : defaultPlan)
)

const defaultAttractionImage = 'https://images.unsplash.com/photo-1508804185872-d7be30e9a0ec?w=600&auto=format&fit=crop&q=80'

const handleImageError = (e: Event) => {
  const target = e.target as HTMLImageElement
  if (target && target.src !== defaultAttractionImage) {
    target.src = defaultAttractionImage
  }
}

// 高德地图实例与标记
let mapInstance: any = null
let markers: any[] = []
let polylines: any[] = []
let infoWindowInstance: any = null
const mapLoading = ref(true)
const currentMapDay = ref(-1) // -1 表示显示全部天数

const getMealTypeName = (type: string) => {
  switch (type) {
    case 'breakfast': return '早餐'
    case 'lunch': return '午餐'
    case 'dinner': return '晚餐'
    case 'snack': return '特色小吃'
    default: return '餐饮'
  }
}

// 动线段交通方式类型文本
const getLegTypeName = (routeType: string) => {
  if (!routeType) return '公共交通'
  if (routeType === 'walking' || routeType.includes('步行')) return '步行'
  if (routeType === 'transit' || routeType.includes('公交') || routeType.includes('地铁') || routeType.includes('公共交通')) return '公共交通'
  if (routeType === 'driving' || routeType.includes('打车') || routeType.includes('专线') || routeType.includes('驾')) return '打车/驾车'
  return '路程'
}

// 动线段描述（cost 存在且 >0 时追加估算费用）
const getLegDesc = (leg: RouteLeg) => {
  let text = leg.description || ''
  if (leg.cost && leg.cost > 0) {
    text += ` · 约¥${leg.cost}`
  }
  return text
}

// 餐饮排序：早餐 → 午餐 → 晚餐 → 小吃，其余类型排最后
const mealTypeOrder: Record<string, number> = { breakfast: 0, lunch: 1, dinner: 2, snack: 3 }
const sortedMeals = (meals: Meal[] | undefined): Meal[] => {
  if (!meals) return []
  return [...meals].sort((a, b) => {
    const ia = mealTypeOrder[a.type] ?? 99
    const ib = mealTypeOrder[b.type] ?? 99
    return ia - ib
  })
}

// 初始化高德地图
const initAMap = async () => {
  try {
    mapLoading.value = true

    window._AMapSecurityConfig = {
      securityJsCode: (import.meta as any).env.VITE_AMAP_SECURITY_CODE || '',
    }

    const AMap = await AMapLoader.load({
      key: (import.meta as any).env.VITE_AMAP_KEY || '113f72f90ff84fc1daed58345ac00d8d',
      version: '2.0',
      plugins: ['AMap.Scale', 'AMap.ToolBar', 'AMap.Polyline', 'AMap.Marker', 'AMap.Geocoder'],
    })

    window.AMap = AMap

    mapInstance = new AMap.Map('amap-container', {
      zoom: 11,
      viewMode: '2D',
      mapStyle: 'amap://styles/normal',
    })

    if (tripPlan.value.city) {
      mapInstance.setCity(tripPlan.value.city)
    }

    mapInstance.addControl(new AMap.Scale())
    mapInstance.addControl(new AMap.ToolBar({ position: 'RB' }))
    infoWindowInstance = new AMap.InfoWindow({ offset: new AMap.Pixel(0, -30) })

    await renderMarkersAndRoutes(currentMapDay.value)
  } catch (error: any) {
    console.error('高德地图加载异常:', error)
  } finally {
    mapLoading.value = false
  }
}

// 快速安全的地理编码 Promise
const geocodeWithTimeout = (geocoder: any, address: string): Promise<any> => {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(null), 800)
    try {
      geocoder.getLocation(address, (status: string, result: any) => {
        clearTimeout(timer)
        if (status === 'complete' && result.geocodes && result.geocodes.length) {
          resolve(result.geocodes[0].location)
        } else {
          resolve(null)
        }
      })
    } catch {
      clearTimeout(timer)
      resolve(null)
    }
  })
}

// 渲染 Marker 与轨迹
const renderMarkersAndRoutes = async (dayFilter: number) => {
  if (!mapInstance || !window.AMap) return

  if (markers.length > 0) {
    mapInstance.remove(markers)
    markers = []
  }
  if (polylines.length > 0) {
    mapInstance.remove(polylines)
    polylines = []
  }

  const allPoints: any[] = []
  const daysToRender = dayFilter === -1
    ? (tripPlan.value.days || [])
    : (tripPlan.value.days || []).filter((_, idx) => idx === dayFilter)

  // 经典自然天数颜色（典雅、清晰）
  const dayColors = ['#1d4ed8', '#059669', '#d97706', '#7c3aed', '#0284c7', '#e11d48']
  const geocoder = new window.AMap.Geocoder({ city: tripPlan.value.city })

  for (let d = 0; d < daysToRender.length; d++) {
    const day = daysToRender[d]
    const color = dayColors[day.day_index % dayColors.length]
    const dayCoords: any[] = []

    // 1. 如果当日有酒店位置，先加入酒店 Marker 作为起点
    if (day.hotel) {
      let hLng = day.hotel.location?.longitude
      let hLat = day.hotel.location?.latitude

      if ((!hLng || !hLat || hLng === 0) && day.hotel.name) {
        try {
          const hGeo: any = await geocodeWithTimeout(geocoder, `${tripPlan.value.city}${day.hotel.name}`)
          if (hGeo) {
            hLng = hGeo.lng
            hLat = hGeo.lat
            if (!day.hotel.location) day.hotel.location = {}
            day.hotel.location.longitude = hLng
            day.hotel.location.latitude = hLat
          }
        } catch {}
      }

      if (hLng && hLat && hLng !== 0) {
        const hotelPos = new window.AMap.LngLat(hLng, hLat)
        dayCoords.push(hotelPos)
        allPoints.push(hotelPos)

        const hotelMarkerContent = document.createElement('div')
        hotelMarkerContent.className = 'clean-hotel-marker'
        hotelMarkerContent.innerHTML = `<span class="hotel-marker-icon">住</span>`

        const hotelMarker = new window.AMap.Marker({
          position: hotelPos,
          content: hotelMarkerContent,
          offset: new window.AMap.Pixel(-14, -14),
          title: `[住宿] ${day.hotel.name}`,
        })

        hotelMarker.on('click', () => {
          openHotelInfoWindow(day.hotel, hotelPos)
        })

        markers.push(hotelMarker)
        mapInstance.add(hotelMarker)
      }
    }

    // 2. 依次渲染当日景点 Marker
    for (let i = 0; i < (day.attractions || []).length; i++) {
      const attr = day.attractions[i]
      let lng = attr.location?.longitude
      let lat = attr.location?.latitude

      if (!lng || !lat || lng === 0) {
        try {
          const queryAddr = `${tripPlan.value.city}${attr.name}`
          const geoRes: any = await geocodeWithTimeout(geocoder, queryAddr)
          if (geoRes) {
            lng = geoRes.lng
            lat = geoRes.lat
            if (!attr.location) attr.location = {}
            attr.location.longitude = lng
            attr.location.latitude = lat
          }
        } catch (e) {
          console.warn('Geocoding fallback failed for', attr.name)
        }
      }

      if (lng && lat && lng !== 0) {
        const position = new window.AMap.LngLat(lng, lat)
        dayCoords.push(position)
        allPoints.push(position)

        // 自定义 Marker 内容
        const markerContent = document.createElement('div')
        markerContent.className = 'clean-map-marker'
        markerContent.style.backgroundColor = color
        markerContent.innerHTML = `<span class="marker-idx">${i + 1}</span>`

        const marker = new window.AMap.Marker({
          position,
          content: markerContent,
          offset: new window.AMap.Pixel(-13, -13),
          title: attr.name,
        })

        marker.on('click', () => {
          openInfoWindow(attr, position)
        })

        markers.push(marker)
        mapInstance.add(marker)
      }
    }

    // 3. 若有起点酒店，在游览结束后路线闭环回到酒店
    if (day.hotel && day.hotel.location && day.hotel.location.longitude !== 0 && dayCoords.length > 1) {
      const returnPos = new window.AMap.LngLat(day.hotel.location.longitude, day.hotel.location.latitude)
      dayCoords.push(returnPos)
    }

    // 绘制每日景点之间的连线 Polyline
    if (dayCoords.length > 1) {
      const polyline = new window.AMap.Polyline({
        path: dayCoords,
        strokeColor: color,
        strokeWeight: 4,
        strokeOpacity: 0.85,
        strokeStyle: 'solid',
        lineJoin: 'round',
        showDir: true,
      })
      polylines.push(polyline)
      mapInstance.add(polyline)
    }
  }

  if (markers.length > 0) {
    mapInstance.setFitView(markers, false, [40, 40, 40, 40])
  } else if (tripPlan.value.city) {
    mapInstance.setCity(tripPlan.value.city)
  }
}

// 弹出景点信息窗体
const openInfoWindow = (attr: Attraction, position: any) => {
  if (!mapInstance || !infoWindowInstance) return

  const content = `
    <div style="padding: 10px 12px; max-width: 260px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
      <div style="font-weight: 700; font-size: 14px; margin-bottom: 6px; color: #0f172a;">${attr.name}</div>
      <div style="font-size: 12px; color: #475569; margin-bottom: 3px;">建议游玩: ${attr.visit_duration || 120} 分钟</div>
      <div style="font-size: 12px; color: #059669; font-weight: 600; margin-bottom: 6px;">门票: ${attr.ticket_price ? '¥' + attr.ticket_price : '免费'}</div>
      <div style="font-size: 12px; color: #334155; line-height: 1.5;">${attr.description || ''}</div>
    </div>
  `
  infoWindowInstance.setContent(content)
  infoWindowInstance.open(mapInstance, position)
}

// 弹出酒店信息窗体
const openHotelInfoWindow = (hotel: any, position: any) => {
  if (!mapInstance || !infoWindowInstance) return

  const content = `
    <div style="padding: 10px 12px; max-width: 260px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
      <div style="font-weight: 700; font-size: 14px; margin-bottom: 6px; color: #92400e;">${hotel.name}</div>
      <div style="font-size: 12px; color: #475569; margin-bottom: 4px;">地址: ${hotel.address || '优质核心地段'}</div>
      <div style="font-size: 12px; color: #d97706; font-weight: 600; margin-bottom: 4px;">预估费用: 约 ¥${hotel.estimated_cost || 350}/晚</div>
      <div style="font-size: 11px; color: #64748b;">今日旅行出发与返程入住地</div>
    </div>
  `
  infoWindowInstance.setContent(content)
  infoWindowInstance.open(mapInstance, position)
}

// 点击卡片聚焦地图景点
const focusOnMap = (attr: Attraction) => {
  if (!mapInstance || !window.AMap) return
  if (attr.location?.longitude && attr.location?.latitude && attr.location.longitude !== 0) {
    const pos = new window.AMap.LngLat(attr.location.longitude, attr.location.latitude)
    mapInstance.panTo(pos)
    mapInstance.setZoom(14)
    openInfoWindow(attr, pos)
  } else {
    const geocoder = new window.AMap.Geocoder({ city: tripPlan.value.city })
    geocoder.getLocation(`${tripPlan.value.city}${attr.name}`, (status: string, result: any) => {
      if (status === 'complete' && result.geocodes && result.geocodes.length) {
        const pos = result.geocodes[0].location
        mapInstance.panTo(pos)
        mapInstance.setZoom(14)
        openInfoWindow(attr, pos)
      }
    })
  }
}

// 点击卡片聚焦地图酒店
const focusOnHotel = (hotel: any) => {
  if (!mapInstance || !window.AMap || !hotel) return
  if (hotel.location?.longitude && hotel.location?.latitude && hotel.location.longitude !== 0) {
    const pos = new window.AMap.LngLat(hotel.location.longitude, hotel.location.latitude)
    mapInstance.panTo(pos)
    mapInstance.setZoom(14)
    openHotelInfoWindow(hotel, pos)
  } else if (hotel.address || hotel.name) {
    const geocoder = new window.AMap.Geocoder({ city: tripPlan.value.city })
    geocoder.getLocation(`${tripPlan.value.city}${hotel.name}`, (status: string, result: any) => {
      if (status === 'complete' && result.geocodes && result.geocodes.length) {
        const pos = result.geocodes[0].location
        mapInstance.panTo(pos)
        mapInstance.setZoom(14)
        openHotelInfoWindow(hotel, pos)
      }
    })
  }
}

// 切换天数路线过滤
const switchMapDay = (dayIdx: number) => {
  currentMapDay.value = dayIdx
  renderMarkersAndRoutes(dayIdx)
}

// 返回首页
const handleBackToHome = () => {
  emit('backToHome')
}

// 复制纯文本行程
const copyPlanToClipboard = async () => {
  const plan = tripPlan.value
  let text = `【${plan.city}旅行规划方案】\n`
  text += `出行日期：${plan.start_date} ~ ${plan.end_date} (共 ${plan.days?.length || 0} 天)\n`
  text += `出行建议：${plan.overall_suggestions || '无'}\n\n`

  if (plan.budget) {
    text += `预算明细：门票 ¥${plan.budget.total_attractions} | 酒店 ¥${plan.budget.total_hotels} | 餐饮 ¥${plan.budget.total_meals} | 交通 ¥${plan.budget.total_transportation} | 总计 ¥${plan.budget.total}\n\n`
  }

  (plan.days || []).forEach((d) => {
    text += `=== Day ${d.day_index + 1} (${d.date}) ===\n`
    text += `概要：${d.description || ''}\n`
    if (d.hotel) text += `住宿：${d.hotel.name} (地址: ${d.hotel.address || '市区'})\n`
    if (d.legs && d.legs.length > 0) {
      text += `动线明细：\n`
      d.legs.forEach(leg => {
        text += `  - ${leg.from_name} -> ${leg.to_name}: ${leg.description}\n`
      })
    }
    text += `景点：${(d.attractions || []).map(a => a.name).join(' -> ')}\n`
    text += `美食：${(d.meals || []).map(m => `${getMealTypeName(m.type)}：${m.name}`).join('、')}\n\n`
  })

  try {
    await navigator.clipboard.writeText(text)
    message.success('行程内容已成功复制到剪贴板！')
  } catch (e) {
    message.error('复制失败，请手动复制')
  }
}

// 导出菜单处理
const handleExportMenu = ({ key }: { key: string }) => {
  if (key === 'markdown') {
    exportMarkdown()
  } else if (key === 'image') {
    exportImage()
  } else if (key === 'print') {
    window.print()
  }
}

// 导出为 Markdown 文件
const exportMarkdown = () => {
  const plan = tripPlan.value
  let md = `# ${plan.city}旅行规划方案\n\n`
  md += `**出行日期**：${plan.start_date} 至 ${plan.end_date} (共 ${plan.days?.length || 0} 天)\n\n`
  md += `### 综合出行建议\n${plan.overall_suggestions || '祝您旅途愉快！'}\n\n`

  if (plan.budget) {
    md += `### 全程预算明细\n`
    md += `- 景点门票总计：¥${plan.budget.total_attractions}\n`
    md += `- 酒店住宿总计：¥${plan.budget.total_hotels}\n`
    md += `- 餐饮美食总计：¥${plan.budget.total_meals}\n`
    md += `- 市内交通总计：¥${plan.budget.total_transportation}\n`
    md += `- **预估总费用：¥${plan.budget.total}**\n\n`
  }

  md += `---\n\n## 每日详细行程\n\n`
  ;(plan.days || []).forEach((d) => {
    md += `### Day ${d.day_index + 1} (${d.date})\n`
    md += `**行程概述**：${d.description || ''}\n\n`
    if (d.hotel) {
      md += `**住宿推荐**：${d.hotel.name} (预估 ¥${d.hotel.estimated_cost || 300}/晚)\n\n`
    }
    md += `**景点游览**：\n`
    ;(d.attractions || []).forEach((a, i) => {
      md += `${i + 1}. **${a.name}** | 门票: ${a.ticket_price ? '¥' + a.ticket_price : '免费'} | 建议游玩: ${a.visit_duration || 120}分钟 | 地址: ${a.address || '市内'}\n`
    })
    md += `\n**美食推荐**：\n`
    ;(d.meals || []).forEach((m) => {
      md += `- ${getMealTypeName(m.type)}：**${m.name}** (人均约 ¥${m.estimated_cost || 50})\n`
    })
    md += `\n---\n\n`
  })

  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8;' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `${plan.city}_旅行计划.md`
  link.click()
  message.success('Markdown 文件已成功导出！')
}

// 导出长图
const exportImage = async () => {
  const elem = document.getElementById('printable-area')
  if (!elem) return
  message.loading({ content: '正在生成高清长图，请稍候...', key: 'exportImg' })
  try {
    const canvas = await html2canvas(elem, {
      useCORS: true,
      scale: 2,
      backgroundColor: '#f8fafc',
    })
    const imgData = canvas.toDataURL('image/png')
    const link = document.createElement('a')
    link.href = imgData
    link.download = `${tripPlan.value.city}_旅行计划长图.png`
    link.click()
    message.success({ content: '长图导出成功！', key: 'exportImg' })
  } catch (err: any) {
    message.error({ content: '导出图片失败: ' + err.message, key: 'exportImg' })
  }
}

onMounted(() => {
  nextTick(() => {
    initAMap()
  })
})

onUnmounted(() => {
  if (mapInstance) {
    mapInstance.destroy()
  }
})
</script>

<style scoped>
.result-container {
  position: relative;
  min-height: 100vh;
  background-color: #f8fafc;
  color: #0f172a;
  padding-bottom: 80px;
  overflow-x: hidden;
}

/* 顶部导航栏 */
.top-nav-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 28px;
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.nav-left {
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 0;
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: #334155;
  padding: 6px 14px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  transition: all 0.15s ease;
}

.back-btn:hover {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #1e40af;
}

.trip-main-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex-wrap: wrap;
}

.city-badge {
  font-size: 18px;
  font-weight: 800;
  color: #0f172a;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.badge-icon {
  font-size: 16px;
  color: #1e40af;
}

.days-badge {
  font-size: 13px;
  color: #1e40af;
  background: #eff6ff;
  border: 1px solid #dbeafe;
  padding: 3px 10px;
  border-radius: 6px;
}

.nav-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.copy-text-btn {
  display: inline-flex;
  align-items: center;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  color: #475569;
  padding: 7px 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.copy-text-btn:hover {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #1e40af;
}

.export-dropdown-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%);
  border: none;
  color: #ffffff;
  padding: 7px 16px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 2px 8px rgba(30, 58, 138, 0.25);
}

.export-dropdown-btn:hover {
  background: linear-gradient(135deg, #172554 0%, #1e3a8a 100%);
}

.arrow-down {
  font-size: 10px;
}

/* 主内容区 */
.result-body {
  position: relative;
  z-index: 1;
  max-width: 1200px;
  margin: 24px auto 0;
  padding: 0 20px;
}

/* 看板网格布局 */
.dashboard-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 28px;
}

@media (max-width: 900px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
  }
}

.summary-column {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 通用卡片容器 */
.clean-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
  min-width: 0;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.panel-icon {
  font-size: 16px;
  color: #1e40af;
}

.panel-title {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
}

.suggestions-text {
  font-size: 13px;
  line-height: 1.7;
  color: #334155;
  white-space: pre-line;
  word-break: break-word;
  background: #f8fafc;
  border-left: 3px solid #2563eb;
  padding: 12px 14px;
  border-radius: 0 8px 8px 0;
}

/* 天气卡片 */
.weather-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: 8px;
}

.weather-item {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 8px 10px;
  text-align: center;
}

.w-date {
  font-size: 11px;
  color: #64748b;
}

.w-cond {
  font-size: 13px;
  font-weight: 700;
  color: #1e40af;
  margin: 2px 0;
}

.w-temp {
  font-size: 12px;
  color: #334155;
}

.w-wind {
  font-size: 11px;
  color: #94a3b8;
}

/* 预算面板 */
.budget-subtitle {
  font-size: 11px;
  color: #64748b;
  margin-left: auto;
}

.budget-grid-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 14px;
}

.budget-card-mini {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 12px;
  transition: all 0.15s ease;
}

.budget-card-mini:hover {
  border-color: #cbd5e1;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
}

.b-icon {
  font-size: 16px;
  border-radius: 8px;
  width: 34px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.budget-card-mini.is-attractions .b-icon {
  background: #ecfdf5;
  color: #059669;
  border: 1px solid #a7f3d0;
}

.budget-card-mini.is-hotels .b-icon {
  background: #fffbeb;
  color: #d97706;
  border: 1px solid #fde68a;
}

.budget-card-mini.is-meals .b-icon {
  background: #fff7ed;
  color: #ea580c;
  border: 1px solid #fed7aa;
}

.budget-card-mini.is-transport .b-icon {
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #bfdbfe;
}

.b-info {
  min-width: 0;
}

.b-label {
  font-size: 11px;
  color: #64748b;
}

.b-value {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}

.budget-total-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: linear-gradient(135deg, #f8fafc 0%, #eff6ff 100%);
  border: 1px solid #bfdbfe;
  border-radius: 10px;
  padding: 12px 16px;
  flex-wrap: wrap;
  gap: 8px;
}

.total-left {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}

.total-label {
  font-size: 13px;
  font-weight: 700;
  color: #1e3a8a;
}

.total-hint {
  font-size: 11px;
  color: #64748b;
  margin-left: 4px;
}

.total-amount {
  display: flex;
  align-items: baseline;
  color: #1d4ed8;
}

.currency {
  font-size: 15px;
  font-weight: 700;
  margin-right: 2px;
}

.amount-num {
  font-size: 22px;
  font-weight: 800;
}

/* 地图面板 */
.map-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 380px;
}

.map-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 8px;
}

.map-title-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
}

.map-day-tabs {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.day-tab-btn {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: #475569;
  font-size: 12px;
  padding: 3px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.day-tab-btn:hover {
  background: #f1f5f9;
}

.day-tab-btn.active {
  background: #1e3a8a;
  border-color: #1e3a8a;
  color: #ffffff;
  font-weight: 600;
}

.map-container-wrapper {
  position: relative;
  flex: 1;
  min-height: 300px;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid #e2e8f0;
}

.amap-instance {
  width: 100%;
  height: 100%;
  min-height: 300px;
}

.map-loading-mask {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.8);
  z-index: 10;
}

/* 每日日程部分 */
.days-itinerary-section {
  margin-top: 12px;
}

.section-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 18px;
}

.sec-icon {
  font-size: 18px;
  color: #1e40af;
}

.sec-title {
  font-size: 18px;
  font-weight: 800;
  color: #0f172a;
  margin: 0;
}

.days-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.day-card {
  padding: 24px;
}

.day-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 14px;
}

.day-badge-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.day-index-badge {
  background: #1e3a8a;
  color: #ffffff;
  font-weight: 700;
  font-size: 13px;
  padding: 4px 10px;
  border-radius: 6px;
  white-space: nowrap;
}

.day-date-text {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}

.day-hotel-brief {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  font-size: 12px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  padding: 4px 10px;
  border-radius: 6px;
}

.hotel-name {
  font-weight: 600;
  color: #92400e;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hotel-price {
  color: #b45309;
  font-weight: 500;
  white-space: nowrap;
}

.day-desc-box {
  background: #f8fafc;
  border-left: 3px solid #1e40af;
  padding: 10px 14px;
  border-radius: 0 6px 6px 0;
  font-size: 13px;
  line-height: 1.6;
  color: #334155;
  margin-bottom: 20px;
  word-break: break-word;
}

.sub-sec-header {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 12px;
}

.sub-sec-title {
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.sub-title-icon {
  font-size: 14px;
  color: #1e40af;
}

.sub-sec-hint {
  font-size: 11px;
  color: #94a3b8;
}

/* 景点卡片网格 */
.attractions-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
  margin-bottom: 20px;
}

.attraction-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
}

.attraction-card:hover {
  border-color: #3b82f6;
  box-shadow: 0 4px 14px rgba(59, 130, 246, 0.12);
  transform: translateY(-2px);
}

.attr-image-wrap {
  position: relative;
  height: 140px;
  width: 100%;
  overflow: hidden;
  background: #f1f5f9;
}

.attr-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s ease;
}

.attraction-card:hover .attr-img {
  transform: scale(1.04);
}

.attr-order-badge {
  position: absolute;
  top: 8px;
  left: 8px;
  width: 22px;
  height: 22px;
  background: #1e3a8a;
  color: #ffffff;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 12px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.attr-price-tag {
  position: absolute;
  bottom: 8px;
  right: 8px;
  background: rgba(15, 23, 42, 0.75);
  color: #ffffff;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}

.attr-info {
  padding: 12px 14px;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.attr-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
  gap: 6px;
}

.attr-name {
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attr-duration {
  font-size: 11px;
  color: #1d4ed8;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}

.attr-desc {
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
  margin-bottom: 6px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-word;
}

.attr-address {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #94a3b8;
  margin-top: auto;
}

.addr-icon {
  flex-shrink: 0;
}

.addr-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 餐饮卡片网格 */
.meals-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 10px;
}

.meal-card {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 12px;
}

.meal-type-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 6px;
  border-radius: 4px;
  background: #e2e8f0;
  color: #475569;
  white-space: nowrap;
  flex-shrink: 0;
}

.meal-type-tag.breakfast {
  background: #fefce8;
  color: #854d0e;
  border: 1px solid #fef08a;
}

.meal-type-tag.lunch {
  background: #fff7ed;
  color: #9a3412;
  border: 1px solid #fed7aa;
}

.meal-type-tag.dinner {
  background: #eef2ff;
  color: #3730a3;
  border: 1px solid #c7d2fe;
}

.meal-type-tag.snack {
  background: #f0fdf4;
  color: #166534;
  border: 1px solid #bbf7d0;
}

.meal-details {
  flex: 1;
  min-width: 0;
}

.meal-name {
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meal-cost {
  font-size: 11px;
  color: #b45309;
  font-weight: 600;
  margin: 1px 0;
}

.meal-address {
  font-size: 11px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 打印样式支持 */
@media print {
  .travel-bg-container,
  .no-print,
  .top-nav-bar .nav-right,
  .back-btn {
    display: none !important;
  }
  body, .result-container {
    background: #ffffff !important;
    color: #000000 !important;
  }
  .clean-card {
    border: 1px solid #cccccc !important;
    box-shadow: none !important;
    page-break-inside: avoid;
  }
}

/* 住宿卡片样式 */
.day-hotel-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 10px;
  padding: 12px 16px;
  margin-bottom: 16px;
  cursor: pointer;
  transition: all 0.2s ease;
  flex-wrap: wrap;
  gap: 10px;
}

.day-hotel-card:hover {
  background: #fef3c7;
  border-color: #f59e0b;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(245, 158, 11, 0.15);
}

.hotel-card-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.hotel-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.hotel-pill {
  font-size: 11px;
  font-weight: 600;
  background: #fef3c7;
  color: #92400e;
  border: 1px solid #fcd34d;
  padding: 2px 8px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.hotel-title {
  font-size: 14px;
  font-weight: 700;
  color: #78350f;
}

.hotel-addr-row {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #92400e;
}

.hotel-card-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.hotel-cost-val {
  font-size: 14px;
  font-weight: 700;
  color: #b45309;
}

.cost-unit {
  font-size: 11px;
  color: #92400e;
  font-weight: normal;
}

.hotel-loc-btn {
  font-size: 12px;
  color: #b45309;
  background: #ffffff;
  border: 1px solid #fcd34d;
  padding: 3px 8px;
  border-radius: 6px;
  font-weight: 600;
}

/* 每日动线与交通明细 */
.transit-flow-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 20px;
}

.transit-timeline-list {
  display: flex;
  flex-direction: column;
  gap: 0;
  margin-top: 10px;
}

.transit-step-item {
  display: flex;
  flex-direction: column;
}

.step-point-node {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
}

.point-badge {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #1e3a8a;
  color: #ffffff;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.point-badge.is-hotel {
  background: #d97706;
}

.point-name {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.step-route-leg {
  display: flex;
  align-items: center;
  margin-left: 11px;
  padding: 6px 0 6px 18px;
  position: relative;
}

.leg-dash-line {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 2px;
  border-left: 2px dashed #93c5fd;
}

.leg-pill-badge {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 20px;
  padding: 3px 12px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.leg-type-badge {
  font-size: 11px;
  font-weight: 600;
  color: #1d4ed8;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  padding: 1px 6px;
  border-radius: 4px;
}

.leg-desc-text {
  font-size: 11px;
  font-weight: 600;
  color: #334155;
}
</style>

<!-- 全局覆盖高德地图标记样式 -->
<style>
.clean-map-marker {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: 2px solid #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25);
  cursor: pointer;
  transition: transform 0.15s ease;
}

.clean-map-marker:hover {
  transform: scale(1.18);
}

.marker-idx {
  color: #ffffff;
  font-size: 12px;
  font-weight: 700;
}

.clean-hotel-marker {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #d97706;
  border: 2px solid #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 8px rgba(217, 119, 6, 0.4);
  cursor: pointer;
  transition: transform 0.15s ease;
  font-size: 11px;
  font-weight: 700;
  color: #ffffff;
}

.clean-hotel-marker:hover {
  transform: scale(1.2);
}
</style>
