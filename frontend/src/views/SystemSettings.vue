<template>
  <div class="settings">
    <div class="page-header">
      <h1 class="page-title"><font-awesome-icon icon="cog" /> 系统设置</h1>
      <el-button type="primary" :loading="reloading" @click="handleReload">
        <font-awesome-icon icon="rotate" /> 刷新缓存
      </el-button>
    </div>

    <el-card v-if="exchangeRate" class="rate-card">
      <template #header>
        <span><font-awesome-icon icon="dollar-sign" /> 汇率缓存</span>
      </template>
      <div class="rate-body">
        <div class="rate-info">
          <span class="rate-label">当前汇率</span>
          <span class="rate-value">{{ exchangeRate.rate?.toFixed(6) ?? '暂无数据' }}</span>
          <span v-if="exchangeRate.updated_at" class="rate-time">
            更新于 {{ exchangeRate.updated_at }}
          </span>
        </div>
        <el-button text type="primary" :loading="updatingRate" @click="showRateDialog = true">
          <font-awesome-icon icon="pen" /> 手动更新
        </el-button>
      </div>
    </el-card>

    <el-card class="main-card">
      <el-tabs v-model="activeTab" @tab-change="onTabChange">
        <el-tab-pane label="报警配置" name="alert">
          <div v-loading="alert.loading" class="tab-content">
            <el-form v-if="alert.data" label-width="160px" class="settings-form">
              <div class="form-section">
                <h4 class="section-title"><font-awesome-icon icon="bell" /> 绝对价格报警</h4>
                <el-form-item label="启用绝对价格报警">
                  <el-switch v-model="alert.data.enable_absolute_alert" />
                </el-form-item>
                <el-form-item label="绝对低价阈值">
                  <el-input-number
                    v-model="alert.data.absolute_low_price"
                    :min="0"
                    :precision="1"
                    :disabled="!alert.data.enable_absolute_alert"
                  />
                  <span class="unit">¥</span>
                </el-form-item>
              </div>

              <div class="form-section">
                <h4 class="section-title"><font-awesome-icon icon="clock" /> 相对价格报警</h4>
                <el-form-item label="启用相对价格报警">
                  <el-switch v-model="alert.data.enable_relative_alert" />
                </el-form-item>
                <el-form-item label="相对窗口时长">
                  <el-input-number
                    v-model="alert.data.relative_window_hours"
                    :min="1"
                    :max="720"
                    :disabled="!alert.data.enable_relative_alert"
                  />
                  <span class="unit">小时</span>
                </el-form-item>
              </div>

              <div class="form-section">
                <h4 class="section-title"><font-awesome-icon icon="arrow-trend-up" /> 突破报警</h4>
                <el-form-item label="启用突破报警">
                  <el-switch v-model="alert.data.enable_breakout_alert" />
                </el-form-item>
                <el-form-item label="盘整时长">
                  <el-input-number
                    v-model="alert.data.consolidation_hours"
                    :min="1"
                    :max="720"
                    :disabled="!alert.data.enable_breakout_alert"
                  />
                  <span class="unit">小时</span>
                </el-form-item>
                <el-form-item label="波动率阈值">
                  <el-input-number
                    v-model="alert.data.volatility_threshold"
                    :min="0.001"
                    :max="0.1"
                    :precision="3"
                    :step="0.001"
                    :disabled="!alert.data.enable_breakout_alert"
                  />
                  <span class="unit">(小数)</span>
                </el-form-item>
              </div>

              <div class="form-section">
                <h4 class="section-title"><font-awesome-icon icon="wave-square" /> 技术指标报警</h4>
                <el-form-item label="启用趋势报警">
                  <el-switch v-model="alert.data.enable_trend_alert" />
                </el-form-item>
                <el-form-item label="启用波动率报警">
                  <el-switch v-model="alert.data.enable_volatility_alert" />
                </el-form-item>
                <el-form-item label="启用均线交叉报警">
                  <el-switch v-model="alert.data.enable_ma_cross_alert" />
                </el-form-item>
                <el-form-item label="短期均线周期">
                  <el-input-number
                    v-model="alert.data.ma_short_period"
                    :min="2"
                    :max="200"
                    :disabled="!alert.data.enable_ma_cross_alert"
                  />
                </el-form-item>
                <el-form-item label="长期均线周期">
                  <el-input-number
                    v-model="alert.data.ma_long_period"
                    :min="5"
                    :max="500"
                    :disabled="!alert.data.enable_ma_cross_alert"
                  />
                </el-form-item>
              </div>

              <div class="form-section">
                <h4 class="section-title"><font-awesome-icon icon="bolt" /> 快速变化报警</h4>
                <el-form-item label="启用连续变化报警">
                  <el-switch v-model="alert.data.enable_consecutive_alert" />
                </el-form-item>
                <el-form-item label="连续变化次数">
                  <el-input-number
                    v-model="alert.data.consecutive_count"
                    :min="2"
                    :max="50"
                    :disabled="!alert.data.enable_consecutive_alert"
                  />
                  <span class="unit">次</span>
                </el-form-item>
                <el-form-item label="启用快速变化报警">
                  <el-switch v-model="alert.data.enable_rapid_change_alert" />
                </el-form-item>
                <el-form-item label="快速变化阈值">
                  <el-input-number
                    v-model="alert.data.rapid_change_threshold"
                    :min="0.001"
                    :max="0.5"
                    :precision="3"
                    :step="0.001"
                    :disabled="!alert.data.enable_rapid_change_alert"
                  />
                  <span class="unit">(小数)</span>
                </el-form-item>
                <el-form-item label="快速变化窗口">
                  <el-input-number
                    v-model="alert.data.rapid_change_window_minutes"
                    :min="1"
                    :max="1440"
                    :disabled="!alert.data.enable_rapid_change_alert"
                  />
                  <span class="unit">分钟</span>
                </el-form-item>
              </div>

              <div class="form-section">
                <h4 class="section-title">
                  <font-awesome-icon icon="angle-double-down" /> 长期低位报警
                </h4>
                <el-form-item label="启用长期低位报警">
                  <el-switch v-model="alert.data.enable_long_term_low_alert" />
                </el-form-item>
              </div>

              <el-form-item class="form-actions">
                <el-button type="primary" :loading="alert.saving" @click="alert.save()">
                  保存报警配置
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>

        <el-tab-pane label="AI 配置" name="ai">
          <div v-loading="ai.loading" class="tab-content">
            <el-form v-if="ai.data" label-width="160px" class="settings-form">
              <el-form-item label="启用 AI">
                <el-switch v-model="ai.data.enabled" />
              </el-form-item>
              <el-form-item label="启用 Prompt 检查">
                <el-switch v-model="ai.data.prompt_check" />
              </el-form-item>
              <el-form-item label="Temperature">
                <el-input-number
                  v-model="ai.data.temperature"
                  :min="0"
                  :max="2"
                  :precision="1"
                  :step="0.1"
                />
              </el-form-item>
              <el-form-item label="Max Tokens">
                <el-input-number v-model="ai.data.max_tokens" :min="256" :max="32768" :step="256" />
              </el-form-item>
              <el-form-item label="检查间隔">
                <el-input-number v-model="ai.data.check_interval_checks" :min="1" :max="1000" />
                <span class="unit">次</span>
              </el-form-item>
              <el-form-item label="最大重试次数">
                <el-input-number v-model="ai.data.max_retries" :min="0" :max="10" />
              </el-form-item>
              <el-form-item label="重试基础延迟">
                <el-input-number
                  v-model="ai.data.retry_base_delay"
                  :min="0.1"
                  :max="60"
                  :precision="1"
                  :step="0.5"
                />
                <span class="unit">秒</span>
              </el-form-item>
              <el-form-item label="缓存 TTL">
                <el-input-number v-model="ai.data.cache_ttl_minutes" :min="1" :max="1440" />
                <span class="unit">分钟</span>
              </el-form-item>
              <el-form-item class="form-actions">
                <el-button type="primary" :loading="ai.saving" @click="ai.save()">
                  保存 AI 配置
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>

        <el-tab-pane label="企业微信" name="wechat">
          <div v-loading="wechat.loading" class="tab-content">
            <el-form v-if="wechat.data" label-width="160px" class="settings-form">
              <el-form-item label="启用企业微信通知">
                <el-switch v-model="wechat.data.enabled" />
              </el-form-item>
              <el-form-item label="Webhook 地址">
                <el-input
                  v-model="wechat.data.webhook_url"
                  type="textarea"
                  :rows="3"
                  placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
                />
              </el-form-item>
              <el-form-item class="form-actions">
                <el-button type="primary" :loading="wechat.saving" @click="wechat.save()">
                  保存企业微信配置
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>

        <el-tab-pane label="邮件配置" name="email">
          <div v-loading="email.loading" class="tab-content">
            <el-form v-if="email.data" label-width="160px" class="settings-form">
              <el-form-item label="启用邮件通知">
                <el-switch v-model="email.data.enabled" />
              </el-form-item>
              <el-form-item label="SMTP 服务器">
                <el-input v-model="email.data.smtp_server" placeholder="smtp.qq.com" />
              </el-form-item>
              <el-form-item label="SMTP 端口">
                <el-input-number v-model="email.data.smtp_port" :min="1" :max="65535" />
              </el-form-item>
              <el-form-item label="发件邮箱">
                <el-input v-model="email.data.sender_email" placeholder="your@email.com" />
              </el-form-item>
              <el-form-item label="发件密码">
                <el-input
                  v-model="email.data.sender_password"
                  type="password"
                  show-password
                  placeholder="授权码或密码"
                />
              </el-form-item>
              <el-form-item label="收件邮箱">
                <el-input v-model="email.data.receiver_email" placeholder="receiver@email.com" />
              </el-form-item>
              <el-form-item class="form-actions">
                <el-button type="primary" :loading="email.saving" @click="email.save()">
                  保存邮件配置
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>

        <el-tab-pane label="监控配置" name="monitor">
          <div v-loading="monitor.loading" class="tab-content">
            <el-form v-if="monitor.data" label-width="160px" class="settings-form">
              <el-form-item label="检查间隔">
                <el-input-number v-model="monitor.data.check_interval" :min="1" :max="3600" />
                <span class="unit">秒</span>
              </el-form-item>
              <el-form-item label="主监控品种">
                <el-input v-model="monitor.data.main_symbol" placeholder="gds_AUTD" />
              </el-form-item>
              <el-form-item label="监控品种列表">
                <el-select
                  v-model="monitor.data.monitor_symbols"
                  multiple
                  filterable
                  allow-create
                  default-first-option
                  placeholder="输入品种代码并回车添加"
                  class="full-width-select"
                >
                  <el-option
                    v-for="s in monitor.data.monitor_symbols"
                    :key="s"
                    :label="s"
                    :value="s"
                  />
                </el-select>
              </el-form-item>
              <el-form-item label="交易时段">
                <div class="trading-hours">
                  <div
                    v-for="(slot, index) in monitor.data.trading_hours"
                    :key="index"
                    class="trading-slot"
                  >
                    <el-time-picker
                      v-model="slot[0]"
                      format="HH:mm"
                      value-format="HH:mm"
                      placeholder="开始"
                    />
                    <span class="slot-sep">—</span>
                    <el-time-picker
                      v-model="slot[1]"
                      format="HH:mm"
                      value-format="HH:mm"
                      placeholder="结束"
                    />
                    <el-button
                      text
                      type="danger"
                      size="small"
                      @click="monitor.data.trading_hours.splice(index, 1)"
                    >
                      <font-awesome-icon icon="times" />
                    </el-button>
                  </div>
                  <el-button
                    text
                    type="primary"
                    size="small"
                    @click="monitor.data.trading_hours.push(['09:00', '11:30'])"
                  >
                    <font-awesome-icon icon="plus" /> 添加时段
                  </el-button>
                </div>
              </el-form-item>
              <el-form-item label="盎司转克常数">
                <el-input-number
                  v-model="monitor.data.ounce_to_gram"
                  :precision="4"
                  :step="0.0001"
                  disabled
                />
                <span class="unit">克/盎司（只读）</span>
              </el-form-item>
              <el-form-item label="启动时自动导入">
                <el-switch v-model="monitor.data.auto_import_on_start" />
              </el-form-item>
              <el-form-item label="最小记录阈值">
                <el-input-number
                  v-model="monitor.data.min_records_threshold"
                  :min="10"
                  :max="10000"
                />
                <span class="unit">条</span>
              </el-form-item>
              <el-form-item label="监控周期">
                <el-checkbox-group v-model="monitor.data.periods">
                  <el-checkbox value="60d" label="60天" />
                  <el-checkbox value="1y" label="1年" />
                  <el-checkbox value="30d" label="30天" />
                  <el-checkbox value="7d" label="7天" />
                </el-checkbox-group>
              </el-form-item>
              <el-form-item class="form-actions">
                <el-button type="primary" :loading="monitor.saving" @click="monitor.save()">
                  保存监控配置
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>

        <el-tab-pane label="消息模板" name="message">
          <div v-loading="message.loading" class="tab-content">
            <el-form v-if="message.data" label-width="160px" class="settings-form">
              <el-form-item label="包含时间">
                <el-switch v-model="message.data.include_time" />
              </el-form-item>
              <el-form-item label="价格格式">
                <el-input v-model="message.data.price_format" placeholder="¥{:.2f}" />
              </el-form-item>
              <el-form-item label="最大条件数">
                <el-input-number v-model="message.data.max_conditions" :min="1" :max="20" />
              </el-form-item>
              <el-form-item label="启用建议">
                <el-switch v-model="message.data.enable_suggestions" />
              </el-form-item>
              <el-form-item label="建议级别">
                <el-select
                  v-model="message.data.suggestion_level"
                  :disabled="!message.data.enable_suggestions"
                >
                  <el-option value="low" label="低" />
                  <el-option value="medium" label="中" />
                  <el-option value="high" label="高" />
                </el-select>
              </el-form-item>
              <el-form-item label="包含止损建议">
                <el-switch v-model="message.data.include_stop_loss" />
              </el-form-item>
              <el-form-item class="form-actions">
                <el-button type="primary" :loading="message.saving" @click="message.save()">
                  保存消息模板
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>

        <el-tab-pane label="品种映射" name="symbols">
          <div v-loading="symbolsLoading" class="tab-content">
            <div class="tab-toolbar">
              <el-button type="primary" @click="openAddSymbol">
                <font-awesome-icon icon="plus" /> 新增品种
              </el-button>
            </div>
            <el-table :data="symbols" stripe border class="symbol-table">
              <el-table-column prop="symbol" label="品种代码" width="180" />
              <el-table-column prop="display_name" label="显示名称" width="200" />
              <el-table-column prop="sort_order" label="排序权重" width="120" align="center" />
              <el-table-column label="操作" width="160" align="center">
                <template #default="{ row }">
                  <el-button
                    text
                    type="primary"
                    size="small"
                    @click="openEditSymbol(row as SymbolMapping)"
                  >
                    <font-awesome-icon icon="pen" /> 编辑
                  </el-button>
                  <el-button
                    text
                    type="danger"
                    size="small"
                    @click="handleDeleteSymbol(row.symbol)"
                  >
                    <font-awesome-icon icon="trash" /> 删除
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <el-tab-pane label="日志配置" name="log">
          <div v-loading="log.loading" class="tab-content">
            <el-form v-if="log.data" label-width="160px" class="settings-form">
              <el-alert
                type="warning"
                :closable="false"
                show-icon
                title="最大文件大小、备份文件数量、压缩旧日志、控制台输出 修改后需重启服务生效"
                class="log-notice"
              />
              <el-form-item label="最大文件大小">
                <el-input-number v-model="log.data.max_bytes" :min="1048576" :step="1048576" />
                <span class="unit">字节 ({{ (log.data.max_bytes / 1048576).toFixed(1) }} MB)</span>
              </el-form-item>
              <el-form-item label="备份文件数量">
                <el-input-number v-model="log.data.backup_count" :min="1" :max="100" />
              </el-form-item>
              <el-form-item label="压缩旧日志">
                <el-switch v-model="log.data.compress_backup" />
              </el-form-item>
              <el-form-item label="控制台输出">
                <el-switch v-model="log.data.console_output" />
              </el-form-item>
              <el-form-item label="保留天数">
                <el-input-number v-model="log.data.keep_days" :min="1" :max="365" />
                <span class="unit">天（运行时生效）</span>
              </el-form-item>
              <el-form-item label="日志等级">
                <el-select v-model="log.data.log_level" class="log-level-select">
                  <el-option value="DEBUG" label="DEBUG — 全部日志（默认，开发调试用）" />
                  <el-option value="INFO" label="INFO — 一般信息 + 警告 + 错误" />
                  <el-option value="WARNING" label="WARNING — 仅警告 + 错误" />
                  <el-option value="ERROR" label="ERROR — 仅错误" />
                </el-select>
                <span class="unit">即时生效，无需重启</span>
              </el-form-item>
              <el-form-item class="form-actions">
                <el-button type="primary" :loading="log.saving" @click="log.save()">
                  保存日志配置
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>

        <el-tab-pane label="基础设施" name="infrastructure">
          <div v-loading="infraLoading" class="tab-content">
            <el-alert
              type="info"
              :closable="false"
              show-icon
              title="只读端点，API URL 变更需同步修改解析逻辑，请在 config.py 中修改后重启。"
              class="log-notice"
            />
            <el-descriptions v-if="infrastructure" :column="1" border class="infra-descriptions">
              <el-descriptions-item label="金价数据源 API">
                <code>{{ infrastructure.gold_price_api_url }}</code>
              </el-descriptions-item>
              <el-descriptions-item label="美元汇率 API">
                <code>{{ infrastructure.usd_to_cny_api_url }}</code>
              </el-descriptions-item>
              <el-descriptions-item label="系统时区">
                {{ infrastructure.timezone }}
              </el-descriptions-item>
              <el-descriptions-item label="日志存储目录">
                <code>{{ infrastructure.log_dir }}</code>
              </el-descriptions-item>
            </el-descriptions>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <el-dialog v-model="showRateDialog" title="手动更新汇率" width="400px">
      <el-form label-width="100px">
        <el-form-item label="新汇率">
          <el-input-number v-model="rateInput" :min="1" :max="20" :precision="6" :step="0.0001" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRateDialog = false">取消</el-button>
        <el-button type="primary" :loading="updatingRate" @click="handleUpdateRate">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="showSymbolDialog"
      :title="isEditingSymbol ? '编辑品种映射' : '新增品种映射'"
      width="480px"
    >
      <el-form label-width="120px">
        <el-form-item label="品种代码">
          <el-input
            v-model="symbolForm.symbol"
            :disabled="isEditingSymbol"
            placeholder="如 gds_AUTD"
          />
        </el-form-item>
        <el-form-item label="显示名称">
          <el-input v-model="symbolForm.display_name" placeholder="如 黄金延期" />
        </el-form-item>
        <el-form-item label="排序权重">
          <el-input-number v-model="symbolForm.sort_order" :min="0" :max="999" />
          <span class="unit">越小越靠前</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showSymbolDialog = false">取消</el-button>
        <el-button type="primary" :loading="symbolSaving" @click="handleSaveSymbol">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import {
  faCog,
  faRotate,
  faDollarSign,
  faPen,
  faBell,
  faClock,
  faArrowTrendUp,
  faWaveSquare,
  faBolt,
  faAngleDoubleDown,
  faPlus,
  faTrash,
  faTimes,
} from '@fortawesome/free-solid-svg-icons'
import { settingsApi } from '@/api/modules/settings'
import type { ExchangeRate, SymbolMapping, InfrastructureConfig } from '@/api/modules/settings'
import { useSettingsGroup } from '@/composables/useSettings'

