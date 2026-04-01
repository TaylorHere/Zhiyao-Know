<template>
  <div class="database-container layout-container">
    <!-- 新建知识库弹窗 -->
    <a-modal
      :open="state.openNewDatabaseModel"
      title="新建知识库"
      :confirm-loading="dbState.creating"
      @ok="handleCreateDatabase"
      @cancel="cancelCreateDatabase"
      class="new-database-modal"
      width="800px"
      destroyOnClose
    >
      <!-- 知识库类型选择 -->
      <h3>知识库类型<span style="color: var(--color-error-500)">*</span></h3>
      <div class="kb-type-cards">
        <div
          v-for="(typeInfo, typeKey) in orderedKbTypes"
          :key="typeKey"
          class="kb-type-card"
          :class="{ active: newDatabase.kb_type === typeKey }"
          :data-type="typeKey"
          @click="handleKbTypeChange(typeKey)"
        >
          <div class="card-header">
            <component :is="getKbTypeIcon(typeKey)" class="type-icon" />
            <span class="type-title">{{ getKbTypeLabel(typeKey) }}</span>
          </div>
          <div class="card-description">{{ typeInfo.description }}</div>
        </div>
      </div>

      <h3>知识库名称<span style="color: var(--color-error-500)">*</span></h3>
      <a-input v-model:value="newDatabase.name" placeholder="新建知识库名称" size="large" />

      <h3>嵌入模型</h3>
      <EmbeddingModelSelector
        v-model:value="newDatabase.embed_model_name"
        style="width: 100%"
        size="large"
        placeholder="请选择嵌入模型"
      />

      <!-- 仅对 LightRAG 提供语言选择和LLM选择 -->
      <div v-if="newDatabase.kb_type === 'lightrag'">
        <h3 style="margin-top: 20px">语言</h3>
        <a-select
          v-model:value="newDatabase.language"
          :options="languageOptions"
          style="width: 100%"
          size="large"
          :dropdown-match-select-width="false"
        />

        <h3 style="margin-top: 20px">语言模型 (LLM)</h3>
        <p style="color: var(--gray-700); font-size: 14px">可以在设置中配置语言模型</p>
        <ModelSelectorComponent
          :model_spec="llmModelSpec"
          placeholder="请选择模型"
          @select-model="handleLLMSelect"
          size="large"
          style="width: 100%; height: 60px"
        />
      </div>

      <h3 style="margin-top: 20px">知识库描述</h3>
      <p style="color: var(--gray-700); font-size: 14px">
        在智能体流程中，这里的描述会作为工具的描述。智能体会根据知识库的标题和描述来选择合适的工具。所以这里描述的越详细，智能体越容易选择到合适的工具。
      </p>
      <AiTextarea
        v-model="newDatabase.description"
        :name="newDatabase.name"
        placeholder="新建知识库描述"
        :auto-size="{ minRows: 3, maxRows: 10 }"
      />

      <!-- 共享配置 -->
      <h3>共享设置</h3>
      <ShareConfigForm v-model="shareConfig" :auto-select-user-dept="true" />
      <template #footer>
        <a-button key="back" @click="cancelCreateDatabase">取消</a-button>
        <a-button
          key="submit"
          type="primary"
          :loading="dbState.creating"
          @click="handleCreateDatabase"
          >创建</a-button
        >
      </template>
    </a-modal>

    <!-- 选择知识库弹窗 -->
    <a-modal
      v-model:open="state.selectDatabaseModalVisible"
      title="选择知识库"
      :footer="null"
      width="500px"
      destroyOnClose
      @cancel="tempSelectedDatabaseIdForUpload = null"
    >
      <div class="select-database-modal">
        <div class="selected-files-info">
          <component :is="getUploadIcon()" class="file-icon" />
          <div class="file-info">
            <div class="file-count">
              您已选择{{ selectedFiles.length }}个{{ uploadType === 'folder' ? '文件夹' : '文件' }}
            </div>
            <div class="file-names" v-if="selectedFiles.length <= 3">
              <span v-for="(file, index) in selectedFiles" :key="index" class="file-name">
                {{ file.name }}
                <span v-if="index < selectedFiles.length - 1">、</span>
              </span>
            </div>
            <div class="file-names" v-else>
              <span v-for="(file, index) in selectedFiles.slice(0, 2)" :key="index" class="file-name">
                {{ file.name }}<span v-if="index < 1">、</span>
              </span>
              等{{ selectedFiles.length }}个{{ uploadType === 'folder' ? '文件夹' : '文件' }}
            </div>
          </div>
        </div>
        <div class="database-select-label">请选择上传的知识库</div>
        <a-select
          v-model:value="tempSelectedDatabaseIdForUpload"
          placeholder="请选择知识库"
          size="large"
          style="width: 100%"
          :options="databaseOptions"
        />
        <div class="auto-index-toggle" style="margin-top: 16px;">
          <!-- <a-checkbox v-model:checked="autoIndex">上传后自动入库</a-checkbox> -->
        </div>
        <div class="modal-actions">
          <a-button @click="state.selectDatabaseModalVisible = false">取消</a-button>
          <a-button type="primary" @click="confirmUpload" :loading="uploading">确定</a-button>
        </div>
      </div>
    </a-modal>

    <!-- 上传进度窗口 -->
    <div v-if="uploadTasks.length > 0" class="upload-progress-window">
      <div class="upload-progress-header">
        <a-tabs v-model:activeKey="uploadTabActiveKey" size="small" style="flex: 1">
          <a-tab-pane :key="'uploading'" :tab="`上传中(${uploadingCount})`" />
          <a-tab-pane :key="'completed'" :tab="`已完成(${completedCount})`" />
        </a-tabs>
        <div class="header-actions">
          <a-button type="text" size="small" @click="pauseAllUploads" v-if="uploadingCount > 0">
            全部暂停
          </a-button>
          <a-button type="text" size="small" @click="collapseUploadWindow" class="collapse-btn">
            收起
          </a-button>
        </div>
      </div>
      <div class="upload-progress-content">
        <div
          v-for="task in filteredUploadTasks"
          :key="task.id"
          class="upload-task-item"
        >
          <div class="file-icon-wrapper">
            <component :is="getFileIcon(task.fileName)" class="file-icon" />
          </div>
          <div class="file-info">
            <div class="file-name">{{ task.fileName }}</div>
            <div class="file-size">{{ formatFileSize(task.size) }}</div>
          </div>
          <div class="upload-status">
            <a-progress
              :percent="task.progress"
              :status="task.status === 'error' ? 'exception' : 'active'"
              :stroke-width="4"
              style="width: 200px"
            />
            <span class="status-text">{{ getStatusText(task) }}</span>
          </div>
          <a-button
            type="text"
            size="small"
            @click="pauseUpload(task.id)"
            v-if="task.status === 'uploading'"
          >
            <PauseCircleOutlined />
          </a-button>
        </div>
      </div>
    </div>

    <!-- 主布局：左右分栏 -->
    <div class="unified-layout">
      <!-- 左侧：知识库列表 -->
      <div class="database-sidebar">
        <div class="sidebar-header">
          <Folder class="header-icon" />
          <span class="header-title">知识库</span>
          <a-button
            type="text"
            size="small"
            class="header-add-btn"
            @click="state.openNewDatabaseModel = true"
            title="新建知识库"
          >
            <PlusOutlined />
          </a-button>
        </div>
        <div v-if="dbState.listLoading" class="loading-state">
          <a-spin size="small" />
          <span>加载中...</span>
        </div>
        <div v-else-if="!databases || databases.length === 0" class="empty-state-sidebar">
          <span>暂无知识库</span>
        </div>
        <div v-else class="database-list">
          <div
            v-for="database in databases"
            :key="database.db_id"
            class="database-item"
            :class="{ active: selectedDatabaseId === database.db_id }"
            @click="selectDatabase(database.db_id)"
          >
            <a-tooltip :title="database.name" placement="right">
              <span class="database-name">{{ database.name }}</span>
            </a-tooltip>
          </div>
        </div>
      </div>

      <!-- 右侧：内容区域 -->
      <div class="database-content">
        <!-- 未选中知识库：显示操作卡片 -->
        <div
          v-if="!selectedDatabaseId"
          class="content-empty"
          @drop="handleDrop"
          @dragover.prevent
          @dragenter.prevent
        >
          <div class="upload-hint">
            <p class="hint-text">将文件或文件夹拖到这里</p>
            <p class="hint-or">或者</p>
          </div>
          <div class="action-cards">
            <div class="action-card" @click="state.openNewDatabaseModel = true">
              <div class="card-icon new-kb-icon">
                <component :is="getKbTypeIcon('milvus')" />
              </div>
              <div class="card-title">新建知识库</div>
            </div>
            <div class="action-card" @click="triggerFileUpload">
              <div class="card-icon upload-file-icon">
                <FileUp />
              </div>
              <div class="card-title">上传文件</div>
            </div>
            <div class="action-card" @click="triggerFolderUpload">
              <div class="card-icon upload-folder-icon">
                <FolderUp />
              </div>
              <div class="card-title">上传文件夹</div>
            </div>
          </div>
        </div>

        <!-- 已选中知识库：显示文件列表 -->
        <div v-else class="content-with-database">
          <FileTable :database-id="selectedDatabaseId" :right-panel-visible="false" />
        </div>
      </div>
    </div>

    <!-- 隐藏的文件输入 -->
    <input
      ref="fileInputRef"
      type="file"
      multiple
      style="display: none"
      @change="handleFileSelect"
    />
    <input
      ref="folderInputRef"
      type="file"
      webkitdirectory
      multiple
      style="display: none"
      @change="handleFolderSelect"
    />

    <!-- 文件详情弹窗 -->
    <FileDetailModal />
  </div>
