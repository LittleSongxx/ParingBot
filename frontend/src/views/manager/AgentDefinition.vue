<template>
  <div class="page-wrap">
    <div class="page-head with-action">
      <div class="page-head-main">
        <h2>子 Agent 定义</h2>
        <p class="page-tip">一个角色就是一套人格提示词加一组工具：提示词决定它站在什么立场说话，工具决定它能查到什么。</p>
      </div>
      <div class="page-head-action">
        <span class="chip chip-blue">四个角色 · 同一套执行器</span>
      </div>
    </div>

    <!-- 角色概览：总数、启用数、默认工具调用上限，以及需要提前处理的问题 -->
    <div class="card">
      <div class="block-title">角色一览</div>
      <div class="metric-grid summary-grid">
        <div class="metric-tile">
          <div class="metric-label">角色总数</div>
          <div class="metric-value">{{ data.summary.total }} <small>个</small></div>
        </div>
        <div class="metric-tile">
          <div class="metric-label">启用中</div>
          <div class="metric-value">{{ data.summary.enabled_count }} <small>个</small></div>
        </div>
        <div class="metric-tile">
          <div class="metric-label">单次工具调用默认上限</div>
          <div class="metric-value">{{ data.summary.default_max_tool_call }} <small>次</small></div>
        </div>
      </div>
      <el-alert v-for="(item, index) in data.summary.problems" :key="index" type="warning"
                :closable="false" show-icon class="problem-alert" :title="item">
      </el-alert>
      <div class="table-tip">
        一个角色就是一套人格提示词加一组工具：提示词决定它站在什么立场上说话，工具决定它能查到什么。
        四个角色跑的是同一套执行器，所以这里改的是它的输入，不是四份不同的程序。
        提示词改成停用或清空内容、工具分组下的工具全被停用，这两种情况都会让角色跑起来取不到东西，
        页面上会提前列出来。角色编码由程序固定，不支持新增和删除角色，停用某个角色用操作栏里的按钮。
      </div>
    </div>

    <!-- 角色配置卡片：提示词 / 工具分组 / 调用上限，操作按钮右对齐 -->
    <div class="config-table-card">
      <el-table :data="data.tableData" :show-header="false" class="config-table">
        <el-table-column>
          <template #default="scope">
            <div class="config-card">
              <div class="config-head">
                <span class="config-name">{{ scope.row.agent_name }}</span>
                <span class="mono role-code">{{ scope.row.agent_code }}</span>
                <span class="chip" :class="scope.row.enabled === '是' ? 'chip-green' : ''">
                  {{ scope.row.enabled === '是' ? '已启用' : '已停用' }}
                </span>
              </div>

              <div class="config-meta">
                <div class="meta-item">
                  <span class="meta-label">人格提示词</span>
                  <span class="meta-value">{{ scope.row.prompt_name || scope.row.prompt_code || '未设置' }}</span>
                  <span class="chip" :class="scope.row.prompt_state === '正常' ? 'chip-green' : 'chip-red'">
                    {{ scope.row.prompt_state }}
                  </span>
                </div>
                <div class="meta-item">
                  <span class="meta-label">工具分组</span>
                  <span v-if="scope.row.is_supervisor" class="muted meta-value">不调用工具</span>
                  <span v-else class="meta-value">
                    {{ scope.row.tool_group || '未设置' }}
                    <span class="chip" :class="scope.row.tool_enabled ? 'chip-green' : 'chip-red'">
                      启用 {{ scope.row.tool_enabled }} / {{ scope.row.tool_total }}
                    </span>
                  </span>
                </div>
                <div class="meta-item">
                  <span class="meta-label">单次工具调用上限</span>
                  <span v-if="scope.row.is_supervisor" class="muted meta-value">不适用</span>
                  <span v-else class="meta-value">
                    {{ scope.row.effective_max_tool_call }} 次
                    <span class="mono source-text">{{ scope.row.max_tool_call_source }}</span>
                  </span>
                </div>
                <div class="meta-item">
                  <span class="meta-label">更新时间</span>
                  <span class="meta-value muted">{{ scope.row.update_time }}</span>
                </div>
              </div>

              <div class="config-actions">
                <el-button type="primary" link @click="handleEdit(scope.row)">编辑</el-button>
                <el-button v-if="scope.row.enabled === '是' && !scope.row.is_supervisor"
                           type="warning" link @click="updateEnabled(scope.row, '否')">停用</el-button>
                <el-button v-else-if="scope.row.enabled !== '是'" type="success" link
                           @click="updateEnabled(scope.row, '是')">启用</el-button>
              </div>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-card">
            <div class="empty-title">还没有角色定义</div>
            <div class="empty-desc">角色由程序固定，正常初始化后这里会出现四个 Agent 角色。</div>
          </div>
        </template>
      </el-table>
    </div>

    <el-dialog title="编辑角色" v-model="data.formVisible" width="660px" destroy-on-close>
      <el-form ref="formRef" :rules="data.rules" :model="data.form" label-width="130px" class="dialog-form">
        <div class="soft-panel form-group">
          <div class="section-title">角色信息</div>
          <el-form-item label="角色编码">
            <span class="mono readonly-text">{{ data.form.agent_code }}</span>
          </el-form-item>
          <el-form-item prop="agent_name" label="角色名称">
            <el-input v-model="data.form.agent_name" maxlength="100" style="width: 260px"></el-input>
          </el-form-item>
          <el-form-item label="排序号">
            <el-input-number v-model="data.form.sort" :min="0" :max="999" :precision="0"
                             controls-position="right" style="width: 180px"></el-input-number>
            <span class="inline-tip">只影响这一页的显示顺序。</span>
          </el-form-item>
        </div>

        <div class="soft-panel form-group">
          <div class="section-title">提示词与工具</div>
          <el-form-item prop="prompt_code" label="人格提示词">
            <el-select v-model="data.form.prompt_code" filterable style="width: 320px">
              <el-option v-for="item in data.promptOptions" :key="item.code"
                         :label="item.name + '（' + item.code + '）'" :value="item.code"></el-option>
            </el-select>
            <div class="tip-block">这里只能选启用中且内容非空的模板，换一套提示词等于换这个角色的立场。</div>
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
            <span v-if="!data.form.is_supervisor" class="inline-tip">
              留空表示跟随系统参数里的 {{ data.summary.default_max_tool_call }} 次。到达上限这个角色会中断，
              把原因作为结论交给主管，不会静默继续
            </span>
          </el-form-item>
        </div>
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
  }).catch(() => {})
}

