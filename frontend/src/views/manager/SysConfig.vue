<template>
  <div class="page-wrap">
    <div class="page-head with-action">
      <div class="page-head-main">
        <h2>系统参数</h2>
        <p class="page-tip">匹配过程里的各类上限都在这里，改完立刻生效；参数编码由程序读取，只能改参数值和启用状态。</p>
      </div>
      <div class="page-head-action">
        <span class="chip chip-blue">运行时参数 · 即时生效</span>
      </div>
    </div>

    <div class="card filter-card">
      <el-input v-model="data.keyword" class="filter-input" clearable
                placeholder="请输入参数名称或参数编码查询"></el-input>
      <el-select v-model="data.enabled" clearable class="filter-select" placeholder="启用状态">
        <el-option label="已启用" value="是"></el-option>
        <el-option label="已停用" value="否"></el-option>
      </el-select>
      <div class="filter-actions">
        <el-button type="primary" @click="load">查询</el-button>
        <el-button @click="reset">重置</el-button>
      </div>
    </div>

    <div class="card table-card">
      <el-table :data="data.tableData">
        <el-table-column prop="config_name" label="参数名称" width="170" show-overflow-tooltip />
        <el-table-column prop="config_key" label="参数编码" width="210" show-overflow-tooltip>
          <template #default="scope">
            <span class="mono key-text">{{ scope.row.config_key }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="config_value" label="当前值" width="110">
          <template #default="scope">
            <span class="mono value-text">{{ scope.row.config_value }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="value_type" label="值类型" width="90" />
        <el-table-column prop="remark" label="参数说明" min-width="300" show-overflow-tooltip />
        <el-table-column label="启用状态" width="100">
          <template #default="scope">
            <span class="chip" :class="scope.row.enabled === '是' ? 'chip-green' : ''">
              {{ scope.row.enabled === '是' ? '已启用' : '已停用' }}
            </span>
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
        <template #empty>
          <div class="empty-card">
            <div class="empty-title">没有匹配的系统参数</div>
            <div class="empty-desc">换个参数名称或编码再查一次。</div>
          </div>
        </template>
      </el-table>
      <!-- 这一页改的是运行时的闸门，改完立刻生效，所以在页面上把边界说清楚 -->
      <div class="table-tip">
        这里的参数是匹配过程里的各类上限：调度轮数、单个角色的工具调用次数、筛选官放宽次数、
        单次交付人数、候选池写入条数、补画像次数，改完立刻生效，不用重启。
        参数由程序按参数编码读取，所以这一页只能改参数值和启用状态，不能新增或删除参数。
        停用某个参数后它不再生效，用到它的功能会退回程序里的默认值。
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

    <el-dialog title="编辑参数" v-model="data.formVisible" width="560px" destroy-on-close>
      <el-form ref="formRef" :rules="data.rules" :model="data.form" label-width="90px" class="dialog-form">
        <div class="soft-panel form-group">
          <div class="section-title">参数信息</div>
          <el-form-item label="参数名称">
            <span class="readonly-text">{{ data.form.config_name }}</span>
          </el-form-item>
          <el-form-item label="参数编码">
            <span class="mono readonly-text">{{ data.form.config_key }}</span>
          </el-form-item>
        </div>

        <div class="soft-panel form-group">
          <div class="section-title">参数值与状态</div>
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
        </div>

        <div class="soft-panel form-group">
          <div class="section-title">参数说明</div>
          <div class="summary-box">{{ data.form.remark }}</div>
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
  }).catch(() => {})
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
/* 列表页统一范式：页头 → 筛选卡 → 表格卡（分页在卡片内） */
.filter-card {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.filter-input { width: 300px; }
.filter-select { width: 160px; }

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

.key-text {
  color: var(--pb-muted);
}

.value-text {
  font-weight: 600;
  color: var(--pb-text);
}

.pager-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

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

.readonly-text {
  color: var(--pb-text);
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
