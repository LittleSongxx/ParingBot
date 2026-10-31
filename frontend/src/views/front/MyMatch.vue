<template>
  <div class="main-content page-wrap">
    <!-- 页头：说清这一步在干什么，右侧是发起入口 -->
    <div class="page-head with-action">
      <div class="page-head-main">
        <h2>智能匹配</h2>
        <p class="page-tip">
          这里是唯一执行入口；「画像结果、候选结果、审核结果」三个页面只展示本次运行现场。
          平台把画画像、找候选、反向审核这三件事交给三个专职角色去做，
          合租管家每一轮看一遍当前进展，决定下一步派谁：候选还差得远就派筛选官接着找，
          审核官说画像不够就派画像师补，够交付了就收尾。
          每一轮派了谁、为什么这么派，下面的调度过程里都列得出来。
        </p>
      </div>
      <div class="page-head-action">
        <el-button
            type="primary"
            size="large"
            :loading="data.submitting"
            :disabled="!data.readiness.can_run || isRunning"
            @click="handleRun">{{ isRunning ? '匹配执行中' : '重新智能匹配' }}</el-button>
      </div>
    </div>

    <!-- 匹配挂在租客档案上，还没填档案时先把去处指清楚 -->
    <div v-if="!data.has_profile" class="card block-card">
      <div class="block-title">先补租客档案</div>
      <el-alert
          type="warning"
          :closable="false"
          title="还没有填写租客档案"
          description="发起匹配要先有档案、偏好和动态，请先把这些填好。">
      </el-alert>
      <div class="go-action">
        <el-button type="primary" @click="router.push('/front/memberProfile')">去填写租客档案</el-button>
      </div>
    </div>

    <template v-else>
      <div v-if="data.readiness.blocker" class="card block-card">
        <div class="block-title">发起匹配前要先满足这几项</div>
        <div v-for="item in data.readiness.checks" :key="item.key" class="check-row">
          <span class="check-icon" :class="item.ok ? 'is-ok' : 'is-warn'">
            <el-icon><component :is="item.ok ? CircleCheckFilled : WarningFilled" /></el-icon>
          </span>
          <span class="check-label">{{ item.label }}</span>
          <span class="check-message" :class="{ 'warn-text': !item.ok }">{{ item.message }}</span>
        </div>
        <div v-if="data.readiness.blocker.action_path" class="go-action">
          <el-button type="primary" @click="router.push(data.readiness.blocker.action_path)">
            {{ data.readiness.blocker.action_label }}
          </el-button>
        </div>
      </div>

      <div v-if="!data.task" class="card empty-card">
        <div class="empty-icon"><el-icon><Search /></el-icon></div>
        <div class="empty-title">还没有发起过匹配</div>
        <div class="empty-desc">
          点上面的「重新智能匹配」，主管会按当前最新档案一步步把活派下去。
        </div>
      </div>

      <template v-else>
        <div v-if="isRunning" class="card running-card">
          <div class="running-head">
            <span class="running-dot"></span>
            <div>
              <div class="running-title">智能匹配正在后台执行</div>
              <div class="running-tip">可以离开本页，任务不会中断；回来后会自动恢复进度。</div>
            </div>
          </div>
          <el-progress :percentage="100" :show-text="false" :indeterminate="true" :duration="2" />
          <div class="running-current">
            {{ latestRound
              ? `当前进展：第 ${latestRound.round} 轮，${latestRound.agent_name || '主管正在决策'}`
              : '正在初始化任务，等待主管给出第一轮调度决定……' }}
          </div>
        </div>

        <div class="card block-card">
          <div class="block-title">这一次的匹配任务</div>
          <div class="task-head">
            <span class="task-badge">{{ data.task.task_no }}</span>
            <el-tag :type="data.delivery.partial ? 'warning' : statusType(data.task.status)" size="small">
              {{ data.delivery.partial ? `部分交付 ${data.delivery.delivered}/${data.delivery.requested}` : data.task.status }}
            </el-tag>
            <span class="task-time">发起于 {{ data.task.create_time }}</span>
          </div>
          <div class="metric-grid task-metrics">
            <div class="metric-tile">
              <div class="metric-label">候选池</div>
              <div class="metric-value">{{ data.counts.total }}<small>人</small></div>
            </div>
            <div class="metric-tile">
              <div class="metric-label">已通过</div>
              <div class="metric-value is-ok">{{ data.counts.passed }}<small>人</small></div>
            </div>
            <div class="metric-tile">
              <div class="metric-label">已否决</div>
              <div class="metric-value is-warn">{{ data.counts.rejected }}<small>人</small></div>
            </div>
            <div class="metric-tile">
              <div class="metric-label">待审核</div>
              <div class="metric-value">{{ data.counts.pending }}<small>人</small></div>
            </div>
          </div>
          <div class="task-line">
            要求交付 {{ data.task.deliver_count }} 人，实际交付 {{ data.delivered }} 人，
            调度 {{ data.task.total_round }} 轮（上限 {{ data.limits.round_limit }} 轮）。
            交付的人就是审核通过的候选，到【审核结果】里看名单和每一位的审核结论。
          </div>
          <el-alert
              v-if="data.delivery.partial && !isRunning"
              type="warning"
              :closable="false"
              :title="`本次只交付 ${data.delivery.delivered}/${data.delivery.requested} 人：候选供给不足，不是运行失败`"
              :description="data.delivery.note || ''">
          </el-alert>
          <div v-if="(data.delivery.truncated || []).length" class="task-line">
            按交付上限截断未展示：{{ data.delivery.truncated.join('、') }}
          </div>
          <el-alert
              v-if="data.task.error_message"
              type="warning"
              :closable="false"
              :title="data.task.error_message">
          </el-alert>
          <el-alert
              v-else-if="data.note"
              type="info"
              :closable="false"
              :title="data.note">
          </el-alert>
        </div>

        <div v-if="data.run" class="card block-card">
          <div class="block-title">最近一次运行</div>
          <div class="run-line">
            <span class="run-no">{{ data.run.run_no }}</span>
            <el-tag :type="statusType(data.run.run_status)" size="small">{{ data.run.run_status }}</el-tag>
            <span class="run-cost">耗时 {{ costText(data.run.cost_millis) }}</span>
          </div>
          <div v-if="data.run.output_summary" class="summary-box">{{ data.run.output_summary }}</div>
          <div v-else-if="isRunning" class="summary-box muted">运行结束后将在这里显示最终结论。</div>
        </div>

        <div class="card block-card">
          <div class="block-title">调度过程</div>
          <el-table :data="data.rounds" stripe class="data-table">
            <el-table-column label="轮次" width="80">
              <template #default="scope">第 {{ scope.row.round }} 轮</template>
            </el-table-column>
            <el-table-column label="派给谁" width="160">
              <template #default="scope">
                <span v-if="scope.row.agent_name" class="chip chip-violet">{{ scope.row.agent_name }}</span>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="主管的判断依据" show-overflow-tooltip>
              <template #default="scope">
                <span v-if="scope.row.reason">{{ scope.row.reason }}</span>
                <span v-else class="muted">轮次用尽，主管直接收尾</span>
              </template>
            </el-table-column>
            <el-table-column label="工具调用" width="100">
              <template #default="scope">{{ scope.row.tool_calls }} 次</template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="scope">
                <el-tag :type="scope.row.failed ? 'danger' : (scope.row.conclusion ? 'success' : 'warning')" size="small">
                  {{ scope.row.failed ? '被中断' : (scope.row.conclusion ? '已完成' : '执行中') }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="90">
              <template #default="scope">
                <el-button link type="primary" @click="showRound(scope.row)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="table-tip">
            每一轮都是主管先看一遍进展、再决定派谁。被闸拦下来的轮次会标成「被中断」，
            点「查看」能看到主管这一轮的交代和这个角色回给主管的结论。
          </div>
        </div>

        <div class="card block-card">
          <div class="block-title">否决分类</div>
          <el-table :data="data.distribution" stripe class="data-table">
            <el-table-column prop="label" label="否决原因" width="280"/>
            <el-table-column label="人数" width="90">
              <template #default="scope">
                <span :class="{ muted: !scope.row.count }">{{ scope.row.count }}</span>
              </template>
            </el-table-column>
            <el-table-column label="下一步怎么办" show-overflow-tooltip>
              <template #default="scope">
                <span class="chip chip-blue">{{ scope.row.solution }}</span>
              </template>
            </el-table-column>
          </el-table>
          <div class="table-tip">
            审核官否决一个人必须说明原因。需要再次匹配时，先根据原因调整档案或合住偏好，
            再点击页面上方【重新智能匹配】。
          </div>
        </div>
      </template>
    </template>

    <el-dialog class="match-dialog" v-model="data.detailVisible" title="这一轮发生了什么" width="680px" destroy-on-close>
      <div v-if="data.detail" class="detail-wrap">
        <div class="detail-head">
          <span class="detail-name">第 {{ data.detail.round }} 轮</span>
          <span v-if="data.detail.agent_name" class="chip chip-violet">{{ data.detail.agent_name }}</span>
        </div>
        <div class="detail-block">
          <div class="section-title">主管给它的交代</div>
          <div class="summary-box">{{ data.detail.instruction || '（这一轮没有派角色）' }}</div>
        </div>
        <div class="detail-block">
          <div class="section-title">主管这么派的依据</div>
          <div class="summary-box">{{ data.detail.reason || '（轮次用尽，主管直接收尾）' }}</div>
        </div>
        <div class="detail-block">
          <div class="section-title">这一轮的结果</div>
          <div class="summary-box">{{ data.detail.conclusion || '（这个角色没有回结论）' }}</div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive } from "vue";
