<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <el-input v-model="data.keyword" style="width: 240px; margin-right: 10px"
                placeholder="请输入参数名称或参数编码查询"></el-input>
      <el-select v-model="data.enabled" clearable style="width: 140px; margin-right: 10px" placeholder="启用状态">
        <el-option label="已启用" value="是"></el-option>
        <el-option label="已停用" value="否"></el-option>
      </el-select>
      <el-button type="info" plain @click="load">查询</el-button>
      <el-button type="warning" plain style="margin-left: 10px" @click="reset">重置</el-button>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <el-table stripe :data="data.tableData">
        <el-table-column prop="config_name" label="参数名称" width="170" show-overflow-tooltip />
        <el-table-column prop="config_key" label="参数编码" width="200" show-overflow-tooltip />
        <el-table-column prop="config_value" label="当前值" width="110" />
        <el-table-column prop="value_type" label="值类型" width="90" />
        <el-table-column prop="remark" label="参数说明" min-width="300" show-overflow-tooltip />
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
            <el-button v-if="scope.row.enabled === '是'" type="warning" link
                       @click="updateEnabled(scope.row, '否')">停用</el-button>
            <el-button v-else type="success" link @click="updateEnabled(scope.row, '是')">启用</el-button>
          </template>
        </el-table-column>
      </el-table>
      <!-- 这一页改的是运行时的闸门，改完立刻生效，所以在页面上把边界说清楚 -->
      <div class="table-tip">
        这里的参数是匹配过程里的各类上限：调度轮数、单个角色的工具调用次数、筛选官放宽次数、
        单次交付人数、候选池写入条数、补画像次数，改完立刻生效，不用重启。
        参数由程序按参数编码读取，所以这一页只能改参数值和启用状态，不能新增或删除参数。
        停用某个参数后它不再生效，用到它的功能会退回程序里的默认值。
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

    <el-dialog title="编辑参数" v-model="data.formVisible" width="520px" destroy-on-close>
      <el-form ref="formRef" :rules="data.rules" :model="data.form" label-width="90px">
        <el-form-item label="参数名称">
          <span class="readonly-text">{{ data.form.config_name }}</span>
        </el-form-item>
        <el-form-item label="参数编码">
          <span class="readonly-text">{{ data.form.config_key }}</span>
        </el-form-item>
        <el-form-item prop="config_value" label="参数值">
          <el-input-number v-if="data.form.value_type === '整数'" v-model="data.form.config_value"
                           :min="0" :max="1000000" :precision="0" controls-position="right"
                           style="width: 200px"></el-input-number>
          <el-input-number v-else-if="data.form.value_type === '小数'" v-model="data.form.config_value"
                           :min="0" :precision="2" :step="0.1" controls-position="right"
                           style="width: 200px"></el-input-number>
          <el-input v-else v-model="data.form.config_value" maxlength="500"></el-input>
        </el-form-item>
        <el-form-item label="启用状态">
          <el-radio-group v-model="data.form.enabled">
            <el-radio value="是">启用</el-radio>
            <el-radio value="否">停用</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="参数说明">
          <div class="remark-text">{{ data.form.remark }}</div>
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
  pageNum: 1,
  pageSize: 10,
  total: 0,
  keyword: '',
  enabled: '',
  formVisible: false,
  form: {},
  rules: {
    config_value: [{ required: true, message: '请填写参数值', trigger: 'blur' }]
  }
})

const load = () => {
  request.get('/sysConfig/selectPage', {
    params: {
      page_num: data.pageNum,
      page_size: data.pageSize,
      keyword: data.keyword,
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

const handleEdit = (row) => {
  // 整数型参数的输入框要拿到数字才能回填，字符串会显示成空
  const value = row.value_type === '文本' ? row.config_value : Number(row.config_value)
  data.form = { ...row, config_value: value }
  data.formVisible = true
}

const save = () => {
  formRef.value.validate(valid => {
    if (!valid) {
      return
    }
    const payload = {
      id: data.form.id,
      config_value: data.form.config_value === null ? '' : String(data.form.config_value),
      enabled: data.form.enabled
    }
    request.put('/sysConfig/update', payload).then(res => {
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

// 停用是把参数暂时关掉，读取方会退回程序里的默认值，确认框里写清楚
const updateEnabled = (row, enabled) => {
  const text = enabled === '是'
      ? '启用「' + row.config_name + '」后，用到它的功能又会按这里的值执行，您确定吗？'
      : '停用「' + row.config_name + '」后，它不再生效，用到它的功能会退回程序里的默认值，您确定吗？'
  ElMessageBox.confirm(text, '状态确认', { type: 'warning' }).then(() => {
    request.post('/sysConfig/updateEnabled', { config_id: row.id, enabled }).then(res => {
      if (res.code === '200') {
        ElMessage.success('操作成功')
        load()
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

const reset = () => {
  data.keyword = ''
  data.enabled = ''
  data.pageNum = 1
  load()
}

load()
</script>

<style scoped>
.table-tip {
  color: #999;
  font-size: 12px;
  line-height: 20px;
  padding: 10px 5px 0;
}
.readonly-text {
  color: #606266;
}
.remark-text {
  color: #909399;
  font-size: 13px;
  line-height: 20px;
}
</style>
