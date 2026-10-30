<template>
  <div class="page-wrap">
    <div class="page-head">
      <h2>个人资料</h2>
      <p class="page-tip">维护当前登录账号的头像、姓名与联系方式，保存后右上角的个人信息会同步更新。</p>
    </div>

    <div class="card narrow-card">
      <div class="block-title">基本信息</div>
      <el-form ref="formRef" :rules="data.rules" :model="data.user" label-width="70px" class="narrow-form">
        <el-form-item prop="avatar" label="头像">
          <div class="avatar-wrap">
            <el-upload
                :action="baseUrl + '/files/upload'"
                :headers="uploadHeaders"
                :before-upload="beforeUpload"
                :on-success="handleUploadSuccess"
                :on-error="handleUploadError"
                :show-file-list="false"
                class="avatar-uploader"
            >
              <NameAvatar :name="data.user.name" :src="data.user.avatar" :size="120" />
            </el-upload>
            <div class="form-tip">点击头像上传新图片，支持 jpg / png，大小不超过 2MB，保存后生效。</div>
          </div>
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
          <el-button type="primary" @click="update">保 存</el-button>
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
  // 登录时把账号信息写进了浏览器缓存，这里直接拿来当表单初始值
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
// 外层 Manager.vue 在 RouterView 上监听了这个事件
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
/* 个人资料：居中窄卡片，头像与表单同一列对齐 */
.narrow-card {
  width: 100%;
  max-width: 620px;
  margin: 0 auto;
}

.narrow-form {
  padding: 4px 4px 0;
}

.narrow-form :deep(.el-form-item) {
  margin-bottom: 20px;
}

.avatar-wrap {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.avatar-uploader :deep(.el-upload) {
  display: block;
  padding: 6px;
  border: 1px dashed var(--pb-line-strong);
  border-radius: 18px;
  background: var(--pb-surface-2);
  cursor: pointer;
  transition: border-color 0.18s ease, background 0.18s ease, box-shadow 0.18s ease;
}

.avatar-uploader :deep(.el-upload):hover {
  border-color: var(--pb-brand);
  background: var(--pb-brand-soft);
  box-shadow: var(--pb-glow);
}

.avatar-wrap .form-tip {
  margin-top: 0;
}

.form-actions {
  display: flex;
  justify-content: center;
  gap: 10px;
  margin-top: 6px;
}
</style>
