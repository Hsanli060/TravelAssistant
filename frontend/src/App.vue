<template>
  <div id="app-root">
    <Home
      v-if="currentView === 'home'"
      @plan-generated="handlePlanGenerated"
      @planGenerated="handlePlanGenerated"
    />
    <Result
      v-else-if="currentView === 'result'"
      :plan-data="activePlan"
      @back-to-home="handleBackToHome"
      @backToHome="handleBackToHome"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import Home from './views/Home.vue'
import Result from './views/Result.vue'
import type { TripPlan } from './types'

const currentView = ref<'home' | 'result'>('home')
const activePlan = ref<TripPlan | null>(null)

// 检查是否有之前缓存的行程
const cachedPlanStr = sessionStorage.getItem('current_trip_plan')
if (cachedPlanStr) {
  try {
    activePlan.value = JSON.parse(cachedPlanStr)
    // 默认停留在 home，用户也可直接体验
  } catch (e) {
    console.error(e)
  }
}

const handlePlanGenerated = (plan: TripPlan) => {
  activePlan.value = plan
  currentView.value = 'result'
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

const handleBackToHome = () => {
  currentView.value = 'home'
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
</script>

<style>
* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  margin: 0;
  padding: 0;
  background-color: #f8fafc;
  color: #0f172a;
  font-family: 'Plus Jakarta Sans', 'Noto Sans SC', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

#app-root {
  min-height: 100vh;
  width: 100%;
}

/* 自定义轻量化滚动条 */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background: #f1f5f9;
}

::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}

/* 全局 Ant Design Vue 微调以适配极简风格 */
.ant-btn-primary {
  background-color: #2563eb !important;
  border-color: #2563eb !important;
}

.ant-btn-primary:hover {
  background-color: #1d4ed8 !important;
  border-color: #1d4ed8 !important;
}
</style>