</template>

<script setup>
import { ref, onMounted, reactive, watch, computed, onBeforeUnmount, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useConfigStore } from '@/stores/config'
import { useDatabaseStore } from '@/stores/database'
import { useTaskerStore } from '@/stores/tasker'
import { useUserStore } from '@/stores/user'
import { message } from 'ant-design-vue'
import { PauseCircleOutlined, PlusOutlined } from '@ant-design/icons-vue'
import { Folder, FileUp, FolderUp, FileText, File } from 'lucide-vue-next'
import { typeApi, fileApi } from '@/apis/knowledge_api'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import EmbeddingModelSelector from '@/components/EmbeddingModelSelector.vue'
import ShareConfigForm from '@/components/ShareConfigForm.vue'
import FileTable from '@/components/FileTable.vue'
import FileDetailModal from '@/components/FileDetailModal.vue'
import { parseToShanghai } from '@/utils/time'
import AiTextarea from '@/components/AiTextarea.vue'
import { getKbTypeLabel, getKbTypeIcon, getKbTypeColor } from '@/utils/kb_utils'
import { getFileIcon, formatFileSize } from '@/utils/file_utils'

const route = useRoute()
const router = useRouter()
const configStore = useConfigStore()
const databaseStore = useDatabaseStore()
const taskerStore = useTaskerStore()
const userStore = useUserStore()

