<template>
  <div class="rl-page">
    <div class="rl-card">
      <div class="rl-head">
        <div class="rl-title">合规风险库</div>
        <div class="rl-subtitle">合规管理工作基础，对工作中的合规风险点进行系统梳理和分级管控</div>
      </div>

      <div class="rl-filters">
        <a-input
          v-model:value="filters.keyword"
          placeholder="搜索风险描述、业务类型…"
          class="rl-search"
          allow-clear
          @pressEnter="handleSearch"
        >
          <template #prefix>
            <Search size="16" style="color: var(--gray-400)" />
          </template>
        </a-input>
        <a-button type="primary" @click="handleSearch">搜索</a-button>
        <a-select v-model:value="filters.level" class="rl-select" placeholder="全部等级" allow-clear>
          <a-select-option value="高风险">高风险</a-select-option>
          <a-select-option value="中风险">中风险</a-select-option>
          <a-select-option value="低风险">低风险</a-select-option>
        </a-select>
        <a-select v-model:value="filters.department" class="rl-select" placeholder="全部部门" allow-clear>
          <a-select-option v-for="dept in departments" :key="dept" :value="dept">{{ dept }}</a-select-option>
        </a-select>
      </div>

      <div class="rl-summary">共 {{ filteredList.length }} 条记录</div>

      <a-spin :spinning="loading">
        <a-pagination
          v-if="filteredList.length > 0"
          class="rl-pagination"
          size="small"
          :current="pagination.current"
          :page-size="pagination.pageSize"
          :total="filteredList.length"
          :show-size-changer="true"
          :page-size-options="['10', '20', '50', '100']"
          :show-total="(total) => `共 ${total} 条`"
          @change="handlePageChange"
          @showSizeChange="handlePageChange"
        />
        <div class="rl-list-scroll">
          <div class="rl-list">
            <div v-for="row in pagedList" :key="row.id" class="rl-item" @click="openDetail(row)">
              <div class="rl-item-main">
                <div class="rl-item-top">
                  <a-tag :color="levelColor(row.level)" class="rl-tag">{{ row.level || '未分级' }}</a-tag>
                  <a-tag color="blue" class="rl-tag">{{ row.category || '综合合规' }}</a-tag>
                </div>
                <div class="rl-item-title">{{ row.title }}</div>
                <div class="rl-item-desc">{{ row.desc }}</div>
                <div class="rl-item-chips">
                  <a-tag v-for="chip in row.chips || []" :key="chip" class="rl-chip">{{ chip }}</a-tag>
                </div>
              </div>

              <div class="rl-item-side">
                <a-tag color="blue" class="rl-code">{{ row.code }}</a-tag>
                <ChevronRight class="rl-arrow" size="18" />
              </div>
            </div>
            <a-empty v-if="!loading && filteredList.length === 0" description="暂无数据" />
          </div>
        </div>
      </a-spin>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { Search, ChevronRight } from 'lucide-vue-next'

import { complianceApi } from '@/apis/compliance_api'

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const list = ref([])
const pagination = ref({
  current: 1,
  pageSize: 20
})

const filters = ref({
  keyword: '',
  level: undefined,
  department: undefined
})

const departments = computed(() => {
  return [...new Set((list.value || []).map((item) => item.department).filter(Boolean))]
})

const filteredList = computed(() => {
  const kw = (filters.value.keyword || '').trim()
  return (list.value || []).filter((r) => {
    const hitKw =
      !kw ||
      (r.title || '').includes(kw) ||
      (r.desc || '').includes(kw) ||
      (r.category || '').includes(kw) ||
      (r.code || '').includes(kw) ||
      (r.chips || []).some((c) => c.includes(kw))
    const hitLevel = !filters.value.level || r.level === filters.value.level
    const hitDept = !filters.value.department || r.department === filters.value.department
    return hitKw && hitLevel && hitDept
  })
})

const pagedList = computed(() => {
  const start = (pagination.value.current - 1) * pagination.value.pageSize
  const end = start + pagination.value.pageSize
  return filteredList.value.slice(start, end)
})

const levelColor = (level) => {
  if (level === '高风险') return 'red'
  if (level === '中风险') return 'orange'
  if (level === '低风险') return 'green'
  return 'default'
}

const fetchList = async () => {
  loading.value = true
  try {
    const res = await complianceApi.getRiskLibrary()
    list.value = res.data || []
  } catch (error) {
    message.error(error.message || '获取风险库失败')
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  pagination.value.current = 1
}

const handlePageChange = (page, pageSize) => {
  pagination.value.current = page
  pagination.value.pageSize = pageSize
}

const openDetail = (row) => {
  router.push(`/compliance-risk/risk-library/${row.id}`)
}

onMounted(fetchList)

watch(
  () => route.query.keyword,
  (value) => {
    filters.value.keyword = typeof value === 'string' ? value : ''
    pagination.value.current = 1
  },
  { immediate: true }
)

watch(
  () => [filters.value.level, filters.value.department],
  () => {
    pagination.value.current = 1
  }
)

watch(
  () => filteredList.value.length,
  (total) => {
    const maxPage = Math.max(1, Math.ceil(total / pagination.value.pageSize))
    if (pagination.value.current > maxPage) {
      pagination.value.current = maxPage
    }
  }
)
</script>

<style scoped lang="less">
.rl-page {
  width: 100%;
}

.rl-card {
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  height: calc(100vh - 72px);
}

.rl-head {
  margin-bottom: 12px;
}

.rl-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--gray-1000);
}

.rl-subtitle {
  margin-top: 6px;
  font-size: 12px;
  color: var(--gray-600);
}

.rl-filters {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-top: 12px;
  flex-wrap: wrap;
}

.rl-search {
  flex: 1 1 360px;
  min-width: 260px;
  :deep(.ant-input-affix-wrapper) {
    border-radius: 10px;
  }
}

.rl-select {
  width: 320px;
  max-width: 100%;
}

.rl-summary {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--gray-100);
  font-size: 12px;
  color: var(--gray-600);
}

.rl-list {
  margin-top: 0;
}

.rl-pagination {
  margin-top: 10px;
  margin-bottom: 10px;
  display: flex;
  justify-content: flex-end;
}

.rl-list-scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  padding-right: 4px;
}

.rl-card :deep(.ant-spin-nested-loading) {
  flex: 1;
  min-height: 0;
}

.rl-card :deep(.ant-spin-container) {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.rl-item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 8px;
  border-bottom: 1px solid var(--gray-100);
  cursor: pointer;

  &:last-child {
    border-bottom: none;
  }

  &:hover {
    background: var(--gray-25);
    border-radius: 10px;
  }
}

.rl-item-main {
  min-width: 0;
}

.rl-item-top {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.rl-tag {
  border-radius: 10px;
}

.rl-item-title {
  margin-top: 6px;
  font-size: 14px;
  font-weight: 700;
  color: var(--gray-1000);
}

.rl-item-desc {
  margin-top: 6px;
  font-size: 12px;
  color: var(--gray-700);
  line-height: 1.5;
}

.rl-item-chips {
  margin-top: 8px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.rl-chip {
  background: rgba(59, 130, 246, 0.08);
  color: var(--gray-700);
  border: none;
  border-radius: 10px;
}

.rl-item-side {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}

.rl-code {
  border-radius: 10px;
}

.rl-arrow {
  color: var(--gray-400);
}

@media (max-width: 1024px) {
  .rl-card {
    height: auto;
  }
  .rl-list-scroll {
    flex: none;
    overflow: visible;
    padding-right: 0;
  }
}
</style>
