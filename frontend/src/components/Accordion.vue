<script setup lang="ts">
import { ref } from 'vue'

const props = withDefaults(defineProps<{ title: string; defaultOpen?: boolean; testid?: string }>(), {
  defaultOpen: false,
})

const isOpen = ref(props.defaultOpen)
</script>

<template>
  <section class="accordion">
    <button type="button" :aria-expanded="isOpen" :data-testid="testid" @click="isOpen = !isOpen">
      <span>{{ title }}</span><span class="accordion-symbol">{{ isOpen ? '−' : '+' }}</span>
    </button>
    <div class="accordion-content" :hidden="!isOpen">
      <slot />
    </div>
  </section>
</template>
