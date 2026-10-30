<template>
  <div class="main-content page-wrap">
    <!-- 首屏 hero：一句话说清平台怎么帮租客找室友，右侧常驻三步流程 -->
    <section class="home-hero">
      <div class="hero-main">
        <span class="hero-eyebrow"><i class="status-dot"></i> Multi-Agent Matching · 租客工作台</span>
        <h1>把找室友，<br />交给三个专职 Agent</h1>
        <p class="hero-sub">
          平台会读你的自我介绍和动态，先给你画出一份生活习惯画像；再按你的合住偏好检索候选室友，
          逐个站在对方的立场上复核一遍，最后把双方都愿意合住的人交给你。
          档案填得越全，推荐的室友越合拍。
        </p>
        <div class="hero-actions">
          <el-button type="primary" size="large" @click="router.push('/front/person')">完善资料</el-button>
          <router-link class="hero-btn-ghost" to="/front/myMatch">发起匹配</router-link>
        </div>
        <div class="hero-steps">
          <span class="hero-step"><b>01</b>完善档案与偏好</span>
          <span class="hero-step"><b>02</b>发布生活动态</span>
          <span class="hero-step"><b>03</b>发起智能匹配</span>
        </div>
      </div>

      <aside class="hero-aside">
        <div class="hero-panel">
          <div class="hero-panel-title">一次匹配，三个角色接力</div>
          <ul class="hero-panel-list">
            <li>
              <span class="hero-num">1</span>
              <div><b>画像师</b><p>从档案与动态原文里整理标签，每个标签都要有依据</p></div>
            </li>
            <li>
              <span class="hero-num">2</span>
              <div><b>筛选官</b><p>先按「必须」项硬筛，候选不够再放宽「加分」项</p></div>
            </li>
            <li>
              <span class="hero-num">3</span>
              <div><b>审核官</b><p>站到候选方立场反向复核，通过和否决都有结论</p></div>
            </li>
          </ul>
          <div class="hero-panel-foot"><i class="status-dot"></i> 模型只做判断 · 代码守边界 · 每步可复盘</div>
        </div>
      </aside>
    </section>

    <!-- 快捷入口：顶部菜单里的租客页面，点一下直接进对应页面 -->
    <div class="card">
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
    <div class="card">
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
/* ---------------- Hero ---------------- */
.home-hero {
  position: relative;
  overflow: hidden;
  display: grid;
  grid-template-columns: minmax(0, 1.28fr) minmax(290px, 0.72fr);
  gap: 28px;
  padding: 32px 34px;
  border: 1px solid var(--pb-line);
  border-radius: var(--pb-radius-lg);
  background:
    radial-gradient(720px 320px at 88% -30%, rgba(96, 165, 250, 0.18), transparent 62%),
    radial-gradient(520px 260px at -8% 118%, rgba(37, 99, 235, 0.1), transparent 60%),
    linear-gradient(135deg, #ffffff 0%, #f6f8ff 58%, #ecf2ff 100%);
  box-shadow: var(--pb-shadow-card);
}

.hero-main {
  min-width: 0;
}

.hero-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 13px;
  border-radius: 999px;
  border: 1px solid rgba(37, 99, 235, 0.18);
  background: rgba(255, 255, 255, 0.86);
  color: var(--pb-brand);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.01em;
}

.home-hero h1 {
  margin: 17px 0 12px;
  font-size: 32px;
  line-height: 1.3;
  font-weight: 750;
  letter-spacing: -0.03em;
  color: var(--pb-text);
}

.hero-sub {
  margin: 0;
  max-width: 640px;
  font-size: 13.5px;
  line-height: 1.9;
  color: var(--pb-muted);
}

.hero-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 22px;
}

.hero-btn-ghost {
  display: inline-flex;
  align-items: center;
  height: 40px;
  padding: 0 20px;
  border-radius: 10px;
  border: 1px solid rgba(37, 99, 235, 0.26);
  background: rgba(255, 255, 255, 0.9);
  color: var(--pb-brand);
  font-size: 14px;
  font-weight: 600;
  transition: all 0.18s ease;
}
.hero-btn-ghost:hover {
  border-color: var(--pb-brand);
  background: var(--pb-brand-soft);
  color: var(--pb-brand-dark);
  transform: translateY(-1px);
  box-shadow: 0 8px 20px rgba(37, 99, 235, 0.14);
}

