<template>
  <div class="home-container">
    <div class="content-wrapper">
      <!-- 页面头部 Hero 区 -->
      <header class="hero-section">
        <div class="hero-top-row">
          <div class="brand-pill">
            <CompassOutlined class="pill-icon" />
            <span class="pill-text">AI 多智能体旅行规划系统</span>
          </div>
          <button
            type="button"
            class="api-settings-btn"
            @click="isApiSettingsOpen = true"
            title="配置自定义 OpenAI/DeepSeek API Key"
          >
            <SettingOutlined class="btn-icon" />
            <span class="btn-text">API 设置</span>
            <span v-if="hasCustomKey" class="status-dot active" title="当前已启用自定义 API Key"></span>
          </button>
        </div>

        <h1 class="hero-title">
          智能规划您的下一次旅程
        </h1>
        <p class="hero-subtitle">
          融合实时气象预报、高德地图真实 POI 数据与 LangGraph 多智能体协同，一键生成结构化、高可行性的定制攻略
        </p>

        <!-- 特色亮点微标签 (简洁 Outline 图标) -->
        <div class="feature-tags">
          <span class="feature-tag">
            <CloudOutlined class="ft-icon" /> 实时气象研判
          </span>
          <span class="feature-tag">
            <EnvironmentOutlined class="ft-icon" /> 高德真实 POI
          </span>
          <span class="feature-tag">
            <NodeIndexOutlined class="ft-icon" /> 智能聚类动线
          </span>
          <span class="feature-tag">
            <WalletOutlined class="ft-icon" /> 细分预算精算
          </span>
        </div>
      </header>

      <!-- 主表单卡片 -->
      <div class="main-form-card">
        <a-form
          :model="formData"
          layout="vertical"
          @finish="handleStartPlanning"
          class="planning-form"
        >
          <!-- 模块 1：目的地与日期 -->
          <section class="form-section">
            <div class="section-title-row">
              <span class="section-badge">1</span>
              <h2 class="section-title">目的地与出行日期</h2>
            </div>

            <!-- 热门目的地快捷选择 -->
            <div class="quick-cities-bar">
              <span class="quick-title">热门城市：</span>
              <div class="city-chips-group">
                <button
                  type="button"
                  v-for="city in popularCities"
                  :key="city"
                  class="city-chip"
                  :class="{ active: formData.city === city }"
                  @click="formData.city = city"
                >
                  {{ city }}
                </button>
              </div>
            </div>

            <a-row :gutter="[16, 16]">
              <a-col :xs="24" :sm="12" :md="9">
                <a-form-item label="目的地城市" :required="true">
                  <a-input
                    v-model:value="formData.city"
                    placeholder="请输入城市名（如：北京 / 成都 / 杭州）"
                    size="large"
                    allow-clear
                    class="clean-input"
                  >
                    <template #prefix>
                      <EnvironmentOutlined class="input-icon" />
                    </template>
                  </a-input>
                </a-form-item>
              </a-col>

              <a-col :xs="24" :sm="12" :md="10">
                <a-form-item label="出行日期范围" :required="true">
                  <a-range-picker
                    v-model:value="dateRange"
                    style="width: 100%"
                    size="large"
                    class="clean-input"
                    :disabled-date="disabledPastDates"
                    @change="onDateRangeChange"
                  />
                </a-form-item>
              </a-col>

              <a-col :xs="24" :sm="24" :md="5">
                <a-form-item label="行程天数">
                  <div class="days-pill-display">
                    <span class="days-number">{{ formData.travel_days || 3 }}</span>
                    <span class="days-unit">天行程</span>
                  </div>
                </a-form-item>
              </a-col>
            </a-row>
          </section>

          <div class="section-divider"></div>

          <!-- 模块 2：出行偏好与标准 -->
          <section class="form-section">
            <div class="section-title-row">
              <span class="section-badge">2</span>
              <h2 class="section-title">出行偏好与标准</h2>
            </div>

            <a-row :gutter="[16, 16]">
              <a-col :xs="24" :md="12">
                <a-form-item name="transportation" label="市内交通方式">
                  <a-select
                    v-model:value="formData.transportation"
                    size="large"
                    class="clean-select"
                  >
                    <a-select-option value="公共交通">公共交通 (地铁 / 公交)</a-select-option>
                    <a-select-option value="打车/网约车">网约车 / 出租车接驳</a-select-option>
                    <a-select-option value="自驾出行">自驾出行 / 租车</a-select-option>
                    <a-select-option value="步行与慢行">徒步漫游 (Citywalk)</a-select-option>
                    <a-select-option value="混合出行">灵活混合出行</a-select-option>
                  </a-select>
                </a-form-item>
              </a-col>

              <a-col :xs="24" :md="12">
                <a-form-item name="accommodation" label="住宿标准">
                  <a-select
                    v-model:value="formData.accommodation"
                    size="large"
                    class="clean-select"
                  >
                    <a-select-option value="经济型酒店">经济实惠型 (约 200-350元/晚)</a-select-option>
                    <a-select-option value="舒适型酒店">舒适商务型 (约 350-600元/晚)</a-select-option>
                    <a-select-option value="高档豪华型">高档豪华型 (约 600-1200元/晚)</a-select-option>
                    <a-select-option value="特色民宿客栈">特色民宿 / 风情客栈</a-select-option>
                  </a-select>
                </a-form-item>
              </a-col>
            </a-row>

            <!-- 游玩风格标签多选 (简洁雅致 Text Chips) -->
            <div class="preferences-container">
              <label class="field-label">游玩主题偏好（可多选）：</label>
              <div class="preference-chips-grid">
                <button
                  type="button"
                  v-for="tag in availableTags"
                  :key="tag"
                  class="preference-chip"
                  :class="{ selected: selectedPreferences.includes(tag) }"
                  @click="togglePreference(tag)"
                >
                  <CheckOutlined v-if="selectedPreferences.includes(tag)" class="chip-check-icon" />
                  <span class="chip-text">{{ tag }}</span>
                </button>
              </div>
            </div>
          </section>

          <div class="section-divider"></div>

          <!-- 模块 3：个性化诉求与快捷标签 -->
          <section class="form-section">
            <div class="section-title-row">
              <span class="section-badge">3</span>
              <h2 class="section-title">特别需求与补充说明</h2>
            </div>

            <!-- 快捷需求一键填入 (极简雅致) -->
            <div class="quick-prompts-bar">
              <span class="quick-title">快捷填入：</span>
              <div class="prompt-buttons-wrap">
                <button
                  type="button"
                  v-for="prompt in quickPrompts"
                  :key="prompt"
                  class="prompt-btn"
                  @click="appendPrompt(prompt)"
                >
                  + {{ prompt }}
                </button>
              </div>
            </div>

            <a-form-item name="free_text_input" class="mb-0">
              <a-textarea
                v-model:value="formData.free_text_input"
                placeholder="例如：希望多安排室内展馆避暑，行程不要太赶，晚上想去逛当地特色夜市..."
                :rows="3"
                :maxlength="300"
                show-count
                class="clean-textarea"
              />
            </a-form-item>
          </section>

          <!-- 提交生成按钮 -->
          <div class="form-submit-row">
            <button
              type="button"
              class="primary-submit-btn"
              :disabled="loading"
              @click="handleStartPlanning"
            >
              <SendOutlined class="submit-icon" />
              <span class="submit-text">开始智能规划行程</span>
            </button>
          </div>
        </a-form>
      </div>
    </div>

    <!-- 智能体分步协同生成弹窗 (现代极简工程风) -->
    <!-- 智能体分步协同生成弹窗 (现代极简工程风，支持 Esc 与显式取消) -->
    <a-modal
      v-model:open="loading"
      :footer="null"
      :closable="true"
      :mask-closable="false"
      :keyboard="true"
      centered
      width="520px"
      wrap-class-name="agent-modal-clean-wrap"
      @cancel="handleCancelPlanning"
    >
      <div class="agent-dialog-content">
        <div class="dialog-header">
          <div class="dialog-avatar">
            <CompassOutlined class="dialog-avatar-icon" />
          </div>
          <h3 class="dialog-title">多智能体正在协同规划</h3>
          <p class="dialog-desc">正在调取高德气象与 POI 真实空间数据，为您计算最优行程动线</p>
        </div>

        <!-- 4 阶段智能体执行列表 -->
        <div class="agent-step-cards">
          <div
            v-for="(step, idx) in agentSteps"
            :key="idx"
            class="agent-step-row"
            :class="{
              active: currentStepIndex === idx,
              completed: currentStepIndex > idx,
              waiting: currentStepIndex < idx
            }"
          >
            <div class="step-status-indicator">
              <CheckOutlined v-if="currentStepIndex > idx" class="icon-check" />
              <LoadingOutlined v-else-if="currentStepIndex === idx" class="icon-spin" />
              <span v-else class="icon-number">{{ idx + 1 }}</span>
            </div>
            <div class="step-text-wrap">
              <div class="step-agent-title">{{ step.agent }}</div>
              <div class="step-agent-detail">{{ step.action }}</div>
            </div>
          </div>
        </div>

        <div class="dialog-progress-area">
          <a-progress
            :percent="progressPercent"
            :stroke-color="'#2563eb'"
            :show-info="false"
            status="active"
          />
          <div class="dialog-timer-info">
            预计耗时约 20-30 秒 · 已耗时 <strong>{{ elapsedTime }}</strong> 秒
          </div>
        </div>

        <!-- 取消规划按钮区域 -->
        <div class="dialog-cancel-action">
          <button type="button" class="clean-cancel-btn" @click="handleCancelPlanning">
            <CloseOutlined class="btn-cancel-icon" />
            <span>取消本次规划 (按 Esc 键立即退出)</span>
          </button>
        </div>
      </div>
    </a-modal>

    <!-- 自带 API Key 设置弹窗 -->
    <ApiSettingsModal
      v-model:open="isApiSettingsOpen"
      @saved="checkKeyStatus"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch, onMounted, onUnmounted } from 'vue'
