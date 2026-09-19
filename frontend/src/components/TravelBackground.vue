<template>
  <div class="travel-bg-container" :class="`variant-${variant}`" aria-hidden="true">
    <!-- 1. 环境光晕氛围层 -->
    <div class="ambient-glow glow-top-left"></div>
    <div class="ambient-glow glow-top-right"></div>
    <div class="ambient-glow glow-bottom-center"></div>

    <!-- 2. 空间经纬网与等高线脉络 SVG -->
    <svg class="topo-grid-svg" xmlns="http://www.w3.org/2000/svg" width="100%" height="100%">
      <defs>
        <!-- 经纬交叉微网点 -->
        <pattern id="grid-dots" width="48" height="48" patternUnits="userSpaceOnUse">
          <circle cx="2" cy="2" r="1" fill="#1e3a8a" fill-opacity="0.12" />
        </pattern>
        <!-- 航线渐变色 -->
        <linearGradient id="flight-grad" x1="0%" y1="100%" x2="100%" y2="0%">
          <stop offset="0%" stop-color="#1e3a8a" stop-opacity="0.05" />
          <stop offset="50%" stop-color="#2563eb" stop-opacity="0.35" />
          <stop offset="100%" stop-color="#d97706" stop-opacity="0.4" />
        </linearGradient>
      </defs>

      <!-- 点阵背景 -->
      <rect width="100%" height="100%" fill="url(#grid-dots)" />

      <!-- 山川等高线波纹 (Topographic Curves) -->
      <path
        d="M -100,180 C 200,120 400,260 700,160 C 1000,60 1300,220 1600,140 C 1800,90 2000,200 2200,150"
        fill="none"
        stroke="#1e3a8a"
        stroke-width="1.2"
        stroke-opacity="0.1"
      />
      <path
        d="M -100,220 C 180,160 420,300 680,200 C 960,100 1280,260 1580,180 C 1820,120 2020,240 2200,190"
        fill="none"
        stroke="#1e3a8a"
        stroke-width="0.8"
        stroke-dasharray="4 6"
        stroke-opacity="0.08"
      />
      <path
        d="M -50,600 C 250,540 500,680 850,580 C 1200,480 1450,640 1800,560 C 2000,510 2200,600 2300,570"
        fill="none"
        stroke="#d97706"
        stroke-width="0.9"
        stroke-opacity="0.06"
      />

      <!-- 优雅跨区域航线弧线 (Flight Route Arc) -->
      <path
        class="flight-route-path"
        d="M 50,420 Q 480,-20 1080,120 T 1800,60"
        fill="none"
        stroke="url(#flight-grad)"
        stroke-width="2"
        stroke-dasharray="6 8"
      />

      <!-- 航线端点雷达波环 -->
      <g transform="translate(1080, 120)">
        <circle r="4" fill="#2563eb" fill-opacity="0.7" />
        <circle r="10" fill="none" stroke="#2563eb" stroke-width="1" stroke-opacity="0.3" class="radar-ping" />
        <text x="12" y="4" font-size="10" fill="#1e40af" font-weight="600" opacity="0.6">WAYPOINT · DESTINATION</text>
      </g>
    </svg>

    <!-- 3. 动态客机图标沿航线飞翔 (Minimalist Aircraft) -->
    <div class="flying-aircraft-wrap">
      <div class="aircraft-icon-box">
        <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="#1e40af" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.3c.4-.2.6-.6.5-1.1z"/>
        </svg>
      </div>
    </div>

    <!-- 4. 浮空热气球 (Hot Air Balloon) - 经典旅行探险标志 -->
    <div class="floating-balloon-wrap">
      <svg viewBox="0 0 64 80" width="54" height="68" class="balloon-svg" fill="none">
        <!-- 气球主体经线与横线 -->
        <ellipse cx="32" cy="28" rx="24" ry="26" fill="#eff6ff" stroke="#1d4ed8" stroke-width="1.5" stroke-opacity="0.35" />
        <path d="M32 2 Q 46 28 32 54" stroke="#1d4ed8" stroke-width="1.2" stroke-opacity="0.3" fill="none" />
        <path d="M32 2 Q 18 28 32 54" stroke="#1d4ed8" stroke-width="1.2" stroke-opacity="0.3" fill="none" />
        <path d="M12 20 Q 32 26 52 20" stroke="#d97706" stroke-width="1.2" stroke-opacity="0.35" fill="none" />
        <path d="M14 36 Q 32 42 50 36" stroke="#d97706" stroke-width="1.2" stroke-opacity="0.35" fill="none" />
        <!-- 吊篮绳索与吊篮 -->
        <line x1="24" y1="54" x2="26" y2="64" stroke="#1e40af" stroke-width="1" stroke-opacity="0.3" />
        <line x1="40" y1="54" x2="38" y2="64" stroke="#1e40af" stroke-width="1" stroke-opacity="0.3" />
        <rect x="25" y="64" width="14" height="10" rx="2" fill="#fffbeb" stroke="#b45309" stroke-width="1.2" stroke-opacity="0.4" />
      </svg>
      <div class="balloon-caption">VOYAGE 01</div>
    </div>

    <!-- 5. 典雅复古罗盘星盘刻度水印 (Compass Rose & Astrolabe) -->
    <div class="compass-rose-wrap">
      <svg viewBox="0 0 200 200" width="220" height="220" class="compass-svg" fill="none">
        <!-- 外圈刻度 -->
        <circle cx="100" cy="100" r="94" stroke="#1e3a8a" stroke-width="1" stroke-opacity="0.14" />
        <circle cx="100" cy="100" r="86" stroke="#1e3a8a" stroke-width="0.8" stroke-opacity="0.08" stroke-dasharray="2 4" />
        <circle cx="100" cy="100" r="64" stroke="#d97706" stroke-width="0.8" stroke-opacity="0.12" />
        <!-- 八角星航向指示指针 -->
        <polygon points="100,20 106,94 180,100 106,106 100,180 94,106 20,100 94,94" fill="#1e3a8a" fill-opacity="0.03" stroke="#1e3a8a" stroke-width="1" stroke-opacity="0.12" />
        <polygon points="100,32 104,96 168,100 104,104 100,168 96,104 32,100 96,96" fill="#d97706" fill-opacity="0.02" stroke="#d97706" stroke-width="0.8" stroke-opacity="0.1" />
        <!-- 罗盘基准方位字模 -->
        <text x="100" y="16" text-anchor="middle" font-size="11" font-weight="700" fill="#1e3a8a" fill-opacity="0.3">N</text>
        <text x="188" y="104" text-anchor="middle" font-size="11" font-weight="700" fill="#1e3a8a" fill-opacity="0.3">E</text>
        <text x="100" y="196" text-anchor="middle" font-size="11" font-weight="700" fill="#1e3a8a" fill-opacity="0.3">S</text>
        <text x="12" y="104" text-anchor="middle" font-size="11" font-weight="700" fill="#1e3a8a" fill-opacity="0.3">W</text>
        <circle cx="100" cy="100" r="3" fill="#1e3a8a" fill-opacity="0.25" />
      </svg>
    </div>

    <!-- 6. 复古旅行护照印章徽章 (Vintage Passport Stamps) -->
    <div class="passport-stamp stamp-top-right">
      <div class="stamp-inner">
        <div class="stamp-border">
          <span class="stamp-title">WANDERLUST</span>
          <div class="stamp-center">
            <span class="stamp-code">DISCOVERY</span>
            <span class="stamp-date">★ 2026 ★</span>
          </div>
          <span class="stamp-sub">TRAVEL ASSISTANT</span>
        </div>
      </div>
    </div>

    <div class="passport-stamp stamp-bottom-left">
      <div class="stamp-inner hexagon">
        <div class="stamp-border">
          <span class="stamp-code">GEO · PASS</span>
          <span class="stamp-sub">CUSTOM TOUR</span>
          <span class="stamp-date">AUTHENTIC POI</span>
        </div>
      </div>
    </div>

    <!-- 7. 地理经纬微注印记 (Geographic Coordinates) -->
    <div class="geo-tag tag-top-center">
      <span class="dot-live"></span>
      <span>N 39°54′15″ E 116°23′29″ · SPATIAL CLUSTERING ACTIVE</span>
    </div>

    <div class="geo-tag tag-bottom-right">
      <span>AI AGENT ROUTE OPTIMIZER · MULTI-DAY PLANNER</span>
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: 'home' | 'result'
  }>(),
  {
    variant: 'home',
  }
)
</script>