// 使用 store 的状态
const { databases, state: dbState } = storeToRefs(databaseStore)
const { tasks: taskerTasks } = storeToRefs(taskerStore)

const state = reactive({
  openNewDatabaseModel: false,
  selectDatabaseModalVisible: false
})

// 选中的知识库ID
const selectedDatabaseId = ref(null)
// 上传时临时选择的知识库ID（用于模态框，避免影响主界面）
const tempSelectedDatabaseIdForUpload = ref(null)

// 上传相关
const uploadType = ref('file') // 'file' | 'folder'
const selectedFiles = ref([])
const uploading = ref(false)
const fileInputRef = ref(null)
const folderInputRef = ref(null)

// 自动入库相关
const autoIndex = ref(true)
const indexParams = ref({
  chunk_size: 1000,
  chunk_overlap: 200,
  qa_separator: ''
})

// 上传任务列表
const uploadTasks = ref([])
const uploadTabActiveKey = ref('uploading')
let uploadPollingTimer = null

// 新建知识库相关
const shareConfig = ref({
  is_shared: true,
  accessible_department_ids: []
})

const languageOptions = [
  { label: '中文 Chinese', value: 'Chinese' },
  { label: '英语 English', value: 'English' },
  { label: '日语 Japanese', value: 'Japanese' },
  { label: '韩语 Korean', value: 'Korean' },
  { label: '德语 German', value: 'German' },
  { label: '法语 French', value: 'French' },
  { label: '西班牙语 Spanish', value: 'Spanish' },
  { label: '葡萄牙语 Portuguese', value: 'Portuguese' },
  { label: '俄语 Russian', value: 'Russian' },
  { label: '阿拉伯语 Arabic', value: 'Arabic' },
  { label: '印地语 Hindi', value: 'Hindi' }
]

const createEmptyDatabaseForm = () => ({
  name: '',
  description: '',
  embed_model_name: configStore.config?.embed_model,
  kb_type: 'milvus',
  is_private: false,
  storage: '',
  language: 'Chinese',
  llm_info: {
    provider: '',
    model_name: ''
  }
})

const newDatabase = reactive(createEmptyDatabaseForm())

const llmModelSpec = computed(() => {
  const provider = newDatabase.llm_info?.provider || ''
  const modelName = newDatabase.llm_info?.model_name || ''
  if (provider && modelName) {
    return `${provider}/${modelName}`
  }
  return ''
})

// 支持的知识库类型
const supportedKbTypes = ref({})
const orderedKbTypes = computed(() => supportedKbTypes.value)

// 知识库选项（用于下拉选择）
const databaseOptions = computed(() => {
  return (databases.value || []).map((db) => ({
    label: db.name,
    value: db.db_id
  }))
})

// 上传任务相关计算属性
const uploadingCount = computed(() => {
  return uploadTasks.value.filter((t) => t.status === 'uploading').length
})

const completedCount = computed(() => {
  return uploadTasks.value.filter((t) => ['success', 'error'].includes(t.status)).length
})

const filteredUploadTasks = computed(() => {
  const tasks = uploadTasks.value
  if (uploadTabActiveKey.value === 'uploading') {
    // 显示正在上传和等待中的任务
    return tasks.filter((t) => t.status === 'uploading' || t.status === 'pending')
  } else {
    // 显示已完成的任务（包括成功、失败、取消）
    return tasks.filter((t) => ['success', 'error', 'cancelled'].includes(t.status))
  }
})

// 加载支持的知识库类型
const loadSupportedKbTypes = async () => {
  try {
    const data = await typeApi.getKnowledgeBaseTypes()
    supportedKbTypes.value = data.kb_types
  } catch (error) {
    console.error('加载知识库类型失败:', error)
    supportedKbTypes.value = {
      lightrag: {
        description: '基于图检索的知识库，支持实体关系构建和复杂查询',
        class_name: 'LightRagKB'
      }
    }
  }
}

