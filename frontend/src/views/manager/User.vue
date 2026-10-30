<template>
  <div class="page-wrap">
    <!-- 页头：标题 + 说明 + 右侧主操作 -->
    <div class="page-head with-action">
      <div class="page-head-main">
        <h2>用户管理</h2>
        <p class="page-tip">管理平台账号与角色、联系方式与启用状态；删除账号会连带清掉其名下的租客数据。</p>
      </div>
      <div class="page-head-action">
        <el-button type="primary" @click="handleAdd">新增用户</el-button>
        <el-button type="danger" plain @click="delBatch">批量删除</el-button>
      </div>
    </div>

    <!-- 筛选卡：搜索 + 角色筛选 + 查询/重置 -->
    <div class="card filter-card">
      <el-input v-model="data.name" class="filter-input" clearable placeholder="请输入姓名查询"></el-input>
      <el-select v-model="data.role" clearable class="filter-select" placeholder="请选择角色">
        <el-option label="管理员" value="ADMIN"></el-option>
        <el-option label="租客" value="USER"></el-option>
      </el-select>
      <div class="filter-actions">
        <el-button type="primary" @click="load">查询</el-button>
        <el-button @click="reset">重置</el-button>
      </div>
    </div>

    <!-- 表格卡：全局表格样式 + 卡片内右对齐分页 -->
    <div class="card table-card">
      <el-table :data="data.tableData" @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="55" />
        <el-table-column prop="username" label="账号" min-width="120" />
        <el-table-column prop="avatar" label="头像" width="80">
          <template #default="scope">
            <NameAvatar :name="scope.row.name" :src="scope.row.avatar" :size="40" />
          </template>
        </el-table-column>
        <el-table-column prop="name" label="姓名" min-width="100" />
        <el-table-column prop="role" label="角色" width="90">
          <template #default="scope">
            {{ scope.row.role === 'ADMIN' ? '管理员' : '租客' }}
          </template>
        </el-table-column>
        <el-table-column prop="phone" label="电话" min-width="130" />
        <!-- 邮箱比较长，超出列宽时收成一行，鼠标移上去看完整内容 -->
        <el-table-column prop="email" label="邮箱" min-width="180" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="90">
          <template #default="scope">
            <el-tag :type="scope.row.status === 'NORMAL' ? 'success' : 'danger'">
              {{ scope.row.status === 'NORMAL' ? '正常' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="create_time" label="注册时间" width="170" />
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="scope">
            <el-button type="primary" circle :icon="Edit" aria-label="编辑用户" title="编辑用户"
                       @click="handleEdit(scope.row)"></el-button>
            <el-button type="danger" circle :icon="Delete" aria-label="删除用户" title="删除用户"
                       @click="del(scope.row)"></el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-card">
            <div class="empty-title">暂无用户数据</div>
            <div class="empty-desc">调整筛选条件再试试，或点右上角「新增用户」创建一条。</div>
          </div>
        </template>
      </el-table>
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

    <!-- 弹窗：按「账号信息 / 基本资料」分组，不再密集平铺 -->
    <el-dialog title="用户信息" v-model="data.formVisible" width="580px" destroy-on-close>
      <el-form ref="formRef" :rules="data.rules" :model="data.form" label-width="80px" class="dialog-form">
        <div class="soft-panel form-group">
          <div class="section-title">账号信息</div>
          <el-form-item prop="username" label="账号">
            <el-input v-model="data.form.username" placeholder="请输入 3-30 个字符的账号"
                      :disabled="!!data.form.id"></el-input>
          </el-form-item>
          <el-form-item v-if="!data.form.id" prop="password" label="密码">
            <el-input v-model="data.form.password" show-password placeholder="不填写时默认密码为 123456"></el-input>
          </el-form-item>
        </div>

        <div class="soft-panel form-group">
          <div class="section-title">基本资料</div>
          <el-form-item prop="avatar" label="头像">
            <el-upload :action="baseUrl + '/files/upload'" :headers="uploadHeaders" :on-success="handleFileUpload" list-type="picture">
              <el-button type="primary" plain>点击上传</el-button>
            </el-upload>
          </el-form-item>
          <el-form-item prop="name" label="姓名">
            <el-input v-model="data.form.name" placeholder="请输入姓名"></el-input>
          </el-form-item>
          <el-form-item prop="role" label="角色">
            <el-select v-model="data.form.role" style="width: 100%">
              <el-option label="管理员" value="ADMIN"></el-option>
              <el-option label="租客" value="USER"></el-option>
            </el-select>
          </el-form-item>
          <el-form-item prop="phone" label="电话">
            <el-input v-model="data.form.phone" placeholder="请输入电话"></el-input>
          </el-form-item>
          <el-form-item prop="email" label="邮箱">
            <el-input v-model="data.form.email" placeholder="请输入邮箱"></el-input>
          </el-form-item>
          <el-form-item prop="status" label="状态">
            <el-radio-group v-model="data.form.status">
              <el-radio value="NORMAL">正常</el-radio>
              <el-radio value="DISABLED">停用</el-radio>
            </el-radio-group>
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="data.formVisible = false">取消</el-button>
        <el-button type="primary" @click="save">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { Delete, Edit } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/utils/request.js'
import NameAvatar from '@/components/NameAvatar.vue'

const baseUrl = import.meta.env.VITE_BASE_URL
// 上传组件自己发请求，不走 request.js 的拦截器，token 请求头要在这里单独带上
const uploadHeaders = { token: JSON.parse(localStorage.getItem('xm-user') || '{}').token || '' }
const formRef = ref()

const data = reactive({
  formVisible: false,
  form: {},
  tableData: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  name: '',
  role: '',
  ids: [],
  // 账号和密码的规则与自助注册保持一致，页面先拦一道，后端还会再校验一次
  rules: {
    username: [
      { required: true, message: '请输入账号', trigger: 'blur' },
      { min: 3, max: 30, message: '账号长度需要在 3 到 30 个字符之间', trigger: 'blur' }
    ],
    password: [
      { min: 6, max: 30, message: '密码长度需要在 6 到 30 个字符之间', trigger: 'blur' }
    ],
    // 电话和邮箱可以不填，填了才判格式，规则与后端保持一致
    phone: [
      { pattern: /^1[3-9]\d{9}$/, message: '电话请填写 11 位手机号', trigger: 'blur' }
    ],
    email: [
      { type: 'email', message: '邮箱格式不正确', trigger: ['blur', 'change'] }
    ]
  }
})

const load = () => {
  request.get('/user/selectPage', {
    params: {
      page_num: data.pageNum,
      page_size: data.pageSize,
      name: data.name,
      role: data.role
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

const handleAdd = () => {
  data.form = { role: 'USER', status: 'NORMAL' }
  data.formVisible = true
}

const handleEdit = (row) => {
  data.form = JSON.parse(JSON.stringify(row))
  data.formVisible = true
}

const save = () => {
  formRef.value.validate(valid => {
    if (!valid) {
      return
    }
    const action = data.form.id
        ? request.put('/user/update', data.form)
        : request.post('/user/add', data.form)
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

// 删除会连带清掉什么，写在确认框里，让管理员点确定之前就知道这次删掉了多少东西
const delScopeText = (row) => {
  const scope = row.role === 'USER'
      ? '，他名下的租客档案、合住偏好、动态与画像会一并删除'
      : ''
  return '删除「' + row.name + '」这个账号' + scope + '，您确定吗？'
}

const del = (row) => {
  ElMessageBox.confirm(delScopeText(row), '删除确认', { type: 'warning' }).then(() => {
    request.delete('/user/delete/' + row.id).then(res => {
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
  ElMessageBox.confirm(
      '删除选中的 ' + data.ids.length + ' 个账号，其中租客名下的档案、合住偏好、动态与画像会一并删除，您确定吗？',
      '删除确认', { type: 'warning' }).then(() => {
    request.delete('/user/deleteBatch', { data: data.ids }).then(res => {
      if (res.code === '200') {
        ElMessage.success('删除成功')
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

const handleFileUpload = (res) => {
  data.form.avatar = res.data
}

const reset = () => {
  data.name = ''
  data.role = ''
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

.filter-input { width: 260px; }
.filter-select { width: 180px; }

.filter-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
}

.table-card {
  padding: 18px 20px 16px;
}

.table-card :deep(.el-table) {
  background: transparent;
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

.pager-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
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
