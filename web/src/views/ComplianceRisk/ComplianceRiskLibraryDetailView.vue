<template>
  <div class="rd-page">
    <div class="rd-top">
      <a-button type="link" class="rd-back" @click="goBack">返回</a-button>
    </div>

    <a-spin :spinning="loading">
      <div class="rd-card">
        <div class="rd-head">
          <div class="rd-title-row">
            <div class="rd-title">{{ record.title }}</div>
            <a-tag :color="levelColor">{{ record.level || '未分级' }}</a-tag>
          </div>
          <div class="rd-code">风险行为编号：{{ record.code }}</div>
        </div>

        <div class="rd-sections">
          <div class="rd-section">
            <div class="rd-section-title">基础信息</div>
            <div class="rd-grid">
              <div class="rd-kv">
                <div class="k">一级业务</div>
                <div class="v">{{ record.business_lv1 || '-' }}</div>
              </div>
              <div class="rd-kv">
                <div class="k">二级业务</div>
                <div class="v">{{ record.business_lv2 || '-' }}</div>
              </div>
              <div class="rd-kv span-2">
                <div class="k">合规风险名称</div>
                <div class="v">{{ record.title || '-' }}</div>
              </div>
              <div class="rd-kv">
                <div class="k">风险行为编号</div>
                <div class="v">{{ record.code || '-' }}</div>
              </div>
              <div class="rd-kv">
                <div class="k">风险等级</div>
                <div class="v">{{ record.level || '-' }}</div>
              </div>
              <div class="rd-kv">
                <div class="k">创建时间</div>
                <div class="v">{{ record.created_at || '-' }}</div>
              </div>
              <div class="rd-kv">
                <div class="k">更新时间</div>
                <div class="v">{{ record.updated_at || '-' }}</div>
              </div>
            </div>
          </div>

          <div class="rd-section">
            <div class="rd-section-title">风险信息</div>
            <div class="rd-grid">
              <div class="rd-kv span-2">
                <div class="k">风险行为描述</div>
                <div class="v">{{ record.desc || '-' }}</div>
              </div>
              <div class="rd-kv span-2">
                <div class="k">责任或后果</div>
                <div class="v">{{ record.consequence || '-' }}</div>
              </div>
              <div class="rd-kv">
                <div class="k">底线</div>
                <div class="v">{{ record.bottom_line || '-' }}</div>
              </div>
            </div>
          </div>

          <div class="rd-section">
            <div class="rd-section-title">合规依据</div>
            <div class="rd-text">
              <div class="rd-blocks">
                <div v-for="label in basisLabels" :key="label" class="rd-block">
                  <div class="rd-block-title">{{ label }}</div>
                  <div class="rd-block-content">{{ basisSectionMap[label] || '-' }}</div>
                </div>
                <div v-for="(item, idx) in basisExtraBlocks" :key="`extra-${idx}`" class="rd-block">
                  <div class="rd-block-title">{{ item.title }}</div>
                  <div class="rd-block-content">{{ item.content }}</div>
                </div>
              </div>
            </div>
          </div>

          <div class="rd-section">
            <div class="rd-section-title">合规义务</div>
            <div class="rd-text">{{ normalizeText(record.obligation) }}</div>
          </div>

          <div class="rd-section">
            <div class="rd-section-title">风险控制措施</div>
            <div class="rd-text">
              <div v-if="(record.measures || []).length > 0" class="rd-lines">
                <div v-for="(m, idx) in record.measures || []" :key="idx" class="rd-line">{{ m }}</div>
              </div>
              <div v-else>-</div>
            </div>
          </div>

          <div class="rd-section">
            <div class="rd-section-title">部门信息</div>
            <div class="rd-grid">
              <div class="rd-kv">
                <div class="k">归口部门</div>
                <div class="v">{{ record.department || '-' }}</div>
              </div>
              <div class="rd-kv">
                <div class="k">配合部门</div>
                <div class="v">{{ record.cooperate_department || '-' }}</div>
              </div>
            </div>
          </div>

          <div class="rd-section">
            <div class="rd-section-title">管理信息</div>
            <div class="rd-grid">
              <div class="rd-kv">
                <div class="k">风险编号</div>
                <div class="v">{{ record.code }}</div>
              </div>
              <div class="rd-kv">
                <div class="k">备注</div>
                <div class="v">{{ record.remark || '-' }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <a-empty v-if="!loading && !record.id" description="记录不存在" />
    </a-spin>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'

import { complianceApi } from '@/apis/compliance_api'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const record = ref({})

const levelColor = computed(() => {
  if (record.value.level === '高风险') return 'red'
  if (record.value.level === '中风险') return 'orange'
  if (record.value.level === '低风险') return 'green'
  return 'default'
})

const basisLabels = ['国家政策', '法律法规', '监管规定', '行业准则', '规章制度', '其他']
const basisSectionMap = computed(() => {
  const sections = parseLabeledSections(record.value.basis, basisLabels)
  const map = {}
  for (const item of sections) {
    map[item.title] = item.content
  }
  return map
})
const basisExtraBlocks = computed(() => {
  const sections = parseLabeledSections(record.value.basis, basisLabels)
  return sections.filter((item) => !basisLabels.includes(item.title))
})

const fetchDetail = async () => {
  const id = Number(route.params.risk_id)
  if (!id) return
  loading.value = true
  try {
    const res = await complianceApi.getRiskLibraryDetail(id)
    record.value = res.data || {}
  } catch (error) {
    message.error(error.message || '获取风险详情失败')
  } finally {
    loading.value = false
  }
}

const splitTextBlocks = (value) => {
  const raw = String(value || '')
    .replace(/\r/g, '')
    .trim()
  if (!raw) return []

  const lines = raw
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  if (lines.length === 0) return []

  const isItemStart = (line) => /^(?:\d+[.、]|[（(]?\d+[）)]|[一二三四五六七八九十]+[、.])/.test(line)
  const items = []
  let current = ''
  for (const line of lines) {
    if (isItemStart(line)) {
      if (current) items.push(current.trim())
      current = line
      continue
    }
    if (current) {
      current += `\n${line}`
    } else {
      items.push(line)
    }
  }
  if (current) items.push(current.trim())

  if (items.length <= 1) {
    const sentenceParts = raw
      .split(/；|;/)
      .map((part) => part.trim())
      .filter(Boolean)
    if (sentenceParts.length > 1) return sentenceParts
  }
  return items
}

const normalizeText = (value) => {
  if (Array.isArray(value)) {
    const lines = value.map((item) => String(item || '').trim()).filter(Boolean)
    return lines.length > 0 ? lines.join('\n') : '-'
  }
  const text = String(value || '').trim()
  return text || '-'
}

const parseLabeledSections = (value, labels) => {
  const raw = String(value || '')
    .replace(/\r/g, '')
    .trim()
  if (!raw) return []

  const matches = []
  for (const label of labels) {
    const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const regex = new RegExp(`(?:^|\\n)${escaped}[:：]\\s*`, 'g')
    let m
    while ((m = regex.exec(raw)) !== null) {
      matches.push({ label, index: m.index + (m[0].startsWith('\n') ? 1 : 0), length: m[0].length - (m[0].startsWith('\n') ? 1 : 0) })
    }
  }
  if (matches.length === 0) {
    return splitTextBlocks(raw).map((content) => ({ title: '未分类内容', content }))
  }
  matches.sort((a, b) => a.index - b.index)

  const sections = []
  for (let i = 0; i < matches.length; i++) {
    const cur = matches[i]
    const contentStart = cur.index + cur.length
    const contentEnd = i + 1 < matches.length ? matches[i + 1].index : raw.length
    const content = raw.slice(contentStart, contentEnd).trim()
    if (content) {
      sections.push({ title: cur.label, content })
    }
  }
  return sections
}

const goBack = () => {
  router.push('/compliance-risk/risk-library')
}

onMounted(fetchDetail)
</script>

<style scoped lang="less">
.rd-page {
  width: 100%;
}

.rd-top {
  margin-bottom: 10px;
}

.rd-back {
  padding: 0;
  height: auto;
}

.rd-card {
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  padding: 16px;
}

.rd-head {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--gray-100);
}

.rd-title-row {
  display: flex;
  gap: 10px;
  align-items: center;
}

.rd-title {
  font-size: 16px;
  font-weight: 800;
  color: var(--gray-1000);
}

.rd-code {
  margin-top: 6px;
  font-size: 12px;
  color: var(--gray-600);
}

.rd-sections {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.rd-section {
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  padding: 14px;
}

.rd-section-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--gray-1000);
  margin-bottom: 10px;
}

.rd-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px 18px;
}

.rd-kv {
  .k {
    font-size: 12px;
    color: var(--gray-500);
    margin-bottom: 6px;
  }
  .v {
    font-size: 13px;
    color: var(--gray-900);
    line-height: 1.55;
  }
}

.span-2 {
  grid-column: 1 / 3;
}

.rd-text {
  font-size: 13px;
  color: var(--gray-900);
  line-height: 1.65;
  white-space: pre-wrap;
}

.rd-lines {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.rd-line {
  white-space: pre-wrap;
}

.rd-blocks {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.rd-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 10px;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  background: var(--gray-50);
}

.rd-block-title {
  font-size: 12px;
  color: var(--gray-700);
  font-weight: 700;
}

.rd-block-content {
  white-space: pre-wrap;
}
</style>
