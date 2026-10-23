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

const colors = ['#1F6F6B', '#8B5A2B', '#3F6B63', '#526D82', '#6A5A8C', '#4F8A86']
const loadFailed = ref(false)
const displayName = computed(() => (props.name || '').trim() || '用户')
const initial = computed(() => Array.from(displayName.value)[0])
const colorIndex = computed(() => initial.value.codePointAt(0) % colors.length)
const avatarStyle = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
  fontSize: `${Math.max(14, Math.round(props.size * 0.38))}px`,
  backgroundColor: colors[colorIndex.value]
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
}
.image-avatar {
  object-fit: cover;
}
.text-avatar {
  color: #fff;
  font-weight: 600;
  line-height: 1;
  user-select: none;
}
</style>