import { message } from 'ant-design-vue'
import dayjs, { Dayjs } from 'dayjs'
import {
  CompassOutlined,
  SettingOutlined,
  EnvironmentOutlined,
  CloudOutlined,
  NodeIndexOutlined,
  WalletOutlined,
  CheckOutlined,
  LoadingOutlined,
  SendOutlined,
  CloseOutlined,
} from '@ant-design/icons-vue'
import { tripApi } from '../services/api'
import type { TripRequest, TripPlan } from '../types'
import ApiSettingsModal from '../components/ApiSettingsModal.vue'

const isApiSettingsOpen = ref(false)
const hasCustomKey = ref(false)

// 规划任务取消与中断控制
const currentPlanRequestId = ref('')
let currentAbortController: AbortController | null = null
const isCancelled = ref(false)

const checkKeyStatus = () => {
  hasCustomKey.value = !!localStorage.getItem('ta_llm_api_key')
}

// 全局 Esc 快捷键监听：即使焦点在其他元素上，只要处于生成中也能一键秒级取消
const onWindowKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Escape' && loading.value) {
    handleCancelPlanning()
  }
}

onMounted(() => {
  checkKeyStatus()
  window.addEventListener('keydown', onWindowKeyDown)
})

const emit = defineEmits<{
  (e: 'planGenerated', plan: TripPlan): void
  (e: 'plan-generated', plan: TripPlan): void
}>()

