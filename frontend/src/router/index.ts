import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import JobFinderView from '../views/JobFinderView.vue'
import RiskView from '../views/RiskView.vue'
import DestinationsView from '../views/DestinationsView.vue'
import AboutView from '../views/AboutView.vue'
import HelpView from '../views/HelpView.vue'
import AboutUsView from '../views/AboutUsView.vue'
import { appState } from '../store/appState'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  scrollBehavior(to) {
    if (to.hash) return { el: to.hash, behavior: 'smooth' }
    return { top: 0 }
  },
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/check-my-job', name: 'job-finder', component: JobFinderView },
    { path: '/risk', name: 'risk', component: RiskView },
    { path: '/destinations', name: 'destinations', component: DestinationsView },
    { path: '/how-it-works', name: 'about', component: AboutView },
    { path: '/hurt-at-work', name: 'help', component: HelpView },
    { path: '/about-us', name: 'about-us', component: AboutUsView },
  ],
})

// AC1.2: no risk or destination data loads until an occupation has been confirmed.
router.beforeEach((to) => {
  if ((to.name === 'risk' || to.name === 'destinations') && !appState.selectedOccupationId) {
    return { name: 'job-finder' }
  }
})

export default router
