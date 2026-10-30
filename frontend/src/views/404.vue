<template>
  <div class="auth-shell">
    <div class="auth-orbs">
      <div class="auth-orb auth-orb-a"></div>
      <div class="auth-orb auth-orb-b"></div>
    </div>
    <section class="auth-card auth-single" style="text-align: center">
      <img src="@/assets/imgs/logo-bot.svg" alt="ParingBot" style="width: 56px; height: 56px; border-radius: 16px" />
      <h1 class="auth-title" style="margin-top: 18px">404</h1>
      <p class="auth-sub" style="margin-bottom: 22px">这个页面不存在，可能已经被移动或删除了。</p>
      <el-button type="primary" size="large" class="auth-submit" @click="router.push('/')">回到首页</el-button>
    </section>
  </div>
</template>

<script setup>
import router from "@/router/index.js";
</script>
