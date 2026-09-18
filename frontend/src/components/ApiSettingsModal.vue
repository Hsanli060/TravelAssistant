<template>
  <a-modal
    :open="open"
    :footer="null"
    :width="540"
    :destroy-on-close="true"
    @cancel="handleClose"
    class="api-settings-modal"
  >
    <template #title>
      <div class="modal-custom-title">
        <SettingOutlined class="title-icon" />
        <span>大模型 API 设置 (BYOK)</span>
      </div>
    </template>

    <div class="api-settings-content">
      <!-- 隐私与安全承诺 -->
      <div class="tip-banner">
        <SafetyCertificateOutlined class="tip-icon" />
        <div class="tip-text">
          <strong>本地隔离与隐私保证：</strong>
          您的 API 凭据仅存储于<strong>当前浏览器本地 (localStorage)</strong>。发起规划时经由请求头单向透传，<strong>服务端用完即弃，零存储、不落日志</strong>。
        </div>
      </div>

      <a-form layout="vertical" class="settings-form">
        <!-- API Key 输入框 -->
        <a-form-item label="API Key" :required="true">
          <a-input-password
            v-model:value="form.apiKey"
            placeholder="请输入 OpenAI 兼容格式的 API Key (如 sk-...)"
            size="large"
            allow-clear
            class="refined-input"
          >
            <template #prefix>
              <KeyOutlined class="field-icon" />
            </template>
          </a-input-password>
          <div class="field-hint">
            支持 DeepSeek、OpenAI、Kimi、通义千问等兼容 OpenAI 协议的 API Key。
          </div>
        </a-form-item>

        <!-- Base URL 输入框 -->
        <a-form-item label="Base URL (接口地址)">
          <a-input
            v-model:value="form.baseUrl"
            placeholder="例如 https://api.deepseek.com/v1 (留空则默认使用服务端配置)"
            size="large"
            allow-clear
            class="refined-input"
          >
            <template #prefix>
              <GlobalOutlined class="field-icon" />
            </template>
          </a-input>
          <div class="field-hint">
            如使用 DeepSeek 官方接口请填 <code>https://api.deepseek.com/v1</code>；如使用官方 OpenAI 可留空。已内置严密 SSRF 防护，禁止填写局域网/环回地址。
          </div>
        </a-form-item>

        <!-- 底部操作按钮 -->
        <div class="modal-action-row">
          <a-button
            type="text"
            danger
            @click="handleClear"
            :disabled="!hasStoredKey && !form.apiKey"
            class="clear-btn"
          >
            <DeleteOutlined /> 清空配置
          </a-button>

          <div class="right-buttons">
            <a-button
              :loading="isTesting"
              :disabled="!form.apiKey.trim()"
              @click="handleTestConnection"
              class="test-btn"
            >
              <ThunderboltOutlined /> 测试连接
            </a-button>
            <a-button @click="handleClose" class="cancel-btn">
              取消
            </a-button>
            <a-button type="primary" @click="handleSave" class="save-btn">
              保存配置
            </a-button>
          </div>
        </div>
      </a-form>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
import { ref, reactive, watch, computed } from 'vue'
import { message } from 'ant-design-vue'
import {
  SettingOutlined,
  SafetyCertificateOutlined,
  KeyOutlined,
  GlobalOutlined,
  DeleteOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons-vue'
import { tripApi } from '../services/api'

const props = defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  (e: 'update:open', val: boolean): void
  (e: 'saved'): void
}>()

const form = reactive({
  apiKey: '',
  baseUrl: '',
})

const isTesting = ref(false)

// 读取本地已存的值
const loadFromStorage = () => {
  form.apiKey = localStorage.getItem('ta_llm_api_key') || ''
  form.baseUrl = localStorage.getItem('ta_llm_base_url') || ''
}

// 监听弹窗打开，回填当前值
watch(
  () => props.open,
  (newVal) => {
    if (newVal) {
      loadFromStorage()
    }
  },
  { immediate: true }
)

