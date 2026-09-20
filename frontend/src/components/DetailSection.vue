<script setup lang="ts">
// Same content, two shells: a collapsible <details> in the narrow side-by-side view (matches
// every other accordion on the site), or an always-open card once the destination panel is
// expanded to full width — no point hiding content behind a click when there's room to show it.
defineProps<{ title: string; expanded: boolean; defaultOpen?: boolean }>()
</script>

<template>
  <details v-if="!expanded" :open="defaultOpen || undefined">
    <summary>{{ title }}</summary>
    <div class="dbody">
      <slot />
    </div>
  </details>
  <div v-else class="detail-card">
    <div class="detail-card-head">
      <b>{{ title }}</b>
    </div>
    <div class="dbody">
      <slot />
    </div>
  </div>
</template>
