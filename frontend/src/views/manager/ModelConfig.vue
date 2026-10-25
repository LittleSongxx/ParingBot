<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <el-input v-model="data.name" style="width: 200px; margin-right: 10px"
                placeholder="请输入配置名称查询"></el-input>
      <el-select v-model="data.purpose" clearable style="width: 130px; margin-right: 10px" placeholder="模型用途">
        <el-option v-for="item in data.purposes" :key="item" :label="item" :value="item"></el-option>
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
        <el-table-column prop="name" label="配置名称" width="150" show-overflow-tooltip />
        <el-table-column prop="model_purpose" label="用途" width="100" />
        <el-table-column prop="model_name" label="模型名称" width="150" show-overflow-tooltip />
        <el-table-column prop="base_url" label="接口地址" min-width="220" show-overflow-tooltip />
        <el-table-column label="密钥" width="130">
          <template #default="scope">
            <span v-if="scope.row.api_key">{{ scope.row.api_key }}</span>
            <el-tag v-else type="danger" size="small">未填写</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="温度" width="70">
          <template #default="scope">{{ scope.row.temperature === null ? '-' : scope.row.temperature }}</template>
        </el-table-column>
        <el-table-column label="最大Token" width="95">
          <template #default="scope">{{ scope.row.max_tokens || '-' }}</template>
        </el-table-column>
        <el-table-column label="启用状态" width="95">
          <template #default="scope">
            <el-tag :type="scope.row.enabled === '是' ? 'success' : 'info'">
              {{ scope.row.enabled === '是' ? '已启用' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="update_time" label="更新时间" width="170" />
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="scope">
            <el-button type="success" link :loading="data.testingId === scope.row.id"
                       @click="testConnection(scope.row)">测试连通</el-button>
            <el-button type="primary" link @click="handleEdit(scope.row)">编辑</el-button>
            <el-button v-if="scope.row.enabled === '是'" type="warning" link
                       @click="updateEnabled(scope.row, '否')">停用</el-button>
            <el-button v-else type="success" link @click="updateEnabled(scope.row, '是')">启用</el-button>
            <el-button type="danger" link @click="del(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <!-- 这一页的配置改完立刻生效，所以把几条容易踩的规则在页面上说清楚 -->
      <div class="table-tip">
        全平台的模型都在这里配，改完立刻生效，不用重启。一个用途只允许有一条启用中的配置：
        启用新的一条时，同用途原来那条会自动停用。新增的配置默认是停用的，确认填对之后再启用。
        用途有调度、画像、筛选、审核四个，分别给合租管家、画像师、筛选官、审核官用。
        「测试连通」会用这里保存的配置真实调一次模型，让它回一个字。
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

    <el-dialog title="AI 模型配置" v-model="data.formVisible" width="620px" destroy-on-close>
      <el-form ref="formRef" :rules="data.rules" :model="data.form" label-width="110px">
        <el-form-item prop="name" label="配置名称">
          <el-input v-model="data.form.name" maxlength="255"
                    placeholder="例如：画像提取模型"></el-input>
        </el-form-item>
        <el-form-item prop="model_purpose" label="模型用途">
          <el-select v-model="data.form.model_purpose" style="width: 240px" placeholder="请选择用途">
            <el-option v-for="item in data.purposes" :key="item" :label="item" :value="item"></el-option>
          </el-select>
          <span class="field-tip">一个用途只有一条启用中的配置</span>
        </el-form-item>
        <el-form-item label="模型服务商">
          <el-select v-model="data.form.provider" filterable allow-create clearable
                     style="width: 240px" placeholder="选择常用服务商，也可以直接输入"
                     @change="onProviderChange">
            <el-option label="DeepSeek" value="DeepSeek"></el-option>
            <el-option label="通义千问" value="通义千问"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item prop="base_url" label="接口地址">
          <el-input v-model="data.form.base_url" maxlength="500"
                    placeholder="OpenAI 兼容地址，例如 https://api.deepseek.com/v1"></el-input>
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="data.form.api_key" type="password" show-password maxlength="500"
                    placeholder="留空表示不修改，列表里只会显示脱敏后的密钥"></el-input>
        </el-form-item>
        <el-form-item prop="model_name" label="模型名称">
          <el-input v-model="data.form.model_name" maxlength="255"
                    placeholder="例如：deepseek-chat"></el-input>
        </el-form-item>
        <el-form-item label="温度">
          <el-input-number v-model="data.form.temperature" :min="0" :max="2" :step="0.1"
                           :precision="2" controls-position="right" style="width: 160px"></el-input-number>
          <span class="field-tip">0 到 2，留空用服务端默认值；调度、筛选、审核建议 0</span>
        </el-form-item>
        <el-form-item label="最大输出Token">
          <el-input-number v-model="data.form.max_tokens" :min="1" :max="32768" :precision="0"
                           controls-position="right" style="width: 160px"></el-input-number>
          <span class="field-tip">留空用服务端默认值</span>
        </el-form-item>
        <el-form-item label="启用状态">
          <el-radio-group v-model="data.form.enabled">
            <el-radio value="是">启用</el-radio>
            <el-radio value="否">停用</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="data.form.remark" type="textarea" :rows="2" maxlength="500"
                    placeholder="说明这条配置用在哪一步"></el-input>
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

// 选服务商时把它的 OpenAI 兼容地址带出来，省得管理员去翻文档。
// 这里只是给个能直接用的默认值，地址不对可以自己改
const PROVIDER_URLS = {
  'DeepSeek': 'https://api.deepseek.com/v1',
  '通义千问': 'https://dashscope.aliyuncs.com/compatible-mode/v1'
}

const data = reactive({
  tableData: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  name: '',
  purpose: '',
  enabled: '',
  formVisible: false,
  form: {},
  // 正在测试连通的那一行，按钮转圈期间不重复点
  testingId: 0,
  // 用途选项由后端给出，页面不自己维护一份
  purposes: [],
  rules: {
    name: [{ required: true, message: '请填写配置名称', trigger: 'blur' }],
    model_purpose: [{ required: true, message: '请选择模型用途', trigger: 'change' }],
    base_url: [{ required: true, message: '请填写接口地址', trigger: 'blur' }],
    model_name: [{ required: true, message: '请填写模型名称', trigger: 'blur' }]
  }
})

const load = () => {
  request.get('/aiModelConfig/selectPage', {
    params: {
      page_num: data.pageNum,
      page_size: data.pageSize,
      name: data.name,
      model_purpose: data.purpose,
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

const loadPurposeOptions = () => {
  request.get('/aiModelConfig/purposeOptions').then(res => {
    if (res.code === '200') {
      data.purposes = res.data || []
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const handleAdd = () => {
  data.form = {
    model_purpose: '调度',
    provider: 'DeepSeek',
    base_url: PROVIDER_URLS['DeepSeek'],
    temperature: 0,
    max_tokens: 2048,
    // 新增默认停用：启用会顶掉同用途原来那条，确认填对之后再点启用
    enabled: '否'
  }
  data.formVisible = true
}

const handleEdit = (row) => {
  // 深拷贝当前行，避免直接改 tableData 里的对象导致弹窗一改表格就跟着变；
  // 密钥带过来的是脱敏串，不重新输入的话后端会保留原密钥
  data.form = JSON.parse(JSON.stringify(row))
  data.formVisible = true
}

const onProviderChange = (provider) => {
  if (PROVIDER_URLS[provider]) {
    data.form.base_url = PROVIDER_URLS[provider]
  }
}

const save = () => {
  formRef.value.validate(valid => {
    if (!valid) {
      return
    }
    const payload = {
      id: data.form.id,
      name: data.form.name,
      model_purpose: data.form.model_purpose,
      provider: data.form.provider,
      base_url: data.form.base_url,
      api_key: data.form.api_key,
      model_name: data.form.model_name,
      // 输入框清空时拿到的是 null，这里统一成 null 再发，别把空字符串当成数字
      temperature: data.form.temperature ?? null,
      max_tokens: data.form.max_tokens ?? null,
      enabled: data.form.enabled,
      remark: data.form.remark
    }
    const action = payload.id
        ? request.put('/aiModelConfig/update', payload)
        : request.post('/aiModelConfig/add', payload)
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

const testConnection = (row) => {
  data.testingId = row.id
  request.post('/aiModelConfig/test/' + row.id).then(res => {
    if (res.code === '200') {
      // 后端返回的是这次真实调用拿到了什么，例如「模型连通正常，返回：好」
      ElMessage({ message: res.data, type: 'success', duration: 5000, showClose: true })
    } else {
      // 密钥无效、模型名不存在、接口地址连不上，后端都翻译成了人话
      ElMessage({ message: res.msg, type: 'error', duration: 6000, showClose: true })
    }
  }).finally(() => {
    data.testingId = 0
  })
}

// 启用会顶掉同用途原来那条，停用会让这个用途没有可用模型，两种都要先说清后果
const updateEnabled = (row, enabled) => {
  const effect = '走到这一步的匹配会停下来并提示去启用它'
  const text = enabled === '是'
      ? '启用「' + row.name + '」后，它会成为「' + row.model_purpose + '」用途下唯一生效的配置，'
          + '同一用途下原来启用着的那条会自动停用。确定启用吗？'
      : '停用「' + row.name + '」后，' + effect + '。确定停用吗？'
  ElMessageBox.confirm(text, '状态确认', { type: 'warning' }).then(() => {
    request.post('/aiModelConfig/updateEnabled', { config_id: row.id, enabled }).then(res => {
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
  if (row.enabled === '是') {
    return '「' + row.name + '」正在被「' + row.model_purpose + '」用途使用，删掉之后这一步就没有可用模型了。'
        + '请先停用它，或者先把别的配置启用到这个用途上，再回来删除。'
  }
  return ''
}

const del = (row) => {
  const blocked = blockReason(row)
  if (blocked) {
    ElMessageBox.alert(blocked, '这条配置删不了', { type: 'warning' })
    return
  }
  ElMessageBox.confirm('删除配置「' + row.name + '」后，这个用途要用它就得重新填一遍。确定删除吗？',
      '删除确认', { type: 'warning' }).then(() => {
    request.delete('/aiModelConfig/delete/' + row.id).then(res => {
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
  data.name = ''
  data.purpose = ''
  data.enabled = ''
  data.pageNum = 1
  load()
}

loadPurposeOptions()
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
</style>
