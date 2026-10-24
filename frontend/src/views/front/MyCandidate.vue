<template>
  <div class="main-content">
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
          <el-table :data="data.rounds" stripe class="theme-table">
            <el-table-column label="轮次" width="90">
              <template #default="scope">第 {{ scope.row.round }} 轮</template>
            </el-table-column>
            <el-table-column label="这一轮的放宽说明" width="220">
              <template #default="scope">
                <span v-if="scope.row.relax_note">{{ scope.row.relax_note }}</span>
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
          <el-table :data="data.candidates" stripe class="theme-table">
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
                <span v-if="scope.row.relax_note">{{ scope.row.relax_note }}</span>
                <span v-else class="muted">未放宽</span>
              </template>
            </el-table-column>
            <el-table-column prop="screen_score" label="初筛得分" width="100"/>
            <el-table-column prop="audit_status" label="审核状态" width="100"/>
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
          <span class="round-chip">第 {{ data.detail.found_round }} 轮筛出</span>
          <span v-if="data.detail.relax_note" class="round-chip is-warn">
            放宽了 {{ data.detail.relax_note }}
          </span>
        </div>
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
        <div class="detail-block">
          <div class="tag-label">兴趣标签</div>
          <div class="tag-list">
            <span class="tag-chip" v-for="tag in data.detail.interest_tags || []" :key="tag">{{ tag }}</span>
            <span v-if="!(data.detail.interest_tags || []).length" class="tag-empty">这位租客还没有选兴趣标签</span>
          </div>
        </div>
        <div class="detail-block">
          <div class="tag-label">自我介绍</div>
          <div class="summary-box">{{ data.detail.self_intro || '（没有填）' }}</div>
        </div>
        <div class="detail-block">
          <div class="tag-label">室友期望</div>
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
  width: 100px;
  color: #666;
}
.check-message {
  color: #666;
  line-height: 20px;
}
.warn-text {
  color: #e6a23c;
}

/* 一次都没筛过时给一块带图标的空状态，比一行灰字更像一个能动手的地方 */
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
  padding-bottom: 4px;
}
.muted {
  color: #bbb;
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

/* 详情弹窗：谁、哪一轮进来、放宽了什么，一行读完 */
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
.round-chip.is-warn {
  color: #b7791f;
  border-color: #f3e0bd;
  background-color: #fdf6e8;
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
.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.tag-chip {
  padding: 4px 14px;
  border-radius: 999px;
  font-size: 13px;
  line-height: 18px;
  color: #1F6F6B;
  border: 1px solid #D5E8E6;
  background-color: rgba(31, 111, 107, .08);
}
.tag-empty {
  color: #bbb;
  font-size: 13px;
}
/* 自我介绍和室友期望单独抬成一块底色，跟上面的资料表拉开层次 */
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

/* 弹窗挂在 body 上渲染，主题色变量要按它自己的类名给，
   写在 .main-content 上的页面作用域盖不到 */
:global(.candidate-dialog) {
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
:global(.candidate-dialog .el-descriptions) {
  --el-descriptions-item-bordered-label-background: #F5FAF9;
}

</style>
