<template>
  <div class="page-wrap">
    <div class="page-head with-action">
      <div class="page-head-main">
        <h2>调度时间线</h2>
        <p class="page-tip">
          一次运行跑完，过程都留在这里：候选漏斗看这一趟筛出来多少人、被否掉多少、最后交出去几个；
          调度时间线按轮次摊开每一步，谁在什么时候做了什么、花了多久、走没走通，都找得到。
        </p>
      </div>
      <div class="page-head-action">
        <span class="chip chip-blue">过程可复盘 · 数据现查</span>
      </div>
    </div>

    <div class="card filter-card">
      <el-input v-model="data.runNo" class="filter-input" clearable placeholder="运行编号" prefix-icon="Search"
                @keyup.enter="search"></el-input>
      <el-select v-model="data.runType" clearable class="filter-select" placeholder="运行类型" @change="search">
        <el-option v-for="item in data.options.run_types" :key="item" :label="item" :value="item"></el-option>
      </el-select>
      <el-select v-model="data.runStatus" clearable class="filter-select" placeholder="运行状态" @change="search">
        <el-option v-for="item in data.options.run_statuses" :key="item" :label="item" :value="item"></el-option>
      </el-select>
      <div class="filter-actions">
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="reset">重置</el-button>
      </div>
    </div>

    <div class="card table-card">
      <el-table v-loading="data.loading" :data="data.tableData">
        <el-table-column prop="run_no" label="运行编号" width="230" show-overflow-tooltip>
          <template #default="scope">
            <span class="mono run-no">{{ scope.row.run_no }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="run_type" label="运行类型" />
        <el-table-column label="租客">
          <template #default="scope">{{ scope.row.nickname || '—' }}</template>
        </el-table-column>
        <el-table-column prop="task_no" label="匹配任务" width="230" show-overflow-tooltip>
          <template #default="scope">{{ scope.row.task_no || '—' }}</template>
        </el-table-column>
        <el-table-column label="调度轮次" width="100">
          <template #default="scope">{{ scope.row.total_round || 0 }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="scope">
            <el-tag :type="statusType(scope.row.run_status)" size="small">{{ scope.row.run_status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="耗时">
          <template #default="scope">{{ costText(scope.row.cost_millis) }}</template>
        </el-table-column>
        <el-table-column prop="start_time" label="开始时间" />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="scope">
            <el-button type="primary" link @click="openDetail(scope.row)">查看过程</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-card">
            <div class="empty-title">还没有运行记录</div>
            <div class="empty-desc">租客发起一次智能匹配后，这里会出现对应的运行记录。</div>
          </div>
        </template>
      </el-table>
      <div class="table-tip">
        每发起一次智能匹配，这里就会增加一条「匹配编排」运行记录。
        点击【查看过程】可以读取这次匹配从第一轮到收尾的完整过程。
      </div>
      <div class="pager-row" v-if="data.total">
        <el-pagination
            v-model:current-page="data.pageNum"
            background
            layout="prev, pager, next, total"
            :page-size="data.pageSize"
            :total="data.total"
            @current-change="load"
        />
      </div>
    </div>

    <el-dialog v-model="data.detailVisible" title="运行过程" width="92%" top="4vh" destroy-on-close>
      <div v-if="data.detail" class="dialog-body">
        <!-- 运行概览 -->
        <div class="soft-panel detail-block">
          <div class="block-title">运行概览</div>
          <el-descriptions :column="4" border size="small">
            <el-descriptions-item label="运行编号">
              <span class="mono">{{ data.detail.run.run_no }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="运行类型">{{ data.detail.run.run_type }}</el-descriptions-item>
            <el-descriptions-item label="运行状态">
              <el-tag :type="statusType(data.detail.run.run_status)" size="small">
                {{ data.detail.run.run_status }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="租客">{{ data.detail.run.nickname || '—' }}</el-descriptions-item>
            <el-descriptions-item label="匹配任务">{{ data.detail.run.task_no || '—' }}</el-descriptions-item>
            <el-descriptions-item label="调度轮次">{{ data.detail.stat.rounds }} 轮</el-descriptions-item>
            <el-descriptions-item label="步骤总数">{{ data.detail.stat.steps }} 步</el-descriptions-item>
            <el-descriptions-item label="步骤耗时合计">
              {{ costText(data.detail.stat.cost_millis) }}</el-descriptions-item>
            <el-descriptions-item label="开始时间">{{ data.detail.run.start_time || '—' }}</el-descriptions-item>
            <el-descriptions-item label="结束时间">{{ data.detail.run.end_time || '—' }}</el-descriptions-item>
            <el-descriptions-item label="整体耗时" :span="2">
              {{ costText(data.detail.run.cost_millis) }}</el-descriptions-item>
            <el-descriptions-item label="结论" :span="4">
              {{ data.detail.run.output_summary || '—' }}</el-descriptions-item>
            <el-descriptions-item v-if="data.detail.run.error_message" label="失败原因" :span="4">
              <span class="fail-text">{{ data.detail.run.error_message }}</span>
            </el-descriptions-item>
            <el-descriptions-item v-if="data.detail.run.input_snapshot" label="发起时的输入" :span="4">
              <pre class="code-line snapshot">{{ prettyJson(data.detail.run.input_snapshot) }}</pre>
            </el-descriptions-item>
          </el-descriptions>
        </div>

        <!-- 候选漏斗：蓝色渐变条 + 浅灰轨道 -->
        <div class="block-title section-gap">候选漏斗</div>
        <template v-if="data.detail.funnel.available">
          <div class="block-tip">
            从筛出来的人一直看到最后交出去的人。四个数字都是现查候选池数出来的，
            不采信运行当时写下的那句话。
          </div>
          <div class="soft-panel funnel-card">
            <div v-for="stage in data.detail.funnel.stages" :key="stage.key" class="funnel-row">
              <div class="funnel-head">
                <span class="funnel-label">{{ stage.label }}</span>
                <span class="funnel-value" :class="'text-' + stage.key">{{ stage.value }} 人</span>
                <span class="funnel-ratio">占筛出的 {{ stage.ratio }}%</span>
              </div>
              <div class="funnel-track">
                <div class="funnel-bar" :class="'bar-' + stage.key"
                     :style="{ width: barWidth(stage) }"></div>
              </div>
              <div class="funnel-desc">{{ stage.desc }}</div>
            </div>
            <div v-for="(note, index) in data.detail.funnel.notes" :key="index" class="funnel-note">
              {{ note }}
            </div>
          </div>
        </template>
        <el-alert v-else type="warning" :closable="false" show-icon
                  :title="data.detail.funnel.reason"></el-alert>

        <!-- 调度时间线：蓝色节点，每轮一张卡 -->
        <div class="block-title section-gap">调度时间线</div>
        <div class="block-tip">
          每一轮的头一条是主管的调度记录，记着这一轮派给谁、给了什么交代、为什么这么派；
          后面几条是被派角色写下的工具调用和结论。三个角色之间没有直接连线，
          谁接下一步都由上一轮调度记录决定。
        </div>
        <el-timeline v-if="data.detail.timeline.length" class="trace-timeline">
          <el-timeline-item v-for="one in data.detail.timeline" :key="one.round"
                            :type="one.failed ? 'danger' : 'primary'" placement="top"
                            :timestamp="'第 ' + one.round + ' 轮'">
            <div class="round-card">
              <div class="round-head">
                <span class="round-title">{{ roundTitle(one) }}</span>
                <span v-if="one.tool_calls" class="chip">工具调用 {{ one.tool_calls }} 次</span>
                <span v-if="one.failed" class="chip chip-red">有 {{ one.failed }} 步没走通</span>
                <span class="round-cost">{{ costText(one.cost_millis) }}</span>
              </div>
              <div v-if="one.reason" class="round-line"><span class="round-label">为什么这么派</span>{{ one.reason }}</div>
              <div v-if="one.instruction" class="round-line"><span class="round-label">给它的交代</span>{{ one.instruction }}</div>
              <el-table :data="one.steps" size="small" class="steps-table">
                <el-table-column type="expand">
                  <template #default="scope">
                    <div class="expand-box">
                      <div class="expand-label">入参</div>
                      <pre class="code-line expand-code">{{ prettyJson(scope.row.request_params) || '（没有入参）' }}</pre>
                      <div class="expand-label">返回</div>
                      <pre class="code-line expand-code">{{ prettyJson(scope.row.response_result) || '（没有返回）' }}</pre>
                      <template v-if="scope.row.error_message">
                        <div class="expand-label fail-text">失败原因</div>
                        <pre class="code-line expand-code">{{ scope.row.error_message }}</pre>
                      </template>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="步骤" width="70">
                  <template #default="scope">{{ scope.row.step_index }}</template>
                </el-table-column>
                <el-table-column label="类型" width="110">
                  <template #default="scope">
                    <el-tag size="small" :type="typeColor(scope.row.step_type)">
                      {{ scope.row.step_type }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="step_name" label="这一步做了什么" min-width="220"
                                 show-overflow-tooltip />
                <el-table-column label="工具" width="200" show-overflow-tooltip>
                  <template #default="scope">
                    <span v-if="scope.row.tool_code">{{ scope.row.tool_name }}</span>
                    <span v-else>—</span>
                  </template>
                </el-table-column>
                <el-table-column label="状态" width="110">
                  <template #default="scope">
                    <el-tag size="small" :type="scope.row.step_status === '已完成' ? 'success' : 'danger'">
                      {{ scope.row.step_status === '已完成' ? '已完成' : '没走通' }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="耗时" width="100">
                  <template #default="scope">{{ costText(scope.row.cost_millis) }}</template>
                </el-table-column>
                <el-table-column prop="start_time" label="发生时间" width="170" />
              </el-table>
            </div>
          </el-timeline-item>
        </el-timeline>
        <div v-else class="empty-card">
          <div class="empty-title">这次运行没有留下步骤记录</div>
          <div class="empty-desc">可能是运行刚开始或运行记录已被清理。</div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/utils/request.js'

const data = reactive({
  runNo: '',
  runType: '',
  runStatus: '',
  tableData: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  loading: false,
  options: { run_types: [], run_statuses: [] },
  detailVisible: false,
  detail: null
})

const load = () => {
  data.loading = true
  request.get('/trace/selectPage', {
    params: {
      page_num: data.pageNum,
      page_size: data.pageSize,
      run_no: data.runNo,
      run_type: data.runType,
      run_status: data.runStatus
    }
  }).then(res => {
    if (res.code === '200') {
      data.tableData = res.data?.list || []
      data.total = res.data?.total || 0
    } else {
      ElMessage.error(res.msg)
    }
  }).finally(() => {
    data.loading = false
  })
}

const loadOptions = () => {
  request.get('/trace/options').then(res => {
    if (res.code === '200') {
      data.options = res.data
    }
  })
}

// 查询和重置都回到第一页：留在第 3 页再筛，很可能筛完是空的
const search = () => {
  data.pageNum = 1
  load()
}

const reset = () => {
  data.runNo = ''
  data.runType = ''
  data.runStatus = ''
  data.pageNum = 1
  load()
}

const openDetail = (row) => {
  request.get('/trace/detail', { params: { run_id: row.id } }).then(res => {
    if (res.code === '200') {
      data.detail = res.data
      data.detailVisible = true
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const statusType = (status) => {
  if (status === '已完成') return 'success'
  if (status === '运行失败') return 'danger'
  return 'warning'
}

const typeColor = (stepType) => {
  if (stepType === '调度') return 'warning'
  if (stepType === '角色结论') return 'success'
  return 'primary'
}

// 耗时按毫秒存在库里，超过一秒的换成秒显示，一眼能看出快慢
const costText = (millis) => {
  if (millis === null || millis === undefined) return '—'
  return millis >= 1000 ? (millis / 1000).toFixed(1) + ' 秒' : millis + ' 毫秒'
}

// 漏斗条的宽度按占筛出总数的比例来，人数最少也给 3% 的红条，
// 否则 0 人的那一级和「这一级不存在」在页面上分不出来
const barWidth = (stage) => (stage.value ? Math.max(stage.ratio, 3) + '%' : '0%')

const roundTitle = (one) => {
  if (one.scheduled && one.finished) return '主管看过进展，决定收尾，这一轮不再派人'
  if (one.scheduled) return '主管把这一轮派给' + (one.agent_name || '未登记的角色')
  return '这一轮由' + (one.agent_name || '未登记的角色') + '自己跑完'
}

// 入参和返回多数是 JSON 文本，格式化后缩进展示；
// 结论这类普通文本解析失败就原样返回
const prettyJson = (text) => {
  if (!text) return ''
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch (e) {
    return text
  }
}

load()
loadOptions()
</script>

<style scoped>
/* 列表页统一范式：页头 → 筛选卡 → 表格卡（分页在卡片内） */
.filter-card {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.filter-input { width: 240px; }
.filter-select { width: 160px; }

.filter-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
}

.table-card {
  padding: 18px 20px 16px;
}

.table-card :deep(.el-table__empty-block) {
  background: transparent;
}

.table-card :deep(.el-table__empty-text) {
  width: 100%;
  line-height: 1.6;
}

.table-card :deep(.empty-card) {
  width: 100%;
  margin: 6px 0;
  padding: 38px 20px;
}

.run-no {
  font-size: 12.5px;
  color: var(--pb-muted);
}

.pager-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

/* 详情弹窗整体滚动 */
.dialog-body {
  max-height: 76vh;
  overflow-y: auto;
  padding: 0 4px 4px;
}

.detail-block {
  margin-bottom: 6px;
}

.detail-block .block-title {
  margin-bottom: 10px;
}

.section-gap {
  margin-top: 26px;
}

.block-tip {
  margin-bottom: 12px;
  color: var(--pb-muted);
  font-size: 12.5px;
  line-height: 21px;
}

.snapshot {
  max-height: 200px;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}

/* 候选漏斗：轨道浅灰，条为蓝色渐变 */
.funnel-card {
  padding: 16px 18px;
}

.funnel-row {
  margin-bottom: 16px;
}

.funnel-row:last-of-type {
  margin-bottom: 8px;
}

.funnel-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.funnel-label {
  min-width: 64px;
  font-size: 13px;
  font-weight: 550;
  color: var(--pb-text);
}

.funnel-value {
  font-size: 16px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.funnel-ratio {
  font-size: 12px;
  color: var(--pb-faint);
}

.funnel-track {
  height: 12px;
  margin: 7px 0 5px;
  border-radius: 999px;
  background: var(--pb-surface-3);
  overflow: hidden;
}

.funnel-bar {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #60a5fa 0%, #2563eb 100%);
  transition: width 0.3s ease;
}

.bar-total,
.bar-rejected,
.bar-passed,
.bar-delivered {
  background: linear-gradient(90deg, #60a5fa 0%, #2563eb 100%);
}

.text-total { color: var(--pb-brand); }
.text-rejected { color: var(--pb-danger); }
.text-passed { color: var(--pb-ok); }
.text-delivered { color: var(--pb-warn); }

.funnel-desc {
  font-size: 12px;
  color: var(--pb-faint);
}

.funnel-note {
  margin-top: 8px;
  padding: 6px 10px;
  border-radius: 8px;
  background: var(--pb-warn-soft);
  color: #b45309;
  font-size: 12px;
  line-height: 19px;
}

/* 调度时间线：蓝色节点 + 每轮一张卡 */
.trace-timeline {
  padding-left: 4px;
}

.trace-timeline :deep(.el-timeline-item__node) {
  background: var(--pb-brand);
  box-shadow: 0 0 0 4px var(--pb-brand-soft);
}

.trace-timeline :deep(.el-timeline-item__node--danger) {
  background: var(--pb-danger);
  box-shadow: 0 0 0 4px var(--pb-danger-soft);
}

.trace-timeline :deep(.el-timeline-item__timestamp) {
  color: var(--pb-muted);
  font-size: 12px;
  font-weight: 600;
}

.trace-timeline :deep(.el-timeline-item__tail) {
  border-left-color: var(--pb-line);
}

.round-card {
  padding: 14px 16px;
  background: var(--pb-surface);
  border: 1px solid var(--pb-line);
  border-radius: var(--pb-radius-sm);
  box-shadow: var(--pb-shadow-card);
}

.round-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.round-title {
  font-size: 14px;
  font-weight: 650;
  color: var(--pb-text);
}

.round-cost {
  margin-left: auto;
  font-family: var(--pb-mono);
  font-size: 12px;
  color: var(--pb-faint);
}

.round-line {
  margin-top: 6px;
  color: var(--pb-muted);
  font-size: 13px;
  line-height: 21px;
}

.round-label {
  display: inline-block;
  margin-right: 8px;
  padding: 0 8px;
  border-radius: 999px;
  background: var(--pb-brand-soft);
  color: var(--pb-brand);
  font-size: 11.5px;
  line-height: 19px;
}

.steps-table {
  margin-top: 10px;
}

.expand-box {
  padding: 8px 14px 12px;
}

.expand-label {
  margin: 8px 0 5px;
  font-size: 12px;
  color: var(--pb-faint);
}

.expand-code {
  max-height: 220px;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}

.fail-text {
  color: var(--pb-danger);
}

@media (max-width: 768px) {
  .filter-input,
  .filter-select {
    width: 100%;
  }

  .filter-actions {
    margin-left: 0;
  }
}
</style>
