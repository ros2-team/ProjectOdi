/* Home dashboard presentation helpers.
   Mission commands and state ownership stay in exploring.js.
   This file only reshapes the IDLE DOM after renderIdle() creates it. */

(() => {
  const STATUS_COPY = {
    IDLE: ['IDLE', '새로운 탐험을 기다리고 있어요.'],
    PREPARING: ['PREPARING', '탐험을 시작할 준비를 하고 있어요.'],
    EXPLORING: ['EXPLORING', '새로운 발견을 찾아 탐험하고 있어요.'],
    RETURNING: ['RETURNING', '탐험을 마치고 출발 위치로 돌아가고 있어요.'],
    REFLECTING: ['REFLECTING', '오늘의 경험을 정리해 일기를 만들고 있어요.'],
    COMPLETED: ['COMPLETED', '오늘의 탐험과 기록을 모두 마쳤어요.'],
    NORMAL: ['NORMAL', '주변을 둘러보며 반응하고 있어요.'],
    NORMAL_STARTING: ['NORMAL', '일반 모드를 준비하고 있어요.'],
    NORMAL_STOPPING: ['NORMAL', '일반 모드를 마무리하고 있어요.'],
    RESETTING: ['RESETTING', '다음 활동을 위해 상태를 정리하고 있어요.'],
    ERROR: ['ERROR', '연결 상태를 확인한 뒤 다시 시작해 주세요.']
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  function missionState() {
    try {
      return typeof S !== 'undefined' && S.mission ? S.mission : 'IDLE';
    } catch (_) {
      return 'IDLE';
    }
  }

  function clickExistingButton(id) {
    const button = document.getElementById(id);
    if (!button || button.disabled) return false;
    button.click();
    return true;
  }

  function bindSidebarActions() {
    $$('[data-dashboard-action]').forEach(link => {
      if (link.dataset.bound === '1') return;
      link.dataset.bound = '1';
      link.addEventListener('click', event => {
        event.preventDefault();
        if (link.getAttribute('aria-disabled') === 'true') return;
        const action = link.dataset.dashboardAction;
        if (action === 'explore') clickExistingButton('startBtn');
        if (action === 'normal') clickExistingButton('normalBtn');
      });
    });
  }

  function enhanceIdle() {
    const idle = $('.idle');
    if (!idle || idle.dataset.dashboardEnhanced === '1') return;
    idle.dataset.dashboardEnhanced = '1';

    const hero = $('.welcome', idle);
    if (hero) {
      const kicker = $('.section-kicker', hero);
      const title = $('h1', hero);
      const copy = $('p', hero);
      const tags = $('.welcome-tags', hero);

      if (kicker) kicker.textContent = 'EXPLORATION DIARY ROBOT';
      if (title) title.innerHTML = '작지만,<br>세상을 탐험하는 로봇 <span class="odi-word">ODI</span>';
      if (copy) copy.innerHTML = '스스로 공간을 탐험하고 새로운 대상을 발견하면,<br>호기심을 따라 관찰하고 그 경험을 일기로 남깁니다.';
      if (tags) tags.innerHTML = '<span>탐험</span><i>·</i><span>발견</span><i>·</i><span>관찰</span><i>·</i><span>기록</span>';

      if (!$('.hero-cta', hero)) {
        const cta = document.createElement('button');
        cta.className = 'hero-cta';
        cta.type = 'button';
        cta.textContent = '지금 탐험하러 가기  →';
        cta.addEventListener('click', () => clickExistingButton('startBtn'));
        (tags || copy || title)?.after(cta);
      }
    }

    const live = $('.live-card', idle);
    if (live) {
      const kicker = $('.section-heading .section-kicker', live);
      const heading = $('.section-heading h2', live);
      if (kicker) kicker.textContent = "TODAY'S ODI";
      if (heading) heading.textContent = '오늘의 오디';

      if (!$('.today-status', live)) {
        const status = document.createElement('div');
        status.className = 'today-status';
        status.innerHTML = `
          <span class="today-label">현재 상태</span>
          <strong id="todayMission">IDLE</strong>
          <span class="today-dot" aria-hidden="true"></span>
          <p id="todayMissionCopy">새로운 탐험을 기다리고 있어요.</p>`;
        const watch = $('.watch', live);
        if (watch) live.insertBefore(status, watch);
        else live.appendChild(status);
      }

      const watchLabel = $('.watchfoot span:first-child', live);
      if (watchLabel) watchLabel.textContent = '오디가 보고 있는 화면';
    }

    const modeHeading = $('#modeHeading', idle);
    if (modeHeading) modeHeading.textContent = '오디와 무엇을 해볼까요?';

    const memoryHeading = $('.memory-section .section-heading h2', idle);
    if (memoryHeading) memoryHeading.textContent = '최근 탐험 일기';

    bindSidebarActions();
    syncDashboard();
  }

  function syncDashboard() {
    const mission = missionState();
    const [label, copy] = STATUS_COPY[mission] || [mission, '오디의 현재 상태를 확인하고 있어요.'];
    const stateEl = document.getElementById('todayMission');
    const copyEl = document.getElementById('todayMissionCopy');
    if (stateEl) stateEl.textContent = label;
    if (copyEl) copyEl.textContent = copy;

    const exploreButton = document.getElementById('startBtn');
    const normalButton = document.getElementById('normalBtn');
    const idleReady = mission === 'IDLE';

    $$('[data-dashboard-action="explore"]').forEach(link => {
      link.setAttribute('aria-disabled', String(!idleReady || !exploreButton || exploreButton.disabled));
    });
    $$('[data-dashboard-action="normal"]').forEach(link => {
      link.setAttribute('aria-disabled', String(!idleReady || !normalButton || normalButton.disabled));
    });

    const heroButton = $('.hero-cta');
    if (heroButton) {
      heroButton.disabled = !idleReady || !exploreButton || exploreButton.disabled;
      if (exploreButton && exploreButton.disabled && exploreButton.textContent.includes('깨우는 중')) {
        heroButton.textContent = '탐험을 준비하고 있어요…';
      } else {
        heroButton.textContent = '지금 탐험하러 가기  →';
      }
    }
  }

  function init() {
    bindSidebarActions();
    enhanceIdle();

    const screen = document.getElementById('screen');
    if (screen) {
      new MutationObserver(() => {
        enhanceIdle();
        syncDashboard();
      }).observe(screen, { childList: true, subtree: true });
    }

    window.setInterval(syncDashboard, 1000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
