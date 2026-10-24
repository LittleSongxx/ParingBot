<template>
  <div class="main-content">
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
            <el-tag :type="statusType(data.task.status)" size="small">{{ data.task.status }}</el-tag>
            <span class="task-time">发起于 {{ data.task.create_time }}</span>
          </div>
          <div class="task-line">
            要求交付 {{ data.task.deliver_count }} 人，实际交付 {{ data.delivered }} 人，
            调度 {{ data.task.total_round }} 轮（上限 {{ data.limits.round_limit }} 轮）。
            交付的人就是审核通过的候选，到【审核结果】里看名单和每一位的审核结论。
          </div>
          <div class="count-line">
            <span class="count-chip">
              <span class="count-label">候选池</span>
              <b>{{ data.counts.total }}</b>
            </span>
            <span class="count-chip is-ok">
              <span class="count-label">已通过</span>
              <b>{{ data.counts.passed }}</b>
            </span>
            <span class="count-chip is-warn">
              <span class="count-label">已否决</span>
              <b>{{ data.counts.rejected }}</b>
            </span>
            <span class="count-chip">
              <span class="count-label">待审核</span>
              <b>{{ data.counts.pending }}</b>
            </span>
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
          <el-table :data="data.rounds" stripe class="theme-table">
            <el-table-column label="轮次" width="80">
              <template #default="scope">第 {{ scope.row.round }} 轮</template>
            </el-table-column>
            <el-table-column label="派给谁" width="160">
              <template #default="scope">
                <span v-if="scope.row.agent_name" class="agent-chip">{{ scope.row.agent_name }}</span>
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
          <el-table :data="data.distribution" stripe class="theme-table">
            <el-table-column prop="label" label="否决原因" width="280"/>
            <el-table-column label="人数" width="90">
              <template #default="scope">
                <span :class="{ muted: !scope.row.count }">{{ scope.row.count }}</span>
              </template>
            </el-table-column>
            <el-table-column label="下一步怎么办" show-overflow-tooltip>
              <template #default="scope">
                <span class="next-chip">{{ scope.row.solution }}</span>
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
      <div v-if="data.detail">
        <div class="detail-head">
          <span class="detail-name">第 {{ data.detail.round }} 轮</span>
          <span v-if="data.detail.agent_name" class="round-chip">{{ data.detail.agent_name }}</span>
        </div>
        <div class="detail-block">
          <div class="tag-label">主管给它的交代</div>
          <div class="summary-box">{{ data.detail.instruction || '（这一轮没有派角色）' }}</div>
        </div>
        <div class="detail-block">
          <div class="tag-label">主管这么派的依据</div>
          <div class="summary-box">{{ data.detail.reason || '（轮次用尽，主管直接收尾）' }}</div>
        </div>
        <div class="detail-block">
          <div class="tag-label">这一轮的结果</div>
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
.main-content {
  padding-bottom: 10px;
  --el-color-primary: #1F6F6B;
  --el-color-primary-light-3: #4F8F8A;
  --el-color-primary-light-5: #84B5B2;
  --el-color-primary-light-7: #A9CFCB;
  --el-color-primary-light-8: #C4DCDA;
  --el-color-primary-light-9: #EFF6F5;
  --el-color-primary-dark-2: #24625E;
}

