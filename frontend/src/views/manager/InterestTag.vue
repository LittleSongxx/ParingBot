<template>
  <div class="page-wrap">
    <div class="page-head with-action">
      <div class="page-head-main">
        <h2>兴趣标签</h2>
        <p class="page-tip">画像与匹配共用的标签词表；已被租客使用的标签不能删除，只能停用。</p>
      </div>
      <div class="page-head-action">
        <el-button type="primary" @click="handleAdd">新增标签</el-button>
        <el-button type="danger" plain @click="delBatch">批量删除</el-button>
      </div>
    </div>

    <div class="card filter-card">
      <el-input v-model="data.tagName" class="filter-input" clearable placeholder="请输入标签名查询"></el-input>
      <el-select v-model="data.category" clearable class="filter-select" placeholder="类目">
        <el-option v-for="item in data.categories" :key="item" :label="item" :value="item"></el-option>
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

    <div class="card table-card">
      <el-table :data="data.tableData" @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="55" />
        <el-table-column prop="tag_name" label="标签名" min-width="140" />
        <el-table-column prop="category" label="类目" width="100" />
        <el-table-column prop="used_count" label="使用人数" width="100">
          <template #default="scope">
            <!-- 有人用过的标签删不得，这里直接标出来，管理员不用点一下才知道 -->
            <span :class="{ 'used-count': scope.row.used_count > 0 }">{{ scope.row.used_count }} 人</span>
          </template>
        </el-table-column>
        <el-table-column prop="enabled" label="启用状态" width="100">
          <template #default="scope">
            <span class="chip" :class="scope.row.enabled === '是' ? 'chip-green' : ''">
              {{ scope.row.enabled === '是' ? '已启用' : '已停用' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="sort" label="排序号" width="90" />
        <el-table-column prop="update_time" label="更新时间" width="170" />
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="scope">
            <el-button type="primary" link @click="handleEdit(scope.row)">编辑</el-button>
            <el-button v-if="scope.row.enabled === '是'" type="warning" link @click="updateEnabled(scope.row, '否')">停用</el-button>
            <el-button v-else type="success" link @click="updateEnabled(scope.row, '是')">启用</el-button>
            <el-button type="danger" link @click="del(scope.row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-card">
            <div class="empty-title">词表里还没有标签</div>
            <div class="empty-desc">点右上角「新增标签」补一条，或者调整筛选条件再查。</div>
          </div>
        </template>
      </el-table>
      <!-- 词表是画像和匹配共用的取值来源，删和停用各有什么影响先说清楚 -->
      <div class="table-tip">
        这份词表是给租客打兴趣标签、按兴趣筛候选时共用的取值来源，只能从这里取词，不允许自造。
        已经被租客档案用到的标签不能删除，只能停用：停用之后新提交的档案不再提供这个标签，
        已经有租客在用的不受影响；删除会把租客档案里的那个词变成词表外的取值。
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

    <el-dialog :title="data.form.id ? '编辑标签' : '新增标签'" v-model="data.formVisible" width="500px" destroy-on-close>
      <el-form ref="formRef" :rules="data.rules" :model="data.form" label-width="90px" class="dialog-form">
        <div class="soft-panel form-group">
          <div class="section-title">标签信息</div>
          <el-form-item prop="tag_name" label="标签名">
            <el-input v-model="data.form.tag_name" maxlength="50" placeholder="例如：跑步、下厨"></el-input>
          </el-form-item>
          <el-form-item prop="category" label="类目">
            <el-select v-model="data.form.category" placeholder="请选择类目" style="width: 100%">
              <el-option v-for="item in data.categories" :key="item" :label="item" :value="item"></el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="排序号">
            <el-input-number v-model="data.form.sort" :min="0" :max="999" controls-position="right" style="width: 160px"></el-input-number>
            <span class="inline-tip">同类标签按这个数字从小到大排</span>
          </el-form-item>
        </div>

        <div class="soft-panel form-group">
          <div class="section-title">启用状态</div>
          <el-form-item label="状态">
            <el-radio-group v-model="data.form.enabled">
              <el-radio value="是">启用</el-radio>
              <el-radio value="否">停用</el-radio>
            </el-radio-group>
          </el-form-item>
          <div v-if="data.form.id && data.form.used_count" class="summary-box form-warn">
            已有 {{ data.form.used_count }} 位租客的档案用了这个标签，改名字或换类目会被拦下，
            需要调整请新增一个标签再把这一条停用。
          </div>
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
  tagName: '',
  category: '',
  enabled: '',
  categories: [],
  ids: [],
  formVisible: false,
  form: {},
  rules: {
    tag_name: [{ required: true, message: '请填写标签名', trigger: 'blur' }],
    category: [{ required: true, message: '请选择类目', trigger: 'change' }]
  }
})

