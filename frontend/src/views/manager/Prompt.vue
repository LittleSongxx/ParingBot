<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <el-input v-model="data.keyword" style="width: 220px; margin-right: 10px"
                placeholder="请输入模板名称或编码查询"></el-input>
      <el-select v-model="data.scene" clearable style="width: 150px; margin-right: 10px" placeholder="使用场景">
        <el-option v-for="item in data.sceneOptions" :key="item" :label="item" :value="item"></el-option>
      </el-select>
      <el-select v-model="data.enabled" clearable style="width: 130px; margin-right: 10px" placeholder="启用状态">
        <el-option label="已启用" value="是"></el-option>
        <el-option label="已停用" value="否"></el-option>
      </el-select>
      <el-button type="info" plain @click="load">查询</el-button>
      <el-button type="warning" plain style="margin-left: 10px" @click="reset">重置</el-button>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <el-button type="primary" plain @click="handleAdd">新增</el-button>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <el-table stripe :data="data.tableData">
        <el-table-column prop="code" label="模板编码" width="210" show-overflow-tooltip />
        <el-table-column prop="name" label="模板名称" width="160" show-overflow-tooltip />
        <el-table-column prop="scene" label="使用场景" width="110" />
        <el-table-column prop="variables" label="变量" width="220" show-overflow-tooltip />
        <el-table-column prop="content" label="模板内容" min-width="260" show-overflow-tooltip />
        <el-table-column label="被谁使用" width="140">
          <template #default="scope">
            <el-tag v-if="scope.row.used_by.length" type="warning" size="small">
              {{ scope.row.used_by.join('、') }}
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="启用状态" width="95">
          <template #default="scope">
            <el-tag :type="scope.row.enabled === '是' ? 'success' : 'info'">
              {{ scope.row.enabled === '是' ? '已启用' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="update_time" label="更新时间" width="170" />
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="scope">
            <el-button type="success" link @click="openPreview(scope.row)">预览</el-button>
            <el-button type="primary" link @click="handleEdit(scope.row)">编辑</el-button>
            <el-button v-if="scope.row.enabled === '是'" type="warning" link
                       @click="updateEnabled(scope.row, '否')">停用</el-button>
            <el-button v-else type="success" link @click="updateEnabled(scope.row, '是')">启用</el-button>
            <el-button type="danger" link @click="del(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <!-- 模板是整条链路的输入，几条口径在页面上说清楚 -->
      <div class="table-tip">
        代码按「模板编码」取模板，所以编码全表唯一，改动它之前要确认没有地方在用它。
        模板里的 {变量名} 是占位符，变量清单由内容自动识别，不用手工维护；
        点「预览」给变量填上内容，就能看到真正发给模型的完整文本。
        「被谁使用」列出正拿它当提示词的 Agent 角色。被用着的模板不能改编码、也删不掉，只能停用——
        停用之后那个角色执行时会明确提示模板已被停用，不会偷偷用一份错的内容。
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

    <el-dialog title="Prompt 模板" v-model="data.formVisible" width="720px" destroy-on-close>
      <el-form ref="formRef" :rules="data.rules" :model="data.form" label-width="100px">
        <el-form-item prop="code" label="模板编码">
          <el-input v-model="data.form.code" maxlength="50"
                    placeholder="大写字母、数字和下划线，例如 PORTRAIT_PROMPT"></el-input>
          <div class="field-tip">代码按编码取模板，录入之后尽量不要改</div>
        </el-form-item>
        <el-form-item prop="name" label="模板名称">
          <el-input v-model="data.form.name" maxlength="255" placeholder="例如：画像师提示词"></el-input>
        </el-form-item>
        <el-form-item label="使用场景">
          <el-select v-model="data.form.scene" clearable style="width: 240px" placeholder="请选择使用场景">
            <el-option v-for="item in data.sceneOptions" :key="item" :label="item" :value="item"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="占位变量">
          <span v-if="data.form.variables" class="variable-text">{{ data.form.variables }}</span>
          <span v-else class="variable-text">保存后按模板内容自动识别</span>
          <span v-if="data.form.variables" class="field-tip">保存时按模板内容自动识别，不用手工维护</span>
        </el-form-item>
        <el-form-item prop="content" label="模板内容">
          <el-input v-model="data.form.content" type="textarea" :rows="14" maxlength="20000"
                    placeholder="用 {变量名} 写占位符，花括号里的名字要和代码里传进来的变量名一致"></el-input>
        </el-form-item>
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
      </el-form>
      <template #footer>
        <el-button @click="data.formVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 预览弹窗：为模板里的每个变量填一个值，看看渲染后的完整文本 -->
    <el-dialog title="预览发给模型的内容" v-model="data.previewVisible" width="700px" destroy-on-close>
      <el-alert v-if="data.previewEnabled === '否'" type="warning" :closable="false" show-icon
                title="这条模板已停用，链路调用时会明确提示去启用它，预览只是看拼出来的内容对不对"
                style="margin-bottom: 12px"></el-alert>
      <el-form label-width="140px">
        <el-form-item v-for="name in data.previewNames" :key="name" :label="'{' + name + '}'">
          <el-input v-model="data.previewValues[name]" type="textarea" :rows="2" maxlength="2000"
                    :placeholder="'给变量 ' + name + ' 填一段内容'"></el-input>
        </el-form-item>
      </el-form>
      <div v-if="!data.previewNames.length" class="preview-tip" style="margin-bottom: 10px">
        这条模板里没有占位变量，预览看到的就是原文。
      </div>
      <el-button type="primary" style="margin-bottom: 12px" @click="doPreview">渲染</el-button>
      <div v-if="data.previewText" class="preview-box">
        <div class="preview-tip">下面就是真正会发给模型的完整内容，共 {{ data.previewText.length }} 个字</div>
        <pre class="preview-text">{{ data.previewText }}</pre>
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
.table-tip {
  color: #999;
  font-size: 12px;
  line-height: 20px;
  padding: 10px 5px 0;
}
.field-tip {
  color: #909399;
  font-size: 12px;
  margin-left: 10px;
}
.variable-text {
  color: #606266;
}
.preview-box {
  background: #f7f7f7;
  border-radius: 4px;
  padding: 10px 12px;
}
.preview-tip {
  color: #909399;
  font-size: 12px;
  margin-bottom: 6px;
}
.preview-text {
  margin: 0;
  max-height: 320px;
  overflow: auto;
  /* 保留模板里的换行，看到的排版就是发给模型的排版 */
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  font-family: inherit;
  line-height: 20px;
}
</style>
