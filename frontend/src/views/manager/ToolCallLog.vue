<template>
  <div class="page-wrap">
    <div class="page-head with-action">
      <div class="page-head-main">
        <h2>工具调用日志</h2>
        <p class="page-tip">每次工具调用都会留一条记录，入参、返回、返回行数、耗时都能在这里复盘；失败原因单独标出。</p>
      </div>
      <div class="page-head-action">
        <el-button type="danger" plain @click="deleteBatch">批量删除</el-button>
      </div>
    </div>

    <div class="card filter-card">
      <el-input-number v-model="data.runId" :min="1" :precision="0" controls-position="right"
                       class="filter-number" placeholder="运行编号"></el-input-number>
      <el-select v-model="data.agentCode" clearable class="filter-select" placeholder="角色">
        <el-option v-for="item in data.options.agents" :key="item.agent_code"
                   :label="item.agent_name" :value="item.agent_code"></el-option>
      </el-select>
      <el-select v-model="data.toolCode" clearable filterable class="filter-select-wide" placeholder="工具">
        <el-option v-for="item in data.options.tools" :key="item.tool_code"
                   :label="item.tool_name" :value="item.tool_code"></el-option>
      </el-select>
      <el-select v-model="data.success" clearable class="filter-select" placeholder="调用结果">
        <el-option label="成功" value="是"></el-option>
        <el-option label="失败" value="否"></el-option>
      </el-select>
      <div class="filter-actions">
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="reset">重置</el-button>
      </div>
    </div>

    <div class="card table-card">
      <el-table :data="data.tableData" @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="50" />
        <el-table-column prop="create_time" label="调用时间" width="170" />
        <el-table-column prop="run_id" label="运行编号" width="100">
          <template #default="scope">
            <span class="mono mono-sub">{{ scope.row.run_id }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="agent_name" label="角色" width="120" />
        <el-table-column label="工具" width="190">
          <template #default="scope">
            <div class="tool-name">{{ scope.row.tool_name }}</div>
            <div class="mono mono-sub">{{ scope.row.tool_code }}</div>
          </template>
        </el-table-column>
        <el-table-column label="返回行数" width="100">
          <template #default="scope">
            <span class="mono mono-sub">{{ scope.row.row_count === null ? '-' : scope.row.row_count }}</span>
          </template>
        </el-table-column>
        <el-table-column label="调用结果" width="100">
          <template #default="scope">
            <span class="chip" :class="scope.row.success === '是' ? 'chip-green' : 'chip-red'">
              {{ scope.row.success === '是' ? '成功' : '失败' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="error_message" label="失败原因" min-width="220" show-overflow-tooltip />
        <el-table-column label="耗时" width="100">
          <template #default="scope">
            <span class="mono mono-sub">{{ scope.row.cost_millis === null ? '-' : scope.row.cost_millis + ' ms' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="scope">
            <el-button type="primary" link @click="openDetail(scope.row)">查看</el-button>
            <el-button type="danger" link @click="handleDelete(scope.row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-card">
            <div class="empty-title">还没有工具调用记录</div>
            <div class="empty-desc">租客发起匹配、Agent 开始调用工具后，这里会出现一条条日志。</div>
          </div>
        </template>
      </el-table>
      <div class="table-tip">
        每次工具调用都会在这里留一条记录，成功和失败都记：入参、返回、返回行数、耗时。
        失败的那几次最值得看——模型传错了参数、工具里的一些条件没满足，原因都写在这一条里。
        按运行编号筛，能看到一次匹配里某个角色依次查了哪些数据。
        删除日志只是清掉记录，不影响已经写进候选池和画像的数据。
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

    <!-- 调用详情：元信息用 chip，入参/返回用 code-line 代码块 -->
    <el-dialog title="调用详情" v-model="data.detailVisible" width="760px" destroy-on-close>
      <div class="detail-meta">
        <span class="chip chip-blue">运行 {{ data.detail.run_id }}</span>
        <span class="chip">{{ data.detail.agent_name }}</span>
        <span class="chip chip-violet">{{ data.detail.tool_name }}</span>
        <span class="mono mono-sub">{{ data.detail.tool_code }}</span>
        <span class="muted detail-time">{{ data.detail.create_time }}</span>
      </div>

      <div class="soft-panel detail-block">
        <div class="block-title">调用入参</div>
        <pre class="code-line detail-code">{{ data.detail.request_params || '（没有入参）' }}</pre>
      </div>

      <div class="soft-panel detail-block">
        <div class="block-title">返回结果</div>
        <pre class="code-line detail-code">{{ data.detail.response_result || '（没有返回）' }}</pre>
      </div>

      <template v-if="data.detail.error_message">
        <div class="soft-panel detail-block fail-block">
          <div class="block-title">失败原因</div>
          <pre class="code-line detail-code">{{ data.detail.error_message }}</pre>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/utils/request.js'

const data = reactive({
  tableData: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  runId: null,
  agentCode: '',
  toolCode: '',
  success: '',
  selection: [],
  options: { agents: [], tools: [], results: [] },
  detailVisible: false,
  detail: {}
})

const load = () => {
  request.get('/toolCallLog/selectPage', {
    params: {
      page_num: data.pageNum,
      page_size: data.pageSize,
      run_id: data.runId || undefined,
      agent_code: data.agentCode,
      tool_code: data.toolCode,
      success: data.success
    }
  }).then(res => {
    if (res.code === '200') {
      data.tableData = res.data?.list || []
      data.total = res.data?.total || 0
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const loadOptions = () => {
  request.get('/toolCallLog/options').then(res => {
    if (res.code === '200') {
      data.options = res.data
    }
  })
}

const handleSelectionChange = (rows) => {
  data.selection = rows
}

const openDetail = (row) => {
  request.get('/toolCallLog/selectOne', { params: { log_id: row.id } }).then(res => {
    if (res.code === '200') {
      data.detail = res.data
      data.detailVisible = true
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const handleDelete = (row) => {
  ElMessageBox.confirm(
      '删除这条调用记录之后，这次调用的入参和返回就找不回来了；'
      + '它没有影响任何业务数据，确定删除吗？', '删除确认', { type: 'warning' }).then(() => {
    request.delete('/toolCallLog/delete/' + row.id).then(res => {
      if (res.code === '200') {
        ElMessage.success('删除成功')
        load()
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

const deleteBatch = () => {
  if (!data.selection.length) {
    ElMessage.warning('请先勾选要删除的调用记录')
    return
  }
  ElMessageBox.confirm(
      '这次会删掉勾选的 ' + data.selection.length + ' 条调用记录，它们的入参和返回都找不回来；'
      + '这些记录没有影响任何业务数据，确定删除吗？', '批量删除确认', { type: 'warning' }).then(() => {
    request.delete('/toolCallLog/deleteBatch', {
      data: data.selection.map(item => item.id)
    }).then(res => {
      if (res.code === '200') {
        ElMessage.success('已删除 ' + res.data + ' 条调用记录')
        load()
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

const search = () => {
  data.pageNum = 1
  load()
}

const reset = () => {
  data.runId = null
  data.agentCode = ''
  data.toolCode = ''
  data.success = ''
  data.pageNum = 1
  load()
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

.filter-number { width: 170px; }
.filter-select { width: 150px; }
.filter-select-wide { width: 200px; }

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

.tool-name {
  color: var(--pb-text);
  line-height: 18px;
}

.mono-sub {
  font-size: 12px;
  color: var(--pb-muted);
}

.pager-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

/* 详情弹窗 */
.detail-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}

.detail-time {
  font-size: 12px;
}

.detail-block {
  margin-bottom: 12px;
}

.detail-block:last-child {
  margin-bottom: 0;
}

.detail-block .block-title {
  margin-bottom: 8px;
}

.detail-code {
  max-height: 240px;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}

.fail-block .block-title::before {
  background: var(--pb-danger);
}

@media (max-width: 768px) {
  .filter-number,
  .filter-select,
  .filter-select-wide {
    width: 100%;
  }

  .filter-actions {
    margin-left: 0;
  }
}
</style>
