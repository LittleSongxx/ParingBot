<template>
  <div class="manager-shell">
    <header class="manager-topbar">
      <div class="manager-brand" @click="router.push('/manager/home')">
        <img class="brand-mark" src="@/assets/imgs/logo-bot.svg" alt="ParingBot" />
        <div class="brand-text">
          <span class="brand-name">ParingBot</span>
          <span class="brand-sub">智能合租匹配平台 · 管理端</span>
        </div>
      </div>
      <div class="manager-topbar-center">
        <el-breadcrumb separator="/">
          <el-breadcrumb-item :to="{ path: '/manager/home' }">首页</el-breadcrumb-item>
          <el-breadcrumb-item>{{ router.currentRoute.value.meta.name }}</el-breadcrumb-item>
        </el-breadcrumb>
      </div>
      <div class="topbar-right">
        <span class="env-chip"><i class="status-dot"></i> Admin Console</span>
        <el-dropdown trigger="click" style="cursor: pointer">
          <div class="user-chip">
            <NameAvatar :name="data.user.name" :src="data.user.avatar" :size="28" />
            <span class="user-name">{{ data.user.name }}</span>
            <el-icon class="chev"><arrow-down /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="router.push('/manager/person')">个人资料</el-dropdown-item>
              <el-dropdown-item @click="router.push('/manager/password')">修改密码</el-dropdown-item>
              <el-dropdown-item divided @click="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <div class="manager-body">
      <aside class="manager-sidebar">
        <el-menu class="sidebar-menu"
                 :default-active="router.currentRoute.value.path"
                 :default-openeds="['system', 'member', 'ai', 'agent']"
                 router>
          <el-menu-item index="/manager/home">
            <el-icon><HomeFilled /></el-icon>
            <span>系统首页</span>
          </el-menu-item>
          <template v-if="data.user.role === 'ADMIN'">
            <el-sub-menu index="system">
              <template #title>
                <el-icon><Setting /></el-icon>
                <span>系统管理</span>
              </template>
              <el-menu-item index="/manager/user">
                <el-icon><User /></el-icon>
                <span>用户管理</span>
              </el-menu-item>
              <el-menu-item index="/manager/sysConfig">
                <el-icon><Tools /></el-icon>
                <span>系统参数</span>
              </el-menu-item>
            </el-sub-menu>
            <el-sub-menu index="member">
              <template #title>
                <el-icon><Collection /></el-icon>
                <span>租客与资源</span>
              </template>
              <el-menu-item index="/manager/member">
                <el-icon><Avatar /></el-icon>
                <span>租客管理</span>
              </el-menu-item>
              <el-menu-item index="/manager/interestTag">
                <el-icon><PriceTag /></el-icon>
                <span>兴趣标签</span>
              </el-menu-item>
            </el-sub-menu>
            <el-sub-menu index="ai">
              <template #title>
                <el-icon><MagicStick /></el-icon>
                <span>AI 能力配置</span>
              </template>
              <el-menu-item index="/manager/modelConfig">
                <el-icon><Cpu /></el-icon>
                <span>AI模型配置</span>
              </el-menu-item>
              <el-menu-item index="/manager/prompt">
                <el-icon><EditPen /></el-icon>
                <span>Prompt模板</span>
              </el-menu-item>
            </el-sub-menu>
            <el-sub-menu index="agent">
              <template #title>
                <el-icon><Connection /></el-icon>
                <span>Agent 工具中心</span>
              </template>
              <el-menu-item index="/manager/agentDefinition">
                <el-icon><User /></el-icon>
                <span>子 Agent 定义</span>
              </el-menu-item>
              <el-menu-item index="/manager/functionTool">
                <el-icon><Tools /></el-icon>
                <span>工具中心</span>
              </el-menu-item>
              <el-menu-item index="/manager/toolCallLog">
                <el-icon><List /></el-icon>
                <span>工具调用日志</span>
              </el-menu-item>
              <el-menu-item index="/manager/matchTrace">
                <el-icon><DataLine /></el-icon>
                <span>调度时间线</span>
              </el-menu-item>
            </el-sub-menu>
          </template>
        </el-menu>
        <div class="sidebar-foot">
          <b>ParingBot</b> · 多 Agent 合租匹配<br />
          模型只做判断 · 代码守边界 · 数据库是事实源
        </div>
      </aside>

      <main class="manager-content">
        <RouterView @updateUser="updateUser" />
      </main>
    </div>
  </div>
</template>

<script setup>
import { reactive } from "vue";
import router from "@/router/index.js";
import { ElMessage } from "element-plus";
import NameAvatar from "@/components/NameAvatar.vue";

const data = reactive({
  user: JSON.parse(localStorage.getItem('xm-user') || '{}')
})

const logout = () => {
  localStorage.removeItem('xm-user')
  router.push('/login')
}

const updateUser = () => {
  data.user = JSON.parse(localStorage.getItem('xm-user') || '{}')
}

if (!data.user.id) {
  logout()
  ElMessage.error('请登录！')
}
</script>