load()
loadOptions()
</script>

<style scoped>
.summary-grid {
  margin-bottom: 12px;
}

.problem-alert {
  margin-top: 8px;
}

/* 角色配置卡片列表：单列 el-table 去表头，承载卡片 */
.config-table-card {
  padding: 0;
}

.config-table {
  background: transparent;
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: transparent;
  --el-table-border-color: transparent;
}

.config-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}

.config-table :deep(td.el-table__cell) {
  padding: 0 !important;
  border: none !important;
  background: transparent !important;
}

.config-table :deep(tr.el-table__row),
.config-table :deep(tr.el-table__row:hover > td.el-table__cell) {
  background: transparent !important;
}

.config-table :deep(.el-table__empty-block) {
  background: transparent;
}

.config-table :deep(.el-table__empty-text) {
  width: 100%;
  line-height: 1.6;
}

.config-table :deep(.empty-card) {
  width: 100%;
  margin: 6px 0;
  padding: 40px 20px;
}

.config-card {
  margin-bottom: 12px;
  padding: 16px 18px;
  background: var(--pb-surface);
  border: 1px solid var(--pb-line);
  border-radius: var(--pb-radius);
  box-shadow: var(--pb-shadow-card);
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.config-card:hover {
  border-color: rgba(17, 24, 39, 0.12);
  box-shadow: var(--pb-shadow-card-hover);
  transform: translateY(-1px);
}

.config-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.config-name {
  font-size: 15px;
  font-weight: 650;
  color: var(--pb-text);
}

.role-code {
  padding: 2px 8px;
  border-radius: 7px;
  background: var(--pb-surface-3);
  color: var(--pb-muted);
  font-size: 12px;
}

.config-meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 24px;
  margin-top: 12px;
}

.meta-item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.meta-label {
  flex: none;
  font-size: 12px;
  color: var(--pb-faint);
}

.meta-value {
  min-width: 0;
  overflow: hidden;
  font-size: 12.5px;
  color: var(--pb-muted);
  text-overflow: ellipsis;
}

.source-text {
  font-size: 11.5px;
  color: var(--pb-faint);
}

.config-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--pb-line);
}

/* 弹窗内分组 */
.dialog-form {
  max-height: 68vh;
  overflow-y: auto;
  padding-right: 4px;
}

.dialog-form :deep(.el-form-item) {
  margin-bottom: 16px;
}

.dialog-form :deep(.el-form-item:last-child) {
  margin-bottom: 4px;
}

.form-group {
  margin-bottom: 14px;
}

.form-group:last-child {
  margin-bottom: 0;
}

.inline-tip {
  margin-left: 10px;
  color: var(--pb-faint);
  font-size: 12px;
  line-height: 18px;
}

.tip-block {
  width: 100%;
  margin-top: 4px;
  color: var(--pb-faint);
  font-size: 12px;
  line-height: 18px;
}

.readonly-text {
  color: var(--pb-text);
}

@media (max-width: 960px) {
  .config-meta { grid-template-columns: minmax(0, 1fr); }
}
</style>
