<template>
  <div class="main-content page-wrap">
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
            <span v-if="data.portrait.focus_hint" class="chip chip-amber chip-wrap">
              <el-icon><WarningFilled /></el-icon>
              本次重点补 {{ data.portrait.focus_hint }}
            </span>
            <span class="portrait-time">生成于 {{ data.portrait.create_time }}</span>
          </div>
          <div class="portrait-stats">
            <span class="chip chip-blue"><b>{{ data.portrait.personality_tags.length }}</b> 性格标签</span>
            <span class="chip chip-green"><b>{{ data.portrait.lifestyle_tags.length }}</b> 生活方式</span>
            <span class="chip chip-violet"><b>{{ data.portrait.cohabit_need_tags.length }}</b> 合住需求</span>
          </div>
          <div v-for="group in data.tagGroups" :key="group.key" class="tag-block" :class="'tag-' + group.key">
            <div class="tag-label">{{ group.label }}</div>
            <div class="tag-list">
              <span class="tag-chip" v-for="tag in data.portrait[group.key]" :key="tag">{{ tag }}</span>
              <span v-if="!data.portrait[group.key].length" class="tag-empty">当前结果没有整理出这类标签</span>
            </div>
          </div>
          <div class="portrait-summary">
            <div class="tag-label">画像概括</div>
            <div class="summary-box">{{ data.portrait.summary || '当前结果没有给出画像概括' }}</div>
          </div>
        </div>

        <div class="card block-card">
          <div class="block-title">每个标签的依据</div>
          <div class="soft-panel evidence-panel">
            <el-table :data="data.portrait.evidence" stripe class="data-table">
              <el-table-column prop="dimension" label="标签类别" width="120"/>
              <el-table-column prop="tag" label="标签" width="180"/>
              <el-table-column prop="source" label="原文依据" show-overflow-tooltip/>
            </el-table>
            <div class="table-tip">
              标签只有在原文里找得到依据时才会留下，找不到依据的这次已经被平台丢掉。
            </div>
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
.page-wrap > .page-head { margin: 0; }
.page-wrap > .card { margin-top: 0; }

.loading-card { min-height: 200px; }
.go-action { margin-top: 16px; }

/* 当前这一版画像：头部交代版本与时间，下面按类别铺标签 */
.portrait-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--pb-line);
}
.portrait-time {
  margin-left: auto;
  font-size: 12px;
  color: var(--pb-faint);
}

.portrait-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 14px 0 6px;
}

.tag-block { padding: 8px 0 14px; }
.tag-label {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--pb-text);
}
.tag-label::before {
  content: "";
  width: 4px;
  height: 13px;
  border-radius: 999px;
  background: linear-gradient(180deg, #60a5fa, #2563eb);
}
.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.tag-chip {
  display: inline-flex;
  align-items: center;
  padding: 5px 13px;
  border-radius: 999px;
  border: 1px solid var(--pb-line);
  background: var(--pb-surface-2);
  color: var(--pb-muted);
  font-size: 12.5px;
  font-weight: 500;
  line-height: 18px;
}
.tag-personality_tags .tag-chip {
  border-color: rgba(37, 99, 235, 0.16);
  background: var(--pb-brand-soft);
  color: var(--pb-brand);
}
.tag-lifestyle_tags .tag-chip {
  border-color: rgba(16, 185, 129, 0.2);
  background: var(--pb-ok-soft);
  color: #047857;
}
.tag-cohabit_need_tags .tag-chip {
  border-color: rgba(139, 92, 246, 0.2);
  background: var(--pb-violet-soft);
  color: #6d28d9;
}
.tag-empty {
  font-size: 12.5px;
  line-height: 28px;
  color: var(--pb-faint);
}

/* 概括单独抬成一块，和上面零散的标签拉开层次 */
.portrait-summary {
  padding-top: 14px;
  border-top: 1px dashed var(--pb-line-strong);
}
.portrait-summary .summary-box { white-space: pre-wrap; }

.data-table { margin-top: 12px; }

/* 依据单独放进浅底面板，和上方的画像标签拉开层次 */
.evidence-panel {
  margin-top: 12px;
  padding: 8px 10px 14px;
}
.evidence-panel .data-table { margin-top: 0; }
.evidence-panel .table-tip { padding: 10px 6px 0; }
</style>