const load = () => {
  request.get('/interestTag/selectPage', {
    params: {
      page_num: data.pageNum,
      page_size: data.pageSize,
      tag_name: data.tagName,
      category: data.category,
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

const loadCategories = () => {
  request.get('/interestTag/categories').then(res => {
    if (res.code === '200') {
      data.categories = res.data || []
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const handleAdd = () => {
  data.form = { tag_name: '', category: '', sort: 0, enabled: '是', used_count: 0 }
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
    const url = data.form.id ? '/interestTag/update' : '/interestTag/add'
    const method = data.form.id ? 'put' : 'post'
    request[method](url, data.form).then(res => {
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

const del = (row) => {
  // 有人用过的标签后端会拦，这里先给出该走的替代做法，不白跑一次请求
  if (row.used_count > 0) {
    ElMessageBox.alert(
        '已有 ' + row.used_count + ' 位租客的档案用了「' + row.tag_name + '」，删掉之后他们的标签就不在词表里了。'
        + '请改为停用，停用之后新档案不会再选到它。',
        '这个标签删不了', { type: 'warning' })
    return
  }
  ElMessageBox.confirm('删除标签「' + row.tag_name + '」后，词表里就没有这个词了，您确定吗？',
      '删除确认', { type: 'warning' }).then(() => {
    request.delete('/interestTag/delete/' + row.id).then(res => {
      if (res.code === '200') {
        ElMessage.success('删除成功')
        load()
      } else {
        ElMessage.error(res.msg)
      }
    })
  }).catch(() => {})
}

const delBatch = () => {
  if (!data.ids.length) {
    ElMessage.warning('请选择数据')
    return
  }
  const used = data.tableData.filter(item => data.ids.includes(item.id) && item.used_count > 0)
  if (used.length) {
    ElMessageBox.alert(
        '选中的标签里有 ' + used.length + ' 个已经被租客档案用到：'
        + used.map(item => '「' + item.tag_name + '」').join('、')
        + '。这些标签删不了，请把它们取消勾选，或者改为停用。',
        '选中的标签删不掉', { type: 'warning' })
    return
  }
  ElMessageBox.confirm('删除选中的 ' + data.ids.length + ' 个标签，词表里就没有这些词了，您确定吗？',
      '删除确认', { type: 'warning' }).then(() => {
    request.delete('/interestTag/deleteBatch', { data: data.ids }).then(res => {
      if (res.code === '200') {
        ElMessage.success('删除成功')
        load()
      } else {
        ElMessage.error(res.msg)
      }
    })
  }).catch(() => {})
}

// 停用不影响已经在用的租客档案，只影响新档案能不能选到它，确认框里把这条说清楚
const updateEnabled = (row, enabled) => {
  const used = row.used_count > 0 ? '，已经有 ' + row.used_count + ' 位租客在用它，他们的档案不受影响' : ''
  const text = enabled === '是'
      ? '启用「' + row.tag_name + '」后，租客填档案时又能选到这个词了，您确定吗？'
      : '停用「' + row.tag_name + '」后，新提交的租客档案不再提供这个标签' + used + '，您确定吗？'
  ElMessageBox.confirm(text, '状态确认', { type: 'warning' }).then(() => {
    request.post('/interestTag/updateEnabled', { tag_id: row.id, enabled }).then(res => {
      if (res.code === '200') {
        ElMessage.success('操作成功')
        load()
      } else {
        ElMessage.error(res.msg)
      }
    })
  }).catch(() => {})
}

const handleSelectionChange = (rows) => {
  data.ids = rows.map(item => item.id)
}

const reset = () => {
  data.tagName = ''
  data.category = ''
  data.enabled = ''
  data.pageNum = 1
  load()
}

loadCategories()
load()
</script>

<style scoped>
.filter-card {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.filter-input { width: 240px; }
.filter-select { width: 150px; }

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

.used-count {
  color: var(--pb-brand);
  font-weight: 600;
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

.inline-tip {
  margin-left: 10px;
  color: var(--pb-faint);
  font-size: 12px;
}

.form-warn {
  margin-top: 2px;
  color: #b45309;
  background: var(--pb-warn-soft);
  border-color: rgba(245, 158, 11, 0.24);
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
