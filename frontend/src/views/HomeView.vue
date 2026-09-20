<script setup lang="ts">
import { useRouter } from 'vue-router'
import HeroFigures from '../components/HeroFigures.vue'

const router = useRouter()

function goToJobFinder() {
  router.push('/check-my-job')
}
</script>

<template>
  <section id="home-view" class="page-view" aria-labelledby="home-title">
    <header class="home-hero">
      <div class="blob b1"></div>
      <div class="blob b2"></div>
      <div class="blob b3"></div>
      <div class="wrap hgrid">
        <div>
          <h1 id="home-title" class="reveal-blur" v-reveal style="margin-top: 24px">Is the job hurting you?<br /><em>Find out in a minute.</em></h1>
          <p class="hero-intro reveal-up" v-reveal style="--reveal-delay: 120ms">
            See what your work does to bodies like yours, and where other women in your job went next. Built from
            published national injury and mobility data.
          </p>
          <div class="hero-actions">
            <button class="cta cta-a" type="button" data-testid="button-start-profile" @click="goToJobFinder">
              Check my job &rarr;
            </button>
            <router-link class="cta cta-w" to="/how-it-works">How it works</router-link>
          </div>
          <div class="trust">
            <div><b>1 min</b>from start<br />to an answer</div>
            <div><b>358</b>occupations</div>
            <div><b>Free</b>no sign up,<br />no cost, ever</div>
          </div>
        </div>
        <div class="cast">
          <HeroFigures />
          <div class="ring rg1"></div>
          <div class="ring rg2"></div>
          <svg class="c1" viewBox="0 0 200 300" role="img" aria-label="A woman in a hard hat and high visibility vest">
            <use href="#hero-eng" />
          </svg>
          <svg class="c2" viewBox="0 0 200 300" role="img" aria-label="A woman in care worker scrubs">
            <use href="#hero-care" />
          </svg>
        </div>
      </div>
    </header>

    <div class="mq" aria-hidden="true">
      <div class="mqi">
        <span>KNOW WHAT THE WORK IS DOING TO YOU</span><span>SEE WHERE OTHER WOMEN WENT NEXT</span><span>TAKES ABOUT A MINUTE</span><span>NOBODY NEEDS TO KNOW YOU LOOKED</span>
        <span>KNOW WHAT THE WORK IS DOING TO YOU</span><span>SEE WHERE OTHER WOMEN WENT NEXT</span><span>TAKES ABOUT A MINUTE</span><span>NOBODY NEEDS TO KNOW YOU LOOKED</span>
      </div>
    </div>

    <div class="home-story">
      <div class="wrap">
        <div class="home-story-heading reveal-left" v-reveal>
          <span class="kicker">Three steps</span>
          <h2>You already know your job. That is all we need.</h2>
          <p>No account, no forms, and we never ask why you are looking. Start typing and you will have an answer before your tea goes cold.</p>
        </div>
        <div class="g3">
          <div class="card reveal-up" v-reveal>
            <div class="num">01</div>
            <h3>Say what you do</h3>
            <p>Type it the way you would say it out loud. Carer, cleaner, site engineer. You do not need to know what the government calls your job.</p>
          </div>
          <div class="card reveal-up" v-reveal style="--reveal-delay: 140ms">
            <div class="num">02</div>
            <h3>See where it lands</h3>
            <p>An interactive body map built from published injury data for your occupation. Tap the part that hurts and see what caused it for other women doing your job.</p>
          </div>
          <div class="card reveal-up" v-reveal style="--reveal-delay: 280ms">
            <div class="num">03</div>
            <h3>See the doors</h3>
            <p>The jobs people in your occupation actually moved into, and how many made each move. Not careers advice. Just what happened.</p>
          </div>
        </div>
        <div class="reveal-scale" v-reveal style="margin-top: 32px">
          <button class="cta cta-a" type="button" @click="goToJobFinder">Start with your job &rarr;</button>
        </div>
      </div>
    </div>

    <section class="home-story stats-band">
      <div class="wrap">
        <div class="home-story-heading reveal-up" v-reveal style="text-align: center; margin-left: auto; margin-right: auto">
          <span class="kicker">Why this exists</span>
          <h2>The soreness you are ignoring is already in the data.</h2>
          <p>Injuries in physically demanding work are recorded, counted and published. Almost nobody who does that work ever sees the numbers.</p>
        </div>
        <div class="sgrid">
          <div class="stat reveal-up" v-reveal><b v-countup data-c="10">0</b><span>years of national injury data, read for your occupation</span><cite>Safe Work Australia</cite></div>
          <div class="stat reveal-up" v-reveal style="--reveal-delay: 200ms"><b v-countup data-c="0">0</b><span>things we store about you, because there is nowhere to put them</span><cite>By design</cite></div>
        </div>
      </div>
    </section>

    <div class="home-story">
      <div class="wrap">
        <div class="home-story-heading reveal-left" v-reveal>
          <span class="kicker">What you will see</span>
          <h2>Real numbers, and what they actually mean.</h2>
          <p>Every figure here comes from a published government dataset, and every one of them can be opened to show exactly where it came from.</p>
        </div>
        <div class="dataset-cards">
          <div class="card dataset-card reveal-left" v-reveal>
            <div class="ic" style="background: var(--blush); color: var(--plum-700)">&#9679;</div>
            <h3>Which part of you takes the load</h3>
            <p>Tap a body region and see what the work asks of that part of the body, and the leading causes recorded for this occupation. Where there are too few claims to be reliable, we show you nothing rather than a number you cannot trust.</p>
          </div>
          <div class="card dataset-card reveal-right" v-reveal style="--reveal-delay: 100ms">
            <div class="ic" style="background: var(--teal-l); color: var(--teal)">&#9679;</div>
            <h3>Where people like you went</h3>
            <p>Occupations that people who did your job actually moved into, with the share who made each move. Open one to see what the work involves and what you would need.</p>
          </div>
        </div>
      </div>
    </div>

    <div class="home-story" style="padding-top: 0">
      <div class="wrap">
        <div class="home-story-heading reveal-left" v-reveal><span class="kicker">Common questions</span><h2>Before you start</h2></div>
        <div class="qa reveal-up" v-reveal>
          <details>
            <summary>Will anyone know I looked?</summary>
            <div class="dbody">
              <p>No. There is no account, no login and no form anywhere in the tool. Nothing you type is sent anywhere or stored, and we never ask why you are looking. Close the tab and there is nothing left behind.</p>
            </div>
          </details>
          <details>
            <summary>Is this telling me to quit my job?</summary>
            <div class="dbody">
              <p>No. We show you published data and stop there. What you do with it is entirely yours. Plenty of people look, see the numbers, and stay exactly where they are with a better idea of what to watch for.</p>
            </div>
          </details>
          <details>
            <summary>Where do the numbers come from?</summary>
            <div class="dbody">
              <p>Injury figures come from Safe Work Australia's published workers' compensation data. Job moves come from Jobs and Skills Australia. Both are published Australian government datasets under a Creative Commons licence, and every figure in the tool has a button that shows you its publisher, its coverage period and when we retrieved it.</p>
            </div>
          </details>
          <details>
            <summary>My job is not in the list</summary>
            <div class="dbody">
              <p>Both datasets use the same national occupation classification, so we cover the occupations that appear in both. Some jobs are grouped under a broader title than you would use yourself. If yours is missing, the tool offers the closest ones we do have, and we show nothing rather than guessing at a match.</p>
            </div>
          </details>
          <details>
            <summary>I was hurt at work. Can you help?</summary>
            <div class="dbody">
              <p>Not directly. Telosia gives no medical or legal advice. The <router-link to="/hurt-at-work" style="color: var(--plum-700); font-weight: 700">Hurt at work</router-link> page lists the services that do, including WorkSafe's advisory line. That page holds no form and collects nothing.</p>
            </div>
          </details>
        </div>
      </div>
    </div>

    <div class="home-story" style="padding-top: 0">
      <div class="wrap">
        <div class="alert-box reveal-scale" v-reveal>
          <h2>It takes about a minute.</h2>
          <p>You do not have to decide anything today. You just have to know what the job is doing to you.</p>
          <div class="hrow"><button class="cta cta-a" type="button" @click="goToJobFinder">Check my job &rarr;</button></div>
        </div>
      </div>
    </div>
  </section>
</template>
