/* ============================================================
   exploring.js — 탐험 화면

   DOM 을 다시 만들지 않는다.
   1초마다 innerHTML 을 갈아치우면 <img> 가 매번 다시 로드돼서
   카메라와 지도가 깜빡인다. 값만 제자리에서 바꾼다.

   시나리오는 서버에만 있다 (bridge/fake.py).
   여기 복사해두면 두 곳이 어긋난다.
   ============================================================ */

/* 브리지가 내려주는 모양. bridge/state.py 의 blank_state() 와 1:1. */
const S = {
  mission: 'EXPLORING',
  behavior: 'EXPLORE',
  explore_mode: 'FRONTIER',
  elapsed_sec: 0,
  motivation: 1,
  observed_count: 0,
  queue: [],
  camera: null,
  map: null,
  discoveries: []
};

const FEED_MAX = 5;      // 넘치면 우측 컬럼만 길어져 좌우 높이가 어긋난다

const $ = id => document.getElementById(id);
const el = {
  phase: $('phase'), mode: $('mode'), head: $('head'), clock: $('clock'),
  fill: $('fill'), drive: $('drive'), cam: $('cam'), shotAt: $('shotAt'),
  mapbox: $('mapbox'), queue: $('queue'), feed: $('feed'),
  offline: $('offline'), offlineMsg: $('offlineMsg'), offlineAge: $('offlineAge')
};

let pulseUntil = 0, lastMotivation = 1;
const seen = new Set();
const freshOf = k => seen.has(k) ? '' : (seen.add(k), ' fresh');

/* ── 그리기 ──────────────────────────────────────────── */

function paint(){
  const returning = S.mission === 'RETURNING';

  el.phase.textContent = returning ? '복귀 중' : '탐험 중';
  el.mode.textContent  = returning ? 'RETURN' : S.explore_mode;
  el.head.textContent  = returning ? SAY.RETURNING : (SAY[S.behavior] || SAY.EXPLORE);
  el.clock.textContent = clock(S.elapsed_sec);

  /* 의욕이 뭉텅 깎이면 한 번 깜빡인다 */
  if(S.motivation < lastMotivation - 0.02) pulseUntil = Date.now() + 900;
  lastMotivation = S.motivation;

  const pct = Math.round(S.motivation * 100);
  const dropping = Date.now() < pulseUntil;
  el.fill.style.width = pct + '%';
  el.fill.classList.toggle('drop', dropping);
  el.drive.classList.toggle('spent', dropping);
  el.drive.textContent = pct + '%' + (S.observed_count ? ` · 관찰 ${S.observed_count}` : '');

  paintCamera();
  paintMap();
  paintFeed();
}

/* MJPEG 스트림은 <img> 를 한 번만 만들고 다시는 건드리지 않는다.
   매번 교체하면 32KB 를 새로 받느라 깜빡인다. 브라우저가 알아서 이어 그린다. */
function paintCamera(){
  if(S.camera && !el.cam.dataset.stream){
    el.cam.dataset.stream = '1';
    el.cam.innerHTML = '<img src="/camera/stream" alt="Odi가 보는 화면">';
  }
  el.shotAt.textContent = S.camera?.at || '—';
}

function paintMap(){
  const m = S.map;

  if(!m || !m.url){
    if(el.mapbox.dataset.mode !== 'wait'){
      el.mapbox.dataset.mode = 'wait';
      el.mapbox.innerHTML = '<div class="wait">지도를 그리는 중</div>';
    }
    return;
  }

  /* map.seq 가 올라갔을 때만 PNG 를 다시 받는다 */
  if(el.mapbox.dataset.seq !== String(m.seq)){
    el.mapbox.dataset.seq = String(m.seq);
    el.mapbox.dataset.mode = 'map';
    el.mapbox.innerHTML =
      `<img src="${m.url}" alt="탐험 지도">
       <svg class="layer" viewBox="0 0 ${m.width} ${m.height}"
            preserveAspectRatio="none" aria-hidden="true">
         <polyline id="trail" fill="none" stroke="#F0A649" stroke-width="1.5"
                   stroke-linejoin="round" opacity=".85"
                   points="${(m.path || []).map(p => p.join(',')).join(' ')}"/>
         ${(m.markers || []).map(k => k.action === 'OBSERVE'
            ? `<circle cx="${k.x}" cy="${k.y}" r="4" fill="#F0A649"/>`
            : `<circle cx="${k.x}" cy="${k.y}" r="2.5" fill="#8DA49F" opacity=".55"/>`
          ).join('')}
         <circle id="pose" cx="${m.pose?.[0] || 0}" cy="${m.pose?.[1] || 0}" r="3.5" fill="#E9EFEC"/>
       </svg>`;
    return;
  }

  /* 같은 지도면 경로와 현재 위치만 갱신 — 이미지는 건드리지 않는다 */
  const trail = el.mapbox.querySelector('#trail');
  if(trail && m.path) trail.setAttribute('points', m.path.map(p => p.join(',')).join(' '));
  const pose = el.mapbox.querySelector('#pose');
  if(pose && m.pose){ pose.setAttribute('cx', m.pose[0]); pose.setAttribute('cy', m.pose[1]); }
}

