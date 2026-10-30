<template>
  <div class="main-content page-wrap">
    <div class="page-head narrow-head">
      <div class="page-head-main">
        <h2>修改密码</h2>
        <p class="page-tip">定期更换密码，可以更好地保护账号与你填写的档案信息。</p>
      </div>
    </div>

    <div class="card narrow-card">
      <div class="block-title">账号安全</div>
      <el-alert class="password-tip" type="info" :closable="false" show-icon
                title="保存成功后当前登录会退出，需要用新密码重新登录。"></el-alert>
      <el-form ref="formRef" :rules="data.rules" :model="data.form" label-width="88px">
        <el-form-item label="原密码" prop="password">
          <el-input v-model="data.form.password" placeholder="请输入原密码" show-password></el-input>
        </el-form-item>
        <el-form-item label="新密码" prop="newPassword">
          <el-input v-model="data.form.newPassword" :placeholder="newPasswordPlaceholder" show-password></el-input>
        </el-form-item>
        <el-form-item label="确认密码" prop="confirmPassword">
          <el-input v-model="data.form.confirmPassword" placeholder="请再输入一次新密码" show-password
                    @keyup.enter="updatePassword"></el-input>
        </el-form-item>
        <div class="form-actions">
          <el-button type="primary" size="large" :loading="data.loading" class="submit-btn"
                     @click="updatePassword">保 存</el-button>
        </div>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from "vue";
import request from "@/utils/request.js";
import { ElMessage } from "element-plus";
import router from "@/router/index.js";

const formRef = ref()

// 新密码的长度范围和后端保持一致：页面先拦一道，提交上去的一定符合规则
const PASSWORD_MIN_LENGTH = 6
const PASSWORD_MAX_LENGTH = 30
const newPasswordPlaceholder = `请输入 ${PASSWORD_MIN_LENGTH}-${PASSWORD_MAX_LENGTH} 位新密码`

// 确认密码要和上面填的新密码一模一样。两次输入只隔一个输入框，
// 拦下来当场重填，比提交后由后端报「两次输入的密码不一致」省事
const validateConfirm = (rule, value, callback) => {
  if (value !== data.form.newPassword) {
    callback(new Error('两次输入的新密码不一致'))
    return
  }
  callback()
}

const data = reactive({
  // 只提交这三个字段。改的是哪个账号由请求头里的 token 决定，前端不传 id
  form: { password: '', newPassword: '', confirmPassword: '' },
  rules: {
    password: [
      { required: true, message: '请输入原密码', trigger: 'blur' }
    ],
    newPassword: [
      { required: true, message: '请输入新密码', trigger: 'blur' },
      {
        min: PASSWORD_MIN_LENGTH, max: PASSWORD_MAX_LENGTH,
        message: `新密码长度需要在 ${PASSWORD_MIN_LENGTH} 到 ${PASSWORD_MAX_LENGTH} 个字符之间`,
        trigger: 'blur'
      }
    ],
    confirmPassword: [
      { required: true, message: '请再输入一次新密码', trigger: 'blur' },
      { validator: validateConfirm, trigger: 'blur' }
    ]
  },
  // 请求期间把按钮置灰，防止连点提交
  loading: false
})

const updatePassword = () => {
  formRef.value.validate(valid => {
    if (!valid) {
      return
    }
    // 新旧密码一样等于没改，后端也会拦，这里先提示一句，省一次请求
    if (data.form.newPassword === data.form.password) {
      ElMessage.error('新密码不能与原密码相同')
      return
    }
    data.loading = true
    request.put('/updatePassword', data.form).then(res => {
      if (res.code === '200') {
        // 密码换了，旧密码签发的登录态跟着作废：清掉缓存回登录页，用新密码重新进
        ElMessage.success('密码已修改，请用新密码重新登录')
        localStorage.removeItem('xm-user')
        router.push('/login')
      } else {
        ElMessage.error(res.msg)
      }
    }).finally(() => {
      data.loading = false
    })
  })
}
</script>

<style scoped>
/* 页头与卡片收在同一个窄列里，居中排版 */
.page-wrap > .page-head { margin-bottom: 0; }
.page-wrap > .card { margin-top: 0; }

.narrow-head,
.narrow-card {
  width: 100%;
  max-width: 560px;
  margin-left: auto;
  margin-right: auto;
}

.narrow-card {
  padding: 22px 28px 26px;
}

.password-tip {
  margin: 2px 0 20px;
}

.form-actions {
  display: flex;
  justify-content: center;
  padding-top: 6px;
}

.submit-btn {
  min-width: 180px;
}

@media (max-width: 640px) {
  .narrow-card { padding: 18px 16px 20px; }
  .submit-btn { width: 100%; }
}
</style>
