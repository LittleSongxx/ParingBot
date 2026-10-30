<template>
  <div class="front-shell">
    <header class="front-topbar">
      <div class="front-inner">
        <div class="front-brand" @click="router.push('/front/home')">
          <img class="brand-mark" src="@/assets/imgs/logo-bot.svg" alt="ParingBot" />
          <div class="brand-text">
            <span class="brand-name">ParingBot</span>
            <span class="brand-sub">智能合租匹配</span>
          </div>
        </div>
        <nav class="front-nav">
          <el-menu :default-active="router.currentRoute.value.path" router mode="horizontal">
            <el-menu-item index="/front/home">首页</el-menu-item>
            <el-menu-item index="/front/memberProfile">租客档案</el-menu-item>
            <el-menu-item index="/front/myPreference">合住偏好</el-menu-item>
            <el-menu-item index="/front/myMoment">我的动态</el-menu-item>
            <el-menu-item index="/front/myMatch">智能匹配</el-menu-item>
            <el-menu-item index="/front/myPortrait">画像结果</el-menu-item>
            <el-menu-item index="/front/myCandidate">候选结果</el-menu-item>
            <el-menu-item index="/front/myAudit">审核结果</el-menu-item>
          </el-menu>
        </nav>
        <div class="front-actions">
          <div v-if="!data.user.id" style="display: flex; gap: 8px">
            <el-button @click="router.push('/login')">登录</el-button>
            <el-button type="primary" @click="router.push('/register')">注册</el-button>
          </div>
          <el-dropdown v-else trigger="click" style="cursor: pointer">
            <div class="front-user-chip">
              <NameAvatar :name="data.user.name" :src="data.user.avatar" :size="28" />
              <span class="user-name">{{ data.user.name }}</span>
              <el-icon style="color: var(--pb-faint); font-size: 12px"><arrow-down /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="router.push('/front/person')">个人中心</el-dropdown-item>
                <el-dropdown-item @click="router.push('/front/password')">修改密码</el-dropdown-item>
                <el-dropdown-item divided @click="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
    </header>

    <main class="front-main">
      <RouterView @updateUser="updateUser" />
    </main>
    <Footer />
  </div>
</template>

<script setup>
import router from "@/router/index.js";
import { reactive } from "vue";
import NameAvatar from "@/components/NameAvatar.vue";
import Footer from "@/components/Footer.vue";

const data = reactive({
  user: JSON.parse(localStorage.getItem('xm-user') || '{}'),
})

const logout = () => {
  localStorage.removeItem('xm-user')
  router.push('/login')
}

const updateUser = () => {
  data.user = JSON.parse(localStorage.getItem('xm-user') || '{}')
}
</script>
