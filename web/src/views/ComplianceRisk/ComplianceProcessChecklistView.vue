<template>
  <div class="pc-page">
    <div class="pc-card">
      <div class="pc-head">
        <div class="pc-title">流程管控清单</div>
        <div class="pc-subtitle">通过识别业务流程中的合规风险，设置关键风险点，实现“合规入流程”</div>
      </div>

      <div class="pc-filters">
        <a-input
          v-model:value="filters.keyword"
          placeholder="搜索流程名称、合规要点…"
          class="pc-search"
          allow-clear
          @pressEnter="handleSearch"
        >
          <template #prefix>
            <Search size="16" style="color: var(--gray-400)" />
          </template>
        </a-input>
        <a-button type="primary" @click="handleSearch">搜索</a-button>
        <a-select v-model:value="filters.department" class="pc-select" placeholder="全部部门" allow-clear>
          <a-select-option v-for="dept in departments" :key="dept" :value="dept">{{ dept }}</a-select-option>
        </a-select>
      </div>

      <div class="pc-summary">共 {{ filteredList.length }} 条记录</div>

      <a-spin :spinning="loading">
        <a-pagination
          v-if="filteredList.length > 0"
          class="pc-pagination"
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
        <div class="pc-list-scroll">
          <div class="pc-list">
            <div v-for="row in pagedList" :key="row.id" class="pc-item" @click="openDetail(row)">
              <div class="pc-item-main">
                <div class="pc-item-code">{{ row.code }}</div>
                <div class="pc-item-title">{{ row.title }}</div>
                <div class="pc-item-desc">{{ row.risk_desc }}</div>
                <div class="pc-item-meta">
                  <a-tag class="pc-chip">{{ row.department || '-' }}</a-tag>
                  <span class="pc-split"></span>
                  <span class="pc-owner">负责人：{{ row.owner || '-' }}</span>
                </div>
              </div>
              <ChevronRight class="pc-arrow" size="18" />
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
      (r.risk_desc || '').includes(kw) ||
      (r.compliance_points || []).some((p) => p.includes(kw)) ||
      (r.department || '').includes(kw) ||
      (r.owner || '').includes(kw) ||
      (r.code || '').includes(kw)
    const hitDept = !filters.value.department || r.department === filters.value.department
    return hitKw && hitDept
  })
})

const pagedList = computed(() => {
  const start = (pagination.value.current - 1) * pagination.value.pageSize
  const end = start + pagination.value.pageSize
  return filteredList.value.slice(start, end)
})

const fetchList = async () => {
  loading.value = true
  try {
    const res = await complianceApi.getProcessChecklist()
    list.value = res.data || []
  } catch (error) {
    message.error(error.message || '获取流程清单失败')
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
  router.push(`/compliance-risk/process-checklist/${row.id}`)
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
  () => filters.value.department,
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
.pc-page {
  width: 100%;
}

.pc-card {
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  height: calc(100vh - 72px);
}

.pc-head {
  margin-bottom: 12px;
}

.pc-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--gray-1000);
}

.pc-subtitle {
  margin-top: 6px;
  font-size: 12px;
  color: var(--gray-600);
}

.pc-filters {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-top: 12px;
  flex-wrap: wrap;
}

.pc-search {
  flex: 1 1 380px;
  min-width: 260px;
  :deep(.ant-input-affix-wrapper) {
    border-radius: 10px;
  }
}

.pc-select {
  width: 320px;
  max-width: 100%;
}

.pc-summary {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--gray-100);
  font-size: 12px;
  color: var(--gray-600);
}

.pc-list {
  margin-top: 0;
}

.pc-pagination {
  margin-top: 10px;
  margin-bottom: 10px;
  display: flex;
  justify-content: flex-end;
}

.pc-list-scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  padding-right: 4px;
}

.pc-card :deep(.ant-spin-nested-loading) {
  flex: 1;
  min-height: 0;
}

.pc-card :deep(.ant-spin-container) {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.pc-item {
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

.pc-item-code {
  font-size: 12px;
  font-weight: 700;
  color: var(--gray-600);
}

.pc-item-title {
  margin-top: 6px;
  font-size: 14px;
  font-weight: 700;
  color: var(--gray-1000);
}

.pc-item-desc {
  margin-top: 6px;
  font-size: 12px;
  color: var(--gray-700);
  line-height: 1.5;
}

.pc-item-meta {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--gray-600);
  flex-wrap: wrap;
}

.pc-chip {
  background: rgba(168, 85, 247, 0.1);
  color: #7c3aed;
  border: none;
}

.pc-split {
  width: 1px;
  height: 12px;
  background: var(--gray-200);
}

.pc-arrow {
  color: var(--gray-400);
  flex: 0 0 auto;
  margin-top: 4px;
}

@media (max-width: 1024px) {
  .pc-card {
    height: auto;
  }
  .pc-search {
    flex-basis: 100%;
  }
  .pc-list-scroll {
    flex: none;
    overflow: visible;
    padding-right: 0;
  }
}
</style>