.hero-steps {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 24px;
}
.hero-step {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 13px 5px 5px;
  border-radius: 999px;
  border: 1px solid var(--pb-line);
  background: rgba(255, 255, 255, 0.78);
  font-size: 12px;
  color: var(--pb-muted);
}
.hero-step b {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 21px;
  height: 21px;
  border-radius: 50%;
  font-size: 10px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #60a5fa, #2563eb);
}

/* 右侧流程面板：白底玻璃感，跟左侧文案拉开层次 */
.hero-aside {
  display: flex;
}
.hero-panel {
  flex: 1;
  min-width: 0;
  padding: 18px 18px 16px;
  border-radius: var(--pb-radius);
  border: 1px solid rgba(37, 99, 235, 0.14);
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(10px);
  box-shadow: 0 10px 28px rgba(37, 99, 235, 0.08);
}
.hero-panel-title {
  margin-bottom: 14px;
  font-size: 13px;
  font-weight: 650;
  color: var(--pb-text);
}
.hero-panel-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.hero-panel-list li {
  display: flex;
  gap: 10px;
}
.hero-num {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 700;
  color: var(--pb-brand);
  background: var(--pb-brand-soft);
}
.hero-panel-list b {
  font-size: 13px;
  color: var(--pb-text);
}
.hero-panel-list p {
  margin: 2px 0 0;
  font-size: 12px;
  line-height: 1.62;
  color: var(--pb-muted);
}
.hero-panel-foot {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 15px;
  padding-top: 13px;
  border-top: 1px dashed var(--pb-line-strong);
  font-size: 11.5px;
  color: var(--pb-faint);
}

/* ---------------- 快捷入口 ---------------- */
.quick-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.quick-item {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 14px 15px;
  border: 1px solid var(--pb-line);
  border-radius: var(--pb-radius-sm);
  background: var(--pb-surface-2);
  cursor: pointer;
  transition: all 0.18s ease;
}
.quick-item:hover {
  border-color: rgba(37, 99, 235, 0.3);
  background: var(--pb-surface);
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.09);
  transform: translateY(-2px);
}
.quick-icon {
  flex: none;
  width: 38px;
  height: 38px;
  border-radius: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  color: var(--pb-brand);
  background: var(--pb-brand-soft);
}
.quick-text {
  min-width: 0;
}
.quick-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--pb-text);
}
.quick-desc {
  margin-top: 2px;
  font-size: 12px;
  color: var(--pb-muted);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

/* ---------------- 流程说明 ---------------- */
.flow-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.flow-item {
  position: relative;
  display: flex;
  gap: 14px;
}
.flow-item:not(:last-child)::before {
  content: "";
  position: absolute;
  left: 13px;
  top: 32px;
  bottom: -16px;
  width: 1px;
  background: linear-gradient(180deg, rgba(37, 99, 235, 0.3), var(--pb-line));
}
.flow-index {
  position: relative;
  z-index: 1;
  flex: none;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 700;
  line-height: 26px;
  text-align: center;
  color: #fff;
  background: linear-gradient(135deg, #60a5fa, #2563eb);
  box-shadow: 0 4px 10px rgba(37, 99, 235, 0.24);
}
.flow-text {
  min-width: 0;
  padding-top: 2px;
}
.flow-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--pb-text);
}
.flow-desc {
  margin-top: 3px;
  font-size: 13px;
  line-height: 1.78;
  color: var(--pb-muted);
}

@media (max-width: 1024px) {
  .home-hero { grid-template-columns: 1fr; padding: 26px 24px; }
  .quick-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .home-hero { padding: 22px 18px; }
  .home-hero h1 { font-size: 26px; }
  .quick-grid { grid-template-columns: 1fr; }
}
</style>
