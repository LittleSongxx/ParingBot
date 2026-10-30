<template>
  <div class="main-content page-wrap">
    <div class="page-head">
      <div class="page-head-main">
        <h2>审核结果</h2>
        <p class="page-tip">
          这一步站的是候选室友那一侧的立场：拿候选方自己的合住偏好，反过来看你适不适合和他合住。
          你这边条件都满足，对方标为必须的项可能有一条不合，这一条就会被否决。
          否决必须分类，其中「画像不够、判断不了」会指出缺少的维度。
          这里仅展示智能匹配中的审核现场，不再单独发起审核；需要再次匹配时，请统一到【智能匹配】发起新一轮。
        </p>
      </div>
    </div>

    <!-- 审核挂在租客档案上，还没填档案时先把去处指清楚 -->
    <div v-if="data.loading" class="card loading-card" v-loading="true" element-loading-text="正在读取审核结果"></div>

    <div v-else-if="!data.has_profile" class="card block-card">
      <div class="block-title">先补租客档案</div>
      <el-alert
          type="warning"
          :closable="false"
          title="还没有填写租客档案"
          description="审核结果依赖租客档案和智能匹配生成的候选，请先把档案填好保存。">
      </el-alert>
      <div class="go-action">
        <el-button type="primary" @click="router.push('/front/memberProfile')">去填写租客档案</el-button>
      </div>
    </div>

    <template v-else>
      <div v-if="!data.task" class="card empty-card">
        <div class="empty-icon"><el-icon><Search /></el-icon></div>
        <div class="empty-title">还没有审核结果</div>
        <div class="empty-desc">请先到【智能匹配】发起一轮，审核官的结果会自动展示在这里。</div>
        <div class="go-action">
          <el-button type="primary" @click="router.push('/front/myMatch')">去智能匹配</el-button>
        </div>
      </div>

      <template v-else>
        <div class="card block-card">
          <div class="block-title">这一批候选</div>
          <div class="task-head">
            <span class="task-badge">{{ data.task.task_no }}</span>
            <span class="task-time">候选池发起于 {{ data.task.create_time }}</span>
          </div>
          <div class="metric-grid audit-metrics">
            <div class="metric-tile">
              <div class="metric-label">候选池</div>
              <div class="metric-value">{{ data.counts.total }}<small>人</small></div>
            </div>
            <div class="metric-tile">
              <div class="metric-label">待审核</div>
              <div class="metric-value">{{ data.counts.pending }}<small>人</small></div>
            </div>
            <div class="metric-tile">
              <div class="metric-label">已通过</div>
              <div class="metric-value is-ok">{{ data.counts.passed }}<small>人</small></div>
            </div>
            <div class="metric-tile">
              <div class="metric-label">已否决</div>
              <div class="metric-value is-warn">{{ data.counts.rejected }}<small>人</small></div>
            </div>
          </div>
          <div v-if="data.run" class="task-line">
            {{ data.run.run_type === '匹配编排' ? '本批来自智能匹配' : '最近一次独立审核' }}：{{ data.run.run_no }}，
            <el-tag :type="statusType(data.run.run_status)" size="small">{{ data.run.run_status }}</el-tag>
            {{ data.run.run_type === '匹配编排' ? '调度 ' : '审核 ' }}{{ data.run.total_round }} 轮，开始于 {{ data.run.create_time }}
          </div>
          <div v-else-if="data.counts.pending > 0" class="task-line">
            还有 {{ data.counts.pending }} 位候选等待审核；本轮执行状态和后续调度请到【智能匹配】查看。
          </div>
          <div v-else class="task-line">这一批候选已经全部审核完成。</div>
          <el-alert
              v-if="data.run && data.run.output_summary"
              type="success"
              :closable="false"
              :title="data.run.output_summary">
          </el-alert>
          <el-alert
              v-if="data.run && data.run.error_message"
              type="warning"
              :closable="false"
              :title="data.run.error_message">
          </el-alert>
        </div>

        <div class="card block-card">
          <div class="block-title">否决分类分布</div>
          <el-table :data="data.distribution" stripe class="data-table">
            <el-table-column label="否决分类" min-width="220">
              <template #default="scope">
                <span :class="scope.row.code === 'MISMATCH_HARD' ? 'chip chip-red' : (scope.row.code === 'PREFERENCE_CONFLICT' ? 'chip chip-amber' : 'chip chip-blue')">
                  {{ scope.row.label }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="分类编码" width="200">
              <template #default="scope"><span class="code-text">{{ scope.row.code }}</span></template>
            </el-table-column>
            <el-table-column label="人数" width="90">
              <template #default="scope">
                <span :class="{ muted: !scope.row.count }">{{ scope.row.count }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="solution" label="下一步做什么" width="180"/>
          </el-table>
          <div class="table-tip">
            三类固定都列出来，人数为零的那一类也在：只列出现过的分类，看不出是没出现还是漏了一类。
            审核结论只说明这位候选为什么通过或被否决，不会直接改变下一次筛选条件。
            需要再次匹配时，先根据原因调整档案或合住偏好，再到【智能匹配】发起新任务。
          </div>
        </div>

        <div class="card block-card">
          <div class="block-title">候选审核清单</div>
          <el-table :data="data.candidates" stripe class="data-table">
            <el-table-column prop="nickname" label="昵称" width="120">
              <template #default="scope">{{ scope.row.nickname || '档案已查不到' }}</template>
            </el-table-column>
            <el-table-column prop="gender" label="性别" width="70"/>
            <el-table-column label="年龄" width="80">
              <template #default="scope">{{ scope.row.age ? scope.row.age + ' 岁' : '未填' }}</template>
            </el-table-column>
            <el-table-column prop="schedule_type" label="作息" width="90"/>
            <el-table-column prop="store" label="意向门店" width="110"/>
            <el-table-column label="筛出轮次" width="100">
              <template #default="scope">第 {{ scope.row.found_round }} 轮</template>
            </el-table-column>
            <el-table-column label="审核结论" width="110">
              <template #default="scope">
                <el-tag :type="auditType(scope.row.audit_status)" size="small">
                  {{ scope.row.audit_status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="否决分类" width="200">
              <template #default="scope">
                <span v-if="scope.row.reject_label" :class="scope.row.reject_code === 'MISMATCH_HARD' ? 'chip chip-red' : (scope.row.reject_code === 'PREFERENCE_CONFLICT' ? 'chip chip-amber' : 'chip chip-blue')">{{ scope.row.reject_label }}</span>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="第几批审的" width="110">
              <template #default="scope">
                <span v-if="scope.row.audit_round">第 {{ scope.row.audit_round }} 批</span>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="90">
              <template #default="scope">
                <el-button link type="primary" @click="showDetail(scope.row)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="table-tip">
            清单里的数字和结论全部来自候选池的现查结果，模型结论里报的人数对不上时会写在审核结论里。
          </div>
        </div>

        <div class="card block-card">
          <div class="block-title">否决清单</div>
          <el-table :data="data.rejected" stripe class="data-table">
            <el-table-column prop="nickname" label="昵称" width="120">
              <template #default="scope">{{ scope.row.nickname || '档案已查不到' }}</template>
            </el-table-column>
            <el-table-column label="否决分类" width="200">
              <template #default="scope">
                <span :class="scope.row.reject_code === 'MISMATCH_HARD' ? 'chip chip-red' : (scope.row.reject_code === 'PREFERENCE_CONFLICT' ? 'chip chip-amber' : 'chip chip-blue')">{{ scope.row.reject_label }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="reject_reason" label="否决理由" min-width="260" show-overflow-tooltip/>
            <el-table-column label="下一步" width="180">
              <template #default="scope">{{ solutionOf(scope.row.reject_code) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="90">
              <template #default="scope">
                <el-button link type="primary" @click="showDetail(scope.row)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div v-if="!data.rejected.length" class="table-tip">
            这一批候选没有被否决的人。等审完之后这里会出现每一位被否决的候选与否决理由。
          </div>
          <div v-else class="table-tip">
            理由里点名了缺哪个维度的记录，可以作为补充租客档案和画像的依据。
          </div>
        </div>
      </template>
    </template>

    <el-dialog class="audit-dialog" title="审核详情" v-model="data.detailVisible" width="760px" destroy-on-close>
      <template v-if="data.detail">
        <div class="detail-head">
          <span class="detail-name">{{ data.detail.nickname || '档案已查不到' }}</span>
          <el-tag :type="auditType(data.detail.audit_status)" size="small">
            {{ data.detail.audit_status }}
          </el-tag>
          <span v-if="data.detail.audit_round" class="chip chip-blue">
            第 {{ data.detail.audit_round }} 批审的
          </span>
        </div>
        <div class="detail-panel">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="性别">{{ data.detail.gender || '未填' }}</el-descriptions-item>
            <el-descriptions-item label="年龄">
              {{ data.detail.age ? data.detail.age + ' 岁' : '未填' }}
            </el-descriptions-item>
            <el-descriptions-item label="月租预算">
              {{ data.detail.rent_budget ? data.detail.rent_budget + ' 元' : '未填' }}
            </el-descriptions-item>
            <el-descriptions-item label="意向门店">{{ data.detail.store || '未填' }}</el-descriptions-item>
            <el-descriptions-item label="作息">{{ data.detail.schedule_type || '未填' }}</el-descriptions-item>
            <el-descriptions-item label="整洁度">{{ data.detail.tidiness || '未填' }}</el-descriptions-item>
            <el-descriptions-item label="是否养宠">{{ data.detail.has_pet || '未填' }}</el-descriptions-item>
            <el-descriptions-item label="是否吸烟">{{ data.detail.smoking || '未填' }}</el-descriptions-item>
            <el-descriptions-item label="第几轮筛出">第 {{ data.detail.found_round }} 轮</el-descriptions-item>
          </el-descriptions>
        </div>
        <div class="detail-block">
          <div class="section-title">审核结论</div>
          <div v-if="data.detail.reject_reason" class="summary-box">
            {{ data.detail.reject_label }}：{{ data.detail.reject_reason }}
          </div>
          <div v-else-if="data.detail.audit_status === '待审核'" class="summary-box">
            这位候选还没有审核结论；本轮执行状态和后续调度请到【智能匹配】查看。
          </div>
          <div v-else class="summary-box">通过了：候选方标为必须的条件对申请方都成立。</div>
        </div>
        <div class="detail-block">
          <div class="section-title">候选方标为必须的条件</div>
          <div v-if="(data.detail.must_need || []).length" class="need-list">
            <div v-for="item in data.detail.must_need" :key="item.code" class="need-row">
              <span class="need-name">{{ item.name }}</span>
              <span class="need-value">{{ item.need }}</span>
            </div>
          </div>
          <div v-else class="muted">这位候选标为必须的项都填的是不限，等于对谁都不设门槛。</div>
        </div>
        <div class="detail-block">
          <div class="section-title">代码复核</div>
          <div class="summary-box">{{ (data.detail.recheck || {}).note }}</div>
        </div>
        <div class="detail-block">
          <div class="section-title">他在意的全部条件</div>
          <div class="summary-box">{{ data.detail.preference_text || '这位候选还没有填合住偏好。' }}</div>
        </div>
        <div class="detail-block">
          <div class="section-title">他的自我介绍</div>
          <div class="summary-box">{{ data.detail.self_intro || '（没有填）' }}</div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive } from "vue";
import { ElMessage } from "element-plus";
import { Search } from "@element-plus/icons-vue";
import router from "@/router/index.js";
import request from "@/utils/request.js";

// 三种否决分类下一步该做什么，和接口里给的分布口径一致
const SOLUTIONS = {
  MISMATCH_HARD: '本候选不匹配',
  PREFERENCE_CONFLICT: '本候选不匹配',
  PORTRAIT_INSUFFICIENT: '补充资料后再匹配'
}

const data = reactive({
  loading: true,
  has_profile: false,
  readiness: { checks: [], blocker: null, can_run: false },
  task: null,
  run: null,
  counts: { total: 0, passed: 0, rejected: 0, pending: 0 },
  distribution: [],
  candidates: [],
  rejected: [],
  detailVisible: false,
  detail: null
})

const load = () => {
  request.get('/auditor/my').then(res => {
    if (res.code !== '200') {
      ElMessage.error(res.msg)
      return
    }
    Object.assign(data, res.data)
  }).finally(() => {
    data.loading = false
  })
}

const statusType = (status) => {
  if (status === '已完成') return 'success'
  if (status === '运行失败') return 'danger'
  return 'warning'
}

const auditType = (status) => {
  if (status === '通过') return 'success'
  if (status === '否决') return 'danger'
  return 'info'
}

const solutionOf = (code) => SOLUTIONS[code] || '—'

const showDetail = (row) => {
  request.get('/auditor/selectCandidate', { params: { candidate_id: row.id } }).then(res => {
    if (res.code === '200') {
      data.detail = res.data
      data.detailVisible = true
    } else {
      ElMessage.error(res.msg)
    }
  })
}

load()
</script>

<style scoped>
.page-wrap > .page-head { margin: 0; }
.page-wrap > .card { margin-top: 0; }

.loading-card { min-height: 200px; }
.go-action { margin-top: 16px; }

/* 任务卡：任务号胶囊 + 时间靠右 */
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

.audit-metrics { margin: 16px 0 4px; }
.audit-metrics .metric-value.is-ok { color: #047857; }
.audit-metrics .metric-value.is-warn { color: #b45309; }

.task-line {
  padding: 12px 0;
  font-size: 13px;
  line-height: 1.9;
  color: rgba(17, 24, 39, 0.78);
}
.task-line .el-tag { vertical-align: 1px; }
.block-card .el-alert { margin-top: 12px; }

.data-table { margin-top: 12px; }

/* 分类编码用等宽字，和左侧的彩色分类标签区分 */
.code-text {
  font-family: var(--pb-mono);
  font-size: 12px;
  color: var(--pb-muted);
}

/* 详情弹窗 */
.detail-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 2px 0 4px;
}
.detail-name { font-size: 16px; font-weight: 650; color: var(--pb-text); }
.detail-panel { margin-top: 12px; }
.detail-block { margin-top: 16px; }
.detail-block .section-title { margin-bottom: 8px; }

/* 候选方标为必须的条件：一条一行，整块浅底 */
.need-list {
  padding: 2px 16px;
  border: 1px solid var(--pb-line);
  border-radius: var(--pb-radius-sm);
  background: var(--pb-surface-2);
}
.need-row {
  display: flex;
  gap: 12px;
  padding: 8px 0;
  font-size: 13px;
}
.need-row + .need-row { border-top: 1px solid var(--pb-line); }
.need-name { flex: none; width: 110px; color: var(--pb-muted); }
.need-value { color: var(--pb-text); }

@media (max-width: 768px) {
  .task-time { margin-left: 0; }
}
</style>
