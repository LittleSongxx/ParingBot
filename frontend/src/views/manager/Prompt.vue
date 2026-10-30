<template>
  <div class="page-wrap">
    <div class="page-head with-action">
      <div class="page-head-main">
        <h2>Prompt 模板</h2>
        <p class="page-tip">四个 Agent 角色按模板编码取提示词；模板里的 {变量名} 由内容自动识别，点预览可以看真正发给模型的文本。</p>
      </div>
      <div class="page-head-action">
        <el-button type="primary" @click="handleAdd">新增模板</el-button>
      </div>
    </div>

    <div class="card filter-card">
      <el-input v-model="data.keyword" class="filter-input" clearable placeholder="请输入模板名称或编码查询"></el-input>
      <el-select v-model="data.scene" clearable class="filter-select" placeholder="使用场景">
        <el-option v-for="item in data.sceneOptions" :key="item" :label="item" :value="item"></el-option>
      </el-select>
      <el-select v-model="data.enabled" clearable class="filter-select" placeholder="启用状态">
        <el-option label="已启用" value="是"></el-option>
        <el-option label="已停用" value="否"></el-option>
      </el-select>
      <div class="filter-actions">
        <el-button type="primary" @click="load">查询</el-button>
        <el-button @click="reset">重置</el-button>
      </div>
    </div>

    <!-- 模板卡片列表：编码/变量用 mono，状态与占用关系用 chip -->
    <div class="config-table-card">
      <el-table :data="data.tableData" :show-header="false" class="config-table">
        <el-table-column>
          <template #default="scope">
            <div class="config-card">
              <div class="config-head">
                <span class="mono prompt-code">{{ scope.row.code }}</span>
                <span class="config-name">{{ scope.row.name }}</span>
                <span class="chip chip-cyan">{{ scope.row.scene }}</span>
                <span class="chip" :class="scope.row.enabled === '是' ? 'chip-green' : ''">
                  {{ scope.row.enabled === '是' ? '已启用' : '已停用' }}
                </span>
                <span v-if="scope.row.used_by.length" class="chip chip-amber">
                  被「{{ scope.row.used_by.join('、') }}」使用
                </span>
                <span v-else class="chip">暂未被使用</span>
              </div>

              <div class="config-meta">
                <div class="meta-item">
                  <span class="meta-label">占位变量</span>
                  <span class="mono meta-value">{{ scope.row.variables || '无' }}</span>
                </div>
                <div class="meta-item">
                  <span class="meta-label">更新时间</span>
                  <span class="meta-value muted">{{ scope.row.update_time }}</span>
                </div>
              </div>

              <div class="prompt-content">{{ scope.row.content }}</div>

              <div class="config-actions">
                <el-button type="success" link @click="openPreview(scope.row)">预览</el-button>
                <el-button type="primary" link @click="handleEdit(scope.row)">编辑</el-button>
                <el-button v-if="scope.row.enabled === '是'" type="warning" link
                           @click="updateEnabled(scope.row, '否')">停用</el-button>
                <el-button v-else type="success" link @click="updateEnabled(scope.row, '是')">启用</el-button>
                <el-button type="danger" link @click="del(scope.row)">删除</el-button>
              </div>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-card">
            <div class="empty-title">还没有 Prompt 模板</div>
            <div class="empty-desc">点右上角「新增模板」，按四个 Agent 角色各维护一份提示词。</div>
          </div>
        </template>
      </el-table>
      <!-- 模板是整条链路的输入，几条口径在页面上说清楚 -->
      <div class="table-tip">
        代码按「模板编码」取模板，所以编码全表唯一，改动它之前要确认没有地方在用它。
        模板里的 {变量名} 是占位符，变量清单由内容自动识别，不用手工维护；
        点「预览」给变量填上内容，就能看到真正发给模型的完整文本。
        「被谁使用」列出正拿它当提示词的 Agent 角色。被用着的模板不能改编码、也删不掉，只能停用——
        停用之后那个角色执行时会明确提示模板已被停用，不会偷偷用一份错的内容。
      </div>
      <div class="pager-card card" v-if="data.total">
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

    <el-dialog title="Prompt 模板" v-model="data.formVisible" width="760px" destroy-on-close>
      <el-form ref="formRef" :rules="data.rules" :model="data.form" label-width="100px" class="dialog-form">
        <div class="soft-panel form-group">
          <div class="section-title">模板标识</div>
          <el-form-item prop="code" label="模板编码">
            <el-input v-model="data.form.code" maxlength="50"
                      placeholder="大写字母、数字和下划线，例如 PORTRAIT_PROMPT"></el-input>
            <div class="inline-tip block-tip">代码按编码取模板，录入之后尽量不要改</div>
          </el-form-item>
          <el-form-item prop="name" label="模板名称">
            <el-input v-model="data.form.name" maxlength="255" placeholder="例如：画像师提示词"></el-input>
          </el-form-item>
          <el-form-item label="使用场景">
            <el-select v-model="data.form.scene" clearable style="width: 240px" placeholder="请选择使用场景">
              <el-option v-for="item in data.sceneOptions" :key="item" :label="item" :value="item"></el-option>
            </el-select>
          </el-form-item>
        </div>

        <div class="soft-panel form-group">
          <div class="section-title">模板内容</div>
          <el-form-item label="占位变量">
            <span v-if="data.form.variables" class="mono variable-text">{{ data.form.variables }}</span>
            <span v-else class="variable-text muted">保存后按模板内容自动识别</span>
            <span v-if="data.form.variables" class="inline-tip">保存时按模板内容自动识别，不用手工维护</span>
          </el-form-item>
          <el-form-item prop="content" label="模板内容">
            <el-input v-model="data.form.content" type="textarea" :rows="14" maxlength="20000"
                      placeholder="用 {变量名} 写占位符，花括号里的名字要和代码里传进来的变量名一致"></el-input>
          </el-form-item>
        </div>

        <div class="soft-panel form-group">
          <div class="section-title">状态与备注</div>
          <el-form-item label="启用状态">
            <el-radio-group v-model="data.form.enabled">
              <el-radio value="是">启用</el-radio>
              <el-radio value="否">停用</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="data.form.remark" type="textarea" :rows="2" maxlength="500"
                      placeholder="说明这个模板用在哪个环节"></el-input>
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="data.formVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 预览弹窗：为模板里的每个变量填一个值，看看渲染后的完整文本 -->
    <el-dialog title="预览发给模型的内容" v-model="data.previewVisible" width="720px" destroy-on-close>
      <el-alert v-if="data.previewEnabled === '否'" type="warning" :closable="false" show-icon
                title="这条模板已停用，链路调用时会明确提示去启用它，预览只是看拼出来的内容对不对"
                style="margin-bottom: 12px"></el-alert>

      <div class="soft-panel form-group">
        <div class="section-title">变量取值</div>
        <el-form label-width="140px" class="preview-form">
          <el-form-item v-for="name in data.previewNames" :key="name" :label="'{' + name + '}'">
            <el-input v-model="data.previewValues[name]" type="textarea" :rows="2" maxlength="2000"
                      :placeholder="'给变量 ' + name + ' 填一段内容'"></el-input>
          </el-form-item>
        </el-form>
        <div v-if="!data.previewNames.length" class="empty-hint">
          这条模板里没有占位变量，预览看到的就是原文。
        </div>
      </div>

      <div class="preview-actions">
        <el-button type="primary" @click="doPreview">渲染</el-button>
      </div>

      <div v-if="data.previewText" class="soft-panel preview-box">
        <div class="preview-tip">下面就是真正会发给模型的完整内容，共 {{ data.previewText.length }} 个字</div>
        <pre class="code-line preview-text">{{ data.previewText }}</pre>
      </div>
      <template #footer>
        <el-button @click="data.previewVisible = false">关闭</el-button>
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
  pageNum: 1,
  pageSize: 10,
  total: 0,
  keyword: '',
  scene: '',
  enabled: '',
  // 场景选项由后端给出，页面不自己维护一份
  sceneOptions: [],
  formVisible: false,
  form: {},
  previewVisible: false,
  previewId: 0,
  previewEnabled: '是',
  // 当前模板的变量名清单，预览时按它逐个生成输入框
  previewNames: [],
  previewValues: {},
  previewText: '',
  rules: {
    code: [{ required: true, message: '请填写模板编码', trigger: 'blur' }],
    name: [{ required: true, message: '请填写模板名称', trigger: 'blur' }],
    content: [{ required: true, message: '请填写模板内容', trigger: 'blur' }]
  }
})

