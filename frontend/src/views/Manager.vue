<template>
  <div class="manager-container">
    <div class="manager-header">
      <div class="manager-header-left">
        <img src="@/assets/imgs/logo.png" alt="">
        <div class="title">长租公寓智能合租匹配平台</div>
      </div>
      <div class="manager-header-center">
        <el-breadcrumb separator="/">
          <el-breadcrumb-item :to="{ path: '/manager/home' }">首页</el-breadcrumb-item>
          <el-breadcrumb-item>{{ router.currentRoute.value.meta.name }}</el-breadcrumb-item>
        </el-breadcrumb>
      </div>
      <div class="manager-header-right">
        <el-dropdown style="cursor: pointer">
          <div style="padding-right: 20px; display: flex; align-items: center">
            <NameAvatar :name="data.user.name" :src="data.user.avatar" :size="40" />
            <span style="margin-left: 5px; color: white">{{ data.user.name }}</span><el-icon color="#fff"><arrow-down /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="router.push('/manager/person')">个人资料</el-dropdown-item>
              <el-dropdown-item @click="router.push('/manager/password')">修改密码</el-dropdown-item>
              <el-dropdown-item @click="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>
    <!-- 下面部分开始 -->
    <div style="display: flex">
      <div class="manager-main-left">
        <el-menu :default-active="router.currentRoute.value.path"
                 :default-openeds="['system', 'member', 'ai', 'agent']"
                 router
        >
          <el-menu-item index="/manager/home">
            <el-icon><HomeFilled /></el-icon>
            <span>系统首页</span>
          </el-menu-item>
          <!-- 管理端功能按业务域分组：顶层只留首页，功能页挂在分组下面 -->
          <template v-if="data.user.role === 'ADMIN'">
            <!-- 系统管理：账号与运行参数，属于平台级配置 -->
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
            <!-- 租客与资源：租客档案和兴趣标签词表挂在这一组，它们是 Agent 读取的原始材料 -->
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
            <!-- AI 能力配置：模型接入和提示词都属于 AI 链路的基础配置 -->
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
            <!-- Agent 工具中心：四个角色的分工、它们手上的工具，以及每次工具调用的记录 -->
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
              <!-- 过程回放：一次运行从第一轮调度到收尾的每一步、以及候选从筛出到交付的漏斗 -->
              <el-menu-item index="/manager/matchTrace">
                <el-icon><DataLine /></el-icon>
                <span>调度时间线</span>
              </el-menu-item>
            </el-sub-menu>
          </template>
        </el-menu>
      </div>
      <div class="manager-main-right">
        <RouterView @updateUser="updateUser" />
      </div>
    </div>
    <!-- 下面部分结束 -->


  </div>
</template>

<script setup>
import { reactive } from "vue";
import router from "@/router/index.js";
import {ElMessage} from "element-plus";
import NameAvatar from "@/components/NameAvatar.vue";

const data = reactive({
  user: JSON.parse(localStorage.getItem('xm-user') || '{}')
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

if (!data.user.id) {
  logout()
  ElMessage.error('请登录！')
}
</script>

<style scoped>
@import "@/assets/css/manager.css";
</style>
