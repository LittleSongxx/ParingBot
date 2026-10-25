<template>
  <div class="login-container">
    <div class="login-box">
      <div class="login-title">注册账号</div>
      <div class="login-subtitle">注册后登录，就能完善档案、发起匹配</div>
      <el-form ref="formRef" :model="data.form" :rules="data.rules">
        <el-form-item prop="username">
          <el-input :prefix-icon="User" size="large" v-model="data.form.username" placeholder="请输入账号"></el-input>
        </el-form-item>
        <el-form-item prop="password">
          <el-input show-password :prefix-icon="Lock" size="large" v-model="data.form.password" placeholder="请输入密码"></el-input>
        </el-form-item>
        <el-form-item prop="confirmPassword">
          <el-input show-password :prefix-icon="Lock" size="large" v-model="data.form.confirmPassword"
                    placeholder="请再次输入密码" @keyup.enter="register"></el-input>
        </el-form-item>
        <el-form-item>
          <el-button size="large" type="primary" style="width: 100%" :loading="data.loading" @click="register">注 册</el-button>
        </el-form-item>
        <div style="text-align: right">
          已有账号？请 <router-link to="/login">登录</router-link>
        </div>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from "vue";
import { User, Lock } from "@element-plus/icons-vue";
import request from "@/utils/request.js";
import { ElMessage } from "element-plus";
import router from "@/router/index.js";

// 两次密码是否一致要在页面上先拦一道，用户不用等到提交才知道填错了
const validateConfirmPassword = (rule, value, callback) => {
  if (!value) {
    callback(new Error('请再次输入密码'))
  } else if (value !== data.form.password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

const data = reactive({
  form: {},
  // 长度规则和后端的校验保持一致，改的时候两边一起改
  rules: {
    username: [
      { required: true, message: '请输入账号', trigger: 'blur' },
      { min: 3, max: 30, message: '账号长度需要在 3 到 30 个字符之间', trigger: 'blur' }
    ],
    password: [
      { required: true, message: '请输入密码', trigger: 'blur' },
      { min: 6, max: 30, message: '密码长度需要在 6 到 30 个字符之间', trigger: 'blur' }
    ],
    confirmPassword: [
      { validator: validateConfirmPassword, trigger: 'blur' }
    ]
  },
  loading: false
})

const formRef = ref()

const register = () => {
  formRef.value.validate(valid => {
    if (!valid) return
    data.loading = true
    request.post('/register', data.form).then(res => {
      if (res.code === '200') {
        // 注册成功不停留在本页，直接引导到登录页去登录
        ElMessage.success('注册成功，请登录')
        router.push('/login')
      } else {
        // 账号已存在、两次密码不一致这些业务失败，后端在 msg 里返回人话提示
        ElMessage.error(res.msg)
      }
    }).finally(() => {
      data.loading = false
    })
  })
}
</script>

<style scoped>
.login-container {
  height: 100vh;
  overflow: hidden;
  display: flex;
  justify-content: center;
  align-items: center;
  background: linear-gradient(135deg, #F5FAF9 0%, #DCEBEA 45%, #C0DCDA 100%);
  --el-color-primary: #1F6F6B;
  --el-color-primary-light-3: #4F8F8A;
  --el-color-primary-light-5: #84B5B2;
  --el-color-primary-light-7: #A9CFCB;
  --el-color-primary-light-8: #C4DCDA;
  --el-color-primary-light-9: #EFF6F5;
  --el-color-primary-dark-2: #24625E;
}
.login-box {
  width: 380px;
  padding: 36px 30px 24px;
  border-radius: 12px;
  box-shadow: 0 12px 32px rgba(31, 111, 107, 0.18);
  background-color: #fff;
}
.login-title {
  font-size: 24px;
  font-weight: bold;
  text-align: center;
  color: #1F6F6B;
}
.login-subtitle {
  margin: 10px 0 26px;
  font-size: 13px;
  color: #8a8a8a;
  text-align: center;
}

/* 页面里的跳转链接跟着主题色走，不用浏览器默认的蓝色 */
.login-box a {
  color: #1F6F6B;
}
.login-box a:hover {
  color: #2A7F7A;
}
</style>
