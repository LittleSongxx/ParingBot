<template>
  <div class="main-content">
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
          <div class="count-line">
            <span class="count-chip">
              <span class="count-label">候选池</span>
              <b>{{ data.counts.total }}</b>
            </span>
            <span class="count-chip">
              <span class="count-label">待审核</span>
              <b>{{ data.counts.pending }}</b>
            </span>
            <span class="count-chip is-ok">
              <span class="count-label">已通过</span>
              <b>{{ data.counts.passed }}</b>
            </span>
            <span class="count-chip is-warn">
              <span class="count-label">已否决</span>
              <b>{{ data.counts.rejected }}</b>
            </span>
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
          <el-table :data="data.distribution" stripe class="theme-table">
            <el-table-column prop="label" label="否决分类" min-width="220"/>
            <el-table-column prop="code" label="分类编码" width="200"/>
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
          <el-table :data="data.candidates" stripe class="theme-table">
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
                <span v-if="scope.row.reject_label">{{ scope.row.reject_label }}</span>
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
          <el-table :data="data.rejected" stripe class="theme-table">
            <el-table-column prop="nickname" label="昵称" width="120">
              <template #default="scope">{{ scope.row.nickname || '档案已查不到' }}</template>
            </el-table-column>
            <el-table-column label="否决分类" width="200">
              <template #default="scope">
                <span class="reject-chip">{{ scope.row.reject_label }}</span>
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
          <span v-if="data.detail.audit_round" class="round-chip">
            第 {{ data.detail.audit_round }} 批审的
          </span>
        </div>
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
        <div class="detail-block">
          <div class="tag-label">审核结论</div>
          <div v-if="data.detail.reject_reason" class="summary-box">
            {{ data.detail.reject_label }}：{{ data.detail.reject_reason }}
          </div>
          <div v-else-if="data.detail.audit_status === '待审核'" class="summary-box">
            这位候选还没有审核结论；本轮执行状态和后续调度请到【智能匹配】查看。
          </div>
          <div v-else class="summary-box">通过了：候选方标为必须的条件对申请方都成立。</div>
        </div>
        <div class="detail-block">
          <div class="tag-label">候选方标为必须的条件</div>
          <div v-if="(data.detail.must_need || []).length" class="need-list">
            <div v-for="item in data.detail.must_need" :key="item.code" class="need-row">
              <span class="need-name">{{ item.name }}</span>
              <span class="need-value">{{ item.need }}</span>
            </div>
          </div>
          <div v-else class="muted">这位候选标为必须的项都填的是不限，等于对谁都不设门槛。</div>
        </div>
        <div class="detail-block">
          <div class="tag-label">代码复核</div>
          <div class="summary-box">{{ (data.detail.recheck || {}).note }}</div>
        </div>
        <div class="detail-block">
          <div class="tag-label">他在意的全部条件</div>
          <div class="summary-box">{{ data.detail.preference_text || '这位候选还没有填合住偏好。' }}</div>
        </div>
        <div class="detail-block">
          <div class="tag-label">他的自我介绍</div>
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
.loading-card {
  min-height: 180px;
  margin-top: 12px;
}

/* 卡片标题统一加粗，不加任何装饰线条 */
.block-card {
  margin-top: 12px;
  padding: 20px 24px 22px;
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
  width: 104px;
  color: #666;
}
.check-message {
  color: #666;
  line-height: 20px;
}
.warn-text {
  color: #e6a23c;
}
.ok-text {
  color: #67c23a;
}

/* 一次都没审过、连候选池都还没有时，给一块带图标的空状态 */
.empty-card {
  margin-top: 12px;
  padding: 28px 24px 32px;
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

/* 四个计数做成胶囊：通过走绿、否决走橙，没填数字的用浅底色兜住 */
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

/* 三张表跟着主题色走：表头浅底色，表头字用主题色 */
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

/* 详情弹窗：谁、哪一批审的，一行读完 */
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

/* 候选方标为必须的条件，一条一行，整块用和其它块一样的 1px 边框 */
.need-list {
  border: 1px solid #DFECEB;
  border-radius: 8px;
  padding: 4px 14px;
  background-color: rgba(31, 111, 107, .04);
}
.need-row {
  display: flex;
  padding: 7px 0;
  font-size: 13px;
}
.need-row + .need-row {
  border-top: 1px solid #DFEAE9;
}
.need-name {
  width: 110px;
  color: #666;
}
.need-value {
  color: #333;
}

/* 弹窗里成段的内容统一抬成一块底色，跟上面的资料表拉开层次 */
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

/* 否决策略胶囊：否决是这一页里唯一的负向结论，用偏红的一支区分 */
.reject-chip {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 18px;
  color: #b3413f;
  border: 1px solid #f0d5d4;
  background-color: #fdf3f2;
}

/* 弹窗挂在 body 上渲染，主题色变量要按它自己的类名给，
   写在 .main-content 上的页面作用域盖不到 */
:global(.audit-dialog) {
  --el-color-primary: #1F6F6B;
  --el-color-primary-light-3: #4F8F8A;
  --el-color-primary-light-5: #84B5B2;
  --el-color-primary-light-7: #A9CFCB;
  --el-color-primary-light-8: #C4DCDA;
  --el-color-primary-light-9: #EFF6F5;
  --el-color-primary-dark-2: #24625E;
}
/* 资料表的表头底色跟着主题色走；这个变量 Element Plus 挂在自己的 .el-descriptions 上，
   写在弹窗根节点上会被它盖掉，所以要直接给到 .el-descriptions */
:global(.audit-dialog .el-descriptions) {
  --el-descriptions-item-bordered-label-background: #F5FAF9;
}

</style>
