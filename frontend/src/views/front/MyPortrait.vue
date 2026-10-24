<template>
  <div class="main-content">
    <div class="page-head">
      <div class="page-head-main">
        <h2>画像结果</h2>
        <p class="page-tip">
          这里展示智能匹配过程中画像师生成的现场结果。画像来自你的自我介绍、室友期望和动态原文，
          每个标签都会标明依据；需要重新生成时，请统一到【智能匹配】发起新一轮。
        </p>
      </div>
    </div>

    <!-- 画像挂在租客档案上，还没填档案时先把去处指清楚 -->
    <div v-if="data.loading" class="card loading-card" v-loading="true" element-loading-text="正在读取画像结果"></div>

    <div v-else-if="!data.has_profile" class="card block-card">
      <div class="block-title">先补租客档案</div>
      <el-alert
          type="warning"
          :closable="false"
          title="还没有填写租客档案"
          description="画像以租客档案和动态原文为材料，请先把档案填好保存。">
      </el-alert>
      <div class="go-action">
        <el-button type="primary" @click="router.push('/front/memberProfile')">去填写租客档案</el-button>
      </div>
    </div>

    <template v-else>
      <div v-if="!data.portrait" class="card empty-card">
        <div class="empty-icon"><el-icon><MagicStick /></el-icon></div>
        <div class="empty-title">还没有画像结果</div>
        <div class="empty-desc">请先到【智能匹配】发起一轮，画像师的结果会自动展示在这里。</div>
        <div class="go-action"><el-button type="primary" @click="router.push('/front/myMatch')">去智能匹配</el-button></div>
      </div>

      <template v-else>
        <div class="card portrait-card">
          <div class="portrait-head">
            <span v-if="data.portrait.focus_hint" class="focus-chip">
              <el-icon><WarningFilled /></el-icon>
              本次重点补 {{ data.portrait.focus_hint }}
            </span>
            <span class="portrait-time">生成于 {{ data.portrait.create_time }}</span>
          </div>
          <div v-for="group in data.tagGroups" :key="group.key" class="tag-block">
            <div class="tag-label">{{ group.label }}</div>
            <div class="tag-list">
              <span class="tag-chip" v-for="tag in data.portrait[group.key]" :key="tag">{{ tag }}</span>
              <span v-if="!data.portrait[group.key].length" class="tag-empty">当前结果没有整理出这类标签</span>
            </div>
          </div>
          <div class="tag-block">
            <div class="tag-label">画像概括</div>
            <div class="summary-box">{{ data.portrait.summary || '当前结果没有给出画像概括' }}</div>
          </div>
        </div>

        <div class="card block-card">
          <div class="block-title">每个标签的依据</div>
          <el-table :data="data.portrait.evidence" stripe class="portrait-table">
            <el-table-column prop="dimension" label="标签类别" width="120"/>
            <el-table-column prop="tag" label="标签" width="180"/>
            <el-table-column prop="source" label="原文依据" show-overflow-tooltip/>
          </el-table>
          <div class="table-tip">
            标签只有在原文里找得到依据时才会留下，找不到依据的这次已经被平台丢掉。
          </div>
        </div>

      </template>
    </template>
  </div>
</template>

<script setup>
import { reactive } from "vue";
import { ElMessage } from "element-plus";
import { MagicStick, WarningFilled } from "@element-plus/icons-vue";
import router from "@/router/index.js";
import request from "@/utils/request.js";

const data = reactive({
  loading: true,
  has_profile: false,
  readiness: { checks: [], blocker: null, can_generate: false },
  portrait: null,
  // 三类标签和它们在返回里的字段名，页面上按同一份顺序渲染
  tagGroups: [
    { key: 'personality_tags', label: '性格标签' },
    { key: 'lifestyle_tags', label: '生活方式标签' },
    { key: 'cohabit_need_tags', label: '合住需求标签' }
  ]
})

const load = () => {
  request.get('/portrait/my').then(res => {
    if (res.code !== '200') {
      ElMessage.error(res.msg)
      return
    }
    Object.assign(data, res.data)
  }).finally(() => {
    data.loading = false
  })
}

load()
</script>

<style scoped>
.main-content {
  padding-bottom: 10px;
  --el-color-primary: #1F6F6B;
  --el-color-primary-light-3: #4F8F8A;
  --el-color-primary-light-5: #84B5B2;
  --el-color-primary-light-7: #A9CFCB;
  --el-color-primary-light-8: #C4DCDA;
  --el-color-primary-light-9: #EFF6F5;
  --el-color-primary-dark-2: #24625E;
}
.loading-card {
  min-height: 180px;
  margin-top: 12px;
}

