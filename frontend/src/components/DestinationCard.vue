<script setup lang="ts">
import type { Destination } from '../data/types'

type LoadBand = 'down' | 'up' | 'same' | null

const props = defineProps<{
  destination: Destination
  index: number
  band?: LoadBand
  active?: boolean
}>()

const bandLabel: Record<Exclude<LoadBand, null>, string> = {
  down: 'Easier on your body',
  up: 'Harder on your body',
  same: 'Similar to your job',
}

const emit = defineEmits<{ open: [] }>()
</script>

<template>
  <button
    class="destination-item"
    :class="{ active: props.active }"
    type="button"
    :data-testid="`button-destination-${index + 1}`"
    @click="emit('open')"
  >
    <span class="tags">
      <span class="tag">{{ destination.tag }}</span>
      <span v-if="props.band" class="band-badge" :class="props.band">{{ bandLabel[props.band] }}</span>
    </span>
    <span class="nm">{{ destination.title }}</span>
    <span class="share">
      <b>{{ destination.share.toFixed(1) }}%</b>
      <span>of observed moves</span>
    </span>
    <span class="go" aria-hidden="true">&rarr;</span>
  </button>
</template>
