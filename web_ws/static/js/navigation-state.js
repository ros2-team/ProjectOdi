/* Keep the sidebar selection in sync with the robot-driven screen.
   This does not change mission state or intercept commands. */
(() => {
  const forced = new URLSearchParams(location.search).get('screen');

  function missionState() {
    if (forced) return forced;
    try {
      return typeof S !== 'undefined' && S.mission ? S.mission : 'IDLE';
    } catch (_) {
      return 'IDLE';
    }
  }

  function activeNav(mission) {
    if (['NORMAL', 'NORMAL_STARTING', 'NORMAL_STOPPING'].includes(mission)) return 'normal';
    if (['PREPARING', 'EXPLORING', 'RETURNING', 'REFLECTING', 'RESETTING', 'ERROR'].includes(mission)) return 'explore';
    return 'home';
  }

  function sync() {
    const mission = missionState();
    document.body.dataset.mission = mission.toLowerCase();
    const active = activeNav(mission);

    document.querySelectorAll('.site-header [data-nav]').forEach(link => {
      const shouldBeCurrent = link.dataset.nav === active;
      if (shouldBeCurrent) {
        if (link.getAttribute('aria-current') !== 'page') link.setAttribute('aria-current', 'page');
      } else if (link.hasAttribute('aria-current')) {
        link.removeAttribute('aria-current');
      }
    });
  }

  sync();
  window.setInterval(sync, 1000);
})();