/* 卡片标题统一加粗，不加任何装饰线条 */
.block-card {
  margin-top: 12px;
  padding: 20px 24px 22px;
}
.block-title {
  font-size: 16px;
  font-weight: bold;
  line-height: 20px;
  color: #333;
}
.block-card .el-alert {
  margin-top: 14px;
}
.go-action {
  padding-top: 16px;
}

/* 前置条件逐条列出，满足和没满足用两套底色区分 */
.check-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  background-color: #fafafa;
  font-size: 13px;
}
.check-icon {
  flex: none;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
}
.check-icon.is-ok {
  color: #67c23a;
  background-color: rgba(103, 194, 58, .12);
}
.check-icon.is-warn {
  color: #e6a23c;
  background-color: rgba(230, 162, 60, .16);
}
.check-label {
  flex: none;
  width: 100px;
  color: #666;
}
.check-message {
  color: #666;
  line-height: 20px;
}
.warn-text {
  color: #e6a23c;
}

/* 一版画像都没有时给一块带图标的空状态，比一行灰字更像一个能动手的地方 */
.empty-card {
  margin-top: 12px;
  padding: 28px 24px 32px;
  text-align: center;
}
.empty-icon {
  width: 52px;
  height: 52px;
  margin: 0 auto 12px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  color: #1F6F6B;
  background-color: rgba(31, 111, 107, .1);
}
.empty-title {
  font-size: 15px;
  font-weight: bold;
  color: #333;
}
.empty-desc {
  margin-top: 6px;
  font-size: 13px;
  line-height: 22px;
  color: #999;
}

/* 当前这一版画像：头部交代版本和时间，下面按类别铺标签 */
.portrait-card {
  margin-top: 12px;
  padding: 20px 24px 22px;
  border: 1px solid #DFECEB;
  border-radius: 10px;
  box-shadow: 0 1px 2px rgba(31, 111, 107, .05);
}
.portrait-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 16px;
  border-bottom: 1px solid #E4F0EF;
  margin-bottom: 16px;
}
.focus-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 18px;
  color: #b7791f;
  border: 1px solid #f3e0bd;
  background-color: #fdf6e8;
}
.portrait-time {
  color: #999;
  font-size: 12px;
  margin-left: auto;
}
.tag-block {
  padding-bottom: 14px;
}
.tag-label {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #666;
  font-size: 13px;
  padding-bottom: 8px;
}
.tag-label::before {
  content: "";
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: #1F6F6B;
}
.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.tag-chip {
  padding: 4px 14px;
  border-radius: 999px;
  font-size: 13px;
  line-height: 18px;
  color: #1F6F6B;
  border: 1px solid #D5E8E6;
  background-color: rgba(31, 111, 107, .08);
}
.tag-empty {
  color: #bbb;
  font-size: 13px;
  line-height: 26px;
}
/* 概括单独抬成一块底色，跟上面零散的标签拉开层次 */
.summary-box {
  padding: 14px 16px;
  border-radius: 8px;
  border: 1px solid #DFECEB;
  background-color: rgba(31, 111, 107, .05);
  color: #333;
  font-size: 13px;
  line-height: 24px;
  white-space: pre-wrap;
}

/* 两张明细表跟着主题色走：表头浅底色，表头字用主题色 */
.portrait-table {
  margin-top: 14px;
  --el-table-header-bg-color: #F5FAF9;
  --el-table-header-text-color: #1F6F6B;
  --el-table-row-hover-bg-color: #F2F8F7;
}
.table-tip {
  color: #999;
  font-size: 12px;
  line-height: 20px;
  padding-top: 10px;
}
.dialog-sub-title {
  padding-top: 4px;
  font-size: 15px;
  font-weight: bold;
  color: #333;
}

/* 弹窗挂在 body 上渲染，主题色变量要按它自己的类名给，
   写在 .main-content 上的页面作用域盖不到 */
:global(.portrait-dialog) {
  --el-color-primary: #1F6F6B;
  --el-color-primary-light-3: #4F8F8A;
  --el-color-primary-light-5: #84B5B2;
  --el-color-primary-light-7: #A9CFCB;
  --el-color-primary-light-8: #C4DCDA;
  --el-color-primary-light-9: #EFF6F5;
  --el-color-primary-dark-2: #24625E;
}

</style>
