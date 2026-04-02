<template>
  <div class="pd-page">
    <div class="pd-top">
      <a-button type="link" class="pd-back" @click="goBack">返回</a-button>
    </div>

    <a-spin :spinning="loading">
      <div class="pd-card">
        <div class="pd-head">
          <div class="pd-title-row">
            <div class="pd-title">{{ record.title }}</div>
            <a-tag class="pd-dept">{{ record.department || '-' }}</a-tag>
          </div>
          <div class="pd-code">末级流程编号：{{ record.code }}</div>
        </div>

        <div class="pd-sections">
          <div class="pd-section">
            <div class="pd-section-title">流程信息</div>
            <div class="pd-grid">
              <div class="pd-kv">
                <div class="k">一级流程</div>
                <div class="v">{{ record.level1_process || '-' }}</div>
              </div>
              <div class="pd-kv">
                <div class="k">二级流程</div>
                <div class="v">{{ record.level2_process || '-' }}</div>
              </div>
              <div class="pd-kv">
                <div class="k">三级流程</div>
                <div class="v">{{ record.level3_process || '-' }}</div>
              </div>
              <div class="pd-kv">
                <div class="k">合规审查责任部门</div>
                <div class="v">{{ record.department || '-' }}</div>
              </div>
              <div class="pd-kv span-2">
                <div class="k">末级流程名称</div>
                <div class="v">{{ record.title || '-' }}</div>
              </div>
              <div class="pd-kv">
                <div class="k">末级流程编号</div>
                <div class="v">{{ record.code || '-' }}</div>
              </div>
              <div class="pd-kv">
                <div class="k">创建时间</div>
                <div class="v">{{ record.created_at || '-' }}</div>
              </div>
              <div class="pd-kv">
                <div class="k">更新时间</div>
                <div class="v">{{ record.updated_at || '-' }}</div>
              </div>
            </div>
          </div>

          <div class="pd-section">
            <div class="pd-section-title">合规重要环节</div>
            <div class="pd-text">{{ normalizeText(record.risk_desc) }}</div>
          </div>

          <div class="pd-section">
            <div class="pd-section-title">合规审查内容</div>
            <div class="pd-text">{{ normalizeText(record.compliance_points) }}</div>
          </div>

          <div class="pd-section">
            <div class="pd-section-title">合规风险点</div>
            <div class="pd-text">{{ normalizeText(record.risk_points) }}</div>
          </div>

          <div class="pd-section">
            <div class="pd-section-title">监督评价要点</div>
            <div class="pd-text">{{ normalizeText(record.measures) }}</div>
          </div>

          <div class="pd-section">
            <div class="pd-section-title">合规义务来源（内外部制度依据）</div>
            <div class="pd-text">
              <div class="pd-blocks">
                <div v-for="(item, idx) in sourceBasisBlocks" :key="idx" class="pd-block">
                  <div class="pd-block-title">{{ item.title }}</div>
                  <div class="pd-block-content">{{ item.content || '-' }}</div>
                </div>
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
const sourceBasisBlocks = computed(() => {
  const basisMap = parseSourceBasisMap(record.value.source_basis)
  return [
    { title: '法律法规、国家政策', content: basisMap.external },
    { title: '内部制度', content: basisMap.internal },
  ]
})

const fetchDetail = async () => {
  const id = Number(route.params.process_id)
  if (!id) return
  loading.value = true
  try {
    const res = await complianceApi.getProcessChecklistDetail(id)
    record.value = res.data || {}
  } catch (error) {
    message.error(error.message || '获取流程详情失败')
  } finally {
    loading.value = false
  }
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
      const hasLeadingNewline = m[0].startsWith('\n')
      matches.push({
        label,
        index: m.index + (hasLeadingNewline ? 1 : 0),
        length: m[0].length - (hasLeadingNewline ? 1 : 0),
      })
    }
  }
  if (matches.length === 0) return []
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

const parseSourceBasisMap = (value) => {
  const sections = parseLabeledSections(value, ['法律法规国家政策', '法律法规、国家政策', '内部制度'])
  const map = { external: '', internal: '' }
  for (const item of sections) {
    if (item.title.includes('内部制度')) {
      map.internal = item.content
      continue
    }
    if (item.title.includes('法律法规国家政策') || item.title.includes('法律法规、国家政策')) {
      map.external = item.content
    }
  }
  if (!map.external && !map.internal) {
    map.external = normalizeText(value) === '-' ? '' : normalizeText(value)
  }
  return map
}

const goBack = () => {
  router.push('/compliance-risk/process-checklist')
}

onMounted(fetchDetail)
</script>

<style scoped lang="less">
.pd-page {
  width: 100%;
}

.pd-top {
  margin-bottom: 10px;
}

.pd-back {
  padding: 0;
  height: auto;
}

.pd-card {
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  padding: 16px;
}

.pd-head {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--gray-100);
}

.pd-title-row {
  display: flex;
  gap: 10px;
  align-items: center;
}

.pd-title {
  font-size: 16px;
  font-weight: 800;
  color: var(--gray-1000);
}

.pd-dept {
  background: rgba(168, 85, 247, 0.1);
  color: #7c3aed;
  border: none;
  border-radius: 10px;
}

.pd-code {
  margin-top: 6px;
  font-size: 12px;
  color: var(--gray-600);
}

.pd-sections {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.pd-section {
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  padding: 14px;
}

.pd-section-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--gray-1000);
  margin-bottom: 10px;
}

.pd-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px 18px;
}

.pd-kv {
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

.pd-text {
  font-size: 13px;
  color: var(--gray-900);
  line-height: 1.65;
  white-space: pre-wrap;
}

.pd-lines {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.pd-line {
  white-space: pre-wrap;
}

.pd-blocks {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.pd-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 10px;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  background: var(--gray-50);
}

.pd-block-title {
  font-size: 12px;
  color: var(--gray-700);
  font-weight: 700;
}

.pd-block-content {
  white-space: pre-wrap;
}
</style>
