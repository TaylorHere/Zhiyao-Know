<template>
  <div class="cr-layout">
    <div class="cr-sider">
      <div class="cr-sider-card">
        <div
          v-for="item in menus"
          :key="item.key"
          class="cr-menu-item"
          :class="{ active: isActive(item) }"
          @click="handleMenuClick(item)"
        >
          {{ item.label }}
        </div>
      </div>
    </div>
    <div class="cr-main">
      <router-view />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'

const route = useRoute()
const router = useRouter()

const menus = computed(() => [
  { key: 'knowledge', label: '合规知识中心', to: '/compliance-risk/knowledge' },
  { key: 'risk-library', label: '合规风险库', to: '/compliance-risk/risk-library' },
  { key: 'process', label: '业务流程管控清单', to: '/compliance-risk/process-checklist' },
  { key: 'position', label: '重要岗位履责合规义务清单', to: '/compliance-risk/position-responsibility' },
  { key: 'import', label: '数据导入', to: '/compliance-risk/data-import' }
])

const isActive = (item) => {
  if (!item.to) return false
  return route.path === item.to || route.path.startsWith(item.to + '/')
}

const handleMenuClick = (item) => {
  if (item.disabled) {
    message.info('暂未开放')
    return
  }
  if (item.to) router.push(item.to)
}
</script>

<style scoped lang="less">
.cr-layout {
  display: flex;
  gap: 16px;
  padding: 16px;
  background-color: var(--gray-25);
  min-height: calc(100vh - 32px);
}

.cr-sider {
  flex: 0 0 220px;
  position: sticky;
  top: 16px;
  align-self: flex-start;
  max-height: calc(100vh - 32px);
}

.cr-sider-card {
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  padding: 10px;
  max-height: calc(100vh - 32px);
  overflow-y: auto;
}

.cr-menu-item {
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 13px;
  color: var(--gray-800);
  cursor: pointer;
  user-select: none;
  transition: background-color 0.15s ease, color 0.15s ease;

  &:hover {
    background: var(--gray-25);
  }

  &.active {
    background: rgba(59, 130, 246, 0.12);
    color: var(--main-color);
    font-weight: 600;
  }
}

.cr-main {
  flex: 1 1 auto;
  min-width: 0;
}

@media (max-width: 1024px) {
  .cr-layout {
    flex-direction: column;
  }
  .cr-sider {
    flex: 0 0 auto;
    position: static;
    max-height: none;
  }
  .cr-sider-card {
    max-height: none;
    overflow: visible;
  }
}
</style>
