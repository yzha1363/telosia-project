<script setup lang="ts">
import { computed } from 'vue'
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'

const props = defineProps<{ text: string }>()
const markdown = new MarkdownIt({ breaks: true, html: false, linkify: true, typographer: false })
const html = computed(() => DOMPurify.sanitize(markdown.render(props.text), {
  USE_PROFILES: { html: true },
}))
</script>

<template>
  <div v-html="html"></div>
</template>