library.add(
  faCog,
  faRotate,
  faDollarSign,
  faPen,
  faBell,
  faClock,
  faArrowTrendUp,
  faWaveSquare,
  faBolt,
  faAngleDoubleDown,
  faPlus,
  faTrash,
  faTimes,
)

const activeTab = ref('alert')

const alert = useSettingsGroup(
  () => settingsApi.getAlert(),
  (data) => settingsApi.updateAlert(data),
)

const ai = useSettingsGroup(
  () => settingsApi.getAI(),
  (data) => settingsApi.updateAI(data),
)

const wechat = useSettingsGroup(
  () => settingsApi.getWeChat(),
  (data) => settingsApi.updateWeChat(data),
)

const email = useSettingsGroup(
  () => settingsApi.getEmail(),
  (data) => settingsApi.updateEmail(data),
)

const monitor = useSettingsGroup(
  () => settingsApi.getMonitor(),
  (data) => settingsApi.updateMonitor(data),
)

const message = useSettingsGroup(
  () => settingsApi.getMessage(),
  (data) => settingsApi.updateMessage(data),
)

const exchangeRate = ref<ExchangeRate | null>(null)
const reloading = ref(false)
const updatingRate = ref(false)
const showRateDialog = ref(false)
const rateInput = ref(0)

