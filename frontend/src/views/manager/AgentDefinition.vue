<template>
  <div>
    <!-- 角色概览：四个角色各自绑了哪套提示词、手上有什么工具、能不能上场 -->
    <div class="card" style="margin-bottom: 5px">
      <div class="card-title">角色一览</div>
      <div class="stat-line">
        <el-tag type="info">角色 {{ data.summary.total }} 个</el-tag>
        <el-tag type="success">启用中 {{ data.summary.enabled_count }} 个</el-tag>
        <el-tag type="info">未单独设置时跟随系统参数：{{ data.summary.default_max_tool_call }} 次</el-tag>
      </div>
      <el-alert v-for="(item, index) in data.summary.problems" :key="index" type="warning"
                :closable="false" show-icon style="margin-top: 8px" :title="item">
      </el-alert>
      <div class="table-tip">
        一个角色就是一套人格提示词加一组工具：提示词决定它站在什么立场上说话，工具决定它能查到什么。
        四个角色跑的是同一套执行器，所以这里改的是它的输入，不是四份不同的程序。
        提示词改成停用或清空内容、工具分组下的工具全被停用，这两种情况都会让角色跑起来取不到东西，
        页面上会提前列出来。角色编码由程序固定，不支持新增和删除角色，停用某个角色用操作栏里的按钮。
      </div>
    </div>

    <div class="card">
      <el-table stripe :data="data.tableData">
        <el-table-column label="角色" width="180">
          <template #default="scope">
            <div class="name-line">{{ scope.row.agent_name }}</div>
            <div class="code-line">{{ scope.row.agent_code }}</div>
          </template>
        </el-table-column>
        <el-table-column label="人格提示词" min-width="220">
          <template #default="scope">
            <div>{{ scope.row.prompt_name || scope.row.prompt_code || '未设置' }}</div>
            <el-tag size="small" :type="scope.row.prompt_state === '正常' ? 'success' : 'danger'">
              {{ scope.row.prompt_state }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="工具分组" width="180">
          <template #default="scope">
            <span v-if="scope.row.is_supervisor" class="muted-text">不调用工具</span>
            <span v-else>
              {{ scope.row.tool_group || '未设置' }}
              <el-tag size="small" :type="scope.row.tool_enabled ? 'success' : 'danger'">
                启用 {{ scope.row.tool_enabled }} / {{ scope.row.tool_total }}
              </el-tag>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="单次工具调用上限" width="180">
          <template #default="scope">
            <span v-if="scope.row.is_supervisor" class="muted-text">不适用</span>
            <span v-else>
              {{ scope.row.effective_max_tool_call }} 次
              <div class="code-line">{{ scope.row.max_tool_call_source }}</div>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="启用状态" width="100">
          <template #default="scope">
            <el-tag :type="scope.row.enabled === '是' ? 'success' : 'info'">
              {{ scope.row.enabled === '是' ? '已启用' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="update_time" label="更新时间" width="170" />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="scope">
            <el-button type="primary" link @click="handleEdit(scope.row)">编辑</el-button>
            <el-button v-if="scope.row.enabled === '是' && !scope.row.is_supervisor"
                       type="warning" link @click="updateEnabled(scope.row, '否')">停用</el-button>
            <el-button v-else-if="scope.row.enabled !== '是'" type="success" link
                       @click="updateEnabled(scope.row, '是')">启用</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog title="编辑角色" v-model="data.formVisible" width="620px" destroy-on-close>
      <el-form ref="formRef" :rules="data.rules" :model="data.form" label-width="130px">
        <el-form-item label="角色编码">
          <span class="readonly-text">{{ data.form.agent_code }}</span>
        </el-form-item>
        <el-form-item prop="agent_name" label="角色名称">
          <el-input v-model="data.form.agent_name" maxlength="100" style="width: 260px"></el-input>
        </el-form-item>
        <el-form-item prop="prompt_code" label="人格提示词">
          <el-select v-model="data.form.prompt_code" filterable style="width: 320px">
            <el-option v-for="item in data.promptOptions" :key="item.code"
                       :label="item.name + '（' + item.code + '）'" :value="item.code"></el-option>
          </el-select>
          <div class="form-tip">这里只能选启用中且内容非空的模板，换一套提示词等于换这个角色的立场。</div>
        </el-form-item>
        <el-form-item label="工具分组">
          <span v-if="data.form.is_supervisor" class="readonly-text">
            不调用工具：主管只决定这一轮派谁，查数据的事交给子角色
          </span>
          <el-select v-else v-model="data.form.tool_group" style="width: 320px">
            <el-option v-for="item in data.groupOptions" :key="item.tool_group"
                       :label="item.tool_group + '（启用 ' + item.tool_enabled + ' / ' + item.tool_total + '）'"
                       :value="item.tool_group"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="单次工具调用上限">
          <el-input-number v-if="!data.form.is_supervisor" v-model="data.form.max_tool_call"
                           :min="1" :max="200" :precision="0" controls-position="right"
                           style="width: 180px"></el-input-number>
          <span v-if="!data.form.is_supervisor" class="form-tip">
            留空表示跟随系统参数里的 {{ data.summary.default_max_tool_call }} 次。到达上限这个角色会中断，
            把原因作为结论交给主管，不会静默继续
          </span>
        </el-form-item>
        <el-form-item label="排序号">
          <el-input-number v-model="data.form.sort" :min="0" :max="999" :precision="0"
                           controls-position="right" style="width: 180px"></el-input-number>
          <div class="form-tip">只影响这一页的显示顺序。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="data.formVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/utils/request.js'

const formRef = ref()

const data = reactive({
  tableData: [],
  summary: { total: 0, enabled_count: 0, default_max_tool_call: 0, problems: [] },
  groupOptions: [],
  promptOptions: [],
  formVisible: false,
  form: {},
  rules: {
    agent_name: [{ required: true, message: '请填写角色名称', trigger: 'blur' }],
    prompt_code: [{ required: true, message: '请选择这个角色的人格提示词', trigger: 'change' }]
  }
})

const load = () => {
  request.get('/agentDefinition/list').then(res => {
    if (res.code === '200') {
      data.tableData = res.data?.list || []
      data.summary = {
        total: res.data?.total || 0,
        enabled_count: res.data?.enabled_count || 0,
        default_max_tool_call: res.data?.default_max_tool_call || 0,
        problems: res.data?.problems || []
      }
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const loadOptions = () => {
  request.get('/agentDefinition/options').then(res => {
    if (res.code === '200') {
      data.groupOptions = res.data?.groups || []
      data.promptOptions = res.data?.prompts || []
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const handleEdit = (row) => {
  data.form = { ...row }
  // 当前绑的这一套已经不能用了时，它不在下拉里；补一条进去，
  // 否则选择框会显示成空，看起来像是没绑提示词
  if (row.prompt_state !== '正常' && row.prompt_code
      && !data.promptOptions.some(item => item.code === row.prompt_code)) {
    data.promptOptions = [...data.promptOptions,
      { code: row.prompt_code, name: (row.prompt_name || row.prompt_code) + '（当前不可用）' }]
  }
  data.formVisible = true
}

const save = () => {
  formRef.value.validate(valid => {
    if (!valid) {
      return
    }
    const payload = {
      agent_id: data.form.id,
      agent_name: data.form.agent_name,
      prompt_code: data.form.prompt_code,
      tool_group: data.form.is_supervisor ? null : data.form.tool_group,
      max_tool_call: data.form.is_supervisor ? null : (data.form.max_tool_call ?? null),
      sort: data.form.sort ?? 0
    }
    request.put('/agentDefinition/update', payload).then(res => {
      if (res.code === '200') {
        ElMessage.success('保存成功')
        data.formVisible = false
        load()
        loadOptions()
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

// 停用是把角色从调度里摘出去，确认框里说清摘掉之后会发生什么
const updateEnabled = (row, enabled) => {
  const text = enabled === '是'
      ? '启用「' + row.agent_name + '」后，主管派活时就能派给它。要确认它的提示词和工具分组都配好了，确定启用吗？'
      : '停用「' + row.agent_name + '」后，主管派不了这个角色，它负责的那一段工作没人做，确定停用吗？'
  ElMessageBox.confirm(text, '状态确认', { type: 'warning' }).then(() => {
    request.post('/agentDefinition/updateEnabled', { agent_id: row.id, enabled }).then(res => {
      if (res.code === '200') {
        ElMessage.success('操作成功')
        load()
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

load()
loadOptions()
</script>

<style scoped>
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 10px;
}
.stat-line .el-tag {
  margin-right: 8px;
}
.name-line {
  color: #303133;
}
.code-line {
  color: #909399;
  font-size: 12px;
}
.muted-text {
  color: #909399;
}
.readonly-text {
  color: #606266;
}
.form-tip {
  color: #909399;
  font-size: 12px;
  line-height: 18px;
  margin-top: 4px;
}
.table-tip {
  color: #999;
  font-size: 12px;
  line-height: 20px;
  padding: 10px 5px 0;
}
</style>
