<template>
  <div class="auth-shell">
    <div class="auth-orbs">
      <div class="auth-orb auth-orb-a"></div>
      <div class="auth-orb auth-orb-b"></div>
    </div>

    <div class="auth-grid">
      <section class="auth-card">
        <div class="auth-brand">
          <img class="brand-mark" src="@/assets/imgs/logo-bot.svg" alt="ParingBot" />
          <div class="brand-text">
            <span class="brand-name">ParingBot</span>
            <span class="brand-sub">智能合租匹配平台</span>
          </div>
        </div>

        <h1 class="auth-title">欢迎回来</h1>
        <p class="auth-sub">登录后开始一次由多个 Agent 协作的合租匹配。</p>

        <el-form ref="formRef" :model="data.form" :rules="data.rules">
          <el-form-item prop="username">
            <el-input :prefix-icon="User" size="large" v-model="data.form.username" placeholder="请输入账号" />
          </el-form-item>
          <el-form-item prop="password">
            <el-input show-password :prefix-icon="Lock" size="large" v-model="data.form.password"
                      placeholder="请输入密码" @keyup.enter="login" />
          </el-form-item>
          <el-form-item>
            <el-button size="large" type="primary" class="auth-submit" :loading="data.loading" @click="login">
              登 录
            </el-button>
          </el-form-item>
        </el-form>

        <div class="auth-demo">
          <span class="auth-demo-title">演示账号 · 点击填入</span>
          <div class="auth-demo-row">
            <button class="demo-chip" type="button" @click="fill('admin', 'admin')">
              <span class="demo-dot admin"></span>管理员 admin / admin
            </button>
            <button class="demo-chip" type="button" @click="fill('member01', '123456')">
              <span class="demo-dot user"></span>租客 member01 / 123456
            </button>
          </div>
        </div>

        <div class="auth-foot">还没有账号？<router-link to="/register">立即注册</router-link></div>
      </section>

      <aside class="auth-hero">
        <span class="hero-eyebrow"><i class="status-dot"></i> Multi-Agent Matching</span>
        <h2>把找室友，<br />交给三个专职 Agent</h2>
        <p class="hero-sub">
          合租管家每一轮看一遍库里的真实进展，决定派画像师、筛选官还是审核官；
          候选不够就放宽「加分」项，画像不够就补一版，通过审核的人数够了就收尾交付。
        </p>
        <ul class="hero-list">
          <li>
            <span class="hero-num">01</span>
            <div><b>主管调度</b><p>每一轮都基于数据库对账结论决定下一步，而不是模型自报</p></div>
          </li>
          <li>
            <span class="hero-num">02</span>
            <div><b>画像与筛选</b><p>标签必须有原文依据；候选只找同性、只写档案已审核通过的人</p></div>
          </li>
          <li>
            <span class="hero-num">03</span>
            <div><b>双向审核</b><p>代码复核会翻案：违反候选方必须项或同性规则，当场改判否决</p></div>
          </li>
        </ul>
        <div class="hero-foot">模型只做判断 · 代码守边界 · 每一步可复盘</div>
      </aside>
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
    username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
    password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
  },
  loading: false
})

const formRef = ref()

const fill = (username, password) => {
  data.form.username = username
  data.form.password = password
  formRef.value?.clearValidate()
}

const login = () => {
  formRef.value.validate(valid => {
    if (!valid) return
    data.loading = true
    request.post('/login', data.form).then(res => {
      if (res.code === '200') {
        ElMessage.success('登录成功')
        localStorage.setItem('xm-user', JSON.stringify(res.data))
        const target = res.data.role === 'ADMIN' ? '/manager/home' : '/front/home'
        router.push(target)
      } else {
        ElMessage.error(res.msg)
      }
    }).finally(() => {
      data.loading = false
    })
  })
}
</script>
