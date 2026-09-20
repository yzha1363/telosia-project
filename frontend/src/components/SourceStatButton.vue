<script setup lang="ts">
import { openSource } from '../store/sourceDialog'

const props = defineProps<{
  sourceId: number
  label: string
  what?: string
}>()
</script>

<template>
  <button type="button" class="source-stat-button" :aria-label="label" @click="openSource(sourceId, props.what)">
    <slot />
    <span class="src-dot" aria-hidden="true"></span>
  </button>
</template>