const resetNewDatabase = () => {
  Object.assign(newDatabase, createEmptyDatabaseForm())
  shareConfig.value = {
    is_shared: true,
    accessible_department_ids: []
  }
}

const cancelCreateDatabase = () => {
  state.openNewDatabaseModel = false
  resetNewDatabase()
}

const handleKbTypeChange = (type) => {
  resetNewDatabase()
  newDatabase.kb_type = type
}

const handleLLMSelect = (spec) => {
  if (typeof spec !== 'string' || !spec) return
  const index = spec.indexOf('/')
  const provider = index !== -1 ? spec.slice(0, index) : ''
  const modelName = index !== -1 ? spec.slice(index + 1) : ''
  newDatabase.llm_info.provider = provider
  newDatabase.llm_info.model_name = modelName
}

const buildRequestData = () => {
  const requestData = {
    database_name: newDatabase.name.trim(),
    description: newDatabase.description?.trim() || '',
    embed_model_name: newDatabase.embed_model_name || configStore.config.embed_model,
    kb_type: newDatabase.kb_type,
    additional_params: {
      is_private: newDatabase.is_private || false
    }
  }

  requestData.share_config = {
    is_shared: shareConfig.value.is_shared,
    accessible_departments: shareConfig.value.is_shared
      ? []
      : shareConfig.value.accessible_department_ids || []
  }

  if (['milvus'].includes(newDatabase.kb_type)) {
    if (newDatabase.storage) {
      requestData.additional_params.storage = newDatabase.storage
    }
  }

  if (newDatabase.kb_type === 'lightrag') {
    requestData.additional_params.language = newDatabase.language || 'English'
    if (newDatabase.llm_info.provider && newDatabase.llm_info.model_name) {
      requestData.llm_info = {
        provider: newDatabase.llm_info.provider,
        model_name: newDatabase.llm_info.model_name
      }
    }
  }

  return requestData
}

const handleCreateDatabase = async () => {
  const requestData = buildRequestData()
  try {
    await databaseStore.createDatabase(requestData)
    resetNewDatabase()
    state.openNewDatabaseModel = false
  } catch (error) {
    // 错误已在 store 中处理
  }
}

// 选择知识库
const selectDatabase = async (databaseId) => {
  selectedDatabaseId.value = databaseId
  // 设置 store 的 databaseId，以便 FileTable 组件使用
  databaseStore.databaseId = databaseId
  // 加载知识库信息
  await databaseStore.getDatabaseInfo(databaseId)
}

// 触发文件上传
const triggerFileUpload = () => {
  uploadType.value = 'file'
  fileInputRef.value?.click()
}

// 触发文件夹上传
const triggerFolderUpload = () => {
  uploadType.value = 'folder'
  folderInputRef.value?.click()
}

// 处理文件选择
const handleFileSelect = (event) => {
  const files = Array.from(event.target.files || [])
  if (files.length === 0) return
  selectedFiles.value = files
  state.selectDatabaseModalVisible = true
  event.target.value = '' // 重置input
}

// 处理文件夹选择
const handleFolderSelect = (event) => {
  const files = Array.from(event.target.files || [])
  if (files.length === 0) return
  selectedFiles.value = files
  state.selectDatabaseModalVisible = true
  event.target.value = '' // 重置input
}

// 获取上传图标
const getUploadIcon = () => {
  return uploadType.value === 'folder' ? FolderUp : FileUp
}

// 确认上传
const confirmUpload = async () => {
  // 使用临时选择的知识库ID
  const uploadDatabaseId = tempSelectedDatabaseIdForUpload.value
  if (!uploadDatabaseId) {
    message.error('请选择知识库')
    return
  }

  if (selectedFiles.value.length === 0) {
    message.error('请选择文件')
    return
  }

  uploading.value = true
  state.selectDatabaseModalVisible = false

  // 创建上传任务（使用 reactive 确保响应式）
  const tasks = selectedFiles.value.map((file) => {
    return reactive({
      id: `upload_${Date.now()}_${Math.random()}`,
      fileName: file.name,
      size: file.size,
      file: file,
      progress: 0,
      status: 'pending',
      taskId: null,
      xhr: null,
      error: null,
      dbId: uploadDatabaseId, // 保存上传目标的知识库ID
      file_path: null, // 上传后返回的文件路径
      content_hash: null // 上传后返回的内容哈希
    })
  })

  uploadTasks.value.push(...tasks)
  
  // 显示上传进度窗口
  state.uploadProgressWindowVisible = true

  // 开始上传（并发上传，不等待完成）
  tasks.forEach(task => {
    // 立即更新状态为 uploading，确保 UI 显示
    task.status = 'uploading'
    uploadFile(task, uploadDatabaseId).catch(error => {
      console.error('上传失败:', error)
      // 错误已在 uploadFile 中处理
    })
  })

  selectedFiles.value = []
  tempSelectedDatabaseIdForUpload.value = null // 清空临时选择
  uploading.value = false
}

