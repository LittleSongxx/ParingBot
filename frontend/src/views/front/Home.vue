<template>
  <div class="main-content">
    <!-- 页头：一句话说清平台怎么帮租客找室友，右侧是完善个人资料的入口 -->
    <div class="page-head with-action">
      <div class="page-head-main">
        <h2>首页</h2>
        <p class="page-tip">
          平台会读你的自我介绍和动态，先给你画出一份生活习惯画像；再按你的合住偏好检索候选室友，
          逐个站在对方的立场上复核一遍，最后把双方都愿意合住的人交给你。
          档案填得越全，推荐的室友越合拍。
        </p>
      </div>
      <div class="page-head-action">
        <el-button @click="router.push('/front/person')">完善资料</el-button>
      </div>
    </div>

    <!-- 快捷入口：顶部菜单里的租客页面，点一下直接进对应页面 -->
    <div class="card block">
      <div class="block-title">我的功能</div>
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

    <!-- 从填档案到拿到室友名单要走的几步，纯说明文本，让刚注册的租客知道下一步该去哪一页 -->
    <div class="card block">
      <div class="block-title">从档案到合租匹配，跟着这几步走</div>
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
import router from "@/router/index.js";
import {
  Avatar, Filter, Camera, Reading, Collection, DocumentChecked, Connection
} from "@element-plus/icons-vue";

// 快捷入口，路径和顶部菜单里的页面一一对应
const shortcuts = [
  { name: "租客档案", desc: "补全作息、预算等档案与生活照", path: "/front/memberProfile", icon: Avatar },
  { name: "合住偏好", desc: "设定希望室友满足的条件", path: "/front/myPreference", icon: Filter },
  { name: "我的动态", desc: "记录起居日常，给画像留素材", path: "/front/myMoment", icon: Camera },
  { name: "智能匹配", desc: "统一发起完整匹配并查看实时进度", path: "/front/myMatch", icon: Connection },
  { name: "画像结果", desc: "查看画像师生成的标签与依据", path: "/front/myPortrait", icon: Reading },
  { name: "候选结果", desc: "查看筛选官找出的候选与放宽过程", path: "/front/myCandidate", icon: Collection },
  { name: "审核结果", desc: "查看审核官的通过、否决与原因", path: "/front/myAudit", icon: DocumentChecked },
];

// 租客从填档案到拿到室友名单要走的几步，按顺序列出来
const flow = [
  { title: "完善租客档案", desc: "租客档案里补全意向门店、月租预算、作息、整洁度、自我介绍和生活照，保存后由管理员审核，审核通过才会进入别人的候选池。" },
  { title: "写下合住偏好", desc: "到合住偏好里设定室友的年龄区间、预算区间、整洁度、作息、门店范围等条件，并标出哪些必须、哪些可以放宽。" },
  { title: "发布动态，留下素材", desc: "我的动态里记录起居日常，画像师会从这些原文里整理你的生活习惯、性格和合住需求。" },
  { title: "重新智能匹配", desc: "智能匹配是唯一执行入口，提交后可离开页面；合租管家会在后台调度三个子 Agent。" },
  { title: "查看三个结果现场", desc: "画像结果看标签依据，候选结果看每轮筛选，审核结果看通过、否决和原因。" },
];
</script>

<style scoped>
/* .main-content 的宽度和留白在 front.css 里，这里只补底部留白 */
.main-content {
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

/* 窄屏下把卡片区退回一列，说明文字才不会被挤成一行一个词 */
@media (max-width: 1280px) {
  .quick-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

</style>
