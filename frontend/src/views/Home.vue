<template>
  <div class="home-container">
    <div class="content-wrapper">
      <!-- 页面头部 Hero 区 -->
      <header class="hero-section">
        <div class="brand-pill">
          <span class="pill-icon">✈️</span>
          <span class="pill-text">AI 智能多智能体旅行规划助手</span>
        </div>
        <h1 class="hero-title">
          轻松规划您的下一次完美旅程
        </h1>
        <p class="hero-subtitle">
          结合气象研判、高德地图真实 POI 与多智能体协同，为您一键定制顺路、省心、结构化的旅行攻略
        </p>

        <!-- 特色亮点微标签 -->
        <div class="feature-tags">
          <span class="feature-tag">🌤️ 实时气象研判</span>
          <span class="feature-tag">📍 高德真实数据</span>
          <span class="feature-tag">🗺️ 动线智能聚类</span>
          <span class="feature-tag">💰 细分预算精算</span>
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
              <span class="quick-title">热门目的地：</span>
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
                      <span class="input-icon">📍</span>
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
                    <a-select-option value="公共交通">🚇 公共交通 (地铁/公交)</a-select-option>
                    <a-select-option value="打车/网约车">🚖 打车 / 网约车接驳</a-select-option>
                    <a-select-option value="自驾出行">🚗 自驾出行 / 租车</a-select-option>
                    <a-select-option value="步行与慢行">🚶 步行与慢行 (Citywalk)</a-select-option>
                    <a-select-option value="混合出行">🔀 灵活混合出行</a-select-option>
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
                    <a-select-option value="经济型酒店">💰 经济实惠型 (约 200-350元/晚)</a-select-option>
                    <a-select-option value="舒适型酒店">🏨 舒适商务型 (约 350-600元/晚)</a-select-option>
                    <a-select-option value="高档豪华型">💎 高档豪华型 (约 600-1200元/晚)</a-select-option>
                    <a-select-option value="特色民宿客栈">🏡 特色民宿 / 风情客栈</a-select-option>
                  </a-select>
                </a-form-item>
              </a-col>
            </a-row>

            <!-- 游玩风格标签多选 -->
            <div class="preferences-container">
              <label class="field-label">游玩主题偏好（可多选）：</label>
              <div class="preference-chips-grid">
                <button
                  type="button"
                  v-for="tag in availableTags"
                  :key="tag.name"
                  class="preference-chip"
                  :class="{ selected: selectedPreferences.includes(tag.name) }"
                  @click="togglePreference(tag.name)"
                >
                  <span class="chip-icon">{{ tag.icon }}</span>
                  <span class="chip-text">{{ tag.name }}</span>
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

            <!-- 快捷需求一键填入 (极简方便) -->
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
              <span class="submit-icon">⚡</span>
              <span class="submit-text">一键生成专属旅行方案</span>
            </button>
          </div>
        </a-form>
      </div>
    </div>

    <!-- 智能体分步协同生成弹窗 -->
    <a-modal
      v-model:open="loading"
      :footer="null"
      :closable="false"
      :mask-closable="false"
      centered
      width="540px"
      wrap-class-name="agent-modal-clean-wrap"
    >
      <div class="agent-dialog-content">
        <div class="dialog-header">
          <div class="dialog-avatar">
            <span>🤖</span>
          </div>
          <h3 class="dialog-title">多智能体正在协同规划</h3>
          <p class="dialog-desc">正在联动高德地图气象与 POI 真实数据，为您定制最优动线</p>
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
              <span v-if="currentStepIndex > idx" class="icon-check">✓</span>
              <span v-else-if="currentStepIndex === idx" class="icon-spin">⟳</span>
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
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onUnmounted } from 'vue'
import { message } from 'ant-design-vue'
import dayjs, { Dayjs } from 'dayjs'
import { tripApi } from '../services/api'
import type { TripRequest, TripPlan } from '../types'

const emit = defineEmits<{
  (e: 'planGenerated', plan: TripPlan): void
  (e: 'plan-generated', plan: TripPlan): void
}>()

// 热门城市列表
const popularCities = ['北京', '上海', '成都', '杭州', '西安', '广州', '重庆', '南京', '三亚', '厦门', '青岛', '武汉']

// 偏好风格标签
const availableTags = [
  { name: '历史文化', icon: '🏛️' },
  { name: '特色美食', icon: '🍜' },
  { name: '自然风光', icon: '🌿' },
  { name: '拍照打卡', icon: '📸' },
  { name: '亲子休闲', icon: '👨‍👩‍👧' },
  { name: '城市漫游', icon: '🚶' },
  { name: '人文艺术', icon: '🎨' },
  { name: '休闲购物', icon: '🛍️' },
]