/* 卡片标题统一加粗，不加任何装饰线条 */
.block-card {
  margin-top: 12px;
  padding: 20px 24px 22px;
}
.running-card {
  margin-top: 12px;
  padding: 20px 24px;
  border: 1px solid #D2EAE8;
  background: linear-gradient(135deg, #fff 0%, #F6FBFA 100%);
}
.running-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.running-dot {
  width: 12px;
  height: 12px;
  flex: none;
  border-radius: 50%;
  background: #1F6F6B;
  box-shadow: 0 0 0 0 rgba(31, 111, 107, .45);
  animation: running-pulse 1.5s infinite;
}
.running-title { font-size: 16px; font-weight: 700; color: #205551; }
.running-tip { margin-top: 4px; font-size: 13px; color: #748C8A; }
.running-current { margin-top: 12px; font-size: 13px; color: #526F6D; }
@keyframes running-pulse {
  70% { box-shadow: 0 0 0 10px rgba(31, 111, 107, 0); }
  100% { box-shadow: 0 0 0 0 rgba(31, 111, 107, 0); }
}
.block-title {
  font-size: 16px;
  font-weight: bold;
  line-height: 20px;
  color: #333;
}
.block-card .el-alert {
  margin-top: 14px;
}
.go-action {
  padding-top: 16px;
}

/* 前置条件逐条列出，满足和没满足用两套底色区分 */
.check-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  background-color: #fafafa;
  font-size: 13px;
}
.check-icon {
  flex: none;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
}
.check-icon.is-ok {
  color: #67c23a;
  background-color: rgba(103, 194, 58, .12);
}
.check-icon.is-warn {
  color: #e6a23c;
  background-color: rgba(230, 162, 60, .16);
}
.check-label {
  flex: none;
  width: 130px;
  color: #666;
}
.check-message {
  color: #666;
  line-height: 20px;
}
.warn-text {
  color: #e6a23c;
}

/* 一次都没发起过时给一块带图标的空状态，比一行灰字更像一个起点 */
.empty-card {
  margin-top: 12px;
  padding: 32px 24px 36px;
  text-align: center;
}
.empty-icon {
  width: 52px;
  height: 52px;
  margin: 0 auto 12px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  color: #1F6F6B;
  background-color: rgba(31, 111, 107, .1);
}
.empty-title {
  font-size: 15px;
  font-weight: bold;
  color: #333;
}
.empty-desc {
  margin-top: 6px;
  font-size: 13px;
  line-height: 22px;
  color: #999;
}

/* 任务卡：任务号做成主题色胶囊，跟右边的发起时间拉开主次 */
.task-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 16px;
  padding-bottom: 12px;
}
.task-badge {
  flex: none;
  padding: 3px 12px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: bold;
  color: #fff;
  background: linear-gradient(120deg, #1F6F6B 0%, #2F8A84 100%);
}
.task-time {
  color: #999;
  font-size: 12px;
  margin-left: auto;
}
.task-line {
  color: #333;
  font-size: 13px;
  line-height: 24px;
  padding-bottom: 12px;
}

/* 四个计数做成胶囊：通过走绿、否决走橙，其余用主题色浅底兜住 */
.count-line {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding-bottom: 14px;
}
.count-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 14px;
  border-radius: 999px;
  border: 1px solid #DFECEB;
  background-color: #F5FAF9;
  font-size: 13px;
  color: #333;
}
.count-chip b {
  font-size: 15px;
  color: #1F6F6B;
}
.count-chip.is-ok {
  border-color: #e0f0d6;
  background-color: rgba(103, 194, 58, .1);
}
.count-chip.is-ok b {
  color: #67c23a;
}
.count-chip.is-warn {
  border-color: #f3e0bd;
  background-color: #fdf6e8;
}
.count-chip.is-warn b {
  color: #e6a23c;
}
.count-label {
  color: #666;
}
.muted {
  color: #bbb;
}

/* 运行卡：运行号一行读完，结论单独抬成一块底色 */
.run-line {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 0 12px;
}
.run-no {
  font-weight: bold;
  font-size: 14px;
  color: #333;
}
.run-cost {
  color: #999;
  font-size: 12px;
  margin-left: auto;
}
.summary-box {
  padding: 14px 16px;
  border-radius: 8px;
  border: 1px solid #DFECEB;
  background-color: rgba(31, 111, 107, .05);
  color: #333;
  font-size: 13px;
  line-height: 24px;
  white-space: pre-wrap;
}

/* 两张表跟着主题色走：表头浅底色，表头字用主题色 */
.theme-table {
  margin-top: 14px;
  --el-table-header-bg-color: #F5FAF9;
  --el-table-header-text-color: #1F6F6B;
  --el-table-row-hover-bg-color: #F2F8F7;
}
.table-tip {
  color: #999;
  font-size: 12px;
  line-height: 20px;
  padding-top: 10px;
}
/* 派给谁那一列做成浅底色胶囊，跟旁边的纯文字列拉开层次 */
.agent-chip {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 18px;
  color: #1F6F6B;
  border: 1px solid #D5E8E6;
  background-color: rgba(31, 111, 107, .08);
}
/* 下一步怎么办指的是动作，用主题色胶囊标出来 */
.next-chip {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 18px;
  color: #1F6F6B;
  border: 1px solid #DFECEB;
  background-color: #F5FAF9;
}

/* 详情弹窗：哪一轮、派给谁，一行读完 */
.detail-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 16px;
}
.detail-name {
  font-size: 16px;
  font-weight: bold;
  color: #333;
}
.round-chip {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 18px;
  color: #1F6F6B;
  border: 1px solid #D5E8E6;
  background-color: rgba(31, 111, 107, .08);
}
.detail-block {
  padding-top: 16px;
}
.tag-label {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #666;
  font-size: 13px;
  padding-bottom: 8px;
}
.tag-label::before {
  content: "";
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: #1F6F6B;
}

/* 弹窗挂在 body 上渲染，主题色变量要按它自己的类名给，
   写在 .main-content 上的页面作用域盖不到 */
:global(.match-dialog) {
  --el-color-primary: #1F6F6B;
  --el-color-primary-light-3: #4F8F8A;
  --el-color-primary-light-5: #84B5B2;
  --el-color-primary-light-7: #A9CFCB;
  --el-color-primary-light-8: #C4DCDA;
  --el-color-primary-light-9: #EFF6F5;
  --el-color-primary-dark-2: #24625E;
}

</style>