const load = () => {
  request.get('/promptTemplate/selectPage', {
    params: {
      page_num: data.pageNum,
      page_size: data.pageSize,
      keyword: data.keyword,
      scene: data.scene,
      enabled: data.enabled
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

const loadSceneOptions = () => {
  request.get('/promptTemplate/sceneOptions').then(res => {
    if (res.code === '200') {
      data.sceneOptions = res.data || []
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const handleAdd = () => {
  data.form = { enabled: '是' }
  data.formVisible = true
}

const handleEdit = (row) => {
  // 深拷贝当前行，避免直接改 tableData 里的对象导致弹窗一改表格就跟着变
  data.form = JSON.parse(JSON.stringify(row))
  data.formVisible = true
}

const save = () => {
  formRef.value.validate(valid => {
    if (!valid) {
      return
    }
    const payload = {
      id: data.form.id,
      code: data.form.code,
      name: data.form.name,
      scene: data.form.scene,
      content: data.form.content,
      enabled: data.form.enabled,
      remark: data.form.remark
    }
    const action = payload.id
        ? request.put('/promptTemplate/update', payload)
        : request.post('/promptTemplate/add', payload)
    action.then(res => {
      if (res.code === '200') {
        ElMessage.success('保存成功')
        data.formVisible = false
        load()
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

const openPreview = (row) => {
  data.previewId = row.id
  data.previewEnabled = row.enabled
  data.previewNames = row.variable_names || []
  data.previewValues = {}
  data.previewText = ''
  data.previewVisible = true
}

const doPreview = () => {
  request.post('/promptTemplate/preview', {
    id: data.previewId,
    values: data.previewValues
  }).then(res => {
    if (res.code === '200') {
      data.previewText = res.data
    } else {
      // 变量没填值时后端会指明缺哪几个
      ElMessage.error(res.msg)
    }
  })
}

const updateEnabled = (row, enabled) => {
  const text = enabled === '是'
      ? '启用「' + row.name + '」后，用到这条模板的环节会按它的内容拼 Prompt。确定启用吗？'
      : '停用「' + row.name + '」后，用到它的环节会明确提示模板已被停用。确定停用吗？'
  ElMessageBox.confirm(text, '状态确认', { type: 'warning' }).then(() => {
    request.post('/promptTemplate/updateEnabled', { template_id: row.id, enabled }).then(res => {
      if (res.code === '200') {
        ElMessage.success('操作成功')
        load()
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

const blockReason = (row) => {
  if (row.used_by.length) {
    return '「' + row.name + '」正被「' + row.used_by.join('、') + '」使用，'
        + '删掉之后这些地方执行时会取不到提示词。如果只是想让它暂时不生效，请改成停用；'
        + '确实要删除，请先把它从用它的地方换掉。'
  }
  return ''
}

const del = (row) => {
  const blocked = blockReason(row)
  if (blocked) {
    ElMessageBox.alert(blocked, '这条模板删不了', { type: 'warning' })
    return
  }
  ElMessageBox.confirm('删除模板「' + row.name + '」后，代码按编码就取不到它了。确定删除吗？',
      '删除确认', { type: 'warning' }).then(() => {
    request.delete('/promptTemplate/delete/' + row.id).then(res => {
      if (res.code === '200') {
        ElMessage.success('删除成功')
        load()
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

const reset = () => {
  data.keyword = ''
  data.scene = ''
  data.enabled = ''
  data.pageNum = 1
  load()
}

loadSceneOptions()
load()
</script>

<style scoped>
/* 配置页：筛选卡 + 一条模板一张卡 */
.filter-card {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.filter-input { width: 280px; }
.filter-select { width: 160px; }

.filter-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
}

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

.prompt-code {
  padding: 2px 8px;
  border-radius: 7px;
  background: var(--pb-surface-3);
  color: var(--pb-muted);
  font-size: 12px;
}

.config-name {
  font-size: 15px;
  font-weight: 650;
  color: var(--pb-text);
}

.config-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 24px;
  margin-top: 10px;
}

.meta-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}

.meta-label {
  flex: none;
  font-size: 12px;
  color: var(--pb-faint);
}

.meta-value {
  overflow: hidden;
  font-size: 12.5px;
  color: var(--pb-muted);
  white-space: nowrap;
  text-overflow: ellipsis;
}

.prompt-content {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: var(--pb-radius-sm);
  background: var(--pb-surface-2);
  border: 1px solid var(--pb-line);
  color: var(--pb-muted);
  font-size: 12.5px;
  line-height: 20px;
  word-break: break-all;
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

.pager-card {
  margin-top: 4px;
  padding: 12px 18px;
  display: flex;
  justify-content: flex-end;
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
}

.block-tip {
  display: block;
  margin-left: 0;
  margin-top: 4px;
}

.variable-text {
  color: var(--pb-text);
}

.preview-form :deep(.el-form-item) {
  margin-bottom: 14px;
}

.empty-hint {
  padding: 4px 0;
  color: var(--pb-faint);
  font-size: 12.5px;
}

.preview-actions {
  display: flex;
  justify-content: flex-end;
  margin: 14px 0 4px;
}

.preview-box {
  margin-top: 12px;
}

.preview-tip {
  margin-bottom: 8px;
  color: var(--pb-faint);
  font-size: 12px;
}

.preview-text {
  max-height: 320px;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
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