// 热门城市列表
const popularCities = ['北京', '上海', '成都', '杭州', '西安', '广州', '重庆', '南京', '三亚', '厦门', '青岛', '武汉']

// 偏好风格标签 (无花哨 Emoji，纯粹雅致)
const availableTags = [
  '历史文化',
  '特色美食',
  '自然风光',
  '拍照打卡',
  '亲子休闲',
  '城市漫游',
  '人文艺术',
  '休闲购物',
]

// 快捷需求提示词
const quickPrompts = [
  '多安排室内博物馆',
  '带老人小孩少走爬坡路',
  '深度品尝地道特色美食',
  '节奏慢一些休闲度假',
  '晚上想逛特色夜市',
  '经典地标打卡',
]

// 默认出行日期：后天起算3天
const defaultStart = dayjs().add(2, 'day')
const defaultEnd = dayjs().add(4, 'day')

const dateRange = ref<[Dayjs, Dayjs]>([defaultStart, defaultEnd])
const selectedPreferences = ref<string[]>(['历史文化', '特色美食'])

const formData = reactive<TripRequest>({
  city: '北京',
  start_date: defaultStart.format('YYYY-MM-DD'),
  end_date: defaultEnd.format('YYYY-MM-DD'),
  travel_days: 3,
  transportation: '公共交通',
  accommodation: '舒适型酒店',
  preferences: ['历史文化', '特色美食'],
  free_text_input: '',
})