<style scoped>
.travel-bg-container {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  min-height: 100%;
  overflow: hidden;
  pointer-events: none;
  user-select: none;
  z-index: 0;
}

/* 环境光晕层 (Ambient Glow) */
.ambient-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  pointer-events: none;
}

.glow-top-left {
  width: 520px;
  height: 520px;
  top: -120px;
  left: -80px;
  background: radial-gradient(circle, rgba(30, 58, 138, 0.08) 0%, rgba(30, 58, 138, 0) 70%);
}

.glow-top-right {
  width: 560px;
  height: 560px;
  top: -100px;
  right: -100px;
  background: radial-gradient(circle, rgba(217, 119, 6, 0.07) 0%, rgba(217, 119, 6, 0) 70%);
}

.glow-bottom-center {
  width: 680px;
  height: 480px;
  bottom: 5%;
  left: 30%;
  background: radial-gradient(circle, rgba(5, 150, 105, 0.04) 0%, rgba(5, 150, 105, 0) 70%);
}

/* 全屏等高线与网格 SVG */
.topo-grid-svg {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  opacity: 0.85;
}

/* 雷达涟漪 */
@keyframes radar-pulse {
  0% {
    r: 4;
    opacity: 0.8;
  }
  100% {
    r: 22;
    opacity: 0;
  }
}