const symbols = ref<SymbolMapping[]>([])
const symbolsLoading = ref(false)
const showSymbolDialog = ref(false)
const symbolForm = ref<SymbolMapping>({ symbol: '', display_name: '', sort_order: 0 })
const isEditingSymbol = ref(false)
const symbolSaving = ref(false)

const log = useSettingsGroup(
  () => settingsApi.getLog(),
  (data) => settingsApi.updateLog(data),
)

const infrastructure = ref<InfrastructureConfig | null>(null)
const infraLoading = ref(false)

const loadExchangeRate = async () => {
  try {
    exchangeRate.value = await settingsApi.getExchangeRate()
  } catch {
    // 错误已在 request 拦截器中处理
  }
}

const loadSymbols = async () => {
  symbolsLoading.value = true
  try {
    symbols.value = await settingsApi.getSymbols()
  } catch {
    // 错误已在 request 拦截器中处理
  } finally {
    symbolsLoading.value = false
  }
}

const openAddSymbol = () => {
  isEditingSymbol.value = false
  symbolForm.value = { symbol: '', display_name: '', sort_order: 0 }
  showSymbolDialog.value = true
}

const openEditSymbol = (row: SymbolMapping) => {
  isEditingSymbol.value = true
  symbolForm.value = { ...row }
  showSymbolDialog.value = true
}

