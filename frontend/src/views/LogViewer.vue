<template>
  <div class="log-viewer">
    <div class="page-header">
      <h1 class="page-title"><font-awesome-icon icon="file-lines" /> 系统日志</h1>
      <div class="header-actions">
        <span class="file-info">
          {{ content?.file_name }}（{{ formatFileSize(content?.file_size ?? 0) }}）
        </span>
        <el-switch
          v-model="autoRefresh"
          active-text="自动刷新"
          :active-value="true"
          :inactive-value="false"
        />
        <el-button text @click="fetchLogs"> <font-awesome-icon icon="rotate" /> 刷新 </el-button>
      </div>
      <div v-if="loading" class="loading-bar"></div>
    </div>

    <el-card class="filter-card">
      <div class="filter-bar">
        <el-select
          v-model="filters.level"
          placeholder="日志级别"
          clearable
          style="width: 140px"
          @change="onFilterChange"
        >
          <el-option label="全部" value="ALL" />
          <el-option label="DEBUG" value="DEBUG" />
          <el-option label="INFO" value="INFO" />
          <el-option label="WARNING" value="WARNING" />
          <el-option label="ERROR" value="ERROR" />
        </el-select>
        <el-input
          v-model="filters.search"
          placeholder="搜索关键词..."
          clearable
          style="width: 260px"
          @keyup.enter="onFilterChange"
          @clear="onFilterChange"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-select v-model="filters.lines" style="width: 120px" @change="onFilterChange">
          <el-option label="100 行" :value="100" />
          <el-option label="200 行" :value="200" />
          <el-option label="500 行" :value="500" />
          <el-option label="1000 行" :value="1000" />
        </el-select>
      </div>
    </el-card>

    <el-card class="content-card">
      <div :style="{ minHeight: loading ? '200px' : '0' }">
        <div v-if="!loading && (!content?.lines || content.lines.length === 0)" class="empty-state">
          <el-empty description="暂无日志" />
        </div>
        <el-scrollbar v-else ref="scrollbarRef" max-height="calc(100vh - 340px)">
          <div class="log-lines">
            <div
              v-for="(line, idx) in content?.lines ?? []"
              :key="idx"
              class="log-line"
              :class="getLineClass(line)"
            >
              <span class="line-number">{{
                (content?.total_lines ?? 0) -
                filters.offset -
                (content?.lines?.length ?? 0) +
                idx +
                1
              }}</span>
              <span class="line-content">{{ line }}</span>
            </div>
          </div>
        </el-scrollbar>
      </div>

      <div class="pagination-bar" v-if="content && content.total_lines > 0">
        <el-pagination
          background
          layout="prev, pager, next, total"
          :total="content.total_lines"
          :page-size="filters.lines"
          :current-page="currentPage"
          @current-change="onPageChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import { faFileLines, faRotate } from '@fortawesome/free-solid-svg-icons'
import { logsApi, type LogContent } from '@/api/modules/logs'

library.add(faFileLines, faRotate)

const content = ref<LogContent | null>(null)
const loading = ref(false)
const autoRefresh = ref(true)
const scrollbarRef = ref<{ setScrollTop(top: number): void } | null>(null)

const filters = ref({
  lines: 200,
  offset: 0,
  level: 'ALL' as string,
  search: '',
})

const currentPage = computed(() => Math.floor(filters.value.offset / filters.value.lines) + 1)

let refreshTimer: ReturnType<typeof setInterval> | null = null

function getLineClass(line: string) {
  if (line.includes('| ERROR') || line.includes('| CRITICAL')) return 'level-error'
  if (line.includes('| WARNING')) return 'level-warning'
  if (line.includes('| INFO')) return 'level-info'
  if (line.includes('| DEBUG')) return 'level-debug'
  return ''
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

async function fetchLogs() {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      lines: filters.value.lines,
      offset: filters.value.offset,
    }
    if (filters.value.level && filters.value.level !== 'ALL') params.level = filters.value.level
    if (filters.value.search) params.search = filters.value.search
    content.value = await logsApi.getContent(params)
    if (content.value && content.value.lines.length === 0 && content.value.total_lines > 0) {
      filters.value.offset = 0
      return fetchLogs()
    }
  } catch {
    ElMessage.error('获取日志失败')
  } finally {
    loading.value = false
    await nextTick()
    scrollbarRef.value?.setScrollTop(999999)
  }
}

function onFilterChange() {
  filters.value.offset = 0
  fetchLogs()
}

function onPageChange(page: number) {
  filters.value.offset = (page - 1) * filters.value.lines
  fetchLogs()
}

watch(
  autoRefresh,
  (val) => {
    if (val) {
      refreshTimer = setInterval(fetchLogs, 10000)
    } else if (refreshTimer) {
      clearInterval(refreshTimer)
      refreshTimer = null
    }
  },
  { immediate: true },
)

onMounted(() => {
  fetchLogs()
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<style lang="scss" scoped>
.log-viewer {
  padding: 0;
}

.page-header {
  position: relative;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;

  .page-title {
    font-size: 20px;
    font-weight: 600;
    margin: 0;
  }

  .header-actions {
    display: flex;
    align-items: center;
    gap: 16px;

    .file-info {
      font-size: 13px;
      color: var(--el-text-color-secondary);
    }
  }

  .loading-bar {
    position: absolute;
    bottom: -8px;
    left: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--color-primary), transparent);
    border-radius: 1px;
    animation: loading-slide 1.5s ease-in-out infinite;
  }
}

@keyframes loading-slide {
  0% {
    width: 0;
    left: 0;
  }
  50% {
    width: 40%;
    left: 30%;
  }
  100% {
    width: 0;
    left: 100%;
  }
}

.filter-card {
  margin-bottom: 12px;

  .filter-bar {
    display: flex;
    align-items: center;
    gap: 12px;
  }
}

.content-card {
  .log-lines {
    font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace;
    font-size: 13px;
    line-height: 1.6;
    background: var(--el-fill-color-lighter);
    border-radius: 4px;
    padding: 8px 0;
  }

  .log-line {
    display: flex;
    padding: 1px 12px;
    white-space: pre-wrap;
    word-break: break-all;

    &:hover {
      background: var(--el-fill-color);
    }

    .line-number {
      flex-shrink: 0;
      width: 48px;
      text-align: right;
      color: var(--el-text-color-placeholder);
      margin-right: 16px;
      user-select: none;
    }

    .line-content {
      flex: 1;
    }
  }

  .level-error {
    color: #f56c6c;
    background: rgba(245, 108, 108, 0.06);
  }

  .level-warning {
    color: #e6a23c;
    background: rgba(230, 162, 60, 0.06);
  }

  .level-info {
    color: var(--el-text-color-primary);
  }

  .level-debug {
    color: var(--el-text-color-secondary);
  }
}

.pagination-bar {
  display: flex;
  justify-content: center;
  margin-top: 16px;
}

.empty-state {
  padding: 40px 0;
}
</style>