// 是否有已经存储的 key
const hasStoredKey = computed(() => {
  return !!localStorage.getItem('ta_llm_api_key')
})

const handleClose = () => {
  emit('update:open', false)
}

// 测试连接逻辑 (0 Token 快速探活)
const handleTestConnection = async () => {
  const cleanKey = form.apiKey.trim()
  const cleanUrl = form.baseUrl.trim()

  if (!cleanKey) {
    message.warning('请先输入 API Key 再进行测试')
    return
  }

  isTesting.value = true
  try {
    const res = await tripApi.verifyApiKey(cleanKey, cleanUrl || undefined)
    if (res.success) {
      message.success(`连接测试通过：${res.message || 'API Key 有效'}`)
    } else {
      message.error(`连接测试未通过：${res.message || 'API Key 无效'}`)
    }
  } catch (err: any) {
    const msg = err.response?.data?.detail?.message || err.message || '测试连接失败'
    message.error(`连接测试失败：${msg}`)
  } finally {
    isTesting.value = false
  }
}

// 保存逻辑
const handleSave = () => {
  const cleanKey = form.apiKey.trim()
  const cleanUrl = form.baseUrl.trim()

  if (!cleanKey) {
    message.warning('请输入 API Key 后再保存')
    return
  }

  // 基础的客户端 URL 校验
  if (cleanUrl) {
    if (!cleanUrl.startsWith('http://') && !cleanUrl.startsWith('https://')) {
      message.error('Base URL 必须以 http:// 或 https:// 开头')
      return
    }
  }

  localStorage.setItem('ta_llm_api_key', cleanKey)
  if (cleanUrl) {
    localStorage.setItem('ta_llm_base_url', cleanUrl)
  } else {
    localStorage.removeItem('ta_llm_base_url')
  }

  message.success('API 设置已保存')
  emit('saved')
  handleClose()
}

// 清除逻辑
const handleClear = () => {
  localStorage.removeItem('ta_llm_api_key')
  localStorage.removeItem('ta_llm_base_url')
  form.apiKey = ''
  form.baseUrl = ''
  message.info('已清除本地配置。若服务端启用严格模式，未配置 Key 将无法生成行程。')
  emit('saved')
  handleClose()
}
</script>

<style scoped>
.modal-custom-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: #0f172a;
}

.title-icon {
  color: #1e40af;
  font-size: 17px;
}

.api-settings-content {
  padding-top: 10px;
}

.tip-banner {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  background: #f0f7ff;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 20px;
  font-size: 13px;
  line-height: 1.55;
  color: #1e3a8a;
}

.tip-icon {
  font-size: 16px;
  color: #1d4ed8;
  margin-top: 2px;
  flex-shrink: 0;
}

.tip-text strong {
  color: #1e3a8a;
  font-weight: 600;
}

.field-icon {
  color: #94a3b8;
  font-size: 14px;
}

.refined-input {
  border-radius: 6px;
}

.field-hint {
  font-size: 12px;
  color: #64748b;
  margin-top: 5px;
  line-height: 1.45;
}

.field-hint code {
  background: #f1f5f9;
  color: #334155;
  padding: 2px 5px;
  border-radius: 4px;
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.modal-action-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid #f1f5f9;
}

.right-buttons {
  display: flex;
  align-items: center;
  gap: 8px;
}

.test-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #1e40af;
  border-color: #bfdbfe;
  background: #eff6ff;
}

.test-btn:hover {
  background: #dbeafe;
  border-color: #93c5fd;
  color: #1d4ed8;
}

.clear-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.save-btn {
  background-color: #1e3a8a;
  border-color: #1e3a8a;
  color: #ffffff;
  box-shadow: 0 1px 3px rgba(30, 58, 138, 0.2);
}

.save-btn:hover {
  background-color: #1d4ed8;
  border-color: #1d4ed8;
}
</style>