// 禁用过去日期
const disabledPastDates = (current: Dayjs) => {
  return current && current < dayjs().startOf('day')
}

const onDateRangeChange = (dates: [Dayjs, Dayjs] | null) => {
  if (dates && dates[0] && dates[1]) {
    formData.start_date = dates[0].format('YYYY-MM-DD')
    formData.end_date = dates[1].format('YYYY-MM-DD')
    formData.travel_days = dates[1].diff(dates[0], 'day') + 1
  }
}

const togglePreference = (tagName: string) => {
  const idx = selectedPreferences.value.indexOf(tagName)
  if (idx > -1) {
    selectedPreferences.value.splice(idx, 1)
  } else {
    selectedPreferences.value.push(tagName)
  }
  formData.preferences = [...selectedPreferences.value]
}

const appendPrompt = (promptText: string) => {
  if (!formData.free_text_input) {
    formData.free_text_input = promptText
  } else {
    if (!formData.free_text_input.includes(promptText)) {
      formData.free_text_input = `${formData.free_text_input}，${promptText}`
    }
  }
}

// 智能体协同步骤 (优雅无 Emoji 专业文案)
const loading = ref(false)
const progressPercent = ref(15)
const currentStepIndex = ref(0)
const elapsedTime = ref(0)
let timerInterval: any = null
let stepInterval: any = null

const agentSteps = [
  { agent: '气象感知智能体 (Weather Agent)', action: '调取高德气象预报，结构化研判出行温度、降水与装备建议' },
  { agent: '景点规划智能体 (Attraction Agent)', action: '结合天气与空间距离聚类核心 POI，编排顺路高效动线' },
  { agent: '酒店餐饮智能体 (Hotel & Food Agent)', action: '甄选贴合行程动线的高性价比酒店与特色品质餐馆' },
  { agent: '规划决策总监 (Planner Agent)', action: '汇聚各智能体专业报告，核算细分预算，输出完整行程' },
]

const startThinkingAnimation = () => {
  loading.value = true
  progressPercent.value = 15
  currentStepIndex.value = 0
  elapsedTime.value = 0

  timerInterval = setInterval(() => {
    elapsedTime.value++
  }, 1000)

  stepInterval = setInterval(() => {
    if (currentStepIndex.value < agentSteps.length - 1) {
      currentStepIndex.value++
      progressPercent.value = (currentStepIndex.value + 1) * 22
    } else {
      progressPercent.value = Math.min(progressPercent.value + 1, 95)
    }
  }, 4500)
}

const stopThinkingAnimation = () => {
  if (timerInterval) clearInterval(timerInterval)
  if (stepInterval) clearInterval(stepInterval)
  progressPercent.value = 100
  loading.value = false
}

// 主动取消规划（按 Esc 键、点右上角叉号或点“取消规划”按钮时触发）
const handleCancelPlanning = () => {
  if (isCancelled.value) return
  isCancelled.value = true

  // 1. 中止前端 HTTP 网络请求（引发 TCP 断开，触发后端 request.is_disconnected() 探测）
  if (currentAbortController) {
    currentAbortController.abort()
    currentAbortController = null
  }

  // 2. 发送显式取消指令通知后端（双重保险，杀停后台 Agent 任务并释放 Token）
  if (currentPlanRequestId.value) {
    tripApi.cancelPlan(currentPlanRequestId.value).catch(() => {})
    currentPlanRequestId.value = ''
  }

  // 3. 停止前端动画与计时器，关闭弹窗
  stopThinkingAnimation()
  message.info('已取消行程规划')
}

// 监听弹窗状态变化：如因 Modal 内部键盘事件导致 open 变为 false，同步触发取消
watch(loading, (newVal, oldVal) => {
  if (oldVal && !newVal && currentAbortController && !isCancelled.value) {
    handleCancelPlanning()
  }
})

onUnmounted(() => {
  if (timerInterval) clearInterval(timerInterval)
  if (stepInterval) clearInterval(stepInterval)
  if (currentAbortController) {
    currentAbortController.abort()
  }
  window.removeEventListener('keydown', onWindowKeyDown)
})