const handleSaveSymbol = async () => {
  symbolSaving.value = true
  try {
    await settingsApi.updateSymbol(symbolForm.value.symbol, symbolForm.value)
    ElMessage.success(isEditingSymbol.value ? '品种配置已更新' : '品种配置已添加')
    showSymbolDialog.value = false
    await loadSymbols()
  } catch {
    // 错误已在 request 拦截器中处理
  } finally {
    symbolSaving.value = false
  }
}

const handleDeleteSymbol = async (symbol: string) => {
  try {
    await ElMessageBox.confirm(`确定要删除品种 [${symbol}] 吗？`, '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await settingsApi.deleteSymbol(symbol)
    ElMessage.success(`品种 [${symbol}] 已删除`)
    await loadSymbols()
  } catch {
    // 用户取消或错误已在 request 拦截器中处理
  }
}

const loadInfrastructure = async () => {
  infraLoading.value = true
  try {
    infrastructure.value = await settingsApi.getInfrastructure()
  } catch {
    // 错误已在 request 拦截器中处理
  } finally {
    infraLoading.value = false
  }
}

const handleReload = async () => {
  reloading.value = true
  try {
    await settingsApi.reload()
    ElMessage.success('缓存已刷新')
  } catch {
    // 错误已在 request 拦截器中处理
  } finally {
    reloading.value = false
  }
}

const handleUpdateRate = async () => {
  updatingRate.value = true
  try {
    await settingsApi.updateExchangeRate(rateInput.value)
    ElMessage.success('汇率更新成功')
    showRateDialog.value = false
    await loadExchangeRate()
  } catch {
    // 错误已在 request 拦截器中处理
  } finally {
    updatingRate.value = false
  }
}

const loadedTabs = ref<Set<string>>(new Set())

const loadTab = (tabName: string) => {
  if (loadedTabs.value.has(tabName)) return
  loadedTabs.value.add(tabName)
  const groups = { alert, ai, wechat, email, monitor, message } as const
  const group = groups[tabName as keyof typeof groups]
  group?.load()
  if (tabName === 'symbols') loadSymbols()
  if (tabName === 'log') log.load()
  if (tabName === 'infrastructure') loadInfrastructure()
}

const onTabChange = (name: string | number) => {
  loadTab(String(name))
}

onMounted(() => {
  loadExchangeRate()
  loadTab(activeTab.value)
})
</script>

<style lang="scss" scoped>
.settings {
  max-width: 960px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;

  .page-title {
    font-size: 22px;
    color: var(--text-primary);
    margin: 0;
  }
}

.rate-card {
  margin-bottom: 20px;
  background: var(--card-bg);
  border: 1px solid var(--card-border);

  .rate-body {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .rate-info {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .rate-label {
    font-size: 14px;
    color: var(--text-secondary);
  }

  .rate-value {
    font-size: 22px;
    font-weight: bold;
    color: var(--price-color);
  }

  .rate-time {
    font-size: 13px;
    color: var(--text-muted);
  }
}

.main-card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
}

.tab-content {
  min-height: 300px;
  padding-top: 8px;
}

.settings-form {
  .form-section {
    margin-bottom: 24px;
    padding: 16px;
    background: var(--bg-secondary);
    border-radius: 8px;
    border: 1px solid var(--border-color);

    .tab-toolbar {
      margin-bottom: 16px;
    }

    .symbol-table {
      width: 100%;
    }

    .log-notice {
      margin-bottom: 20px;
    }

    .infra-descriptions {
      margin-top: 8px;

      code {
        background: var(--bg-secondary);
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 13px;
        word-break: break-all;
      }
    }

    .log-level-select {
      width: 220px;
    }

    .full-width-select {
      width: 100%;
    }

    .trading-hours {
      .trading-slot {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 8px;

        .slot-sep {
          color: var(--text-secondary);
          font-size: 14px;
        }
      }
    }

    .section-title {
      font-size: 15px;
      font-weight: 600;
      color: var(--text-primary);
      margin: 0 0 16px 0;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--border-color);
    }
  }

  .form-actions {
    margin-top: 24px;
    padding-top: 16px;
    border-top: 1px solid var(--border-color);
  }

  .unit {
    margin-left: 8px;
    color: var(--text-secondary);
    font-size: 13px;
  }
}
</style>
