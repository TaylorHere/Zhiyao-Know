<template>
  <div class="kc-page">
    <div class="hero-card">
      <div class="hero-title">合规知识中心</div>
      <div class="hero-subtitle">一库两清单 · 统一浏览 · 快速查询</div>

      <div class="hero-search">
        <a-select v-model:value="searchTarget" class="hero-target-select">
          <a-select-option value="risk-library">合规风险库</a-select-option>
          <a-select-option value="process-checklist">业务流程管控清单</a-select-option>
          <a-select-option value="position-responsibility">重要岗位履责合规义务清单</a-select-option>
        </a-select>
        <a-input
          v-model:value="keyword"
          :placeholder="searchPlaceholder"
          size="large"
          class="hero-search-input"
          allow-clear
          @pressEnter="handleSearch"
        />
        <a-button type="primary" size="large" class="hero-search-btn" @click="handleSearch">搜索</a-button>
      </div>
      <div class="hero-search-hint">搜索后将跳转到对应子页面并自动带入关键词筛选</div>
    </div>

    <div class="section">
      <div class="section-title">快捷入口</div>
      <div class="quick-grid">
        <div v-for="item in quickEntries" :key="item.key" class="quick-card" @click="handleQuickOpen(item)">
          <div class="quick-card-top">
            <div class="quick-icon" :class="`t-${item.tone}`">{{ item.iconText }}</div>
            <div class="quick-meta">
              <div class="quick-name">{{ item.name }}</div>
              <div class="quick-desc">{{ item.desc }}</div>
            </div>
          </div>
          <div class="quick-count">
            <span class="quick-count-number">{{ item.count }}</span>
            <span class="quick-count-unit">条记录</span>
          </div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">最近更新</div>
      <a-spin :spinning="loading">
        <div class="recent-list">
          <div v-for="row in recentUpdates" :key="row.id" class="recent-row">
            <div class="recent-left">
              <a-tag :color="row.typeColor" class="recent-type">{{ row.type }}</a-tag>
              <div class="recent-content">
                <div class="recent-title">{{ row.title }}</div>
                <div class="recent-sub">
                  <span class="recent-role">{{ row.role || '-' }}</span>
                  <span class="dot">·</span>
                  <span class="recent-dept">{{ row.department || '-' }}</span>
                </div>
              </div>
            </div>
            <div class="recent-time">{{ formatTime(row.updated_at) }}</div>
          </div>
          <a-empty v-if="!loading && recentUpdates.length === 0" description="暂无更新" />
        </div>
      </a-spin>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'

import { complianceApi } from '@/apis/compliance_api'

const router = useRouter()
const loading = ref(false)
const keyword = ref('')
const searchTarget = ref('risk-library')
const summary = ref({
  counts: {
    risk_library: 0,
    process_checklist: 0,
    position_responsibility: 0
  },
  recent_updates: []
})

const searchPlaceholder = computed(() => {
  const map = {
    'risk-library': '搜索风险描述、业务类型…',
    'process-checklist': '搜索流程名称、合规要点…',
    'position-responsibility': '搜索岗位名称、职责…'
  }
  return map[searchTarget.value] || '请输入关键词'
})

const quickEntries = computed(() => {
  return [
    {
      key: 'risk-library',
      name: '合规风险库',
      desc: '风险识别与管控清单',
      count: summary.value.counts.risk_library || 0,
      tone: 'red',
      iconText: '风'
    },
    {
      key: 'process-checklist',
      name: '业务流程管控清单',
      desc: '业务流程与准入管控',
      count: summary.value.counts.process_checklist || 0,
      tone: 'purple',
      iconText: '流'
    },
    {
      key: 'position-responsibility',
      name: '重要岗位履责合规义务清单',
      desc: '岗位合规职责体系',
      count: summary.value.counts.position_responsibility || 0,
      tone: 'green',
      iconText: '岗'
    }
  ]
})

