import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { vReveal } from './directives/reveal'
import { vCountup } from './directives/countup'
import './assets/styles.css'

const app = createApp(App)

app.use(router)
app.directive('reveal', vReveal)
app.directive('countup', vCountup)

app.mount('#app')