// 将文件添加到知识库（参考 FileUploadModal 的 chunkData 逻辑）
const addFileToDatabase = async (task, dbId) => {
  if (!task.file_path) {
    throw new Error('文件路径不存在')
  }
  
  // 设置当前知识库ID（addFiles 需要）
  const originalDbId = databaseStore.databaseId
  databaseStore.databaseId = dbId
  
  try {
    const params = {
      content_type: 'file',
      enable_ocr: 'disable' // 默认不启用 OCR，可以根据需要调整
    }
    
    const content_hashes = {}
    if (task.content_hash) {
      content_hashes[task.file_path] = task.content_hash
      params.content_hashes = content_hashes
    }
    
    // 如果启用自动入库，添加相关参数
    if (autoIndex.value) {
      params.auto_index = true
      Object.assign(params, indexParams.value)
    }
    
    await databaseStore.addFiles({
      items: [task.file_path],
      contentType: 'file',
      params: params,
      parentId: null // 上传到根目录
    })
  } finally {
    // 恢复原始知识库ID
    databaseStore.databaseId = originalDbId
  }
}

// 上传文件（使用 XMLHttpRequest 跟踪进度）
const uploadFile = async (task, dbId) => {
  task.status = 'uploading'
  task.progress = 0

  return new Promise((resolve, reject) => {
    if (!dbId) {
      task.status = 'error'
      task.error = '知识库ID不能为空'
      reject(new Error('知识库ID不能为空'))
      return
    }

    const formData = new FormData()
    // 处理文件夹上传的文件名（参考 FileUploadModal 的实现）
    const filename =
      uploadType.value === 'folder' && task.file.webkitRelativePath
        ? task.file.webkitRelativePath
        : task.file.name
    formData.append('file', task.file, filename)

    const xhr = new XMLHttpRequest()
    // 统一使用 upload 接口，通过 webkitRelativePath 来区分文件夹上传（与 FileUploadModal 保持一致）
    const url = `/api/knowledge/files/upload?db_id=${dbId}`

    // 先设置进度监听
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0) {
        const newProgress = Math.round((e.loaded / e.total) * 100)
        task.progress = newProgress
        console.log(`上传进度更新: ${task.fileName} - ${newProgress}% (${e.loaded}/${e.total})`)
      } else {
        // 如果无法计算总大小，至少显示已上传的字节数
        console.log(`上传中: ${task.fileName} - 已上传 ${e.loaded} 字节`)
      }
    }
    
    // 添加 loadstart 事件，确保上传开始
    xhr.upload.onloadstart = () => {
      console.log(`开始上传: ${task.fileName}`)
      task.status = 'uploading'
      task.progress = 0
    }

    // 先打开连接
    xhr.open('POST', url)

    // 获取认证头并设置（必须在 open 之后，send 之前）
    const userStore = useUserStore()
    const headers = userStore.getAuthHeaders()
    for (const [key, value] of Object.entries(headers)) {
      try {
        xhr.setRequestHeader(key, value)
      } catch (e) {
        console.error('设置请求头失败:', key, e)
      }
    }
    
    // 存储 xhr 实例以便取消
    task.xhr = xhr

    // 添加一个定时器，如果进度事件没有触发，至少显示一个最小进度
    let progressTimer = null
    const startProgressSimulation = () => {
      // 如果 2 秒后进度仍然是 0，开始模拟进度（最多到 90%）
      progressTimer = setTimeout(() => {
        if (task.progress === 0 && task.status === 'uploading') {
          // 开始模拟进度，但不超过 90%，等待实际完成
          let simulatedProgress = 10
          const simulateInterval = setInterval(() => {
            if (task.progress < 90 && task.status === 'uploading') {
              simulatedProgress = Math.min(simulatedProgress + 5, 90)
              task.progress = simulatedProgress
            } else {
              clearInterval(simulateInterval)
            }
          }, 500)
        }
      }, 2000)
    }
    
    // 清除模拟进度的定时器
    const clearProgressSimulation = () => {
      if (progressTimer) {
        clearTimeout(progressTimer)
        progressTimer = null
      }
    }

    xhr.onload = () => {
      clearProgressSimulation()
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const result = JSON.parse(xhr.responseText)
          // 保存文件路径和内容哈希（用于后续添加到知识库）
          task.file_path = result.file_path
          task.content_hash = result.content_hash
          
          // 文件上传完成，确保进度为 100%
          task.progress = 100
          task.status = 'uploaded' // 先标记为已上传，等待添加到知识库
          console.log(`文件上传成功: ${task.fileName}`, result)
          
          // 强制触发响应式更新
          nextTick(() => {
            // 确保状态已更新
            if (task.status !== 'uploaded') {
              task.status = 'uploaded'
            }
          })
          
          // 立即调用 addFiles 将文件添加到知识库（参考 FileUploadModal 的流程）
          addFileToDatabase(task, dbId).then(() => {
            task.status = 'success'
            console.log(`文件已添加到知识库: ${task.fileName}`)
            
            // 如果当前选中的知识库就是上传目标，刷新文件列表
            if (selectedDatabaseId.value === dbId) {
              setTimeout(() => {
                databaseStore.getDatabaseInfo(dbId, false, true).catch(error => {
                  console.error('刷新知识库文件列表失败:', error)
                })
              }, 500)
            }
          }).catch(error => {
            task.status = 'error'
            task.error = error.message || '添加到知识库失败'
            console.error(`添加到知识库失败: ${task.fileName}`, error)
          })
          
          if (result.task_id) {
            task.taskId = result.task_id
          }
          resolve(result)
        } catch (e) {
          task.status = 'error'
          task.error = '解析响应失败'
          reject(e)
        }
      } else {
        try {
          const error = JSON.parse(xhr.responseText)
          task.status = 'error'
          task.error = error.detail || '上传失败'
          reject(new Error(task.error))
        } catch (e) {
          task.status = 'error'
          task.error = '上传失败'
          reject(new Error('上传失败'))
        }
      }
    }

    xhr.onerror = () => {
      clearProgressSimulation()
      task.status = 'error'
      task.error = '网络错误'
      reject(new Error('网络错误'))
    }

    xhr.onabort = () => {
      clearProgressSimulation()
      task.status = 'cancelled'
      task.error = '用户取消上传'
      reject(new Error('用户取消上传'))
    }
    
    // 开始进度模拟（如果进度事件没有触发）
    startProgressSimulation()

    // 发送请求（xhr.open 已在上面调用过）
    xhr.send(formData)
  })
}

