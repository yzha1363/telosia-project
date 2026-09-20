<script setup lang="ts">
import { onMounted } from 'vue'
import AccessibilityPanel from './components/AccessibilityPanel.vue'
import SiteHeader from './components/SiteHeader.vue'
import SiteFooter from './components/SiteFooter.vue'
import SourceDialog from './components/SourceDialog.vue'
import CookieModal from './components/CookieModal.vue'
import ChatBot from './components/ChatBot.vue'
import { maybeShowCookieModalOnFirstVisit } from './store/cookies'

onMounted(() => {
  maybeShowCookieModalOnFirstVisit()
})
</script>

<template>
  <a class="skip-link" href="#main">Skip to content</a>

  <SiteHeader />

  <main id="main">
    <router-view />
  </main>

  <SiteFooter />
  <SourceDialog />
  <ChatBot />
  <AccessibilityPanel />
  <CookieModal />
</template>
