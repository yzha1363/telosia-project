<script setup lang="ts">
import { computed } from 'vue'
import type { BodyRegion, BodyRegionName } from '../data/types'
import { physicalDemandColorClass } from '../utils/riskColor'
import bodyFrontUrl from '../assets/body-front.png'

const props = defineProps<{
  activeRegion: BodyRegionName | null
  regions: BodyRegion[]
}>()

const emit = defineEmits<{ select: [region: BodyRegionName] }>()

// Each entry is one clickable shape on the body outline — one path per side, traced
// against body-front.png in a design tool (not hand-measured). "Whole body and fall
// risk" isn't a specific body part, so it has no shape here — it's still selectable from
// the legend list below, same as every other region.
interface ShapeDef {
  region: BodyRegionName
  d: string
}

const frontShapes: ShapeDef[] = [
  {
    region: 'Lower back',
    d: 'M 374 667 L 374 675 L 403 689 L 436 709 L 469 735 L 507 773 L 518 772 L 555 735 L 588 709 L 616 692 L 650 675 L 647 662 L 640 647 L 636 634 L 621 604 L 611 588 L 601 565 L 599 546 L 602 529 L 582 536 L 550 541 L 520 543 L 474 541 L 437 535 L 421 529 L 423 540 L 423 558 L 419 572 L 387 634 Z',
  },
  {
    region: 'Shoulders and upper arms',
    d: 'M 418 276 L 414 278 L 411 278 L 410 279 L 405 279 L 404 280 L 399 280 L 398 281 L 393 281 L 392 282 L 389 282 L 383 285 L 381 285 L 369 291 L 365 295 L 364 295 L 353 306 L 352 309 L 350 311 L 345 321 L 345 323 L 344 324 L 344 326 L 342 330 L 341 337 L 340 338 L 339 348 L 338 349 L 338 355 L 337 356 L 337 394 L 336 395 L 336 417 L 335 418 L 334 432 L 333 433 L 332 443 L 331 444 L 331 448 L 330 449 L 330 453 L 329 454 L 329 459 L 328 460 L 328 464 L 327 465 L 327 469 L 326 470 L 326 475 L 325 476 L 325 481 L 324 482 L 323 492 L 322 493 L 322 497 L 321 498 L 321 503 L 320 504 L 320 508 L 319 509 L 319 512 L 318 513 L 318 516 L 317 517 L 317 521 L 316 522 L 320 524 L 325 525 L 328 527 L 330 527 L 334 529 L 341 530 L 345 532 L 348 532 L 349 533 L 352 533 L 353 534 L 356 534 L 357 535 L 362 535 L 363 536 L 370 536 L 371 537 L 373 536 L 374 529 L 376 525 L 376 522 L 378 518 L 378 515 L 381 509 L 381 506 L 383 502 L 383 498 L 385 494 L 385 491 L 386 490 L 386 488 L 388 484 L 388 481 L 389 480 L 389 477 L 391 473 L 391 470 L 392 469 L 392 466 L 393 465 L 393 462 L 394 461 L 394 458 L 395 457 L 395 453 L 396 452 L 396 450 L 398 446 L 398 442 L 399 441 L 399 428 L 400 427 L 400 415 L 401 414 L 401 405 L 402 404 L 402 399 L 403 398 L 403 394 L 404 393 L 404 390 L 405 389 L 405 386 L 406 385 L 406 382 L 407 381 L 407 378 L 408 377 L 408 374 L 409 373 L 409 370 L 410 369 L 410 366 L 411 365 L 411 362 L 412 361 L 412 358 L 413 357 L 413 354 L 414 353 L 414 350 L 415 349 L 415 346 L 416 345 L 416 342 L 417 341 L 417 338 L 418 337 L 418 333 L 419 332 L 419 327 L 420 326 L 420 318 L 421 317 L 421 295 L 420 294 L 420 286 L 419 285 L 419 280 L 418 279 Z',
  },
  {
    region: 'Shoulders and upper arms',
    d: 'M 606 277 L 605 279 L 605 284 L 604 285 L 604 293 L 603 294 L 603 318 L 604 319 L 604 327 L 605 328 L 606 338 L 607 339 L 607 342 L 608 343 L 608 346 L 609 347 L 609 350 L 610 351 L 610 354 L 611 355 L 611 358 L 612 359 L 612 362 L 613 363 L 613 366 L 614 367 L 614 370 L 615 371 L 615 374 L 616 375 L 616 378 L 617 379 L 617 382 L 618 383 L 618 386 L 619 387 L 619 390 L 620 391 L 620 394 L 621 395 L 621 399 L 622 400 L 622 405 L 623 406 L 623 414 L 624 415 L 624 428 L 625 429 L 625 442 L 626 443 L 626 451 L 627 452 L 628 460 L 630 464 L 630 467 L 631 468 L 631 471 L 632 472 L 633 479 L 634 480 L 634 482 L 636 486 L 636 489 L 638 493 L 638 496 L 640 500 L 640 503 L 642 507 L 642 510 L 643 511 L 643 513 L 645 517 L 645 520 L 647 524 L 647 527 L 648 528 L 649 535 L 650 537 L 653 537 L 654 536 L 661 536 L 662 535 L 667 535 L 668 534 L 671 534 L 672 533 L 679 532 L 683 530 L 690 529 L 691 528 L 696 527 L 699 525 L 704 524 L 706 523 L 706 521 L 705 520 L 705 516 L 704 515 L 704 512 L 703 511 L 703 507 L 702 506 L 702 502 L 701 501 L 701 496 L 700 495 L 700 492 L 699 491 L 698 479 L 697 478 L 697 474 L 696 473 L 696 469 L 695 468 L 695 464 L 694 463 L 694 459 L 693 458 L 693 453 L 692 452 L 692 447 L 691 446 L 691 441 L 690 440 L 690 437 L 689 436 L 689 430 L 688 429 L 688 423 L 687 422 L 687 415 L 686 414 L 686 368 L 685 367 L 685 355 L 684 354 L 683 341 L 682 340 L 682 337 L 681 336 L 681 333 L 680 332 L 680 329 L 679 328 L 678 323 L 672 311 L 670 309 L 669 306 L 657 294 L 656 294 L 653 291 L 650 290 L 646 287 L 644 287 L 639 284 L 637 284 L 633 282 L 630 282 L 629 281 L 625 281 L 624 280 L 620 280 L 619 279 L 614 279 L 613 278 L 609 278 L 608 277 Z',
  },
  {
    region: 'Hands and wrists',
    d: 'M 306 696 C 293 687 277 682 260 682 C 258 692 255 704 251 716 C 247 726 241 734 231 739 L 214 757 L 198 788 L 196 795 L 190 808 L 193 813 L 198 814 L 205 811 L 210 804 L 211 805 L 206 839 L 203 860 L 203 866 L 210 867 L 210 873 L 214 877 L 219 876 L 223 871 L 225 873 L 229 873 L 235 868 L 239 862 L 244 863 L 248 860 L 259 840 L 279 795 L 286 771 L 288 745 L 302 710 C 304 705 305 700 306 696 Z',
  },
  {
    region: 'Hands and wrists',
    d: 'M 718 696 C 731 687 747 682 764 682 C 766 692 769 704 773 716 C 777 726 783 734 793 739 L 810 757 L 826 788 L 828 795 L 834 808 L 831 813 L 826 814 L 819 811 L 814 804 L 813 805 L 818 839 L 821 860 L 821 866 L 814 867 L 814 873 L 810 877 L 805 876 L 801 871 L 799 873 L 795 873 L 789 868 L 785 862 L 780 863 L 776 860 L 765 840 L 745 795 L 738 771 L 736 745 L 722 710 C 720 705 719 700 718 696 Z',
  },
  {
    region: 'Knees',
    d: 'M 445 991 L 435 994 L 425 999 L 415 1007 L 419 1045 L 419 1072 L 437 1082 L 445 1084 L 459 1084 L 476 1078 L 484 1073 L 494 1064 L 498 1042 L 498 1016 L 486 1004 L 469 994 L 459 991 Z',
  },
  {
    region: 'Knees',
    d: 'M 564 991 L 554 994 L 544 999 L 537 1004 L 525 1016 L 526 1049 L 529 1064 L 539 1073 L 556 1082 L 564 1084 L 578 1084 L 591 1080 L 604 1072 L 604 1045 L 608 1007 L 598 999 L 588 994 L 578 991 Z',
  },
  {
    region: 'Legs and feet',
    d: 'M 494 1065 L 484 1074 L 476 1079 L 459 1085 L 445 1085 L 437 1083 L 419 1073 L 419 1080 L 412 1112 L 410 1130 L 410 1153 L 413 1180 L 419 1209 L 429 1243 L 443 1301 L 450 1338 L 449 1376 L 451 1382 L 451 1395 L 443 1437 L 428 1481 L 428 1491 L 433 1498 L 437 1499 L 439 1502 L 443 1504 L 448 1504 L 454 1508 L 461 1507 L 463 1510 L 469 1512 L 474 1511 L 476 1509 L 483 1514 L 494 1513 L 499 1508 L 501 1503 L 501 1490 L 504 1480 L 504 1464 L 500 1440 L 500 1410 L 501 1409 L 501 1399 L 499 1391 L 500 1365 L 493 1341 L 490 1311 L 492 1253 L 494 1245 L 494 1236 L 499 1206 L 502 1175 L 500 1137 L 492 1094 L 492 1073 Z',
  },
  {
    region: 'Legs and feet',
    d: 'M 529 1065 L 531 1073 L 531 1094 L 523 1137 L 521 1175 L 524 1206 L 526 1213 L 529 1245 L 531 1253 L 533 1311 L 530 1341 L 523 1365 L 523 1377 L 524 1378 L 524 1391 L 522 1399 L 523 1440 L 519 1464 L 519 1480 L 522 1490 L 522 1503 L 524 1508 L 529 1513 L 540 1514 L 547 1509 L 549 1511 L 554 1512 L 560 1510 L 562 1507 L 569 1508 L 575 1504 L 580 1504 L 584 1502 L 586 1499 L 590 1498 L 595 1491 L 595 1481 L 580 1437 L 572 1395 L 572 1382 L 574 1376 L 573 1338 L 580 1301 L 594 1243 L 604 1209 L 610 1180 L 613 1153 L 613 1130 L 611 1112 L 604 1080 L 604 1073 L 586 1083 L 578 1085 L 564 1085 L 547 1079 L 539 1074 Z',
  },
]

