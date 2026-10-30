<template>
  <img
      v-if="src && !loadFailed"
      class="name-avatar image-avatar"
      :src="src"
      :alt="displayName + '的头像'"
      :style="avatarStyle"
      @error="loadFailed = true"
  />
  <span
      v-else
      class="name-avatar text-avatar"
      :style="avatarStyle"
      :title="displayName"
  >{{ initial }}</span>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  name: { type: String, default: '' },
  src: { type: String, default: '' },
  size: { type: Number, default: 40 }
})

// 和全局设计 token 一致的柔和高饱和色，按首字稳定取色
const colors = ['#2563eb', '#7c3aed', '#0891b2', '#059669', '#d97706', '#db2777']
const loadFailed = ref(false)
const displayName = computed(() => (props.name || '').trim() || '用户')
const initial = computed(() => Array.from(displayName.value)[0])
const colorIndex = computed(() => initial.value.codePointAt(0) % colors.length)
const avatarStyle = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
  fontSize: `${Math.max(13, Math.round(props.size * 0.38))}px`,
  background: `linear-gradient(135deg, ${colors[colorIndex.value]}, ${colors[colorIndex.value]}cc)`
}))

watch(() => props.src, () => {
  loadFailed.value = false
})
</script>

<style scoped>
.name-avatar {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  border-radius: 50%;
  vertical-align: middle;
  box-shadow: 0 2px 8px rgba(16, 24, 40, 0.12);
}
.image-avatar { object-fit: cover; }
.text-avatar { color: #fff; font-weight: 600; line-height: 1; user-select: none; }
</style>
