<script setup lang="ts">
import { useRouter } from 'vue-router'
import { resetSelection } from '../store/appState'

const router = useRouter()

function goToJobFinder() {
  resetSelection()
  router.push('/check-my-job')
}
</script>

<template>
  <nav class="site-header">
    <div class="wrap nav">
      <router-link to="/" class="logo" aria-label="Telosia, home" data-testid="button-home">
        <svg class="mark" viewBox="0 0 64 64" fill="none" aria-hidden="true">
          <path
            d="M15 52 C15 30 21 13 32 13 C43 13 49 30 49 52"
            fill="none"
            stroke="currentColor"
            stroke-width="6.4"
            stroke-linecap="round"
          />
          <circle cx="32" cy="27.5" r="5.2" fill="currentColor" />
          <path
            d="M25.5 34 C25.5 44 29 51 32 51 C35 51 38.5 44 38.5 34 C35.5 37.5 28.5 37.5 25.5 34 Z"
            fill="currentColor"
          />
          <path d="M49 4 L51.6 10.4 L58 13 L51.6 15.6 L49 22 L46.4 15.6 L40 13 L46.4 10.4 Z" fill="currentColor" />
        </svg>
        <span class="text">
          <span class="n">Telosia</span>
          <span class="t">Map the risk. Move with purpose.</span>
        </span>
      </router-link>

      <div class="nlinks">
        <router-link to="/">Home</router-link>
        <router-link to="/how-it-works">How it works</router-link>
        <router-link to="/hurt-at-work">Hurt at work</router-link>
        <router-link to="/about-us">About us</router-link>
      </div>

      <button class="cta cta-a" type="button" data-testid="button-check-job" @click="goToJobFinder">Check my job</button>
    </div>
  </nav>
</template>

<style scoped>
.logo {
  display: inline-flex;
  align-items: center;
  gap: 0.625rem;
  text-decoration: none;
  flex-shrink: 0;
}
.logo .mark {
  width: 2.4rem;
  height: 2.4rem;
  color: var(--plum-500);
  flex-shrink: 0;
}
.logo .text {
  display: flex;
  flex-direction: column;
  line-height: 1.05;
}
.logo .n {
  font-family: var(--disp);
  font-weight: 800;
  font-size: 1.5rem;
  letter-spacing: -0.02em;
  color: var(--ink);
}
.logo .t {
  font-size: 0.5625rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--plum-500);
  margin-top: 0.18rem;
  font-weight: 600;
}
@media (max-width: 540px) {
  .logo .t {
    display: none;
  }
}
</style>
