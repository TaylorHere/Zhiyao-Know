<template>
  <div class="pr-page">
    <div class="pr-card">
      <div class="pr-head">
        <div class="pr-title">岗位职责清单</div>
        <div class="pr-subtitle">以岗位职责将管控措施落实到岗位，实现“事事有人管、人人都尽责”</div>
      </div>

      <div class="pr-filters">
        <a-input
          v-model:value="filters.keyword"
          placeholder="搜索岗位名称、职责…"
          class="pr-search"
          allow-clear
          @pressEnter="handleSearch"
        >
          <template #prefix>
            <Search size="16" style="color: var(--gray-400)" />
          </template>
        </a-input>
        <a-button type="primary" @click="handleSearch">搜索</a-button>
        <a-select v-model:value="filters.department" class="pr-select" placeholder="全部部门" allow-clear>
          <a-select-option v-for="dept in departments" :key="dept" :value="dept">{{ dept }}</a-select-option>
        </a-select>
      </div>

      <div class="pr-summary">共 {{ filteredList.length }} 条记录</div>

      <a-spin :spinning="loading">
        <a-pagination
          v-if="filteredList.length > 0"
          class="pr-pagination"
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
        <div class="pr-list-scroll">
          <div class="pr-list">
            <div v-for="row in pagedList" :key="row.id" class="pr-item" @click="openDetail(row)">
              <div class="pr-item-main">
                <div class="pr-item-code">{{ row.code }}</div>
                <div class="pr-item-title">{{ row.title }}</div>
                <div class="pr-item-tags">
                  <a-tag class="tag-dept">{{ row.department || '-' }}</a-tag>
                  <a-tag class="tag-type">{{ row.compliance_type || '-' }}</a-tag>
                </div>
              </div>
              <ChevronRight class="pr-arrow" size="18" />
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
      (r.department || '').includes(kw) ||
      (r.compliance_type || '').includes(kw) ||
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
    const res = await complianceApi.getPositionResponsibility()
    list.value = res.data || []
  } catch (error) {
    message.error(error.message || '获取岗位职责清单失败')
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
  router.push(`/compliance-risk/position-responsibility/${row.id}`)
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
.pr-page {
  width: 100%;
}

.pr-card {
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  height: calc(100vh - 72px);
}

.pr-head {
  margin-bottom: 12px;
}

.pr-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--gray-1000);
}

.pr-subtitle {
  margin-top: 6px;
  font-size: 12px;
  color: var(--gray-600);
}

.pr-filters {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-top: 12px;
  flex-wrap: wrap;
}

.pr-search {
  flex: 1 1 380px;
  min-width: 260px;
  :deep(.ant-input-affix-wrapper) {
    border-radius: 10px;
  }
}

.pr-select {
  width: 320px;
  max-width: 100%;
}

.pr-summary {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--gray-100);
  font-size: 12px;
  color: var(--gray-600);
}

.pr-list {
  margin-top: 0;
}

.pr-pagination {
  margin-top: 10px;
  margin-bottom: 10px;
  display: flex;
  justify-content: flex-end;
}

.pr-list-scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  padding-right: 4px;
}

.pr-card :deep(.ant-spin-nested-loading) {
  flex: 1;
  min-height: 0;
}

.pr-card :deep(.ant-spin-container) {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.pr-item {
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

.pr-item-code {
  font-size: 12px;
  font-weight: 700;
  color: var(--gray-600);
}

.pr-item-title {
  margin-top: 6px;
  font-size: 14px;
  font-weight: 700;
  color: var(--gray-1000);
}

.pr-item-tags {
  margin-top: 8px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.tag-dept {
  background: rgba(34, 197, 94, 0.1);
  color: #16a34a;
  border: none;
}

.tag-type {
  background: rgba(59, 130, 246, 0.08);
  color: var(--gray-700);
  border: none;
}

.pr-arrow {
  color: var(--gray-400);
  flex: 0 0 auto;
  margin-top: 4px;
}

@media (max-width: 1024px) {
  .pr-card {
    height: auto;
  }
  .pr-list-scroll {
    flex: none;
    overflow: visible;
    padding-right: 0;
  }
}
</style>
