<template>
  <div class="gd-page">
    <div class="gd-top">
      <a-button type="link" class="gd-back" @click="goBack">返回</a-button>
    </div>

    <a-spin :spinning="loading">
      <div class="gd-card">
        <div class="gd-head">
          <div class="gd-title-row">
            <div class="gd-title">{{ record.title }}</div>
            <a-tag class="gd-dept">{{ record.department || '-' }}</a-tag>
          </div>
        </div>

        <div class="gd-sections">
          <div class="gd-section">
            <div class="gd-section-title">岗位信息</div>
            <div class="gd-grid">
              <div class="gd-kv">
                <div class="k">岗位名称</div>
                <div class="v">{{ record.title || '-' }}</div>
              </div>
              <div class="gd-kv">
                <div class="k">部门名称</div>
                <div class="v">{{ record.department || '-' }}</div>
              </div>
              <div class="gd-kv">
                <div class="k">创建时间</div>
                <div class="v">{{ record.created_at || '-' }}</div>
              </div>
              <div class="gd-kv">
                <div class="k">更新时间</div>
                <div class="v">{{ record.updated_at || '-' }}</div>
              </div>
            </div>
          </div>

          <div class="gd-section">
            <div class="gd-section-title">风险内控合规职责</div>
            <div class="gd-text">{{ normalizeText(record.responsibilities) }}</div>
          </div>

          <div class="gd-section">
            <div class="gd-section-title">合规底线清单</div>
            <div class="gd-text">{{ normalizeText(record.compliance_points) }}</div>
          </div>

          <div class="gd-section">
            <div class="gd-section-title">底线标准与处罚</div>
            <div class="gd-text">{{ normalizeText(record.bottom_line_penalty) }}</div>
          </div>

          <div class="gd-section">
            <div class="gd-section-title">制度依据</div>
            <div class="gd-text">{{ normalizeText(record.related_risks) }}</div>
          </div>

          <div class="gd-section">
            <div class="gd-section-title">合规义务来源（内外部制度依据）</div>
            <div class="gd-text">
              <div class="gd-blocks">
                <div v-for="(item, idx) in sourceBasisBlocks" :key="idx" class="gd-block">
                  <div class="gd-block-title">{{ item.title }}</div>
                  <div class="gd-block-content">{{ item.content || '-' }}</div>
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
  const id = Number(route.params.position_id)
  if (!id) return
  loading.value = true
  try {
    const res = await complianceApi.getPositionResponsibilityDetail(id)
    record.value = res.data || {}
  } catch (error) {
    message.error(error.message || '获取岗位详情失败')
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
  router.push('/compliance-risk/position-responsibility')
}

onMounted(fetchDetail)
</script>

<style scoped lang="less">
.gd-page {
  width: 100%;
}

.gd-top {
  margin-bottom: 10px;
}

.gd-back {
  padding: 0;
  height: auto;
}

.gd-card {
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  padding: 16px;
}

.gd-head {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--gray-100);
}

.gd-title-row {
  display: flex;
  gap: 10px;
  align-items: center;
}

.gd-title {
  font-size: 16px;
  font-weight: 800;
  color: var(--gray-1000);
}

.gd-dept {
  background: rgba(34, 197, 94, 0.1);
  color: #16a34a;
  border: none;
  border-radius: 10px;
}

.gd-code {
  margin-top: 6px;
  font-size: 12px;
  color: var(--gray-600);
}

.gd-sections {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.gd-section {
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  padding: 14px;
}

.gd-section-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--gray-1000);
  margin-bottom: 10px;
}

.gd-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px 18px;
}

.gd-kv {
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

.gd-text {
  font-size: 13px;
  color: var(--gray-900);
  line-height: 1.65;
  white-space: pre-wrap;
}

.gd-lines {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.gd-line {
  white-space: pre-wrap;
}

.gd-blocks {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.gd-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 10px;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  background: var(--gray-50);
}

.gd-block-title {
  font-size: 12px;
  color: var(--gray-700);
  font-weight: 700;
}

.gd-block-content {
  white-space: pre-wrap;
}
</style>
