<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <div class="card-title">工具一览</div>
      <div class="stat-line">
        <el-tag type="info">工具 {{ data.summary.total }} 个</el-tag>
        <el-tag type="success">启用中 {{ data.summary.enabled_count }} 个</el-tag>
        <el-tag type="info">只读 {{ data.summary.read_only_count }} 个 / 写入 {{ data.summary.write_count }} 个</el-tag>
        <el-tag v-for="item in data.summary.groups" :key="item.tool_group" type="info">
          {{ item.tool_group }}：启用 {{ item.tool_enabled }} / {{ item.tool_total }}
        </el-tag>
      </div>
      <el-alert v-for="(item, index) in data.summary.problems" :key="index" type="warning"
                :closable="false" show-icon style="margin-top: 8px" :title="item">
      </el-alert>
      <div class="table-tip">
        工具是四个角色能做的全部事情：查档案、查动态、检索候选、写候选池、回填审核结论。
        每个工具的名称、说明、参数和分组都存在这里，模型每次执行前读的就是这一份，改完立刻生效。
        说明会原样发给模型，所以要写清什么时候该调、什么时候不该调、参数能填什么。
        停用一个工具之后，模型手上的清单里直接没有它，这就是真开关。
        只读类工具可以在页面上试跑，试跑不写调用日志；写入类工具改的是匹配任务里的候选池，
        离开任务去跑写出来的数据没有归属，所以只能在匹配运行时由角色调用。
      </div>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <el-input v-model="data.keyword" style="width: 240px; margin-right: 10px"
                placeholder="请输入工具名称或编码查询"></el-input>
      <el-select v-model="data.toolGroup" clearable style="width: 150px; margin-right: 10px"
                 placeholder="工具分组">
        <el-option v-for="item in data.groupOptions" :key="item.tool_group"
                   :label="item.tool_group" :value="item.tool_group"></el-option>
      </el-select>
      <el-select v-model="data.enabled" clearable style="width: 140px; margin-right: 10px"
                 placeholder="启用状态">
        <el-option label="已启用" value="是"></el-option>
        <el-option label="已停用" value="否"></el-option>
      </el-select>
      <el-button type="info" plain @click="search">查询</el-button>
      <el-button type="warning" plain style="margin-left: 10px" @click="reset">重置</el-button>
      <el-button v-if="data.codeOptions.length" type="primary" plain
                 style="margin-left: 10px" @click="handleAdd">新增工具</el-button>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <el-table stripe :data="data.tableData">
        <el-table-column label="工具" width="200">
          <template #default="scope">
            <div class="name-line">{{ scope.row.tool_name }}</div>
            <div class="code-line">{{ scope.row.tool_code }}</div>
          </template>
        </el-table-column>
        <el-table-column label="用途说明" min-width="320" show-overflow-tooltip>
          <template #default="scope">
            <span>{{ scope.row.description }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="tool_group" label="分组" width="90" />
        <el-table-column label="返回上限" width="100">
          <template #default="scope">
            {{ scope.row.max_return_rows ? scope.row.max_return_rows + ' 行' : '不限制' }}
          </template>
        </el-table-column>
        <el-table-column label="实现状态" width="110">
          <template #default="scope">
            <el-tag size="small" :type="scope.row.has_implementation ? 'success' : 'danger'">
              {{ scope.row.has_implementation ? '已接入' : '找不到实现' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="启用状态" width="100">
          <template #default="scope">
            <el-tag :type="scope.row.enabled === '是' ? 'success' : 'info'">
              {{ scope.row.enabled === '是' ? '已启用' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="sort" label="排序" width="70" />
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="scope">
            <el-button type="primary" link @click="handleEdit(scope.row)">编辑</el-button>
            <el-button v-if="scope.row.read_only" type="success" link
                       @click="openTest(scope.row)">试跑</el-button>
            <el-button v-if="scope.row.enabled === '是'" type="warning" link
                       @click="updateEnabled(scope.row, '否')">停用</el-button>
            <el-button v-else type="success" link @click="updateEnabled(scope.row, '是')">启用</el-button>
            <el-button type="danger" link @click="handleDelete(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="table-tip">
        编码是模型、步骤记录和调用日志找这个工具的依据，登记之后不能改；工具本身也不建议频繁增删，
        调整行为优先改说明和参数。八个工具各自归在画像、筛选、审核三个分组里，分组决定它被哪个角色拿去用。
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

    <el-dialog :title="data.form.id ? '编辑工具' : '新增工具'" v-model="data.formVisible"
               width="720px" destroy-on-close>
      <el-form ref="formRef" :rules="data.rules" :model="data.form" label-width="110px">
        <el-form-item prop="tool_code" label="工具编码">
          <el-select v-if="!data.form.id" v-model="data.form.tool_code" style="width: 320px">
            <el-option v-for="item in data.codeOptions" :key="item.tool_code"
                       :label="item.tool_code" :value="item.tool_code"></el-option>
          </el-select>
          <span v-else class="readonly-text">
            {{ data.form.tool_code }}
            <span class="form-tip">编码和程序里的实现对不上时就取不到工具，所以登记后不能改</span>
          </span>
        </el-form-item>
        <el-form-item prop="tool_name" label="工具名称">
          <el-input v-model="data.form.tool_name" maxlength="255" style="width: 320px"></el-input>
        </el-form-item>
        <el-form-item prop="description" label="用途说明">
          <el-input v-model="data.form.description" type="textarea" :rows="4" maxlength="1000"
                    show-word-limit
                    placeholder="写清什么时候该调、什么时候不该调、参数能填什么"></el-input>
        </el-form-item>
        <el-form-item prop="input_schema" label="参数 Schema">
          <el-input v-model="data.form.input_schema" type="textarea" :rows="6"
                    placeholder='{"type": "object", "properties": {}}'></el-input>
          <div class="form-tip">
            写成 JSON 对象，type 是 object，properties 里每个参数名对应一项；
            没有参数也要写成空对象。写坏了模型传参时才会报错，所以保存时会先校验一遍。
          </div>
        </el-form-item>
        <el-form-item prop="tool_group" label="所属分组">
          <el-select v-model="data.form.tool_group" style="width: 200px">
            <el-option v-for="item in data.groupOptions" :key="item.tool_group"
                       :label="item.tool_group" :value="item.tool_group"></el-option>
          </el-select>
          <div class="form-tip">分组决定这个工具被哪个角色拿去用。</div>
        </el-form-item>
        <el-form-item label="返回上限">
          <el-input-number v-model="data.form.max_return_rows" :min="1" :max="200" :precision="0"
                           controls-position="right" style="width: 180px"></el-input-number>
          <div class="form-tip">一次调用最多返回多少行，留空表示由工具自己决定。填得太大容易把上下文撑满。</div>
        </el-form-item>
        <el-form-item label="启用状态">
          <el-radio-group v-model="data.form.enabled">
            <el-radio value="是">启用</el-radio>
            <el-radio value="否">停用</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="排序号">
          <el-input-number v-model="data.form.sort" :min="0" :max="999" :precision="0"
                           controls-position="right" style="width: 180px"></el-input-number>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="data.formVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog title="试跑工具" v-model="data.testVisible" width="720px" destroy-on-close>
      <div class="test-head">
        <span class="name-line">{{ data.test.tool_name }}</span>
        <span class="code-line">{{ data.test.tool_code }}</span>
      </div>
      <el-form label-width="90px">
        <el-form-item label="租客上下文">
          <el-select v-model="data.test.memberId" filterable remote clearable
                     :remote-method="searchMembers" :loading="data.memberLoading"
                     placeholder="输入昵称搜索租客，读档案这类工具要用" style="width: 320px">
            <el-option v-for="item in data.memberOptions" :key="item.id"
                       :label="item.nickname + '（' + item.audit_status + '）'" :value="item.id"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="工具入参">
          <el-input v-model="data.test.params" type="textarea" :rows="4"
                    placeholder="按上面那份工具的说明传参数，写成 JSON 对象"></el-input>
        </el-form-item>
      </el-form>
      <div class="test-result">
        <div class="form-tip">
          试跑用的上下文里没有匹配任务，所以只让只读类工具试跑；试跑的调用不写调用日志。
        </div>
        <pre class="result-body">{{ data.test.result || '还没有试跑，点下面的按钮看结果' }}</pre>
      </div>
      <template #footer>
        <el-button @click="data.testVisible = false">关闭</el-button>
        <el-button type="primary" :loading="data.testing" @click="runTest">运行一次</el-button>
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
  toolGroup: '',
  enabled: '',
  summary: { total: 0, enabled_count: 0, read_only_count: 0, write_count: 0, groups: [], problems: [] },
  groupOptions: [],
  codeOptions: [],
  formVisible: false,
  form: {},
  rules: {
    tool_code: [{ required: true, message: '请选择工具编码', trigger: 'change' }],
    tool_name: [{ required: true, message: '请填写工具名称', trigger: 'blur' }],
    description: [{ required: true, message: '请填写用途说明，模型靠它判断什么时候该调', trigger: 'blur' }],
    input_schema: [{ required: true, message: '请填写参数 Schema', trigger: 'blur' }],
    tool_group: [{ required: true, message: '请选择工具分组', trigger: 'change' }]
  },
  memberOptions: [],
  memberLoading: false,
  testVisible: false,
  testing: false,
  test: { tool_code: '', tool_name: '', memberId: null, params: '{}', result: '' }
})

const load = () => {
  request.get('/functionTool/selectPage', {
    params: {
      page_num: data.pageNum,
      page_size: data.pageSize,
      keyword: data.keyword,
      tool_group: data.toolGroup,
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

const loadSummary = () => {
  request.get('/functionTool/summary').then(res => {
    if (res.code === '200') {
      data.summary = res.data
      data.groupOptions = res.data?.groups || []
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const loadCodeOptions = () => {
  request.get('/functionTool/codeOptions').then(res => {
    if (res.code === '200') {
      data.codeOptions = res.data || []
    }
  })
}

const handleAdd = () => {
  data.form = {
    tool_code: data.codeOptions[0]?.tool_code || '',
    tool_name: '',
    description: '',
    input_schema: '{"type": "object", "properties": {}}',
    tool_group: data.groupOptions[0]?.tool_group || '',
    max_return_rows: null,
    enabled: '是',
    sort: (data.total > 0 ? data.total : 0) + 1
  }
  data.formVisible = true
}

const handleEdit = (row) => {
  data.form = { ...row }
  data.formVisible = true
}

const save = () => {
  formRef.value.validate(valid => {
    if (!valid) {
      return
    }
    const payload = {
      tool_code: data.form.tool_code,
      tool_name: data.form.tool_name,
      description: data.form.description,
      input_schema: data.form.input_schema,
      tool_group: data.form.tool_group,
      max_return_rows: data.form.max_return_rows ?? null,
      enabled: data.form.enabled,
      sort: data.form.sort ?? 0
    }
    const done = (res) => {
      if (res.code === '200') {
        ElMessage.success('保存成功')
        data.formVisible = false
        load()
        loadSummary()
        loadCodeOptions()
      } else {
        ElMessage.error(res.msg)
      }
    }
    if (data.form.id) {
      request.put('/functionTool/update', { id: data.form.id, ...payload }).then(done)
    } else {
      request.post('/functionTool/add', payload).then(done)
    }
  })
}

// 停用/启用工具，确认框里说清模型那一边会发生什么
const updateEnabled = (row, enabled) => {
  const text = enabled === '是'
      ? '启用「' + row.tool_name + '」后，这个分组下的角色就能调用它。确定启用吗？'
      : '停用「' + row.tool_name + '」后，模型手上的工具清单里就没有它了，用到它的角色会少一条路，确定停用吗？'
  ElMessageBox.confirm(text, '状态确认', { type: 'warning' }).then(() => {
    request.post('/functionTool/updateEnabled', { tool_id: row.id, enabled }).then(res => {
      if (res.code === '200') {
        ElMessage.success('操作成功')
        load()
        loadSummary()
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

const handleDelete = (row) => {
  ElMessageBox.confirm(
      '删除「' + row.tool_name + '」之后，模型再也看不到这个工具，用到它的角色会少一条路。'
      + '这个工具本身没有从属数据，已经产生的调用日志会保留下来，确定删除吗？',
      '删除确认', { type: 'warning' }).then(() => {
    request.delete('/functionTool/delete/' + row.id).then(res => {
      if (res.code === '200') {
        ElMessage.success('删除成功')
        load()
        loadSummary()
        loadCodeOptions()
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

const searchMembers = (keyword) => {
  data.memberLoading = true
  request.get('/functionTool/memberOptions', { params: { keyword: keyword || '' } }).then(res => {
    data.memberLoading = false
    if (res.code === '200') {
      data.memberOptions = res.data || []
    }
  })
}

const openTest = (row) => {
  data.test = { tool_code: row.tool_code, tool_name: row.tool_name, memberId: null, params: '{}', result: '' }
  data.memberOptions = []
  searchMembers('')
  data.testVisible = true
}

const runTest = () => {
  let params = {}
  try {
    params = data.test.params ? JSON.parse(data.test.params) : {}
  } catch (e) {
    ElMessage.error('工具入参要写成 JSON 对象，请检查括号和引号有没有配对')
    return
  }
  data.testing = true
  request.post('/functionTool/testCall', {
    tool_code: data.test.tool_code,
    member_id: data.test.memberId,
    params
  }).then(res => {
    if (res.code === '200') {
      data.test.result = JSON.stringify(res.data.result, null, 2)
    } else {
      data.test.result = res.msg
      ElMessage.error(res.msg)
    }
  }).finally(() => {
    data.testing = false
  })
}

const search = () => {
  data.pageNum = 1
  load()
}

const reset = () => {
  data.keyword = ''
  data.toolGroup = ''
  data.enabled = ''
  data.pageNum = 1
  load()
}

load()
loadSummary()
loadCodeOptions()
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
.test-head {
  margin-bottom: 12px;
}
.test-head .code-line {
  margin-left: 8px;
}
.result-body {
  margin: 6px 0 0;
  max-height: 320px;
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
