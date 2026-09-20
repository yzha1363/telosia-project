<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <section id="about-us-view" class="page-view" aria-labelledby="about-us-title">
    <div class="about-hero-band">
      <div class="about-hero-band-inner">
        <div class="about-hero-band-text">
          <span class="kicker">About us</span>
          <h1 id="about-us-title">About us</h1>
          <p>
            Telosia shows you what a job asks of your body, and where people who did that job went next.
          </p>
          <p>
            Injury data and job movement data are both published in Australia. They sit with different agencies and
            are almost never read together. We joined them.
          </p>
        </div>
      </div>
    </div>

    <div class="wrap" style="padding-bottom: 92px">
      <h2 style="font-size: clamp(1.875rem, 3.4vw, 2.75rem); margin-bottom: 20px">What it <em>does</em></h2>
      <ul class="plain-list do" style="margin-bottom: 56px">
        <li>Shows the physical demands recorded against your occupation, in plain language</li>
        <li>Shows where people in that job actually moved, from observed moves not advice</li>
        <li>Tells you whether a move takes load off your body or puts more on</li>
        <li>Asks for nothing. No account, no login, nothing you type is stored</li>
      </ul>

      <h2 style="font-size: clamp(1.875rem, 3.4vw, 2.75rem); margin-bottom: 20px">Where the data <em>comes</em> from</h2>
      <div class="about-source-cards">
        <div class="help-card amber">
          <h3>Safe Work Australia</h3>
          <p>Injury and hazard records, by occupation.</p>
        </div>
        <div class="help-card">
          <h3>Jobs and Skills Australia</h3>
          <p>Job moves, pay, hours and automation exposure.</p>
        </div>
      </div>
      <p style="color: var(--slate); margin: 20px 0 56px">Every figure carries its publisher, coverage period and the date we retrieved it.</p>

      <h2 style="font-size: clamp(1.875rem, 3.4vw, 2.75rem); margin-bottom: 20px">Who <em>built</em> it</h2>
      <p style="color: var(--slate); max-width: 72ch; margin-bottom: 56px">
        Six postgraduate students at Monash University, as part of an industry studio project. We are not a
        regulator and not a recruiter, and we have no commercial interest in where you go next.
      </p>

      <h2 style="font-size: clamp(1.875rem, 3.4vw, 2.75rem); margin-bottom: 20px">What Telosia is <em>not</em></h2>
      <div class="help-card">
        <p>
          Telosia reports patterns across occupations. It is not a prediction about you, and it is not medical or
          safety advice. If you have been hurt at work, see
          <RouterLink to="/hurt-at-work" style="color: var(--plum-700); font-weight: 700">Hurt at work</RouterLink>.
        </p>
      </div>
    </div>
  </section>
</template>
