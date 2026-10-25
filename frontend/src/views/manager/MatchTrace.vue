<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <el-alert type="info" :closable="false" show-icon
                title="一次运行跑完，过程都留在这里：候选漏斗看这一趟筛出来多少人、被否掉多少、最后交出去几个；调度时间线按轮次摊开每一步，谁在什么时候做了什么、花了多久、走没走通，都找得到。">
      </el-alert>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <el-input v-model="data.runNo" clearable placeholder="运行编号" prefix-icon="Search"
                style="width: 230px; margin-right: 10px" @keyup.enter="search"></el-input>
      <el-select v-model="data.runType" clearable placeholder="运行类型"
                 style="width: 150px; margin-right: 10px" @change="search">
        <el-option v-for="item in data.options.run_types" :key="item" :label="item" :value="item"></el-option>
      </el-select>
      <el-select v-model="data.runStatus" clearable placeholder="运行状态"
                 style="width: 140px; margin-right: 10px" @change="search">
        <el-option v-for="item in data.options.run_statuses" :key="item" :label="item" :value="item"></el-option>
      </el-select>
      <el-button type="info" plain @click="search">查询</el-button>
      <el-button type="warning" plain style="margin-left: 10px" @click="reset">重置</el-button>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <el-table v-loading="data.loading" stripe :data="data.tableData">
        <el-table-column prop="run_no" label="运行编号" width="230" show-overflow-tooltip />
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
      </el-table>
      <div class="table-tip">
        每发起一次智能匹配，这里就会增加一条「匹配编排」运行记录。
        点击【查看过程】可以读取这次匹配从第一轮到收尾的完整过程。
      </div>
    </div>

    <div class="card" v-if="data.total">
      <el-pagination
          v-model:current-page="data.pageNum"
          background
          layout="prev, pager, next"
          :page-size="data.pageSize"
          :total="data.total"
          @current-change="load"
      />
    </div>

    <el-dialog v-model="data.detailVisible" title="运行过程" width="92%" top="4vh" destroy-on-close>
      <div v-if="data.detail" class="dialog-body">
        <el-descriptions :column="4" border size="small">
          <el-descriptions-item label="运行编号">{{ data.detail.run.run_no }}</el-descriptions-item>
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
            <pre class="snapshot">{{ prettyJson(data.detail.run.input_snapshot) }}</pre>
          </el-descriptions-item>
        </el-descriptions>

        <div class="block-title">候选漏斗</div>
        <template v-if="data.detail.funnel.available">
          <div class="block-tip">
            从筛出来的人一直看到最后交出去的人。四个数字都是现查候选池数出来的，
            不采信运行当时写下的那句话。
          </div>
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
        </template>
        <el-alert v-else type="warning" :closable="false" show-icon
                  :title="data.detail.funnel.reason"></el-alert>

        <div class="block-title">调度时间线</div>
        <div class="block-tip">
          每一轮的头一条是主管的调度记录，记着这一轮派给谁、给了什么交代、为什么这么派；
          后面几条是被派角色写下的工具调用和结论。三个角色之间没有直接连线，
          谁接下一步都由上一轮调度记录决定。
        </div>
        <el-timeline v-if="data.detail.timeline.length" style="padding-left: 4px">
          <el-timeline-item v-for="one in data.detail.timeline" :key="one.round"
                            :type="one.failed ? 'danger' : 'primary'" placement="top"
                            :timestamp="'第 ' + one.round + ' 轮'">
            <div class="round-head">
              <span class="round-title">{{ roundTitle(one) }}</span>
              <el-tag v-if="one.tool_calls" size="small" effect="plain" style="margin-left: 8px">
                工具调用 {{ one.tool_calls }} 次</el-tag>
              <el-tag v-if="one.failed" type="danger" size="small" style="margin-left: 6px">
                有 {{ one.failed }} 步没走通</el-tag>
              <span class="round-cost">{{ costText(one.cost_millis) }}</span>
            </div>
            <div v-if="one.reason" class="round-line">为什么这么派：{{ one.reason }}</div>
            <div v-if="one.instruction" class="round-line">给它的交代：{{ one.instruction }}</div>
            <el-table :data="one.steps" size="small" stripe style="margin-top: 8px">
              <el-table-column type="expand">
                <template #default="scope">
                  <div class="expand-box">
                    <div class="expand-label">入参</div>
                    <pre class="expand-body">{{ prettyJson(scope.row.request_params) || '（没有入参）' }}</pre>
                    <div class="expand-label">返回</div>
                    <pre class="expand-body">{{ prettyJson(scope.row.response_result) || '（没有返回）' }}</pre>
                    <template v-if="scope.row.error_message">
                      <div class="expand-label fail-text">失败原因</div>
                      <pre class="expand-body fail-text">{{ scope.row.error_message }}</pre>
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
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="这次运行没有留下步骤记录"></el-empty>
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
.dialog-body {
  max-height: 76vh;
  overflow-y: auto;
  padding: 0 4px;
}

.table-tip {
  color: #909399;
  font-size: 13px;
  line-height: 22px;
  padding: 10px 4px 0;
}

.block-title {
  font-weight: bold;
  font-size: 15px;
  color: #303133;
  margin: 20px 0 8px;
}

.block-tip {
  color: #909399;
  font-size: 13px;
  line-height: 22px;
  margin-bottom: 12px;
}

.funnel-row {
  margin-bottom: 14px;
}

.funnel-head {
  display: flex;
  align-items: center;
  font-size: 13px;
}

.funnel-label {
  width: 60px;
  color: #606266;
}

.funnel-value {
  width: 90px;
  font-weight: bold;
}

.funnel-ratio {
  color: #909399;
}

.funnel-track {
  height: 14px;
  background: #f2f3f5;
  border-radius: 7px;
  overflow: hidden;
  margin: 6px 0 4px;
}

.funnel-bar {
  height: 100%;
  border-radius: 7px;
  transition: width .3s;
}

.bar-total { background: #409eff; }
.bar-rejected { background: #f56c6c; }
.bar-passed { background: #67c23a; }
.bar-delivered { background: #e6a23c; }

.text-total { color: #409eff; }
.text-rejected { color: #f56c6c; }
.text-passed { color: #67c23a; }
.text-delivered { color: #e6a23c; }

.funnel-desc {
  color: #909399;
  font-size: 12px;
}

.funnel-note {
  color: #e6a23c;
  font-size: 12px;
  line-height: 20px;
}

.round-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}

.round-title {
  font-weight: bold;
  font-size: 14px;
  color: #303133;
}

.round-cost {
  margin-left: auto;
  font-size: 12px;
  color: #909399;
}

.round-line {
  color: #606266;
  font-size: 13px;
  line-height: 22px;
  margin-top: 4px;
}

.expand-box {
  padding: 4px 12px;
}

.expand-label {
  font-size: 12px;
  color: #909399;
  margin: 6px 0 2px;
}

.expand-body {
  background: #f7f8fa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 240px;
  overflow: auto;
  margin: 0;
}

.fail-text {
  color: #f56c6c;
}

.snapshot {
  background: #f7f8fa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}
</style>
