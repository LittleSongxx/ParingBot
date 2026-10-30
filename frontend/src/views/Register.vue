<template>
  <div class="auth-shell">
    <div class="auth-orbs">
      <div class="auth-orb auth-orb-a"></div>
      <div class="auth-orb auth-orb-b"></div>
    </div>

    <section class="auth-card auth-single">
      <div class="auth-brand">
        <img class="brand-mark" src="@/assets/imgs/logo-bot.svg" alt="ParingBot" />
        <div class="brand-text">
          <span class="brand-name">ParingBot</span>
          <span class="brand-sub">智能合租匹配平台</span>
        </div>
      </div>

      <h1 class="auth-title">创建账号</h1>
      <p class="auth-sub">注册后登录，就能完善档案、填写偏好并发起智能匹配。</p>

      <el-form ref="formRef" :model="data.form" :rules="data.rules">
        <el-form-item prop="username">
          <el-input :prefix-icon="User" size="large" v-model="data.form.username" placeholder="请输入账号" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input show-password :prefix-icon="Lock" size="large" v-model="data.form.password" placeholder="请输入密码" />
        </el-form-item>
        <el-form-item prop="confirmPassword">
          <el-input show-password :prefix-icon="Lock" size="large" v-model="data.form.confirmPassword"
                    placeholder="请再次输入密码" @keyup.enter="register" />
        </el-form-item>
        <el-form-item>
          <el-button size="large" type="primary" class="auth-submit" :loading="data.loading" @click="register">注 册</el-button>
        </el-form-item>
      </el-form>

      <div class="auth-foot">已有账号？<router-link to="/login">返回登录</router-link></div>
    </section>
  </div>
</template>

<script setup>
import { reactive, ref } from "vue";
import { User, Lock } from "@element-plus/icons-vue";
import request from "@/utils/request.js";
import { ElMessage } from "element-plus";
import router from "@/router/index.js";

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
  rules: {
    username: [
      { required: true, message: '请输入账号', trigger: 'blur' },
      { min: 3, max: 30, message: '账号长度需要在 3 到 30 个字符之间', trigger: 'blur' }
    ],
    password: [
      { required: true, message: '请输入密码', trigger: 'blur' },
      { min: 6, max: 30, message: '密码长度需要在 6 到 30 个字符之间', trigger: 'blur' }
    ],
    confirmPassword: [{ validator: validateConfirmPassword, trigger: 'blur' }]
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
        ElMessage.success('注册成功，请登录')
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