.radar-ping {
  animation: radar-pulse 3s cubic-bezier(0.25, 1, 0.5, 1) infinite;
  transform-origin: center;
}

/* 航线与微型飞机 */
.flying-aircraft-wrap {
  position: absolute;
  top: 62px;
  left: 34%;
  animation: airplane-glide 8s ease-in-out infinite alternate;
}

@keyframes airplane-glide {
  0% {
    transform: translate(0, 0) rotate(18deg);
  }
  50% {
    transform: translate(28px, -12px) rotate(22deg);
  }
  100% {
    transform: translate(60px, -6px) rotate(19deg);
  }
}

.aircraft-icon-box {
  filter: drop-shadow(0 4px 8px rgba(30, 58, 138, 0.15));
  opacity: 0.42;
}

/* 浮空热气球 (Floating Hot Air Balloon) */
.floating-balloon-wrap {
  position: absolute;
  top: 140px;
  left: 42px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  animation: balloon-float 9s ease-in-out infinite;
  opacity: 0.45;
  transition: opacity 0.3s ease;
}

@keyframes balloon-float {
  0%, 100% {
    transform: translateY(0) rotate(-2deg);
  }
  50% {
    transform: translateY(-24px) rotate(2deg);
  }
}

.balloon-svg {
  filter: drop-shadow(0 6px 12px rgba(29, 78, 216, 0.08));
}

.balloon-caption {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 1px;
  color: #1e40af;
  background: rgba(239, 246, 255, 0.6);
  border: 1px solid rgba(191, 219, 254, 0.6);
  padding: 1px 5px;
  border-radius: 4px;
}

/* 罗盘星盘旋转水印 (Compass Rose) */
.compass-rose-wrap {
  position: absolute;
  top: 360px;
  right: -40px;
  opacity: 0.35;
  animation: compass-spin 180s linear infinite;
}

@keyframes compass-spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* 护照火漆印章 (Passport Stamps) */
.passport-stamp {
  position: absolute;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  opacity: 0.28;
  transition: opacity 0.3s ease;
}

.stamp-top-right {
  top: 48px;
  right: 50px;
  transform: rotate(14deg);
}

.stamp-bottom-left {
  top: 520px;
  left: 36px;
  transform: rotate(-10deg);
}

.stamp-inner {
  border: 2px dashed #1e40af;
  border-radius: 50%;
  padding: 5px;
  width: 108px;
  height: 108px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stamp-inner.hexagon {
  border-radius: 18px;
  border: 2px dashed #d97706;
  width: 96px;
  height: 96px;
}

.stamp-border {
  border: 1px solid #1e40af;
  border-radius: 50%;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 6px;
}

.stamp-inner.hexagon .stamp-border {
  border-color: #d97706;
  border-radius: 12px;
}

.stamp-title {
  font-size: 8px;
  font-weight: 800;
  letter-spacing: 1.5px;
  color: #1e3a8a;
}

.stamp-center {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin: 2px 0;
}

.stamp-code {
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 1px;
  color: #1d4ed8;
}

.stamp-inner.hexagon .stamp-code {
  color: #b45309;
}

.stamp-date {
  font-size: 8px;
  font-weight: 700;
  color: #64748b;
}

.stamp-sub {
  font-size: 7px;
  font-weight: 600;
  letter-spacing: 0.5px;
  color: #475569;
}

/* 经纬度地理标记标签 (Geographic Coordinates) */
.geo-tag {
  position: absolute;
  font-family: 'Courier New', Courier, monospace;
  font-size: 10px;
  letter-spacing: 0.8px;
  color: #64748b;
  opacity: 0.4;
  display: flex;
  align-items: center;
  gap: 6px;
}

.tag-top-center {
  top: 14px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(4px);
  padding: 3px 12px;
  border-radius: 20px;
  border: 1px solid rgba(226, 232, 240, 0.8);
}

.dot-live {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 6px #10b981;
  display: inline-block;
}

.tag-bottom-right {
  bottom: 24px;
  right: 24px;
}

/* 结果页微调 (Result 视图更加克制，避免干扰路线地图) */
.variant-result .floating-balloon-wrap,
.variant-result .compass-rose-wrap {
  opacity: 0.18;
}

.variant-result .stamp-top-right {
  display: none;
}

/* 响应式适配：手机端轻量化展示 */
@media (max-width: 900px) {
  .floating-balloon-wrap {
    display: none;
  }
  .compass-rose-wrap {
    right: -80px;
    top: 500px;
    opacity: 0.2;
  }
  .stamp-top-right {
    display: none;
  }
  .tag-top-center {
    display: none;
  }
}
</style>