const handleStartPlanning = async () => {
  if (!formData.city || !formData.city.trim()) {
    message.warning('请填写或选择目的地城市！')
    return
  }
  if (!formData.start_date || !formData.end_date) {
    message.warning('请选择出行日期范围！')
    return
  }

  // 准备本次规划的唯一请求 ID 与 AbortController
  const requestId = 'plan_' + Date.now() + '_' + Math.random().toString(36).slice(2, 9)
  currentPlanRequestId.value = requestId
  currentAbortController = new AbortController()
  isCancelled.value = false

  formData.preferences = [...selectedPreferences.value]
  startThinkingAnimation()

  try {
    const plan = await tripApi.planTrip(formData, {
      requestId,
      signal: currentAbortController.signal,
    })

    // 重点防线：若用户已按 Esc 取消，坚决不弹成功提示、不跳转结果页
    if (isCancelled.value) return

    stopThinkingAnimation()
    message.success('旅行规划方案生成成功！')
    sessionStorage.setItem('current_trip_plan', JSON.stringify(plan))
    emit('planGenerated', plan)
    emit('plan-generated', plan)
  } catch (error: any) {
    stopThinkingAnimation()

    // 若为主动取消，静默返回，坚决不弹错误提示，坚决不跳转
    if (
      isCancelled.value ||
      error?.code === 'ERR_CANCELED' ||
      error?.name === 'CanceledError' ||
      error?.message === 'canceled'
    ) {
      console.log('用户已主动取消旅行规划，流程完全终止')
      return
    }

    console.error('生成旅行规划错误:', error)
    if (error?.code === 'NO_API_KEY' || error?.code === 'BAD_API_KEY') {
      isApiSettingsOpen.value = true
    }
    message.error(error.message || '生成旅行计划失败，请检查后端服务是否启动')
  } finally {
    currentAbortController = null
    currentPlanRequestId.value = ''
  }
}
</script>

<style scoped>
.home-container {
  min-height: 100vh;
  background-color: #f8fafc;
  color: #0f172a;
  padding: 40px 20px 80px;
}

.content-wrapper {
  max-width: 880px;
  margin: 0 auto;
}

/* 头部 Hero 区域 */
.hero-section {
  text-align: center;
  margin-bottom: 32px;
}

.hero-top-row {
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  margin-bottom: 16px;
}

.brand-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1e40af;
  padding: 5px 14px;
  border-radius: 9999px;
  font-size: 13px;
  font-weight: 500;
}

.pill-icon {
  color: #2563eb;
  font-size: 14px;
}

.api-settings-btn {
  position: absolute;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  color: #334155;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

.api-settings-btn:hover {
  border-color: #cbd5e1;
  background: #f8fafc;
  color: #0f172a;
}

.btn-icon {
  font-size: 14px;
  color: #64748b;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #cbd5e1;
  display: inline-block;
}

.status-dot.active {
  background: #10b981;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2);
}

@media (max-width: 640px) {
  .hero-top-row {
    flex-direction: column;
    gap: 10px;
  }
  .api-settings-btn {
    position: static;
    transform: none;
  }
}

.hero-title {
  font-size: 30px;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.02em;
  margin-bottom: 10px;
  line-height: 1.25;
}

.hero-subtitle {
  font-size: 14px;
  color: #64748b;
  max-width: 620px;
  margin: 0 auto 20px;
  line-height: 1.6;
}

.feature-tags {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
}

.feature-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  color: #475569;
  font-size: 12px;
  font-weight: 500;
  padding: 4px 10px;
  border-radius: 6px;
}

.ft-icon {
  color: #475569;
  font-size: 13px;
}

/* 主表单卡片 */
.main-form-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 28px 32px;
  box-shadow: 0 1px 3px 0 rgba(15, 23, 42, 0.04), 0 1px 2px -1px rgba(15, 23, 42, 0.02);
}

@media (max-width: 640px) {
  .main-form-card {
    padding: 20px 16px;
  }
}

.form-section {
  position: relative;
}

.section-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}

.section-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 5px;
  background: #1e3a8a;
  color: #ffffff;
  font-size: 11px;
  font-weight: 600;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
  margin: 0;
}

.section-divider {
  height: 1px;
  background: #f1f5f9;
  margin: 22px 0;
}

/* 热门城市 */
.quick-cities-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}

.quick-title {
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
}