// 轮询上传任务状态（仅用于跟踪后续处理任务，上传进度由XMLHttpRequest直接更新）
const pollUploadTasks = async () => {
  if (uploadTasks.value.length === 0) {
    stopPolling()
    return
  }

  // 检查是否还有需要跟踪的任务（有taskId且状态不是最终状态）
  const tasksToTrack = uploadTasks.value.filter(
    (t) => t.taskId && !['success', 'error'].includes(t.status)
  )

  if (tasksToTrack.length === 0) {
    // 所有任务都已完成，停止轮询
    stopPolling()
    return
  }

  // 从任务中心获取任务状态
  try {
    await taskerStore.loadTasks()

    // 更新上传任务状态（仅更新有taskId的任务，且不覆盖已完成的）
    uploadTasks.value.forEach((uploadTask) => {
      if (uploadTask.taskId && !['success', 'error'].includes(uploadTask.status)) {
        const taskerTask = taskerTasks.value.find((t) => t.id === uploadTask.taskId)
        if (taskerTask) {
          // 如果任务中心显示已完成，更新状态
          if (taskerTask.status === 'success') {
            uploadTask.status = 'success'
            // 保持上传进度为100，不覆盖
            if (uploadTask.progress < 100) {
              uploadTask.progress = 100
            }
          } else if (taskerTask.status === 'failed') {
            uploadTask.status = 'error'
            uploadTask.error = taskerTask.error || '处理失败'
          }
          // 注意：上传进度由XMLHttpRequest的onprogress直接更新，这里不覆盖
        }
      }
    })

    // 再次检查是否全部完成
    const allCompleted = uploadTasks.value.every(
      (t) => t.status === 'success' || t.status === 'error'
    )
    if (allCompleted) {
      const successCount = uploadTasks.value.filter((t) => t.status === 'success').length
      message.success(`上传成功 共${successCount}项`)
      
      // 获取所有上传成功的任务对应的知识库ID（去重）
      const uploadedDbIds = [...new Set(
        uploadTasks.value
          .filter((t) => t.status === 'success' && t.dbId)
          .map((t) => t.dbId)
      )]
      
      // 如果当前选中的知识库在上传列表中，刷新文件列表
      if (selectedDatabaseId.value && uploadedDbIds.includes(selectedDatabaseId.value)) {
        databaseStore.getDatabaseInfo(selectedDatabaseId.value, false, true).catch(error => {
          console.error('刷新知识库文件列表失败:', error)
        })
      }
      
      stopPolling()
    }
  } catch (error) {
    console.error('轮询任务状态失败:', error)
  }
}

const startPolling = () => {
  if (uploadPollingTimer) return
  // 延迟启动轮询，给上传一些时间
  uploadPollingTimer = setInterval(pollUploadTasks, 5000) // 改为5秒轮询一次，减少请求频率
}

const stopPolling = () => {
  if (uploadPollingTimer) {
    clearInterval(uploadPollingTimer)
    uploadPollingTimer = null
  }
}

// 暂停上传
const pauseUpload = (taskId) => {
  const task = uploadTasks.value.find((t) => t.id === taskId)
  if (task && task.taskId) {
    taskerStore.cancelTask(task.taskId)
  }
}

// 全部暂停
const pauseAllUploads = () => {
  uploadTasks.value.forEach((task) => {
    if (task.status === 'uploading' && task.taskId) {
      pauseUpload(task.id)
    }
  })
}