const regionMap = computed(() => new Map(props.regions.map((r) => [r.region, r])))

const classFor = computed(() => (region: BodyRegionName) => physicalDemandColorClass(regionMap.value.get(region)?.score))

// Only regions with a published score stay visibly coloured all the time, like a heatmap.
const hasScore = (region: BodyRegionName) => (regionMap.value.get(region)?.score ?? null) !== null

const legendOrder = computed(() =>
  [...regionMap.value.values()]
    .filter((r) => r.score !== null)
    .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
    .map((r) => r.region as BodyRegionName),
)

function select(region: BodyRegionName) {
  emit('select', region)
}

function onRegionKeydown(event: KeyboardEvent, region: BodyRegionName) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    select(region)
  }
}
</script>

<template>
  <div class="body-map-grid">
    <div class="body-map-primary">
      <svg class="body-map" viewBox="0 0 1024 1536" role="img" aria-labelledby="body-map-title">
        <title id="body-map-title">Interactive map of body regions</title>
        <image :href="bodyFrontUrl" x="0" y="0" width="1024" height="1536" />

        <g
          v-for="(shape, i) in frontShapes"
          :key="`${shape.region}-${i}`"
          class="region-button"
          :class="{ active: activeRegion === shape.region }"
          role="button"
          :data-region="shape.region"
          tabindex="0"
          :aria-label="shape.region"
          :data-testid="`button-region-${shape.region.toLowerCase().replaceAll(' ', '-')}`"
          @click="select(shape.region)"
          @keydown="onRegionKeydown($event, shape.region)"
        >
          <path
            class="region"
            :class="[classFor(shape.region), { 'always-on': hasScore(shape.region) }]"
            :d="shape.d"
          />
        </g>
      </svg>

      <slot name="note" />
    </div>

    <div class="body-map-side">
      <div class="risk-legend">
        <div
          v-for="key in legendOrder"
          :key="key"
          class="risk-row"
          :class="{ active: activeRegion === key }"
          :data-region="key"
        >
          <button class="region-legend-button" type="button" @click="select(key)">
            <span class="swatch" :class="classFor(key)"></span>
            <span>{{ key }}</span>
          </button>
        </div>
      </div>

      <slot name="detail" />
    </div>
  </div>
</template>
