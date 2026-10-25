<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <el-input-number v-model="data.runId" :min="1" :precision="0" controls-position="right"
                       style="width: 170px; margin-right: 10px"
                       placeholder="运行编号"></el-input-number>
      <el-select v-model="data.agentCode" clearable style="width: 150px; margin-right: 10px"
                 placeholder="角色">
        <el-option v-for="item in data.options.agents" :key="item.agent_code"
                   :label="item.agent_name" :value="item.agent_code"></el-option>
      </el-select>
      <el-select v-model="data.toolCode" clearable filterable style="width: 200px; margin-right: 10px"
                 placeholder="工具">
        <el-option v-for="item in data.options.tools" :key="item.tool_code"
                   :label="item.tool_name" :value="item.tool_code"></el-option>
      </el-select>
      <el-select v-model="data.success" clearable style="width: 140px; margin-right: 10px"
                 placeholder="调用结果">
        <el-option label="成功" value="是"></el-option>
        <el-option label="失败" value="否"></el-option>
      </el-select>
      <el-button type="info" plain @click="search">查询</el-button>
      <el-button type="warning" plain style="margin-left: 10px" @click="reset">重置</el-button>
      <el-button type="danger" plain style="margin-left: 10px" @click="deleteBatch">批量删除</el-button>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <el-table stripe :data="data.tableData" @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="50" />
        <el-table-column prop="create_time" label="调用时间" width="170" />
        <el-table-column prop="run_id" label="运行编号" width="100" />
        <el-table-column prop="agent_name" label="角色" width="120" />
        <el-table-column label="工具" width="180">
          <template #default="scope">
            <div>{{ scope.row.tool_name }}</div>
            <div class="code-line">{{ scope.row.tool_code }}</div>
          </template>
        </el-table-column>
        <el-table-column label="返回行数" width="100">
          <template #default="scope">
            {{ scope.row.row_count === null ? '-' : scope.row.row_count }}
          </template>
        </el-table-column>
        <el-table-column label="调用结果" width="100">
          <template #default="scope">
            <el-tag :type="scope.row.success === '是' ? 'success' : 'danger'">
              {{ scope.row.success === '是' ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="error_message" label="失败原因" min-width="220" show-overflow-tooltip />
        <el-table-column label="耗时" width="90">
          <template #default="scope">
            {{ scope.row.cost_millis === null ? '-' : scope.row.cost_millis + ' ms' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="scope">
            <el-button type="primary" link @click="openDetail(scope.row)">查看</el-button>
            <el-button type="danger" link @click="handleDelete(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="table-tip">
        每次工具调用都会在这里留一条记录，成功和失败都记：入参、返回、返回行数、耗时。
        失败的那几次最值得看——模型传错了参数、工具里的一些条件没满足，原因都写在这一条里。
        按运行编号筛，能看到一次匹配里某个角色依次查了哪些数据。
        删除日志只是清掉记录，不影响已经写进候选池和画像的数据。
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

    <el-dialog title="调用详情" v-model="data.detailVisible" width="760px" destroy-on-close>
      <div class="detail-meta">
        运行 {{ data.detail.run_id }} · {{ data.detail.agent_name }} · {{ data.detail.tool_name }}
        （{{ data.detail.tool_code }}） · {{ data.detail.create_time }}
      </div>
      <div class="detail-label">调用入参</div>
      <pre class="detail-body">{{ data.detail.request_params || '（没有入参）' }}</pre>
      <div class="detail-label">返回结果</div>
      <pre class="detail-body">{{ data.detail.response_result || '（没有返回）' }}</pre>
      <template v-if="data.detail.error_message">
        <div class="detail-label">失败原因</div>
        <pre class="detail-body">{{ data.detail.error_message }}</pre>
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
.code-line {
  color: #909399;
  font-size: 12px;
}
.table-tip {
  color: #999;
  font-size: 12px;
  line-height: 20px;
  padding: 10px 5px 0;
}
.detail-meta {
  color: #909399;
  font-size: 12px;
  margin-bottom: 8px;
}
.detail-label {
  color: #606266;
  font-size: 13px;
  font-weight: 600;
  margin: 10px 0 4px;
}
.detail-body {
  margin: 0;
  max-height: 260px;
  overflow: auto;
  background: #f7f7f7;
  border-radius: 4px;
  padding: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 13px;
  font-family: inherit;
  line-height: 20px;
}
</style>
