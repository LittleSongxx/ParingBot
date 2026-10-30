<template>
  <div class="page-wrap">
    <div class="page-head with-action">
      <div class="page-head-main">
        <h2>租客管理</h2>
        <p class="page-tip">审核租客档案、控制档案是否进入候选池；审核通过的租客才会被筛选官检索到。</p>
      </div>
      <div class="page-head-action">
        <span class="chip chip-blue">档案审核通过后才进入候选池</span>
      </div>
    </div>

    <div class="card filter-card">
      <el-input v-model="data.nickname" class="filter-input" clearable placeholder="请输入昵称查询"></el-input>
      <el-select v-model="data.gender" clearable class="filter-select" placeholder="性别">
        <el-option label="男" value="男"></el-option>
        <el-option label="女" value="女"></el-option>
      </el-select>
      <el-select v-model="data.storeId" clearable filterable class="filter-select" placeholder="意向门店">
        <el-option v-for="item in data.stores" :key="item.id" :label="item.name" :value="item.id"></el-option>
      </el-select>
      <el-select v-model="data.auditStatus" clearable class="filter-select" placeholder="审核状态">
        <el-option label="待审核" value="待审核"></el-option>
        <el-option label="已通过" value="已通过"></el-option>
        <el-option label="已驳回" value="已驳回"></el-option>
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
      <el-table :data="data.tableData">
        <el-table-column prop="username" label="账号" width="120" />
        <el-table-column prop="nickname" label="昵称" min-width="120" show-overflow-tooltip />
        <el-table-column prop="gender" label="性别" width="70" />
        <el-table-column prop="age" label="年龄" width="70" />
        <el-table-column prop="store_name" label="意向门店" width="110" />
        <el-table-column prop="schedule_type" label="作息" width="90" />
        <el-table-column prop="occupation" label="职业" min-width="130" show-overflow-tooltip />
        <el-table-column prop="rent_budget" label="月租预算" width="100">
          <template #default="scope">{{ scope.row.rent_budget }} 元</template>
        </el-table-column>
        <el-table-column prop="audit_status" label="审核状态" width="100">
          <template #default="scope">
            <el-tag :type="auditTagType(scope.row.audit_status)">{{ scope.row.audit_status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="enabled" label="启用状态" width="100">
          <template #default="scope">
            <span class="chip" :class="scope.row.enabled === '是' ? 'chip-green' : ''">
              {{ scope.row.enabled === '是' ? '已启用' : '已停用' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="update_time" label="更新时间" width="170" />
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="scope">
            <el-button type="primary" link @click="handleDetail(scope.row)">查看</el-button>
            <el-button type="success" link @click="handleAudit(scope.row)">审核</el-button>
            <el-button v-if="scope.row.enabled === '是'" type="danger" link @click="updateEnabled(scope.row, '否')">停用</el-button>
            <el-button v-else type="warning" link @click="updateEnabled(scope.row, '是')">启用</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-card">
            <div class="empty-title">没有匹配的租客档案</div>
            <div class="empty-desc">调整筛选条件再查一次；删除租客账号请到用户管理操作。</div>
          </div>
        </template>
      </el-table>
      <!-- 档案和生活照是跟着账号走的，删除入口放在用户管理里，这里把去处说明白 -->
      <div class="table-tip">这里只做档案审核和启用停用；要删除租客账号请到用户管理操作，删除时会连带清掉名下的租客档案与生活照。</div>
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

    <!-- 档案详情：资料、生活照、自我介绍分段展示 -->
    <el-dialog title="租客档案" v-model="data.detailVisible" width="720px" destroy-on-close>
      <div v-if="data.detail" class="detail-body">
        <div class="soft-panel detail-block">
          <div class="block-title">基本资料</div>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="账号">{{ data.detail.username }}</el-descriptions-item>
            <el-descriptions-item label="昵称">{{ data.detail.nickname }}</el-descriptions-item>
            <el-descriptions-item label="性别">{{ data.detail.gender }}</el-descriptions-item>
            <el-descriptions-item label="年龄">{{ data.detail.age }} 岁</el-descriptions-item>
            <el-descriptions-item label="出生日期">{{ data.detail.birth_date }}</el-descriptions-item>
            <el-descriptions-item label="职业">{{ data.detail.occupation }}</el-descriptions-item>
            <el-descriptions-item label="意向门店">{{ data.detail.store_name }}（{{ data.detail.area_name }}片区）</el-descriptions-item>
            <el-descriptions-item label="月租预算">{{ data.detail.rent_budget }} 元</el-descriptions-item>
            <el-descriptions-item label="计划租期">{{ data.detail.lease_term }}</el-descriptions-item>
            <el-descriptions-item label="作息">{{ data.detail.schedule_type }}</el-descriptions-item>
            <el-descriptions-item label="整洁度">{{ data.detail.tidiness }}</el-descriptions-item>
            <el-descriptions-item label="是否养宠">{{ data.detail.has_pet || '未填写' }}</el-descriptions-item>
            <el-descriptions-item label="是否吸烟">{{ data.detail.smoking || '未填写' }}</el-descriptions-item>
            <el-descriptions-item label="审核状态">
              <el-tag :type="auditTagType(data.detail.audit_status)">{{ data.detail.audit_status }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="启用状态">{{ data.detail.enabled === '是' ? '已启用' : '已停用' }}</el-descriptions-item>
            <el-descriptions-item label="审核时间">{{ data.detail.audit_time || '未审核' }}</el-descriptions-item>
            <el-descriptions-item label="审核备注" :span="2">{{ data.detail.audit_remark || '无' }}</el-descriptions-item>
            <el-descriptions-item label="兴趣标签" :span="2">
              <template v-if="data.detail.interest_tags.length">
                <el-tag v-for="tag in data.detail.interest_tags" :key="tag" class="tag-item">{{ tag }}</el-tag>
              </template>
              <span v-else>未填写</span>
            </el-descriptions-item>
          </el-descriptions>
        </div>

        <div class="soft-panel detail-block">
          <div class="block-title">生活照</div>
          <div v-if="data.detail.photo_paths.length" class="photo-grid">
            <el-image
                v-for="(photo, index) in data.detail.photo_paths"
                :key="photo"
                class="photo-item"
                :src="photo"
                :preview-src-list="data.detail.photo_paths"
                :initial-index="index"
                fit="cover"
                preview-teleported
            ></el-image>
          </div>
          <div v-else class="detail-text">暂未上传</div>
        </div>

        <div class="soft-panel detail-block">
          <div class="block-title">自我介绍</div>
          <div class="detail-text">{{ data.detail.self_intro || '未填写' }}</div>
        </div>

        <div class="soft-panel detail-block">
          <div class="block-title">室友期望</div>
          <div class="detail-text">{{ data.detail.roommate_expectation || '未填写' }}</div>
        </div>
      </div>
      <template #footer>
        <el-button @click="data.detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 审核弹窗：先看审核对象，再选结论、写备注 -->
    <el-dialog title="档案审核" v-model="data.auditVisible" width="520px" destroy-on-close>
      <el-form label-width="80px" class="dialog-form">
        <div class="soft-panel form-group">
          <div class="section-title">审核对象</div>
          <div class="summary-box audit-target">
            {{ data.auditForm.nickname }}（账号 {{ data.auditForm.username }}）
          </div>
        </div>
        <div class="soft-panel form-group">
          <div class="section-title">审核结论</div>
          <el-form-item label="审核结论">
            <el-radio-group v-model="data.auditForm.audit_status">
              <el-radio value="已通过">通过</el-radio>
              <el-radio value="已驳回">驳回</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="审核备注">
            <el-input
                type="textarea"
                :rows="4"
                maxlength="500"
                show-word-limit
                v-model="data.auditForm.audit_remark"
                :placeholder="data.auditForm.audit_status === '已驳回' ? '请写清要改哪里，租客会照着这条说明修改档案' : '可以不写，也可以写一句通过说明'"></el-input>
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="data.auditVisible = false">取消</el-button>
        <el-button type="primary" @click="submitAudit">提交审核</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import request from "@/utils/request.js";

const data = reactive({
  tableData: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  nickname: '',
  gender: '',
  storeId: null,
  auditStatus: '',
  enabled: '',
  stores: [],
  detailVisible: false,
  detail: null,
  auditVisible: false,
  auditForm: {
    member_id: null,
    nickname: '',
    username: '',
    audit_status: '已通过',
    audit_remark: ''
  }
})

const auditTagType = (status) => {
  if (status === '已通过') {
    return 'success'
  }
  return status === '已驳回' ? 'danger' : 'warning'
}

const load = () => {
  request.get('/member/selectPage', {
    params: {
      page_num: data.pageNum,
      page_size: data.pageSize,
      nickname: data.nickname,
      gender: data.gender,
      store_id: data.storeId || 0,
      audit_status: data.auditStatus,
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

const loadStores = () => {
  request.get('/member/stores').then(res => {
    if (res.code === '200') {
      data.stores = res.data || []
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const handleDetail = (row) => {
  data.detail = null
  data.detailVisible = true
  // 列表里只带了一部分字段，生活照、自我介绍这些要单独取一次完整档案
  request.get('/member/selectById/' + row.id).then(res => {
    if (res.code === '200') {
      data.detail = res.data
    } else {
      data.detailVisible = false
      ElMessage.error(res.msg)
    }
  })
}

const handleAudit = (row) => {
  data.auditForm = {
    member_id: row.id,
    nickname: row.nickname,
    username: row.username,
    // 已经驳回过的档案再打开时默认停在驳回，管理员接着改原因就能重新提交
    audit_status: row.audit_status === '已驳回' ? '已驳回' : '已通过',
    audit_remark: row.audit_remark || ''
  }
  data.auditVisible = true
}

const submitAudit = () => {
  if (data.auditForm.audit_status === '已驳回' && !data.auditForm.audit_remark.trim()) {
    ElMessage.warning('驳回时请填写原因，租客要照着这条说明修改档案')
    return
  }
  request.post('/member/audit', data.auditForm).then(res => {
    if (res.code === '200') {
      ElMessage.success('审核已完成')
      data.auditVisible = false
      load()
    } else {
      ElMessage.error(res.msg)
    }
  })
}

// 停用和启用都会影响这位租客能不能被筛进别人的候选池，确认框里写清影响范围
const updateEnabled = (row, enabled) => {
  const text = enabled === '是'
      ? '启用「' + row.nickname + '」的档案后，只要审核状态是通过，他就能重新进入别人的匹配候选池，您确定吗？'
      : '停用「' + row.nickname + '」的档案后，他不会再进入别人的匹配候选池，已经产生的匹配记录不受影响，您确定吗？'
  ElMessageBox.confirm(text, '状态确认', { type: 'warning' }).then(() => {
    request.post('/member/updateEnabled', { member_id: row.id, enabled }).then(res => {
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
  data.nickname = ''
  data.gender = ''
  data.storeId = null
  data.auditStatus = ''
  data.enabled = ''
  data.pageNum = 1
  load()
}

loadStores()
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

.filter-input { width: 220px; }
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

.pager-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

/* 详情弹窗：分段 soft-panel，长内容内部滚动 */
.detail-body {
  max-height: 68vh;
  overflow-y: auto;
  padding-right: 6px;
}

.detail-block {
  margin-bottom: 12px;
}

.detail-block:last-child {
  margin-bottom: 0;
}

.detail-block .block-title {
  margin-bottom: 10px;
}

.detail-text {
  color: var(--pb-muted);
  line-height: 22px;
  white-space: pre-wrap;
  word-break: break-all;
}

.tag-item {
  margin: 0 6px 6px 0;
}

.photo-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.photo-item {
  width: 108px;
  height: 108px;
  border-radius: 10px;
  border: 1px solid var(--pb-line);
  overflow: hidden;
}

/* 审核弹窗 */
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

.audit-target {
  color: var(--pb-text);
  font-weight: 550;
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