// 收起上传窗口
const collapseUploadWindow = () => {
  uploadTasks.value = []
  stopPolling()
}

// 获取状态文本
const getStatusText = (task) => {
  if (task.status === 'uploading') {
    return task.progress < 100 ? `${task.progress}%` : '上传中'
  }
  if (task.status === 'success') {
    return '已完成'
  }
  if (task.status === 'error') {
    return '失败'
  }
  return '等待中'
}

// 处理拖拽上传
const handleDrop = (event) => {
  event.preventDefault()
  const items = event.dataTransfer.items
  if (!items || items.length === 0) return

  const files = []
  const folders = []

  for (let i = 0; i < items.length; i++) {
    const item = items[i]
    if (item.kind === 'file') {
      const entry = item.webkitGetAsEntry()
      if (entry) {
        if (entry.isDirectory) {
          folders.push(entry)
        } else {
          files.push(item.getAsFile())
        }
      }
    }
  }

  if (files.length > 0) {
    uploadType.value = 'file'
    selectedFiles.value = files
    state.selectDatabaseModalVisible = true
  } else if (folders.length > 0) {
    // 文件夹拖拽需要特殊处理，这里简化处理
    message.info('文件夹拖拽上传功能开发中，请使用"上传文件夹"按钮')
  }
}

// formatFileSize 已从 @/utils/file_utils 导入，不需要重复定义

// 监听上传任务，只在有需要跟踪的任务时启动轮询
watch(
  () => uploadTasks.value,
  (tasks) => {
    // 检查是否有需要跟踪的任务（有taskId且状态不是最终状态）
    const hasTasksToTrack = tasks.some(
      (t) => t.taskId && !['success', 'error'].includes(t.status)
    )
    
    if (hasTasksToTrack && !uploadPollingTimer) {
      // 延迟启动，给上传一些时间
      setTimeout(() => {
        startPolling()
      }, 2000)
    } else if (!hasTasksToTrack && uploadPollingTimer) {
      // 没有需要跟踪的任务，停止轮询
      stopPolling()
    }
  },
  { deep: true }
)

// 移除路由监听，因为不再使用路由跳转，直接通过点击选择知识库
// watch(
//   () => route.path,
//   (newPath) => {
//     if (newPath === '/database') {
//       selectedDatabaseId.value = null
//       databaseStore.loadDatabases()
//     } else if (newPath.startsWith('/database/')) {
//       const dbId = newPath.split('/database/')[1]
//       if (dbId && !dbId.includes('?')) {
//         // 确保是有效的数据库ID（不包含查询参数）
//         selectedDatabaseId.value = dbId
//       }
//     }
//   },
//   { immediate: true }
// )

onMounted(() => {
  loadSupportedKbTypes()
  databaseStore.loadDatabases()
  if (databaseStore.databaseId) {
    selectedDatabaseId.value = databaseStore.databaseId
    databaseStore.getDatabaseInfo(databaseStore.databaseId)
  }
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<style lang="less" scoped>
.database-container {
  height: calc(100vh - 76px); /* 视口高度减去上下边距 */
  display: flex;
  flex-direction: column;
  overflow: hidden;
  margin: 16px; /* 添加上下左右边距 */
  margin-top: 60px;
  background: #ffffff; /* 白色背景 */
  border-radius: 8px; /* 圆角 */
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1); /* 阴影效果 */
  padding: 16px; /* 内边距 */
  box-sizing: border-box; /* 确保 padding 和 margin 包含在高度内 */
}

.unified-layout {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.database-sidebar {
  width: 240px;
  border-right: 1px solid var(--gray-100);
  background: var(--gray-0);
  display: flex;
  flex-direction: column;
  overflow: hidden;

  .sidebar-header {
    padding: 16px;
    border-bottom: 1px solid var(--gray-100);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    font-weight: 600;
    font-size: 16px;
    color: var(--gray-900);

    .header-icon {
      width: 20px;
      height: 20px;
      color: var(--main-color);
    }

    .header-add-btn {
      font-size: 14px;
      color: var(--main-color);
      border: none;
      box-shadow: none;
      padding: 4px 8px;
      height: auto;
      border-radius: 6px;

      &:hover {
        background-color: var(--main-10);
      }
    }
  }

  .loading-state,
  .empty-state-sidebar {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    flex-grow: 1;
    color: var(--gray-500);
    font-size: 14px;
    gap: 8px;
  }

  .database-list {
    flex: 1;
    overflow-y: auto;
    padding: 8px;
  }

  .database-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 12px;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s;
    margin-bottom: 4px;

    &:hover {
      background: var(--gray-50);
    }

    &.active {
      background: var(--main-10);
      color: var(--main-color);
    }

    .database-name {
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 14px;
      font-weight: 500;
    }
  }
}

.database-content {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.content-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background-color: var(--gray-0);
  border-radius: 8px;
  border: 1px dashed var(--gray-200);
  color: var(--gray-500);
  font-size: 16px;
  text-align: center;
  padding: 20px;
  margin: 0 16px;
}

.upload-hint {
  margin-bottom: 20px;
  .hint-text {
    font-size: 16px;
    color: var(--gray-600);
    margin-bottom: 8px;
  }
  .hint-or {
    font-size: 14px;
    color: var(--gray-400);
  }
}

.action-cards {
  display: flex;
  gap: 20px;
  margin-top: 20px;
}

.action-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 160px;
  height: 120px;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  background-color: var(--gray-0);
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover {
    border-color: var(--main-color);
    box-shadow: 0 4px 12px rgba(var(--main-color-rgb), 0.1);
    transform: translateY(-2px);
  }

  .card-icon {
    font-size: 36px;
    color: var(--main-color);
    margin-bottom: 10px;
  }

  .card-title {
    font-size: 14px;
    font-weight: 500;
    color: var(--gray-700);
  }
}