// 快捷需求提示词
const quickPrompts = [
  '多安排室内博物馆',
  '带老人小孩少走爬坡路',
  '深度品尝地道特色美食',
  '节奏慢一些休闲度假',
  '晚上想逛特色夜市',
  '经典地标拍照打卡',
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
  free_text_input: '希望多去室内博物馆，少走长路，喜欢吃烤鸭和小吃',
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

// 智能体协同步骤
const loading = ref(false)
const progressPercent = ref(15)
const currentStepIndex = ref(0)
const elapsedTime = ref(0)
let timerInterval: any = null
let stepInterval: any = null

const agentSteps = [
  { agent: '🌤️ 气象顾问 (Agent 1)', action: '实时调取高德天气数据，研判未来气象与穿衣防晒建议' },
  { agent: '🏛️ 景点规划专家 (Agent 2)', action: '按晴雨分天与顺路原则聚类核心 POI，编排高效动线' },
  { agent: '🏨 酒店美食专家 (Agent 3)', action: '调取真实高德酒店与地道老字号/热门餐馆候选清单' },
  { agent: '🧠 行程规划总监 (Agent 4)', action: '汇聚全局情报，核算四项分类预算与总计，输出结构化行程' },
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

onUnmounted(() => {
  if (timerInterval) clearInterval(timerInterval)
  if (stepInterval) clearInterval(stepInterval)
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

  formData.preferences = [...selectedPreferences.value]
  startThinkingAnimation()

  try {
    const plan = await tripApi.planTrip(formData)
    stopThinkingAnimation()
    message.success('旅行规划方案生成成功！')
    sessionStorage.setItem('current_trip_plan', JSON.stringify(plan))
    emit('planGenerated', plan)
    emit('plan-generated', plan)
  } catch (error: any) {
    stopThinkingAnimation()
    console.error('生成旅行规划错误:', error)
    message.error(error.message || '生成旅行计划失败，请检查后端服务是否启动')
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
  max-width: 900px;
  margin: 0 auto;
}

/* 头部 Hero 区域 */
.hero-section {
  text-align: center;
  margin-bottom: 32px;
}

.brand-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #eff6ff;
  border: 1px solid #dbeafe;
  color: #1d4ed8;
  padding: 4px 14px;
  border-radius: 9999px;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 14px;
}

.pill-icon {
  font-size: 14px;
}

.hero-title {
  font-size: 32px;
  font-weight: 800;
  color: #0f172a;
  letter-spacing: -0.5px;
  margin-bottom: 10px;
  line-height: 1.3;
}

.hero-subtitle {
  font-size: 15px;
  color: #64748b;
  max-width: 640px;
  margin: 0 auto 18px;
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
  background: #ffffff;
  border: 1px solid #e2e8f0;
  color: #475569;
  font-size: 12px;
  font-weight: 500;
  padding: 4px 12px;
  border-radius: 6px;
}

/* 主表单卡片 */
.main-form-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 32px 36px;
  box-shadow: 0 4px 20px -2px rgba(15, 23, 42, 0.05);
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
  gap: 10px;
  margin-bottom: 18px;
}

.section-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: #2563eb;
  color: #ffffff;
  font-size: 12px;
  font-weight: 700;
}

.section-title {
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
}

.section-divider {
  height: 1px;
  background: #f1f5f9;
  margin: 24px 0;
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
  font-size: 13px;
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
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.city-chip:hover {
  background: #eff6ff;
  border-color: #bfdbfe;
  color: #2563eb;
}

.city-chip.active {
  background: #2563eb;
  border-color: #2563eb;
  color: #ffffff;
  font-weight: 600;
}

/* 表单控件样式 */
.clean-input,
.clean-select,
.clean-textarea {
  border-radius: 8px !important;
}

.input-icon {
  font-size: 14px;
  margin-right: 4px;
}

.days-pill-display {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 4px;
  height: 40px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding-top: 6px;
}

.days-number {
  font-size: 20px;
  font-weight: 800;
  color: #2563eb;
}

.days-unit {
  font-size: 13px;
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
  grid-template-columns: repeat(auto-fill, minmax(105px, 1fr));
  gap: 8px;
}

.preference-chip {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 13px;
  color: #475569;
  cursor: pointer;
  transition: all 0.15s ease;
}

.preference-chip:hover {
  background: #f1f5f9;
  border-color: #cbd5e1;
}

.preference-chip.selected {
  background: #eff6ff;
  border-color: #2563eb;
  color: #1d4ed8;
  font-weight: 600;
}

.chip-icon {
  font-size: 14px;
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
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.prompt-btn:hover {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #2563eb;
}

.mb-0 {
  margin-bottom: 0 !important;
}

/* 提交按钮 */
.form-submit-row {
  margin-top: 32px;
  text-align: center;
}

.primary-submit-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  max-width: 420px;
  padding: 14px 28px;
  background: #2563eb;
  color: #ffffff;
  border: none;
  border-radius: 10px;
  font-size: 16px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.25);
}

.primary-submit-btn:hover:not(:disabled) {
  background: #1d4ed8;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.35);
  transform: translateY(-1px);
}

.primary-submit-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.submit-icon {
  font-size: 16px;
}

/* 弹窗内容 */
.agent-dialog-content {
  padding: 12px 6px;
  text-align: center;
}

.dialog-header {
  margin-bottom: 20px;
}

.dialog-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  background: #eff6ff;
  border: 1px solid #dbeafe;
  border-radius: 50%;
  font-size: 24px;
  margin-bottom: 10px;
}

.dialog-title {
  font-size: 18px;
  font-weight: 700;
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
  margin: 20px 0;
}

.agent-step-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  transition: all 0.2s ease;
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
  font-size: 12px;
  font-weight: 700;
  background: #e2e8f0;
  color: #64748b;
  flex-shrink: 0;
}

.agent-step-row.active .step-status-indicator {
  background: #2563eb;
  color: #ffffff;
}

.agent-step-row.completed .step-status-indicator {
  background: #16a34a;
  color: #ffffff;
}

.icon-spin {
  display: inline-block;
  animation: spin 1.2s infinite linear;
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
  font-weight: 700;
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
</style>
