<template>
  <div>
    <div class="front-header">
      <div class="front-header-left">
        <img src="@/assets/imgs/logo.png" alt="">
        <div class="title" @click="router.push('/front/home')">ParingBot 智能合租匹配平台</div>
      </div>
      <div class="front-header-center">
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
      </div>
      <div class="front-header-right">
        <div v-if="!data.user.id">
          <el-button @click="router.push('/login')">登录</el-button>
          <el-button @click="router.push('/register')">注册</el-button>
        </div>
        <div v-else>
          <el-dropdown style="cursor: pointer; height: 60px">
            <div style="display: flex; align-items: center">
              <NameAvatar :name="data.user.name" :src="data.user.avatar" :size="40" />
              <span style="margin-left: 5px;">{{ data.user.name }}</span><el-icon><arrow-down /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                  <el-dropdown-item @click="router.push('/front/person')">个人中心</el-dropdown-item>
                <el-dropdown-item @click="router.push('/front/password')">修改密码</el-dropdown-item>
                <el-dropdown-item @click="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
    </div>
    <div class="main-body">
      <RouterView @updateUser="updateUser" />
    </div>
    <Footer />
  </div>
</template>

<script setup>
  import router from "@/router/index.js";
  import { reactive } from "vue";
  import NameAvatar from "@/components/NameAvatar.vue";

  const data = reactive({
    user: JSON.parse(localStorage.getItem('xm-user') || '{}'),
  })

  // 登录态就是浏览器缓存里的那份账号信息，服务端不保存会话，
  // 所以退出登录清掉缓存回登录页就够了，不需要再调一次后端
  const logout = () => {
    localStorage.removeItem('xm-user')
    router.push('/login')
  }

  const updateUser = () => {
    data.user =  JSON.parse(localStorage.getItem('xm-user') || '{}')
  }
</script>

<style scoped>
@import "@/assets/css/front.css";
</style>