import { ElMessage } from "element-plus";
import { CircleCheckFilled, WarningFilled, Search } from "@element-plus/icons-vue";
import router from "@/router/index.js";
import request from "@/utils/request.js";

const data = reactive({
  has_profile: false,
  readiness: { checks: [], blocker: null, can_run: false },
  task: null,
  run: null,
  rounds: [],
  counts: { total: 0, passed: 0, rejected: 0, pending: 0 },
  distribution: [],
  limits: { round_limit: 0, relax_limit: 0, portrait_limit: 0 },
  note: null,
  delivered: 0,
  delivery: { requested: 0, delivered: 0, passed: 0, partial: false, truncated: [], note: null },
  submitting: false,
  detailVisible: false,
  detail: null
})

const isRunning = computed(() =>
  data.run?.run_status === '运行中' || data.task?.status === '执行中'
)
const latestRound = computed(() => data.rounds.length ? data.rounds[data.rounds.length - 1] : null)
let pollTimer = null
let loadingPage = false

const stopPolling = () => {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

const ensurePolling = () => {
  if (isRunning.value && !pollTimer) pollTimer = setInterval(load, 2000)
  if (!isRunning.value) stopPolling()
}

const load = () => {
  if (loadingPage) return
  loadingPage = true
  request.get('/match/my').then(res => {
    if (res.code !== '200') {
      ElMessage.error(res.msg)
      return
    }
    Object.assign(data, res.data)
  }).catch(() => {
    // 请求拦截器已经把可读错误提示给用户了；这里兜住 reject，
    // 否则 500 会变成未处理的 Promise rejection（浏览器 pageerror）。
  }).finally(() => {
    loadingPage = false
    ensurePolling()
  })
}

const statusType = (status) => {
  if (status === '已完成') return 'success'
  if (status === '执行失败' || status === '运行失败') return 'danger'
  return 'warning'
}

// 耗时按毫秒存在库里，超过一秒的换成秒显示，一眼能看出快慢
const costText = (millis) => {
  if (millis === null || millis === undefined) return '—'
  return millis >= 1000 ? (millis / 1000).toFixed(1) + ' 秒' : millis + ' 毫秒'
}

const handleRun = () => {
  data.submitting = true
  request.post('/match/rerun').then(res => {
    if (res.code === '200') {
      ElMessage.success(res.data.message)
      load()
    } else {
      ElMessage.error(res.msg)
      load()
    }
  }).finally(() => {
    data.submitting = false
  })
}

const showRound = (row) => {
  data.detail = row
  data.detailVisible = true
}

load()
onBeforeUnmount(stopPolling)
</script>

<style scoped>
.page-wrap > .page-head { margin: 0; }
.page-wrap > .card { margin-top: 0; }

.go-action { margin-top: 16px; }

/* 前置条件：图标放进 30px 圆角色块，通过走绿、缺项走琥珀 */
.check-icon {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 10px;
  font-size: 15px;
}
.check-icon.is-ok { color: #047857; background: var(--pb-ok-soft); }
.check-icon.is-warn { color: #b45309; background: var(--pb-warn-soft); }
.check-label { flex: none; min-width: 96px; }
.check-message { flex: 1; min-width: 0; }
.warn-text { color: #b45309; }

/* 运行中：浅蓝渐变卡 + 脉冲圆点 */
.running-card {
  border-color: rgba(37, 99, 235, 0.18);
  background: linear-gradient(135deg, #ffffff 0%, #f6f9ff 100%);
}
.running-head {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 16px;
}
.running-dot {
  flex: none;
  width: 11px;
  height: 11px;
  border-radius: 50%;
  background: var(--pb-brand);
  box-shadow: 0 0 0 0 rgba(37, 99, 235, 0.45);
  animation: match-pulse 1.6s ease-out infinite;
}
@keyframes match-pulse {
  70% { box-shadow: 0 0 0 12px rgba(37, 99, 235, 0); }
  100% { box-shadow: 0 0 0 0 rgba(37, 99, 235, 0); }
}
.running-title { font-size: 15px; font-weight: 650; color: var(--pb-text); }
.running-tip { margin-top: 3px; font-size: 12.5px; color: var(--pb-muted); }
.running-current {
  margin-top: 14px;
  padding: 10px 14px;
  border-radius: 10px;
  border: 1px dashed var(--pb-line-strong);
  background: rgba(255, 255, 255, 0.72);
  font-size: 12.5px;
  line-height: 20px;
  color: var(--pb-muted);
}

/* 任务卡：任务号胶囊 + 四个统计块 */
.task-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 14px;
}
.task-badge {
  flex: none;
  padding: 3px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0.01em;
  color: #fff;
  background: linear-gradient(120deg, #60a5fa, #2563eb);
}
.task-time { margin-left: auto; font-size: 12px; color: var(--pb-faint); }
.task-metrics { margin: 16px 0 14px; }
.task-metrics .metric-value.is-ok { color: #047857; }
.task-metrics .metric-value.is-warn { color: #b45309; }
.task-line {
  padding-bottom: 12px;
  font-size: 13px;
  line-height: 1.85;
  color: rgba(17, 24, 39, 0.78);
}
.block-card .el-alert { margin-top: 12px; }

/* 最近一次运行 */
.run-line {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 0 12px;
}
.run-no {
  font-family: var(--pb-mono);
  font-size: 14px;
  font-weight: 650;
  color: var(--pb-text);
  letter-spacing: -0.01em;
}
.run-cost { margin-left: auto; font-size: 12px; color: var(--pb-faint); }

.data-table { margin-top: 12px; }

/* 详情弹窗 */
.detail-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 2px 0 4px;
}
.detail-name { font-size: 16px; font-weight: 650; color: var(--pb-text); }
.detail-block { margin-top: 14px; }
.detail-block .section-title { margin-bottom: 8px; }

@media (max-width: 768px) {
  .check-row { flex-wrap: wrap; }
  .check-message { flex-basis: 100%; padding-left: 40px; }
  .task-time { margin-left: 0; }
}
</style>