const recentUpdates = computed(() => {
  return (summary.value.recent_updates || []).map((item) => ({
    ...item,
    typeColor: item.type === '风险库' ? 'red' : item.type === '流程清单' ? 'purple' : 'green'
  }))
})

const fetchSummary = async () => {
  loading.value = true
  try {
    const res = await complianceApi.getSummary()
    summary.value = res.data || summary.value
  } catch (error) {
    message.error(error.message || '获取统计信息失败')
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  const kw = (keyword.value || '').trim()
  if (!kw) {
    message.info('请输入关键词')
    return
  }
  router.push(`/compliance-risk/${searchTarget.value}?keyword=${encodeURIComponent(kw)}`)
}

const handleQuickOpen = (item) => {
  const map = {
    'risk-library': '/compliance-risk/risk-library',
    'process-checklist': '/compliance-risk/process-checklist',
    'position-responsibility': '/compliance-risk/position-responsibility'
  }
  router.push(map[item.key])
}

const formatTime = (value) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(
    2,
    '0'
  )} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

onMounted(fetchSummary)
</script>

<style lang="less" scoped>
.kc-page {
  width: 100%;
}

.hero-card {
  border-radius: 14px;
  padding: 18px 18px 16px 18px;
  color: #fff;
  background: linear-gradient(135deg, #3b82f6 0%, #4f46e5 100%);
  box-shadow: none;
}

.hero-title {
  font-size: 18px;
  font-weight: 700;
  line-height: 1.2;
}

.hero-subtitle {
  margin-top: 6px;
  font-size: 12px;
  opacity: 0.9;
}

.hero-search {
  margin-top: 14px;
  display: flex;
  gap: 10px;
  align-items: center;
}

.hero-target-select {
  width: 140px;
  :deep(.ant-select-selector) {
    border-radius: 10px;
  }
}

.hero-search-input {
  flex: 1;
  min-width: 200px;
  :deep(.ant-input-affix-wrapper) {
    border-radius: 10px;
  }
}

.hero-search-btn {
  border-radius: 10px;
  padding: 0 22px;
}

.hero-search-hint {
  margin-top: 8px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.9);
}

.section {
  margin-top: 16px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--gray-900);
  margin-bottom: 10px;
}

.quick-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.quick-card {
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  padding: 14px;
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease;

  &:hover {
    background: var(--gray-25);
    border-color: var(--gray-200);
  }
}

.quick-card-top {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.quick-icon {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 14px;
  flex: 0 0 auto;

  &.t-red {
    background: rgba(239, 68, 68, 0.1);
    color: #ef4444;
  }
  &.t-purple {
    background: rgba(168, 85, 247, 0.1);
    color: #a855f7;
  }
  &.t-green {
    background: rgba(34, 197, 94, 0.1);
    color: #22c55e;
  }
}

.quick-meta {
  flex: 1;
  min-width: 0;
}

.quick-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--gray-1000);
  line-height: 1.2;
}

.quick-desc {
  margin-top: 4px;
  font-size: 12px;
  color: var(--gray-600);
  line-height: 1.2;
}

.quick-count {
  margin-top: 10px;
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.quick-count-number {
  font-size: 22px;
  font-weight: 700;
  color: var(--gray-1000);
}

.quick-count-unit {
  font-size: 12px;
  color: var(--gray-600);
}

.recent-list {
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  overflow: hidden;
}

.recent-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid var(--gray-100);

  &:last-child {
    border-bottom: none;
  }

  &:hover {
    background: var(--gray-25);
  }
}

.recent-left {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  min-width: 0;
}

.recent-content {
  min-width: 0;
}

.recent-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--gray-1000);
}

.recent-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--gray-600);
}

.dot {
  margin: 0 6px;
}

.recent-time {
  font-size: 12px;
  color: var(--gray-500);
  flex: 0 0 auto;
}
</style>