.content-with-database {
  flex: 1;
  overflow: hidden;
}

// 右侧内容区域（已删除，不再使用）
// .database-content {

// 选择知识库弹窗
.select-database-modal {
  .selected-files-info {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 16px;
    background: var(--gray-50);
    border-radius: 8px;
    margin-bottom: 20px;

    .file-icon {
      width: 24px;
      height: 24px;
      color: var(--main-color);
      flex-shrink: 0;
      margin-top: 2px;
    }

    .file-info {
      flex: 1;

      .file-count {
        font-weight: 500;
        color: var(--gray-900);
        margin-bottom: 4px;
      }

      .file-names {
        font-size: 13px;
        color: var(--gray-600);

        .file-name {
          max-width: 200px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          display: inline-block;
        }
      }
    }
  }

  .database-select-label {
    margin-bottom: 8px;
    font-weight: 500;
    color: var(--gray-700);
  }

  .modal-actions {
    display: flex;
    justify-content: flex-end;
    gap: 12px;
    margin-top: 24px;
  }
}

// 上传进度窗口
.upload-progress-window {
  position: fixed;
  top: 80px;
  right: 20px;
  width: 600px;
  max-height: 600px;
  background: var(--gray-0);
  border-radius: 12px;
  box-shadow: 0 8px 24px var(--shadow-2);
  border: 1px solid var(--gray-200);
  z-index: 1000;
  display: flex;
  flex-direction: column;

  .upload-progress-header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    border-bottom: 1px solid var(--gray-100);

    :deep(.ant-tabs) {
      flex: 1;
    }

    .header-actions {
      display: flex;
      gap: 8px;
    }
  }

  .upload-progress-content {
    flex: 1;
    overflow-y: auto;
    padding: 12px;
    max-height: 500px;
  }

  .upload-task-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px;
    border-radius: 8px;
    margin-bottom: 8px;
    background: var(--gray-50);
    transition: all 0.2s;

    &:hover {
      background: var(--gray-100);
    }

    .file-icon-wrapper {
      width: 32px;
      height: 32px;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;

      .file-icon {
        width: 24px;
        height: 24px;
        color: var(--main-color);
      }
    }

    .file-info {
      flex: 1;
      min-width: 0;

      .file-name {
        font-size: 13px;
        font-weight: 500;
        color: var(--gray-900);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .file-size {
        font-size: 12px;
        color: var(--gray-500);
        margin-top: 2px;
      }
    }

    .upload-status {
      display: flex;
      align-items: center;
      gap: 12px;
      flex: 1;
      min-width: 0;

      :deep(.ant-progress) {
        flex: 1;
        min-width: 150px;
      }

      .status-text {
        font-size: 12px;
        color: var(--gray-600);
        min-width: 60px;
        text-align: right;
      }
    }
  }
}

// 新建知识库弹窗样式（保留原有样式）
.new-database-modal {
  .kb-type-cards {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
    margin: 16px 0;

    @media (max-width: 768px) {
      grid-template-columns: 1fr;
      gap: 12px;
    }

    .kb-type-card {
      border: 2px solid var(--gray-150);
      border-radius: 12px;
      padding: 16px;
      cursor: pointer;
      transition: all 0.3s ease;
      background: var(--gray-0);

      &:hover {
        border-color: var(--main-color);
      }

      &.active {
        border-color: var(--main-color);
        background: var(--main-10);
        .type-icon {
          color: var(--main-color);
        }
      }

      .card-header {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 12px;

        .type-icon {
          width: 24px;
          height: 24px;
          color: var(--main-color);
          flex-shrink: 0;
        }

        .type-title {
          font-size: 16px;
          font-weight: 600;
          color: var(--gray-800);
        }
      }

      .card-description {
        font-size: 13px;
        color: var(--gray-600);
        line-height: 1.5;
      }
    }
  }

  h3 {
    margin-top: 20px;
    margin-bottom: 8px;
    font-size: 14px;
    font-weight: 600;
    color: var(--gray-800);

    &:first-child {
      margin-top: 0;
    }
  }
}
</style>
