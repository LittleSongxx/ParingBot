<template>
  <div class="main-content page-wrap">
    <div class="page-head">
      <div class="page-head-main">
        <h2>候选结果</h2>
        <p class="page-tip">
          这里展示智能匹配过程中筛选官生成的候选现场。第一轮按条件硬筛，人数不够交付要求时，
          再一轮放宽一个标为「加分」的维度继续找，每一轮放宽了什么、新增了几个人这里都列得出来。
          标为「必须」的条件不会放宽；需要重新筛选时，请统一到【智能匹配】发起新一轮。
        </p>
      </div>
    </div>

    <!-- 候选池挂在租客档案上，还没填档案时先把去处指清楚 -->
    <div v-if="data.loading" class="card loading-card" v-loading="true" element-loading-text="正在读取候选结果"></div>

    <div v-else-if="!data.has_profile" class="card block-card">
      <div class="block-title">先补租客档案</div>
      <el-alert
          type="warning"
          :closable="false"
          title="还没有填写租客档案"
          description="候选结果依赖租客档案和合住偏好，请先把档案填好保存。">
      </el-alert>
      <div class="go-action">
        <el-button type="primary" @click="router.push('/front/memberProfile')">去填写租客档案</el-button>
      </div>
    </div>

    <template v-else>
      <div v-if="!data.task" class="card empty-card">
        <div class="empty-icon"><el-icon><Search /></el-icon></div>
        <div class="empty-title">还没有候选结果</div>
        <div class="empty-desc">请先到【智能匹配】发起一轮，筛选官的结果会自动展示在这里。</div>
        <div class="go-action"><el-button type="primary" @click="router.push('/front/myMatch')">去智能匹配</el-button></div>
      </div>

      <template v-else>
        <div class="card block-card">
          <div class="block-title">这一次的筛选任务</div>
          <div class="task-head">
            <span class="task-badge">{{ data.task.task_no }}</span>
            <el-tag :type="statusType(data.task.status)" size="small">{{ data.task.status }}</el-tag>
            <span class="task-time">发起于 {{ data.task.create_time }}</span>
          </div>
          <div class="task-line">
            要求交付 {{ data.task.deliver_count }} 人，实际筛了 {{ data.task.total_round }} 轮，
            候选池现在有 {{ data.candidates.length }} 人。
          </div>
          <el-alert
              v-if="data.task.error_message"
              type="warning"
              :closable="false"
              :title="data.task.error_message">
          </el-alert>
        </div>

        <div class="card block-card">
          <div class="block-title">每一轮筛出来的结果</div>
          <el-table :data="data.rounds" stripe class="data-table">
            <el-table-column label="轮次" width="90">
              <template #default="scope">第 {{ scope.row.round }} 轮</template>
            </el-table-column>
            <el-table-column label="这一轮的放宽说明" width="220">
              <template #default="scope">
                <span v-if="scope.row.relax_note" class="chip chip-amber">{{ scope.row.relax_note }}</span>
                <span v-else class="muted">未放宽</span>
              </template>
            </el-table-column>
            <el-table-column prop="added" label="本轮新增" width="100"/>
            <el-table-column prop="total" label="累计候选" width="100"/>
            <el-table-column label="说明" show-overflow-tooltip>
              <template #default="scope">{{ roundTip(scope.row) }}</template>
            </el-table-column>
          </el-table>
          <div class="table-tip">
            放宽说明写在筛出这个人的那一轮上：说清放宽了哪个维度、放宽了多少，例如「年龄上限+2」。
          </div>
        </div>

        <div class="card block-card">
          <div class="block-title">候选名单</div>
          <el-table :data="data.candidates" stripe class="data-table">
            <el-table-column prop="nickname" label="昵称" width="120">
              <template #default="scope">{{ scope.row.nickname || '档案已查不到' }}</template>
            </el-table-column>
            <el-table-column prop="gender" label="性别" width="70"/>
            <el-table-column label="年龄" width="80">
              <template #default="scope">{{ scope.row.age ? scope.row.age + ' 岁' : '未填' }}</template>
            </el-table-column>
            <el-table-column label="月租预算" width="100">
              <template #default="scope">{{ scope.row.rent_budget ? scope.row.rent_budget + ' 元' : '未填' }}</template>
            </el-table-column>
            <el-table-column prop="schedule_type" label="作息" width="90"/>
            <el-table-column prop="store" label="意向门店" width="110"/>
            <el-table-column label="筛出轮次" width="100">
              <template #default="scope">第 {{ scope.row.found_round }} 轮</template>
            </el-table-column>
            <el-table-column label="放宽说明" width="150">
              <template #default="scope">
                <span v-if="scope.row.relax_note" class="chip chip-amber">{{ scope.row.relax_note }}</span>
                <span v-else class="muted">未放宽</span>
              </template>
            </el-table-column>
            <el-table-column label="初筛得分" width="100">
              <template #default="scope"><b class="score-text">{{ scope.row.screen_score }}</b></template>
            </el-table-column>
            <el-table-column label="审核状态" width="100">
              <template #default="scope">
                <el-tag :type="scope.row.audit_status === '通过' ? 'success' : (scope.row.audit_status === '否决' ? 'danger' : 'info')" size="small">
                  {{ scope.row.audit_status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="90">
              <template #default="scope">
                <el-button link type="primary" @click="showDetail(scope.row)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="table-tip">
            初筛得分是筛选官按偏好符合程度给的参考分，后面的双向审核通过之后才算交付的人选。
          </div>
        </div>
      </template>
    </template>

    <el-dialog class="candidate-dialog" title="候选详情" v-model="data.detailVisible" width="720px" destroy-on-close>
      <template v-if="data.detail">
        <div class="detail-head">
          <span class="detail-name">{{ data.detail.nickname || '档案已查不到' }}</span>
          <span class="chip chip-blue">第 {{ data.detail.found_round }} 轮筛出</span>
          <span v-if="data.detail.relax_note" class="chip chip-amber">
            放宽了 {{ data.detail.relax_note }}
          </span>
        </div>
        <div class="detail-panel">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="性别">{{ data.detail.gender || '未填' }}</el-descriptions-item>
            <el-descriptions-item label="年龄">
              {{ data.detail.age ? data.detail.age + ' 岁' : '未填' }}
            </el-descriptions-item>
            <el-descriptions-item label="职业">{{ data.detail.occupation || '未填' }}</el-descriptions-item>
            <el-descriptions-item label="意向门店">
              {{ data.detail.store ? data.detail.store + '（' + data.detail.area + '片区）' : '未填' }}
            </el-descriptions-item>
            <el-descriptions-item label="月租预算">
              {{ data.detail.rent_budget ? data.detail.rent_budget + ' 元' : '未填' }}
            </el-descriptions-item>
            <el-descriptions-item label="计划租期">{{ data.detail.lease_term || '未填' }}</el-descriptions-item>
            <el-descriptions-item label="作息">{{ data.detail.schedule_type || '未填' }}</el-descriptions-item>
            <el-descriptions-item label="整洁度">{{ data.detail.tidiness || '未填' }}</el-descriptions-item>
            <el-descriptions-item label="是否养宠">{{ data.detail.has_pet || '未填' }}</el-descriptions-item>
            <el-descriptions-item label="是否吸烟">{{ data.detail.smoking || '未填' }}</el-descriptions-item>
          </el-descriptions>
        </div>
        <div class="detail-block">
          <div class="section-title">兴趣标签</div>
          <div class="tag-list">
            <span class="tag-chip" v-for="tag in data.detail.interest_tags || []" :key="tag">{{ tag }}</span>
            <span v-if="!(data.detail.interest_tags || []).length" class="tag-empty">这位租客还没有选兴趣标签</span>
          </div>
        </div>
        <div class="detail-block">
          <div class="section-title">自我介绍</div>
          <div class="summary-box">{{ data.detail.self_intro || '（没有填）' }}</div>
        </div>
        <div class="detail-block">
          <div class="section-title">室友期望</div>
          <div class="summary-box">{{ data.detail.roommate_expectation || '（没有填）' }}</div>
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

const data = reactive({
  loading: true,
  has_profile: false,
  readiness: { checks: [], blocker: null, can_run: false },
  task: null,
  rounds: [],
  candidates: [],
  detailVisible: false,
  detail: null
})

const load = () => {
  request.get('/screener/my').then(res => {
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
  if (status === '执行失败') return 'danger'
  return 'warning'
}

// 轮次表最后那一列：把这一轮发生了什么写成一句人话
const roundTip = (row) => {
  if (row.added && row.relax_note) {
    return '放宽「' + row.relax_note + '」之后新增 ' + row.added + ' 人'
  }
  if (row.added) {
    return '按原条件筛出 ' + row.added + ' 人'
  }
  if (row.relax_note) {
    return '放宽「' + row.relax_note + '」之后这一轮没有人新进来'
  }
  return '这一轮没有筛出人'
}

const showDetail = (row) => {
  request.get('/screener/selectCandidate', { params: { candidate_id: row.id } }).then(res => {
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
.task-line {
  padding: 12px 0;
  font-size: 13px;
  line-height: 1.85;
  color: rgba(17, 24, 39, 0.78);
}
.block-card .el-alert { margin-top: 12px; }

.data-table { margin-top: 12px; }

/* 初筛得分是参考分，用等宽数字强调一下 */
.score-text {
  font-family: var(--pb-mono);
  font-size: 13px;
  font-weight: 650;
  color: var(--pb-text);
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

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.tag-chip {
  display: inline-flex;
  align-items: center;
  padding: 5px 13px;
  border-radius: 999px;
  border: 1px solid rgba(37, 99, 235, 0.16);
  background: var(--pb-brand-soft);
  color: var(--pb-brand);
  font-size: 12.5px;
  font-weight: 500;
  line-height: 18px;
}
.tag-empty { font-size: 12.5px; color: var(--pb-faint); }

@media (max-width: 768px) {
  .task-time { margin-left: 0; }
}
</style>