/* 피드는 내용이 바뀔 때만 다시 그린다 */
function paintFeed(){
  el.queue.hidden = !S.queue.length;
  if(S.queue.length) el.queue.textContent = '다음 차례 · ' + S.queue.join(', ');

  const sig = S.discoveries
    .map(d => `${d.detection_id}:${d.decision?.action || '-'}:${d.observed ? 1 : 0}`)
    .join('|');
  if(el.feed.dataset.sig === sig) return;
  el.feed.dataset.sig = sig;

  if(!S.discoveries.length){
    el.feed.innerHTML =
      '<p class="empty">아직 아무것도 못 만났어요.<br>계속 돌아다니는 중입니다.</p>';
    return;
  }

  const rest = S.discoveries.length - FEED_MAX;
  el.feed.innerHTML =
    S.discoveries.slice(0, FEED_MAX).map(entryHtml).join('') +
    (rest > 0 ? `<div class="more">그 외 ${rest}개는 일기에서</div>` : '');
}

/* IGNORE도 반드시 남긴다. 지나친 게 보여야 고른 게 의미를 갖는다.
   사진은 지금 보고 있는 것에만 — 끝난 것까지 달면 우측만 계속 길어진다. */
function entryHtml(d){
  const a = d.decision?.action;
  const cls = a === 'IGNORE' ? 'ignore' : (d.observed ? 'done' : 'observe');
  const tag = a === 'IGNORE'  ? ''
            : d.observed      ? '<span class="tag done">관찰 완료</span>'
            : a === 'OBSERVE' ? '<span class="tag observe">관찰 중</span>'
                              : '<span class="tag observe">살펴보는 중</span>';

  const live = a !== 'IGNORE' && !d.observed;
  const shot = live
    ? `<div class="photo">${d.photo_url ? `<img src="${d.photo_url}" alt="">` : '사진'}</div>`
    : '';
  const reason = why(d);

  return `
  <div class="entry ${cls}${freshOf(d.detection_id + ':' + (a || 'new') + ':' + (d.observed ? 1 : 0))}">
    <div class="name mono">${nameOf(d)}</div>
    <div class="said">${describe(d)}</div>
    ${shot}${tag}
    ${a === 'IGNORE' ? '' : `<div class="meta">${d.at}${reason ? ' · ' + reason : ''}</div>`}
  </div>`;
}

/* ── 브리지 연결 ─────────────────────────────────────
   상태의 주인은 로봇이다. 웹은 받은 것만 그린다. */

const WS_URL = `ws://${location.host || 'localhost:8000'}/ws`;
let lastMsgAt = 0, everConnected = false;

function connect(){
  let ws;
  try { ws = new WebSocket(WS_URL); } catch(e){ return setTimeout(connect, 2000); }

  ws.onopen    = () => { everConnected = true; };
  ws.onmessage = e => {
    lastMsgAt = Date.now();
    try { Object.assign(S, JSON.parse(e.data)); paint(); }
    catch(err){ console.error('bad payload', err); }
  };
  ws.onclose = () => setTimeout(connect, 2000);
  ws.onerror = () => {};
}

/* 마지막 수신 시각으로 연결 상태를 판단한다.
   화면이 멈춘 건지 로봇이 멈춘 건지 구분되어야 한다. */
setInterval(() => {
  const age = lastMsgAt ? (Date.now() - lastMsgAt) / 1000 : 999;
  el.offline.hidden = age < 5;
  if(age < 5) return;

  if(everConnected){
    el.offlineMsg.textContent = '로봇과 연결이 끊겼어요. 화면은 마지막으로 받은 상태입니다.';
    el.offlineAge.textContent = `${Math.round(age)}초 전`;
  } else {
    el.offlineMsg.textContent = '브리지에 연결하지 못했어요. run.py 가 실행 중인지 확인해 주세요.';
    el.offlineAge.textContent = WS_URL;
  }
}, 1000);

paint();
connect();