<template>
  <div class="home-page">
    <!-- 页头：一句话说清管理端的功能是怎么组织的 -->
    <div class="page-head">
      <h2>系统首页</h2>
      <p class="page-tip">
        ParingBot 智能合租匹配平台管理端。平台配置、租客资源、AI 能力配置与 Agent 工具中心按业务域收在左侧的功能分组里，
        常用页面也可以从下面的快捷入口直接进。
      </p>
    </div>

    <!-- 快捷入口：平台管理员常用的配置页与观测页，点一下直接进对应页面 -->
    <div class="card block" v-if="data.isAdmin">
      <div class="block-title">快捷入口</div>
      <div class="quick-grid">
        <div class="quick-item" v-for="item in shortcuts" :key="item.path" @click="router.push(item.path)">
          <div class="quick-icon">
            <el-icon><component :is="item.icon" /></el-icon>
          </div>
          <div class="quick-text">
            <div class="quick-name">{{ item.name }}</div>
            <div class="quick-desc">{{ item.desc }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 配置与使用顺序：纯说明文本，让刚接手的管理员知道下一步该去哪一页 -->
    <div class="card block">
      <div class="block-title">后台配置与使用顺序</div>
      <div class="flow-list">
        <div class="flow-item" v-for="(item, index) in flow" :key="item.title">
          <div class="flow-index">{{ index + 1 }}</div>
          <div class="flow-text">
            <div class="flow-title">{{ item.title }}</div>
            <div class="flow-desc">{{ item.desc }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive } from "vue";
import router from "@/router/index.js";
import {
  Avatar, PriceTag, Cpu, EditPen, User, Tools, List, DataLine
} from "@element-plus/icons-vue";

// 快捷入口，路径和左侧菜单里的页面一一对应
const shortcuts = [
  { name: "租客管理", desc: "租客档案、生活照与启用状态", path: "/manager/member", icon: Avatar },
  { name: "兴趣标签", desc: "画像与筛选共用的标签词表", path: "/manager/interestTag", icon: PriceTag },
  { name: "AI模型配置", desc: "各用途的模型、密钥与参数", path: "/manager/modelConfig", icon: Cpu },
  { name: "Prompt模板", desc: "四个 Agent 角色的提示词", path: "/manager/prompt", icon: EditPen },
  { name: "子 Agent 定义", desc: "四个角色的启停、提示词与工具分组", path: "/manager/agentDefinition", icon: User },
  { name: "工具中心", desc: "Agent 能调的工具与试跑", path: "/manager/functionTool", icon: Tools },
  { name: "工具调用日志", desc: "每一次工具调用的入参与返回", path: "/manager/toolCallLog", icon: List },
  { name: "调度时间线", desc: "一次匹配每一轮派了谁、候选漏斗", path: "/manager/matchTrace", icon: DataLine },
];

// 后台从上到下要准备的几件事，按顺序列出来
const flow = [
  { title: "接入模型", desc: "到 AI 模型配置里，为调度、画像、筛选、审核四个用途各启用一条配置，填好接口地址和 API Key。" },
  { title: "维护提示词", desc: "到 Prompt 模板里维护四个 Agent 角色的提示词，角色按编码取用。" },
  { title: "定角色与工具", desc: "子 Agent 定义里确认四个角色的启停和工具分组，工具中心里维护每个工具。" },
  { title: "审核租客档案", desc: "租客管理里审核租客提交的档案，审核通过的租客才会被筛选官检索到。" },
  { title: "看调度过程", desc: "租客发起匹配后到调度时间线看主管每一轮派了谁、候选走到哪一步，到工具调用日志看每一次调用。" },
];

const user = JSON.parse(localStorage.getItem('xm-user') || '{}')

const data = reactive({
  // 业务分组只对平台管理员开放，租客账号进管理端只有首页
  isAdmin: user.role === 'ADMIN',
})
</script>

<style scoped>
.home-page {
  padding-bottom: 10px;
}

.block {
  margin-top: 12px;
}

/* 卡片标题统一加粗，不加任何装饰线条 */
.block-title {
  margin-bottom: 14px;
  font-size: 16px;
  font-weight: bold;
  line-height: 20px;
  color: #333;
}

.quick-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.quick-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border: 1px solid #DFECEB;
  border-radius: 8px;
  background-color: #fff;
  cursor: pointer;
  transition: all .2s;
}
.quick-item:hover {
  border-color: #1F6F6B;
  box-shadow: 0 8px 16px rgba(31, 111, 107, .14);
  transform: translateY(-2px);
}
.quick-icon {
  flex: none;
  width: 38px;
  height: 38px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  color: #1F6F6B;
  background-color: rgba(31, 111, 107, .1);
}
.quick-text {
  min-width: 0;
}
.quick-name {
  font-size: 14px;
  font-weight: 500;
  color: #333;
}
.quick-desc {
  margin-top: 2px;
  font-size: 12px;
  color: #999;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}


.flow-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.flow-item {
  display: flex;
  gap: 12px;
}
.flow-index {
  flex: none;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  font-size: 12px;
  line-height: 22px;
  text-align: center;
  color: #fff;
  background: linear-gradient(135deg, #1F6F6B 0%, #2A7F7A 100%);
}
.flow-text {
  min-width: 0;
}
.flow-title {
  font-size: 14px;
  font-weight: 500;
  color: #333;
}
.flow-desc {
  margin-top: 2px;
  font-size: 12px;
  line-height: 20px;
  color: #999;
}


/* 卡片区改成两列之后，窄屏下退回一列，避免说明文字被挤成一列单词 */
@media (max-width: 1280px) {
  .quick-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