.city-chips-group {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.city-chip {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: #475569;
  font-size: 12px;
  padding: 3px 9px;
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.12s ease;
}

.city-chip:hover {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #1e40af;
}

.city-chip.active {
  background: #1e3a8a;
  border-color: #1e3a8a;
  color: #ffffff;
  font-weight: 500;
}

/* 表单控件样式 */
.clean-input,
.clean-select,
.clean-textarea {
  border-radius: 6px !important;
}

.input-icon {
  color: #94a3b8;
  font-size: 14px;
}

.days-pill-display {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 3px;
  height: 40px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding-top: 8px;
}

.days-number {
  font-size: 18px;
  font-weight: 700;
  color: #1e40af;
}

.days-unit {
  font-size: 12px;
  color: #64748b;
}

/* 偏好风格多选 */
.preferences-container {
  margin-top: 4px;
}

.field-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: #334155;
  margin-bottom: 10px;
}

.preference-chips-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: 8px;
}

.preference-chip {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 7px 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 13px;
  color: #475569;
  cursor: pointer;
  transition: all 0.12s ease;
}

.preference-chip:hover {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #1e40af;
}

.preference-chip.selected {
  background: #eff6ff;
  border-color: #3b82f6;
  color: #1e40af;
  font-weight: 600;
}

.chip-check-icon {
  font-size: 12px;
  color: #2563eb;
}

/* 快捷提示词 */
.quick-prompts-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.prompt-buttons-wrap {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.prompt-btn {
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  color: #64748b;
  font-size: 12px;
  padding: 3px 8px;
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.12s ease;
}

.prompt-btn:hover {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #1d4ed8;
}

.mb-0 {
  margin-bottom: 0 !important;
}

/* 提交按钮 */
.form-submit-row {
  margin-top: 30px;
  text-align: center;
}

.primary-submit-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  max-width: 380px;
  padding: 12px 24px;
  background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%);
  color: #ffffff;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 4px 14px rgba(30, 58, 138, 0.25);
}

.primary-submit-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #172554 0%, #1e3a8a 100%);
  box-shadow: 0 6px 18px rgba(30, 58, 138, 0.35);
  transform: translateY(-1px);
}

.primary-submit-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.submit-icon {
  font-size: 15px;
}

/* 智能体弹窗内容 */
.agent-dialog-content {
  padding: 12px 4px;
  text-align: center;
}

.dialog-header {
  margin-bottom: 20px;
}

.dialog-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 50%;
  margin-bottom: 10px;
}

.dialog-avatar-icon {
  color: #1e40af;
  font-size: 22px;
}

.dialog-title {
  font-size: 17px;
  font-weight: 600;
  color: #0f172a;
  margin-bottom: 4px;
}

.dialog-desc {
  font-size: 13px;
  color: #64748b;
  margin: 0;
}

.agent-step-cards {
  display: flex;
  flex-direction: column;
  gap: 8px;
  text-align: left;
  margin: 18px 0;
}

.agent-step-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 6px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  transition: all 0.15s ease;
}

.agent-step-row.active {
  background: #eff6ff;
  border-color: #93c5fd;
}

.agent-step-row.completed {
  background: #f0fdf4;
  border-color: #bbf7d0;
}

.step-status-indicator {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  background: #e2e8f0;
  color: #64748b;
  flex-shrink: 0;
}

.agent-step-row.active .step-status-indicator {
  background: #1e3a8a;
  color: #ffffff;
}

.agent-step-row.completed .step-status-indicator {
  background: #16a34a;
  color: #ffffff;
}

.icon-spin {
  display: inline-block;
  font-size: 12px;
  animation: spin 1.2s infinite linear;
}

.icon-check {
  font-size: 12px;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.step-text-wrap {
  min-width: 0;
  flex: 1;
}

.step-agent-title {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
}

.step-agent-detail {
  font-size: 12px;
  color: #64748b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dialog-progress-area {
  margin-top: 16px;
}

.dialog-timer-info {
  font-size: 12px;
  color: #64748b;
  margin-top: 8px;
}

.dialog-cancel-action {
  margin-top: 20px;
  display: flex;
  justify-content: center;
}

.clean-cancel-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 16px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  color: #64748b;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.clean-cancel-btn:hover {
  background: #fef2f2;
  border-color: #fecaca;
  color: #dc2626;
}

.btn-cancel-icon {
  font-size: 12px;
}
</style>
