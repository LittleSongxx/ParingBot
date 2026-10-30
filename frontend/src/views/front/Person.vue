<template>
  <div class="main-content page-wrap">
    <div class="page-head narrow-head">
      <div class="page-head-main">
        <h2>个人资料</h2>
        <p class="page-tip">这里的信息会展示在你的租客档案与匹配结果里，改完点保存即时生效。</p>
      </div>
    </div>

    <div class="card person-card">
      <el-form ref="formRef" :rules="data.rules" :model="data.user" label-width="70px">
        <el-form-item prop="avatar" class="avatar-item">
          <el-upload
              :action="baseUrl + '/files/upload'"
              :headers="uploadHeaders"
              :before-upload="beforeUpload"
              :on-success="handleUploadSuccess"
              :on-error="handleUploadError"
              :show-file-list="false"
              class="avatar-uploader"
          >
            <div class="avatar-box">
              <NameAvatar :name="data.user.name" :src="data.user.avatar" :size="120" />
              <span class="avatar-tip">点击更换头像</span>
            </div>
          </el-upload>
        </el-form-item>
        <el-form-item prop="username" label="账号">
          <el-input disabled v-model="data.user.username" placeholder="请输入账号"></el-input>
        </el-form-item>
        <el-form-item prop="name" label="姓名">
          <el-input v-model="data.user.name" placeholder="请输入姓名"></el-input>
        </el-form-item>
        <el-form-item prop="phone" label="电话">
          <el-input v-model="data.user.phone" placeholder="请输入 11 位手机号"></el-input>
        </el-form-item>
        <el-form-item prop="email" label="邮箱">
          <el-input v-model="data.user.email" placeholder="请输入邮箱"></el-input>
        </el-form-item>
        <div class="form-actions">
          <el-button type="primary" size="large" class="submit-btn" @click="update">保 存</el-button>
        </div>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from "vue";
import request from "@/utils/request.js";
import { ElMessage } from "element-plus";
import NameAvatar from "@/components/NameAvatar.vue";

// 头像上传组件自己发请求，不走 request.js，action 要写完整地址，token 也要在这里手动带上
const baseUrl = import.meta.env.VITE_BASE_URL
const uploadHeaders = { token: JSON.parse(localStorage.getItem('xm-user') || '{}').token || '' }
const formRef = ref()

const data = reactive({
  // 登录时把账号信息写进了浏览器缓存，这里直接拿来当表单初始值，
  // 进页面不用再查一次接口，改完保存再写回缓存
  user: JSON.parse(localStorage.getItem('xm-user') || '{}'),
  rules: {
    name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
    // 电话和邮箱可以不填，填了才判格式，规则与后端保持一致
    phone: [{ pattern: /^1[3-9]\d{9}$/, message: '电话请填写 11 位手机号', trigger: 'blur' }],
    email: [{ type: 'email', message: '邮箱格式不正确', trigger: ['blur', 'change'] }]
  }
})

// 只收图片且不超过 2MB。上传组件自己发请求，所以校验放在上传之前拦
const beforeUpload = (file) => {
  if (!file.type.startsWith('image/')) {
    ElMessage.error('头像只能是图片文件')
    return false
  }
  if (file.size / 1024 / 1024 > 2) {
    ElMessage.error('头像大小不能超过 2MB')
    return false
  }
  return true
}

const handleUploadSuccess = (res) => {
  // 上传接口返回的 data 是文件下载地址，写进表单后页面立刻显示新头像，
  // 点保存才真正写进数据库
  if (res.code !== '200') {
    ElMessage.error(res.msg)
    return
  }
  data.user.avatar = res.data
  ElMessage.success('头像已上传，点保存后生效')
}

const handleUploadError = () => {
  ElMessage.error('头像上传失败，请稍后重试')
}

// 保存成功后要通知外层布局刷新右上角的头像和姓名，
// 外层 Front.vue 在 RouterView 上监听了这个事件
const emit = defineEmits(['updateUser'])

const update = () => {
  formRef.value.validate(valid => {
    if (!valid) {
      return
    }
    // user 里带着 id，后端按 id 更新这条账号；账号和密码不在这里改
    request.put('/user/update', data.user).then(res => {
      if (res.code === '200') {
        ElMessage.success('保存成功')
        // 数据库改完了本地缓存也要同步，否则刷新页面又变回旧值
        localStorage.setItem('xm-user', JSON.stringify(data.user))
        emit('updateUser')
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}
</script>

<style scoped>
.page-wrap > .page-head { margin-bottom: 0; }
.page-wrap > .card { margin-top: 0; }

.narrow-head,
.person-card {
  width: 100%;
  max-width: 640px;
  margin-left: auto;
  margin-right: auto;
}

.person-card {
  padding: 26px 32px 30px;
}

/* 头像单独占一行居中，下面的字段沿用左标签右输入的对齐方式 */
.avatar-item {
  display: flex;
  justify-content: center;
  margin-bottom: 6px;
}
.avatar-item :deep(.el-form-item__label) { display: none; }
.avatar-item :deep(.el-form-item__content) {
  margin-left: 0 !important;
  justify-content: center;
}

.avatar-uploader :deep(.el-upload) {
  border: 1px dashed var(--pb-line-strong);
  border-radius: 50%;
  padding: 5px;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.avatar-uploader :deep(.el-upload:hover) {
  border-color: var(--pb-brand);
  box-shadow: 0 0 0 5px var(--pb-brand-soft);
}

.avatar-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.avatar-tip {
  font-size: 12px;
  color: var(--pb-muted);
}

.form-actions {
  display: flex;
  justify-content: center;
  margin-top: 10px;
  padding-top: 18px;
  border-top: 1px solid var(--pb-line);
}

.submit-btn {
  min-width: 160px;
}

@media (max-width: 640px) {
  .person-card { padding: 20px 16px 22px; }
  .submit-btn { width: 100%; }
}
</style>
