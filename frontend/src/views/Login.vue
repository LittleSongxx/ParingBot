<template>
  <div class="login-container">
    <div class="login-box">
      <div class="login-title">ParingBot 智能合租匹配平台</div>
      <div class="login-subtitle">由多个 Agent 智能体分工协作，为你匹配生活习惯合拍的室友</div>
      <el-form ref="formRef" :model="data.form" :rules="data.rules">
        <el-form-item prop="username">
          <el-input :prefix-icon="User" size="large" v-model="data.form.username" placeholder="请输入账号"></el-input>
        </el-form-item>
        <el-form-item prop="password">
          <el-input show-password :prefix-icon="Lock" size="large" v-model="data.form.password"
                    placeholder="请输入密码" @keyup.enter="login"></el-input>
        </el-form-item>
        <el-form-item>
          <el-button size="large" type="primary" style="width: 100%" :loading="data.loading" @click="login">登 录</el-button>
        </el-form-item>
        <div style="text-align: right">
          还没有账号？请 <router-link to="/register">注册</router-link>
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

const data = reactive({
  form: {},
  rules: {
    username: [
      { required: true, message: '请输入账号', trigger: 'blur' }
    ],
    password: [
      { required: true, message: '请输入密码', trigger: 'blur' }
    ]
  },
  // 请求期间把按钮置灰，防止连点提交产生两条登录请求
  loading: false
})

const formRef = ref()

const login = () => {
  formRef.value.validate(valid => {
    // 表单校验没过就不用发请求了
    if (!valid) return
    data.loading = true
    request.post('/login', data.form).then(res => {
      if (res.code === '200') {
        ElMessage.success('登录成功')
        // res.data 里带着后端签发的 token 和账号信息，存进浏览器缓存后，
        // request.js 的请求拦截器每次都会把 token 放进请求头
        localStorage.setItem('xm-user', JSON.stringify(res.data))
        // 管理员进管理端、租客进用户端，各自落在自己用得上的页面上。
        // 具体进哪个页面由 user.role 决定，同一个登录入口服务两类账号
        const target = res.data.role === 'ADMIN' ? '/manager/home' : '/front/home'
        router.push(target)
      } else {
        // 账号密码错误、账号被停用这些业务失败，后端在 msg 里返回人话提示
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
