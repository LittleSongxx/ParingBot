<template>
  <div class="main-content page-wrap">
    <!-- 页头：说明这一页要填什么、填完会走到哪一步 -->
    <div class="page-head with-action">
      <div class="page-head-main">
        <h2>租客档案</h2>
        <p class="page-tip">
          档案填得越全，画像越贴近你真实的生活习惯，匹配到的室友也越合拍。
          保存后先由管理员审核，审核通过才会进入匹配候选池。
        </p>
      </div>
      <div class="page-head-action">
        <span class="chip chip-blue">
          {{ data.profile ? '审核状态：' + (data.profile.audit_status || '待审核') : '档案未填写' }}
        </span>
      </div>
    </div>

    <div class="card state-card">
      <div class="block-title">档案审核状态</div>
      <!-- 还没填过档案时先把接下来要做什么说清楚，不直接甩一个空表单 -->
      <el-alert
          v-if="!data.profile"
          type="info"
          :closable="false"
          title="还没有填写租客档案"
          description="把昵称、出生日期、意向门店、作息这些基本信息填完整后保存，档案会先提交给管理员审核，审核通过之后才会进入匹配候选池。">
      </el-alert>
      <template v-else>
        <el-alert
            v-if="data.profile.enabled === '否'"
            type="error"
            :closable="false"
            title="这份档案已被管理员停用"
            description="停用期间档案不会进入匹配候选池，想恢复请先联系管理员了解被停用的原因。">
        </el-alert>
        <el-alert
            v-else-if="data.profile.audit_status === '已驳回'"
            type="error"
            :closable="false"
            :title="'档案被驳回：' + (data.profile.audit_remark || '管理员没有写驳回原因')"
            description="照着上面的说明把档案改好再保存，保存后会重新进入待审核。">
        </el-alert>
        <el-alert
            v-else-if="data.profile.audit_status === '已通过'"
            type="success"
            :closable="false"
            title="档案已通过审核"
            description="你的档案已经进入匹配候选池。改动档案后会重新回到待审核，改完记得再看一眼审核状态。">
        </el-alert>
        <el-alert
            v-else
            type="warning"
            :closable="false"
            title="档案等待审核"
            description="管理员审核通过之后，你的档案才会进入匹配候选池。">
        </el-alert>
      </template>
    </div>

    <div class="card form-card">
      <div class="block-title">填写档案</div>
      <el-form class="basic-form" ref="formRef" :rules="data.rules" :model="data.form" label-width="96px">
        <div class="sub-title full-span">基本信息</div>
        <el-form-item prop="nickname" label="昵称">
          <el-input v-model="data.form.nickname" placeholder="展示在档案卡上的名字，可以不写真名"></el-input>
        </el-form-item>
        <el-form-item prop="gender" label="性别">
          <el-radio-group v-model="data.form.gender">
            <el-radio value="男">男</el-radio>
            <el-radio value="女">女</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item prop="birth_date" label="出生日期">
          <el-date-picker
              class="fill"
              v-model="data.form.birth_date"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="请选择出生日期">
          </el-date-picker>
        </el-form-item>
        <el-form-item prop="occupation" label="职业">
          <el-input v-model="data.form.occupation" placeholder="例如：小学老师、软件工程师"></el-input>
        </el-form-item>
        <el-form-item prop="store_id" label="意向门店">
          <el-select class="fill" v-model="data.form.store_id" placeholder="请选择想入住的门店" filterable>
            <el-option-group v-for="group in data.storeGroups" :key="group.area" :label="group.area + '片区'">
              <el-option v-for="item in group.stores" :key="item.id" :label="item.name" :value="item.id"></el-option>
            </el-option-group>
          </el-select>
        </el-form-item>
        <el-form-item prop="rent_budget" label="月租预算">
          <el-input-number v-model="data.form.rent_budget" :min="800" :max="20000" :step="100" style="width: 180px"></el-input-number>
          <span class="unit-text">元 / 月</span>
        </el-form-item>
        <el-form-item prop="lease_term" label="计划租期">
          <el-select class="fill" v-model="data.form.lease_term" placeholder="请选择打算住多久">
            <el-option v-for="item in data.leaseTerms" :key="item" :label="item" :value="item"></el-option>
          </el-select>
        </el-form-item>
        <div class="sub-title full-span">生活习惯</div>
        <el-form-item prop="schedule_type" label="作息">
          <el-select class="fill" v-model="data.form.schedule_type" placeholder="请选择平时的作息">
            <el-option v-for="item in data.scheduleTypes" :key="item" :label="item" :value="item"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item prop="tidiness" label="整洁度">
          <el-select class="fill" v-model="data.form.tidiness" placeholder="请选择对卫生的要求">
            <el-option v-for="item in data.tidinessLevels" :key="item" :label="item" :value="item"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item prop="has_pet" label="是否养宠">
          <el-select class="fill" v-model="data.form.has_pet" clearable placeholder="没有可以不选">
            <el-option v-for="item in data.hasPetOptions" :key="item" :label="item" :value="item"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item prop="smoking" label="是否吸烟">
          <el-select class="fill" v-model="data.form.smoking" clearable placeholder="没有可以不选">
            <el-option v-for="item in data.smokingOptions" :key="item" :label="item" :value="item"></el-option>
          </el-select>
        </el-form-item>
        <div class="sub-title full-span">兴趣与自我介绍</div>
        <el-form-item class="full-span" prop="interest_tags" label="兴趣标签">
          <el-select class="fill" v-model="data.form.interest_tags" multiple filterable placeholder="最多选 8 个">
            <el-option-group v-for="group in data.tagGroups" :key="group.category" :label="group.category">
              <el-option v-for="tag in group.tags" :key="tag.id" :label="tag.name" :value="tag.name"></el-option>
            </el-option-group>
          </el-select>
        </el-form-item>
        <el-form-item class="full-span" prop="self_intro" label="自我介绍">
          <el-input
              type="textarea"
              :rows="4"
              maxlength="1000"
              show-word-limit
              v-model="data.form.self_intro"
              placeholder="说说你几点睡几点起、卫生习惯、做不做饭、会不会带朋友回来，平台会从这段文字里整理你的画像"></el-input>
        </el-form-item>
        <el-form-item class="full-span" prop="roommate_expectation" label="室友期望">
          <el-input
              type="textarea"
              :rows="3"
              maxlength="500"
              show-word-limit
              v-model="data.form.roommate_expectation"
              placeholder="说说你想和怎样的人合住、最在意哪一点，匹配时会参考这段话"></el-input>
        </el-form-item>
        <el-form-item class="full-span" label="生活照">
          <div v-if="!data.fileList.length" class="empty-photo-tip">暂未上传，照片为选填项，可以稍后补充。</div>
          <el-upload
              :action="baseUrl + '/files/upload'"
              :headers="uploadHeaders"
              list-type="picture-card"
              :limit="9"
              v-model:file-list="data.fileList"
              :before-upload="beforeUpload"
              :on-success="handleUploadSuccess"
              :on-error="handleUploadError"
              :on-exceed="handleExceed"
              :on-remove="handleRemove">
            <el-icon><Plus /></el-icon>
          </el-upload>
          <div class="upload-tip">生活照不是必填项；最多 9 张，单张不超过 5MB。删掉的照片在保存之后才会从服务器一并清掉。</div>
        </el-form-item>
        <div class="form-actions full-span">
          <el-button type="primary" size="large" class="save-btn" @click="save">保存并提交审核</el-button>
          <el-button size="large" @click="loadProfile">重新加载</el-button>
        </div>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { nextTick, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { Plus } from "@element-plus/icons-vue";
import request from "@/utils/request.js";

// 上传组件自己发请求，不走 request.js，action 要写完整地址，token 也要在这里手动带上
const baseUrl = import.meta.env.VITE_BASE_URL
const uploadHeaders = { token: JSON.parse(localStorage.getItem('xm-user') || '{}').token || '' }
const formRef = ref()

const data = reactive({
  profile: null,
  storeGroups: [],
  tidinessLevels: ['随意', '一般', '整洁', '洁癖'],
  leaseTerms: ['3个月以下', '3-6个月', '6-12个月', '1-2年', '2年以上'],
  scheduleTypes: ['早睡早起', '正常作息', '夜猫子'],
  hasPetOptions: ['有', '无'],
  smokingOptions: ['不吸烟', '偶尔', '经常'],
  tagGroups: [],
  fileList: [],
  form: {
    nickname: '',
    gender: '',
    birth_date: '',
    rent_budget: null,
    tidiness: '',
    occupation: '',
    lease_term: '',
    store_id: null,
    schedule_type: '',
    has_pet: '',
    smoking: '',
    interest_tags: [],
    self_intro: '',
    roommate_expectation: ''
  },
  rules: {
    nickname: [{ required: true, message: '请填写昵称', trigger: 'blur' }],
    gender: [{ required: true, message: '请选择性别', trigger: 'change' }],
    birth_date: [{ required: true, message: '请选择出生日期', trigger: 'change' }],
    rent_budget: [{ required: true, message: '请填写月租预算', trigger: 'change' }],
    tidiness: [{ required: true, message: '请选择整洁度', trigger: 'change' }],
    occupation: [{ required: true, message: '请填写职业', trigger: 'blur' }],
    lease_term: [{ required: true, message: '请选择计划租期', trigger: 'change' }],
    store_id: [{ required: true, message: '请选择意向门店', trigger: 'change' }],
    schedule_type: [{ required: true, message: '请选择作息', trigger: 'change' }],
    self_intro: [{ required: true, message: '请填写自我介绍', trigger: 'blur' }]
  }
})

// 把已经填好的档案回填到表单和生活照，审核状态单独放在页面顶部展示
const fillForm = (profile) => {
  data.form = {
    nickname: profile.nickname,
    gender: profile.gender,
    birth_date: profile.birth_date,
    rent_budget: profile.rent_budget,
    tidiness: profile.tidiness,
    occupation: profile.occupation,
    lease_term: profile.lease_term,
    store_id: profile.store_id,
    schedule_type: profile.schedule_type,
    has_pet: profile.has_pet,
    smoking: profile.smoking,
    interest_tags: profile.interest_tags || [],
    self_intro: profile.self_intro,
    roommate_expectation: profile.roommate_expectation
  }
  data.fileList = (profile.photo_paths || []).map(url => ({
    // 文件名取地址最后一段，回显时列表里能看出是哪个文件
    name: url.substring(url.lastIndexOf('/') + 1),
    url
  }))
}

const loadProfile = () => {
  request.get('/member/my').then(res => {
    if (res.code !== '200') {
      ElMessage.error(res.msg)
      return
    }
    data.profile = res.data
    if (res.data) {
      fillForm(res.data)
    }
  })
}

const loadOptions = () => {
  request.get('/member/stores').then(res => {
    if (res.code !== '200') {
      ElMessage.error(res.msg)
      return
    }
    // 门店按片区分组，下拉框里先认片区再挑门店
    const groups = []
    for (const store of res.data || []) {
      let group = groups.find(item => item.area === store.area)
      if (!group) {
        group = { area: store.area, stores: [] }
        groups.push(group)
      }
      group.stores.push(store)
    }
    data.storeGroups = groups
  })
  request.get('/member/interestTags').then(res => {
    if (res.code !== '200') {
      ElMessage.error(res.msg)
      return
    }
    // 标签按类目分组，下拉框里按类目分区展示，选项多了也好找
    const groups = []
    for (const tag of res.data || []) {
      let group = groups.find(item => item.category === tag.category)
      if (!group) {
        group = { category: tag.category, tags: [] }
        groups.push(group)
      }
      group.tags.push(tag)
    }
    data.tagGroups = groups
  })
}

// 只收图片且不超过 5MB。上传组件自己发请求，校验放在上传之前拦
const beforeUpload = (file) => {
  if (!file.type.startsWith('image/')) {
    ElMessage.error('生活照只能上传图片文件')
    return false
  }
  if (file.size / 1024 / 1024 > 5) {
    ElMessage.error('单张照片不能超过 5MB')
    return false
  }
  return true
}

// el-upload 会用 blob: 本地地址渲染缩略图。移除文件时组件会同步 revoke 这个地址，
// 而浏览器可能还在加载那张缩略图，控制台就会报 net::ERR_FILE_NOT_FOUND。
// 这里先把缩略图换成一个透明占位图，等 DOM 更新完再 revoke，就不会再出现这条报错
const TRANSPARENT_PLACEHOLDER = 'data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=='
const releaseBlobPreview = (file) => {
  const url = file && file.url
  if (url && url.startsWith('blob:')) {
    file.url = TRANSPARENT_PLACEHOLDER
    nextTick(() => URL.revokeObjectURL(url))
  }
}

const handleUploadSuccess = (res, file) => {
  if (res.code !== '200') {
    ElMessage.error(res.msg)
    return
  }
  // 上传接口返回的是文件下载地址，写到这一条上做预览，
  // 点保存时才会把整份生活照写进数据库
  releaseBlobPreview(file)
  file.url = res.data
  ElMessage.success('照片已上传，点保存后生效')
}

const handleUploadError = (error, file) => {
  // 上传失败的那张从列表里摘掉，否则保存时会把一个本地预览地址写进数据库
  releaseBlobPreview(file)
  data.fileList = data.fileList.filter(item => item.uid !== file.uid)
  ElMessage.error('照片上传失败，请检查网络后重试')
}

const handleExceed = () => {
  ElMessage.warning('生活照最多放 9 张，想换图请先删掉一张')
}

// 删除缩略图时同步清掉本地预览地址，并保证 fileList 里不残留这一条
const handleRemove = (file) => {
  releaseBlobPreview(file)
  data.fileList = data.fileList.filter(item => item.uid !== file.uid)
}

const save = () => {
  formRef.value.validate(valid => {
    if (!valid) {
      return
    }
    // 还有照片在传的时候先拦住，等地址回来再保存，名单里不会混进本地预览地址
    if (data.fileList.some(file => !file.url)) {
      ElMessage.warning('还有照片没上传完，等照片都显示出来之后再点保存')
      return
    }
    // 生活照以当前列表为准，保存时整份提交，后端对比之后清掉被删掉的文件
    const payload = {
      ...data.form,
      photo_paths: data.fileList.map(file => file.url).filter(url => !!url)
    }
    request.post('/member/saveMy', payload).then(res => {
      if (res.code === '200') {
        ElMessage.success('档案已提交，等待管理员审核')
        data.profile = res.data
        fillForm(res.data)
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

loadOptions()
loadProfile()
</script>

<style scoped>
.page-wrap > .page-head { margin: 0; }
.page-wrap > .card { margin-top: 0; }

/* 审核状态卡：标题下直接放一条状态提示 */
.state-card .el-alert { margin-top: 0; }
.state-card .el-alert + .el-alert { margin-top: 10px; }

/* 表单卡：两列排布，短字段一行两个，长文本和生活照占满整行 */
.form-card {
  padding: 22px 26px 26px;
}
.basic-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 28px;
}
.basic-form .full-span { grid-column: 1 / -1; }
.basic-form :deep(.el-form-item) { margin-bottom: 18px; }
.basic-form :deep(.el-form-item__label) { font-weight: 500; }
.fill { width: 100%; }

/* 表单内分区标题：主题色竖条 + 虚线分隔 */
.sub-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 18px 0 14px;
  padding-top: 18px;
  border-top: 1px dashed var(--pb-line-strong);
  font-size: 14px;
  font-weight: 650;
  color: var(--pb-text);
}
.sub-title::before {
  content: "";
  width: 4px;
  height: 14px;
  border-radius: 999px;
  background: linear-gradient(180deg, #60a5fa, #2563eb);
}
.basic-form .sub-title:first-child {
  margin-top: 0;
  padding-top: 0;
  border-top: none;
}

.unit-text {
  margin-left: 10px;
  font-size: 13px;
  color: var(--pb-muted);
}

.empty-photo-tip {
  width: 100%;
  margin-bottom: 12px;
  padding: 10px 14px;
  border: 1px dashed var(--pb-line-strong);
  border-radius: var(--pb-radius-sm);
  background: var(--pb-surface-2);
  color: var(--pb-muted);
  font-size: 12.5px;
  line-height: 20px;
}
.upload-tip {
  width: 100%;
  margin-top: 10px;
  color: var(--pb-faint);
  font-size: 12px;
  line-height: 20px;
}

/* 生活照：圆角缩略图网格 */
.form-card :deep(.el-upload--picture-card) {
  width: 112px;
  height: 112px;
  border: 1px dashed var(--pb-line-strong);
  border-radius: 12px;
  background: var(--pb-surface-2);
  transition: all 0.18s ease;
}
.form-card :deep(.el-upload--picture-card:hover) {
  border-color: var(--pb-brand);
  color: var(--pb-brand);
  background: var(--pb-brand-soft);
}
.form-card :deep(.el-upload-list--picture-card .el-upload-list__item) {
  width: 112px;
  height: 112px;
  border: 1px solid var(--pb-line);
  border-radius: 12px;
  overflow: hidden;
}

.form-actions {
  display: flex;
  justify-content: center;
  gap: 10px;
  margin-top: 4px;
  padding-top: 20px;
  border-top: 1px solid var(--pb-line);
}
.save-btn { min-width: 180px; }

@media (max-width: 1000px) {
  .basic-form { grid-template-columns: 1fr; }
  .form-card { padding: 18px 16px 20px; }
}
</style>
