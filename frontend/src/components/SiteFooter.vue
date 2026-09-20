<script setup lang="ts">
import { useRouter } from 'vue-router'
import { resetSelection } from '../store/appState'
import { showCookieModal } from '../store/cookies'

const router = useRouter()

function goHome() {
  resetSelection()
  router.push({ path: '/' })
}

function goToJobFinder() {
  resetSelection()
  router.push('/check-my-job')
}
</script>

<template>
  <footer class="site-footer">
    <div class="wrap">
      <div class="ack" role="img" aria-label="Acknowledgment of Country">
        <svg viewBox="0 0 64 40" aria-hidden="true" focusable="false">
          <path
            d="M6 31 C 13 8, 33 5, 40 9 C 37 31, 19 35, 6 31 Z"
            fill="#7C8A3E"
            stroke="#56602A"
            stroke-width="1"
          />
          <path
            d="M28 33 C 39 15, 58 15, 61 21 C 57 34, 40 36, 28 33 Z"
            fill="#9C8B4E"
            stroke="#6B5A2A"
            stroke-width="1"
          />
          <circle cx="20" cy="22" r="2.4" fill="#3F4A1F" />
          <circle cx="48" cy="25" r="2.4" fill="#6B5A2A" />
        </svg>
        <p>
          Telosia acknowledges the Traditional Custodians of Country throughout Australia and their continuing
          connection to land, waters and community. We pay our respects to Elders past and present, and extend that
          respect to all Aboriginal and Torres Strait Islander peoples.
        </p>
      </div>

      <div class="fgrid">
        <div>
          <h4>Telosia</h4>
          <p style="max-width: 40ch">
            Know what the work is doing to your body, and where other women in your job went next. Free, and there
            is no account to make.
          </p>
        </div>
        <div>
          <h4>Pages</h4>
          <button type="button" @click="goHome">Home</button>
          <button type="button" @click="goToJobFinder">Check my job</button>
          <router-link to="/how-it-works">How it works</router-link>
          <router-link to="/hurt-at-work">Hurt at work</router-link>
          <router-link to="/about-us">About us</router-link>
        </div>
        <div>
          <h4>Where the data comes from</h4>
          <a href="https://www.safeworkaustralia.gov.au" target="_blank" rel="noopener">Safe Work Australia</a>
          <a href="https://www.jobsandskills.gov.au" target="_blank" rel="noopener">Jobs and Skills Australia</a>
        </div>
      </div>

      <div class="fbot">
        <span>Telosia shows published data. It does not give medical, legal or career advice.</span>
        <button class="ck-link" @click="showCookieModal">Cookies</button>
      </div>
    </div>
  </footer>
</template>
