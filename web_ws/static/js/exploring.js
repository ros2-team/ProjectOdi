/* ┌─ 연결 지도 ───────────────────────────────────────────────
 * │ 로드되는 곳 : static/index.html (schema.js 다음)
 * │
 * │ 데이터를 받는 곳 :
 * │     ws://호스트/ws        → bridge/app.py 의 ws()
 * │     /camera/stream        → bridge/app.py 의 camera_stream()
 * │
 * │ schema.js 에서 쓰는 것 : SAY, describe(), why(), nameOf(), clock()
 * │
 * │ ★ 아래 S 객체 = bridge/state.py 의 blank_state() 와 1:1
 * │ ★ el 객체의 id = static/index.html 의 id 와 1:1
 * │   둘 중 하나만 바꾸면 그 부분이 조용히 안 나온다.
 * └───────────────────────────────────────────────────────────*/

/* ============================================================
   exploring.js — 탐험 화면

   ────────────────────────────────────────────────────────────
   이 파일의 가장 중요한 설계 결정 : DOM 을 다시 만들지 않는다
   ────────────────────────────────────────────────────────────

   흔히 이렇게 짠다.

       setInterval(() => {
         document.getElementById('app').innerHTML = 화면전체만들기();
       }, 1000);

   간단하고 프로토타입에선 잘 돌아간다. 우리도 처음엔 이랬다.
   그런데 이미지가 들어오는 순간 무너진다.

   innerHTML 을 갈아치우면 안에 있던 모든 엘리먼트가 파괴되고
   새로 만들어진다. <img> 도 새로 생기니까 이미지를 처음부터
   다시 다운로드한다. 1 초마다. CSS 애니메이션도 매초 다시 재생된다.

   그래서 지금은 이렇게 한다.

       el.clock.textContent = clock(S.elapsed_sec);   // 값만 바꾼다
       el.fill.style.width  = pct + '%';              // 스타일만 바꾼다

   DOM 은 처음 한 번만 만들고, 그 뒤로는 필요한 값만 제자리에서 바꾼다.
   React 같은 프레임워크가 내부적으로 하는 일을 손으로 하는 것이다.
   프레임워크를 쓸 만큼 복잡하지 않으니 직접 했다.

   ────────────────────────────────────────────────────────────
   시나리오는 서버에만 있다
   ────────────────────────────────────────────────────────────

   가짜 데모 시나리오는 bridge/fake.py 한 곳에만 있다.
   여기에도 복사해두면 흐름을 고칠 때 한쪽만 고치고 넘어가게 된다.
   ============================================================ */


/* 브리지가 WebSocket 으로 내려주는 상태.
   ★ bridge/state.py 의 blank_state() 와 키 이름이 1:1 로 같아야 한다.
     한쪽만 바꾸면 에러 없이 화면만 조용히 안 바뀐다. */
const S = {
  mission: 'EXPLORING',
  behavior: 'EXPLORE',
  explore_mode: 'FRONTIER',
  session_id: '',
  elapsed_sec: 0,
  motivation: 1,
  observed_count: 0,
  queue: [],
  camera: null,
  map: null,
  discoveries: [],

  /* 배터리. {"percent": 87, "charging": false, "ready": true, "ready_pct": 40}
     ready 는 브리지가 계산해서 내려준다 — 문턱값을 프론트에 또 적어두면
     config.py 만 고치고 여기를 안 고치는 사고가 난다. */
  battery: null,

  /* 온·습도. 아직 센서가 확정되지 않아 항상 null 이다.
     대기 화면에 자리만 잡아뒀고, 값이 들어오면 paintIdle 이 알아서 채운다.
     기대하는 모양 : {"temp_c": 24.3, "humidity": 61, "at": "10:34:12"} */
  env: null
};

/* 피드에 한 번에 보일 최대 개수.
   제한이 없으면 발견이 쌓일수록 오른쪽 컬럼만 길어져서
   왼쪽(카메라+지도)과 높이가 어긋난다. */
const FEED_MAX = 5;


/* ────────────────────────────────────────────────────────────
   DOM 참조를 미리 잡아둔다.

   매번 getElementById 를 부르면 그때마다 문서를 뒤진다.
   1 초에 한 번이라 성능 차이는 미미하지만,
   el.clock 이라고 쓰는 게 코드를 읽기도 훨씬 쉽다.
   ──────────────────────────────────────────────────────────── */
const $ = id => document.getElementById(id);
const el = {
  screen: $('screen'), exploring: $('exploring'),
  phase: $('phase'), mode: $('mode'), head: $('head'), clock: $('clock'),
  fill: $('fill'), drive: $('drive'), cam: $('cam'), shotAt: $('shotAt'),
  mapbox: $('mapbox'), queue: $('queue'), feed: $('feed'),
  offline: $('offline'), offlineMsg: $('offlineMsg'), offlineAge: $('offlineAge')
};


/* 의욕 게이지 깜빡임 상태 */
let pulseUntil = 0;        // 이 시각까지 깜빡인다 (밀리초 타임스탬프)
let lastMotivation = 1;    // 직전 의욕값. 낙차를 감지하려고 들고 있는다

/* 이미 화면에 나타났던 항목들.
   새로 등장하는 것에만 애니메이션을 주기 위해 기록한다. */
const seen = new Set();

/* 처음 보는 항목이면 ' fresh' 클래스를 붙이고, 본 적 있으면 빈 문자열.

   (seen.add(k), ' fresh') 는 쉼표 연산자다.
   앞의 것을 실행하고 뒤의 값을 돌려준다.
   즉 "seen 에 넣고 나서 ' fresh' 를 반환" 이라는 뜻. */
const freshOf = k => seen.has(k) ? '' : (seen.add(k), ' fresh');


/* ============================================================
   화면 라우팅

   ★ 사용자가 화면을 고르는 게 아니라 미션 상태가 화면을 결정한다.
     그래서 "탐험 중인데 시작 버튼이 보인다" 같은 모순이
     구조적으로 생길 수 없다.

         IDLE        시작 화면
         PREPARING   "나갈 준비를 하고 있어요"
         EXPLORING   탐험 화면
         RETURNING   탐험 화면 ("집으로 돌아가는 중")
         REFLECTING  "오늘 있었던 일을 정리하는 중"
         COMPLETED   /diary/{session_id} 로 이동

     개발 중에는 ?screen=IDLE 처럼 주소에 붙여 강제로 볼 수 있다.
   ============================================================ */

const FORCED = new URLSearchParams(location.search).get('screen');

let lastScreen = null;   // 같은 화면을 매초 다시 그리지 않기 위해
let redirected = false;  // 일기로 두 번 이동하는 것을 막는다

/* ★ 페이지가 열려 있는 동안 COMPLETED 가 아닌 상태를 본 적이 있는가.
     이게 필요한 이유 :
       일기 화면에서 '탐험 화면' 링크로 / 에 돌아오면 상태가 아직
       COMPLETED 라서 곧바로 일기로 다시 튕긴다. 시작 화면에 갈 수가 없다.
     '탐험이 끝나는 순간을 이 페이지에서 목격했을 때만' 넘기면
     그 함정이 사라진다. */
let sawActive = false;

/* 시작 요청을 보내고 로봇의 응답을 기다리는 중인가.
   대기 화면이 매초 갱신되므로, 이게 없으면 버튼 문구가 바로 덮인다. */
let sending = false;

/* PREPARING 에 들어온 시각.
   로봇이 응답을 안 하면 여기서 영영 멈추기 때문에, 얼마나 기다렸는지
   세어두었다가 일정 시간이 지나면 빠져나갈 길을 준다. */
let preparingSince = 0;

/* 브리지에서 상태를 한 번이라도 받았는가.
   받기 전에는 S 가 초기값(EXPLORING)이라, 그걸로 화면을 판단하면
   실제 상태와 무관한 화면이 잠깐 스쳤다가 바뀐다. */
let gotData = false;

function paint(){
  /* 첫 데이터가 오기 전에는 아무것도 그리지 않는다.
     연결이 안 되면 상단 배너가 이유를 알려준다. */
  if(!gotData && !FORCED) return;

  const mission = FORCED || S.mission;

  /* ── 탐험 화면이 아니면 ────────────────────────────── */
  if(mission !== 'EXPLORING' && mission !== 'RETURNING'){
    el.exploring.hidden = true;

    if(mission === 'COMPLETED'){
      /* 탐험이 방금 끝났다면 그날의 일기로 넘긴다. */
      if(sawActive && !redirected && !FORCED){
        redirected = true;
        location.href = S.session_id ? `/diary/${S.session_id}` : '/diary';
        return;
      }
      /* 이미 끝나 있는 상태로 페이지에 들어온 경우.
         자동으로 넘기면 시작 화면에 영영 못 가므로 링크만 보여준다. */
      if(lastScreen === 'COMPLETED') return;
      lastScreen = 'COMPLETED';
      renderDone();
      return;
    }

    sawActive = true;

    /* ★ 뼈대는 화면이 바뀔 때 한 번만 만든다.
         대기 화면은 카메라·배터리가 매초 갱신돼야 하는데, 매초 renderIdle()
         을 부르면 <img> 가 새로 생겨서 스트림이 끊기고 깜빡인다.
         탐험 화면과 같은 규칙 — 만들기(render)와 채우기(paint)를 나눈다. */
    if(lastScreen !== mission){
      lastScreen = mission;

      if(mission === 'IDLE')             renderIdle();
      else if(mission === 'PREPARING'){  renderInterlude('나갈 준비를 하고 있어요',
                                                         '센서와 지도를 확인하고 있어요.');
                                         preparingSince = Date.now(); }
      else if(mission === 'REFLECTING')  renderInterlude('오늘 있었던 일을 정리하는 중',
                                                         '사진을 고르고 있어요. 잠시만요.');
      else                               renderInterlude('기다리는 중', mission);
    }

    /* 값 갱신은 매초 */
    if(mission === 'IDLE')           paintIdle();
    else if(mission === 'PREPARING') paintPreparing();
    return;
  }

  /* ── 탐험 화면 ────────────────────────────────────── */
  sawActive = true;
  if(lastScreen !== 'EXPLORING'){
    lastScreen = 'EXPLORING';
    redirected = false;          // 다음 탐험을 위해 초기화
    el.screen.innerHTML = '';
    el.exploring.hidden = false;
  }

  paintExploring();
}


/* ── 대기 화면 ─────────────────────────────────────────
   집에 있는 Odi. 탐험 화면이 '지금 뭘 하고 있나'를 보여준다면
   여기는 '나갈 수 있는 상태인가'를 보여준다.

   ★ 관제 대시보드가 되지 않게 하는 규칙
     숫자가 먼저 오면 대시보드, 문장이 먼저 오고 숫자가 근거로
     따라오면 캐릭터다. 탐험 화면의 describe()/why() 와 같은 문법을 쓴다.
     그래서 배터리도 "87%" 가 아니라 "나갈 준비가 됐어요" 가 먼저다.

   ★ 시작 버튼은 여전히 유일한 초점이다.
     카메라와 배터리를 얹되, 둘 다 버튼을 '설명하는' 자리에 둔다.
     카메라 = 살아있다는 증거, 배터리 = 나갈 수 있는지의 근거. */
function renderIdle(){
  sending = false;

  el.screen.innerHTML = `
    <div class="idle">
      <div class="mark"><span></span></div>
      <h1>Odi</h1>

      <div class="watch">
        <div class="lens" id="idleCam"><div class="wait">아직 눈을 못 떴어요</div></div>
        <div class="watchfoot">
          <span>지금 보고 있는 것</span>
          <span class="mono" id="idleShotAt">—</span>
        </div>
      </div>

      <div class="vitals">
        <div class="vital" id="vBat">
          <span class="k">배터리</span>
          <span class="v mono" id="vBatPct">—</span>
          <span class="bar"><i id="vBatFill"></i></span>
        </div>
        <div class="vital soon">
          <span class="k">온도</span>
          <span class="v mono">—</span>
        </div>
        <div class="vital soon">
          <span class="k">습도</span>
          <span class="v mono">—</span>
        </div>
      </div>

      <button class="start" id="startBtn">탐험 보내기</button>
      <p class="gate" id="gate">상태를 확인하는 중</p>

      <div class="past" id="pastList"></div>
    </div>`;

  document.getElementById('startBtn').addEventListener('click', startMission);

  /* 대기 화면 전용 참조. el 은 index.html 의 고정 엘리먼트를 담고 있고,
     여기 것들은 renderIdle 이 돌 때마다 새로 만들어지므로 그때 갱신한다. */
  Object.assign(el, {
    idleCam:    $('idleCam'),
    idleShotAt: $('idleShotAt'),
    vBat:       $('vBat'),
    vBatPct:    $('vBatPct'),
    vBatFill:   $('vBatFill'),
    gate:       $('gate'),
    startBtn:   $('startBtn')
  });

  loadPast();
  paintIdle();      // 첫 값을 즉시 채운다 (다음 틱까지 '—' 로 두지 않는다)
}


/* 대기 화면 값 갱신. 매초 불린다.
   paintExploring() 과 같이 DOM 을 다시 만들지 않고 제자리에서 바꾼다. */
function paintIdle(){
  if(!el.idleCam) return;      // renderIdle 이 아직 안 돌았다

  /* ── 카메라 ──────────────────────────────────────────
     탐험 화면과 완전히 같은 방식. <img> 를 딱 한 번만 만들고
     그 뒤로는 건드리지 않는다. MJPEG 은 연결을 유지한 채
     브라우저가 알아서 이어 그린다.

     /camera/stream 은 mission 과 무관하게 동작하므로
     대기 중에도 그대로 쓸 수 있다. */
  if(S.camera && !el.idleCam.dataset.stream){
    el.idleCam.dataset.stream = '1';
    el.idleCam.innerHTML = '<img src="/camera/stream" alt="Odi가 보고 있는 화면">';
  }
  el.idleShotAt.textContent = S.camera?.at || '—';

  /* ── 배터리 ──────────────────────────────────────────
     ros_link.on_battery 가 채운다. 로봇이 BatteryState 를 발행하지
     않거나 percentage 가 NaN 이면 계속 null 이다. */
  const b = S.battery;
  if(b){
    const pct = Math.max(0, Math.min(100, b.percent));
    el.vBatPct.textContent = pct + '%';
    el.vBatFill.style.width = pct + '%';
    el.vBat.classList.toggle('low', !b.ready);
    el.vBat.classList.toggle('charging', !!b.charging);
  }else{
    el.vBatPct.textContent = '—';
    el.vBatFill.style.width = '0%';
    el.vBat.classList.remove('low', 'charging');
  }

  /* ── 출발 조건 ───────────────────────────────────────
     ★ 배터리를 '모를 때'는 막지 않는다.
       센서가 아직 안 붙었거나 로봇이 발행 전일 수 있는데,
       그때 버튼이 잠기면 데모 자체가 안 된다.
       아는 것 때문에만 막고, 모르는 것 때문에는 막지 않는다.

     ★ 눌러보기 전에 이유를 알려준다.
       예전에는 눌러야 409 를 보고 알 수 있었다. */
  if(sending) return;          // 시작 요청 중이면 버튼 문구를 덮지 않는다

  const blocked = !!(b && !b.ready);
  el.startBtn.disabled = blocked;
  el.startBtn.textContent = '탐험 보내기';

  if(!b){
    el.gate.textContent = '배터리를 아직 못 읽었어요. 그래도 나갈 수는 있어요.';
  }else if(blocked){
    el.gate.textContent = b.charging
      ? `충전 중이에요. ${b.ready_pct}%가 넘으면 나갈 수 있어요.`
      : '배터리가 부족해요. 충전기에 올려 주세요.';
  }else if(b.charging){
    el.gate.textContent = '충전 중이지만 지금 나가도 괜찮아요.';
  }else{
    el.gate.textContent = '나갈 준비가 됐어요.';
  }
}

/* 지난 일기 목록. 없거나 실패하면 조용히 비워둔다 —
   시작 버튼이 주인공이라 에러 문구로 시선을 뺏을 이유가 없다. */
async function loadPast(){
  try{
    const items = await (await fetch('/api/sessions')).json();
    if(!items.length) return;
    const box = document.getElementById('pastList');
    if(!box) return;
    box.innerHTML = `
      <h2>지난 일기</h2>
      ${items.map(s => `
        <a href="/diary/${s.id}">
          <span class="d">${s.date}</span>
          <span class="t">${s.line || '(일기 없음)'}</span>
          <span class="n">관찰 ${s.observed_count}</span>
        </a>`).join('')}`;
  }catch(e){
    console.warn('지난 일기 목록을 불러오지 못했습니다', e);
  }
}

/* 탐험을 시작한다.

   ★ 상태의 주인은 로봇이다.
     버튼을 눌렀다고 화면을 EXPLORING 으로 바꾸지 않는다.
     로봇이 실제로 못 뜨면 화면만 거짓말을 하게 된다.
     명령만 보내고, 화면은 로봇이 보고한 상태를 기다린다. */
async function startMission(){
  const btn = document.getElementById('startBtn');
  if(btn){ btn.disabled = true; btn.textContent = '깨우는 중…'; }

  /* ★ paintIdle 이 매초 버튼을 되돌려놓지 않게 잠근다.
       이 플래그가 없으면 '깨우는 중…' 이 1 초 만에 '탐험 보내기' 로
       돌아가서, 눌렀는지 안 눌렀는지 알 수 없는 화면이 된다. */
  sending = true;

  try{
    const res = await fetch('/sessions', {method: 'POST'});
    if(res.status === 409){
      // 이미 탐험 중이다. 중복 시작 방지.
      sending = false;
      if(btn){ btn.disabled = false; btn.textContent = '이미 탐험 중이에요'; }
      return;
    }
  }catch(e){
    sending = false;
    if(btn){ btn.disabled = false; btn.textContent = '연결에 실패했어요'; }
    return;
  }

  /* 로봇이 PREPARING 을 보고할 때까지 버튼은 잠긴 채로 둔다.
     상태가 바뀌면 paint() 가 알아서 화면을 갈아준다. */
}

/* 이미 탐험이 끝나 있는 상태로 / 에 들어왔을 때.
   자동 전환 대신 선택지를 준다. */
function renderDone(){
  const link = S.session_id ? `/diary/${S.session_id}` : '/diary';
  el.screen.innerHTML = `
    <div class="interlude">
      <h2>오늘 탐험은 끝났어요</h2>
      <p>일기가 준비되어 있어요.</p>
      <div class="footer">
        <a href="${link}">일기 보기</a>
        <button class="link" id="homeBtn">대기 화면으로</button>
      </div>
    </div>`;

  /* ★ 링크가 아니라 버튼인 이유
       그냥 <a href="/"> 로 두면 서버 상태가 아직 COMPLETED 라서
       이 화면으로 다시 돌아온다. 상태를 IDLE 로 되돌리는 요청을
       먼저 보내야 관제 화면에 갈 수 있다. */
  document.getElementById('homeBtn').addEventListener('click', goHome);
}

function renderInterlude(title, sub){
  el.screen.innerHTML = `
    <div class="interlude">
      <div class="dots"><i></i><i></i><i></i></div>
      <h2>${title}</h2>
      <p>${sub}</p>
      <p class="hint" id="hint"></p>
    </div>`;
}


/* 로봇이 응답을 안 할 때 빠져나갈 길.

   ★ 왜 필요한가
     POST /sessions 는 로봇에게 START 를 보낼 뿐, 로봇이 실제로
     뜨는지는 보장하지 않는다. 로봇 노드가 안 떠 있으면
     MissionState 가 영영 안 와서 이 화면에 갇힌다.

     발표 중에 이렇게 되면 새로고침 말고는 방법이 없다.
     기다린 시간을 알려주고 되돌아갈 버튼을 주는 게 낫다.

   ★ 12 초인 이유
     로봇이 정상이면 보통 2~3 초 안에 EXPLORING 을 보고한다.
     너무 짧으면 정상인데도 경고가 뜨고, 너무 길면 갇힌 것처럼 느껴진다. */
function paintPreparing(){
  const hint = document.getElementById('hint');
  if(!hint || hint.dataset.on) return;      // 이미 띄웠으면 그대로 둔다

  if((Date.now() - preparingSince) / 1000 < 12) return;

  hint.dataset.on = '1';
  hint.innerHTML = `로봇이 아직 응답하지 않아요.
    <button class="link" id="cancelBtn">대기 화면으로</button>`;
  document.getElementById('cancelBtn').addEventListener('click', goHome);
}


/* 관제(대기) 화면으로 되돌아간다.

   ★ 왜 그냥 location.href = '/' 가 아닌가
     서버 상태가 COMPLETED 나 PREPARING 이면 / 로 가도 그 화면이 다시 뜬다.
     먼저 서버에 "이 세션은 다 봤다"고 알려서 상태를 IDLE 로 되돌려야 한다.

   ★ 요청이 실패해도 이동은 한다
     서버가 죽어 있으면 최소한 화면은 넘어가야 사용자가 뭘 해볼 수 있다. */
async function goHome(){
  try{
    await fetch('/sessions/home', {method: 'POST'});
  }catch(e){
    console.warn('대기 상태로 되돌리지 못했습니다', e);
  }
  location.href = '/';
}


/* ============================================================
   탐험 화면 그리기
   ============================================================ */

function paintExploring(){
  const returning = S.mission === 'RETURNING';

  /* 상단 상태 줄.
     FIRST_ENCOUNTER 같은 상태 이름을 그대로 띄우면 '로그'가 된다.
     SAY 표(schema.js)로 사람 말로 번역해야 '캐릭터'가 된다. */
  el.phase.textContent = returning ? '복귀 중' : '탐험 중';
  el.mode.textContent  = returning ? 'RETURN' : S.explore_mode;
  el.head.textContent  = returning ? SAY.RETURNING : (SAY[S.behavior] || SAY.EXPLORE);
  el.clock.textContent = clock(S.elapsed_sec);

  /* ── 의욕 게이지 ──────────────────────────────────────
     평상시엔 아주 천천히 줄고(초당 0.17%), 관찰을 마칠 때
     뭉텅 깎인다(-14%). 그 낙차를 감지해 한 번 깜빡인다.

     0.02 라는 문턱값이 중요하다. 이게 없으면 초당 소모분에도
     반응해서 게이지가 계속 깜빡거린다. */
  if(S.motivation < lastMotivation - 0.02) pulseUntil = Date.now() + 900;
  lastMotivation = S.motivation;

  const pct = Math.round(S.motivation * 100);
  const dropping = Date.now() < pulseUntil;

  el.fill.style.width = pct + '%';
  /* classList.toggle(클래스, 조건) — 조건이 참이면 붙이고 거짓이면 뗀다.
     if/else 로 add/remove 를 나눠 쓰는 것보다 간결하다. */
  el.fill.classList.toggle('drop', dropping);
  el.drive.classList.toggle('spent', dropping);
  el.drive.textContent = pct + '%' + (S.observed_count ? ` · 관찰 ${S.observed_count}` : '');

  paintCamera();
  paintMap();
  paintFeed();
}


/* MJPEG 스트림은 <img> 를 딱 한 번만 만들고 다시는 건드리지 않는다.

   매번 교체하면 32KB 를 새로 받느라 깜빡인다.
   한 번 걸어두면 브라우저가 알아서 계속 이어 그린다.

   S.camera 가 null 인 동안은 만들지 않는다.
   ros_link 가 첫 프레임을 받아야 null 에서 벗어나므로,
   카메라가 없을 때 깨진 이미지 아이콘이 뜨는 걸 막는다. */
function paintCamera(){
  if(S.camera && !el.cam.dataset.stream){
    el.cam.dataset.stream = '1';   // 만들었다는 표시. 두 번 만들지 않는다
    el.cam.innerHTML = '<img src="/camera/stream" alt="Odi가 보는 화면">';
  }
  el.shotAt.textContent = S.camera?.at || '—';
}


/* 지도. 아직 5 단계라 실제로는 안 쓰이지만 구조는 완성돼 있다.

   ★ 좌표 변환을 브리지에서 하는 이유
     지도 PNG 는 미탐색 영역을 잘라내고(crop) 만든다.
     그 crop 범위가 탐험이 진행되며 계속 바뀌는데,
     프론트는 그걸 알 도리가 없다.
     브리지가 픽셀 좌표까지 계산해서 내려주면
     프론트는 그냥 점만 찍으면 된다. */
function paintMap(){
  const m = S.map;

  if(!m || !m.url){
    /* dataset.mode 로 '이미 이 상태로 그렸다'를 기억한다.
       안 그러면 1 초마다 같은 HTML 을 다시 써서 낭비다. */
    if(el.mapbox.dataset.mode !== 'wait'){
      el.mapbox.dataset.mode = 'wait';
      el.mapbox.innerHTML = '<div class="wait">지도를 그리는 중</div>';
    }
    return;
  }

  /* map.seq 가 올라갔을 때만 PNG 를 다시 받는다.
     지도는 3 초에 한 번쯤 갱신되므로 매초 다시 받을 이유가 없다. */
   if(el.mapbox.dataset.seq !== String(m.seq)){
    el.mapbox.dataset.seq = String(m.seq);
    el.mapbox.dataset.mode = 'map';

    /* ★ 이미지와 SVG 를 같은 상자에 함께 넣는다.
       따로 두면 각자 크기를 계산해서 마커가 살짝 어긋난다.
       aspect-ratio 로 지도 비율을 고정하면 둘이 항상 같은 크기가 된다. */
    el.mapbox.innerHTML =
      `<div class="mapwrap" style="aspect-ratio:${m.width}/${m.height}">
         <img src="${m.url}" alt="탐험 지도">
         <svg class="layer" viewBox="0 0 ${m.width} ${m.height}"
              preserveAspectRatio="none" aria-hidden="true">
           <polyline id="trail" fill="none" stroke="#F0A649" stroke-width="1.5"
                     stroke-linejoin="round" opacity=".85"
                     points="${(m.path || []).map(p => p.join(',')).join(' ')}"/>
           ${(m.markers || []).map(k => k.action === 'OBSERVE'
              ? `<circle cx="${k.x}" cy="${k.y}" r="3" fill="#F0A649"/>`
              : `<circle cx="${k.x}" cy="${k.y}" r="2" fill="#8DA49F" opacity=".55"/>`
            ).join('')}
           <circle id="pose" cx="${m.pose?.[0] || 0}" cy="${m.pose?.[1] || 0}" r="2.5" fill="#E9EFEC"/>
         </svg>
       </div>`;
    return;
  }

  /* 같은 지도면 경로선과 현재 위치만 갱신한다.
     <img> 는 건드리지 않으므로 다시 다운로드되지 않는다. */
  const trail = el.mapbox.querySelector('#trail');
  if(trail && m.path) trail.setAttribute('points', m.path.map(p => p.join(',')).join(' '));
  const pose = el.mapbox.querySelector('#pose');
  if(pose && m.pose){ pose.setAttribute('cx', m.pose[0]); pose.setAttribute('cy', m.pose[1]); }
}


/* 발견 피드는 항목이 추가·변경되므로 다시 그려야 한다.
   대신 '내용이 실제로 바뀌었을 때만' 그린다.

   ★ signature 기법
     지금 상태를 짧은 문자열 하나로 요약해 두고,
     지난번과 같으면 아무것도 하지 않는다.

       "d5:OBSERVE:1|d4:IGNORE:0|d3:OBSERVE:1|..."

     발견 개수, 각각의 판단, 관찰 완료 여부가 전부 들어있어서
     이 중 하나라도 바뀌면 문자열이 달라진다.
     시계가 1 초 올라간 것만으로는 다시 그리지 않는다. */
function paintFeed(){
  el.queue.hidden = !S.queue.length;
  if(S.queue.length) el.queue.textContent = '다음 차례 · ' + S.queue.join(', ');

  const sig = S.discoveries
    .map(d => `${d.detection_id}:${d.decision?.action || '-'}:${d.observed ? 1 : 0}`)
    .join('|');
  if(el.feed.dataset.sig === sig) return;    // 똑같다 → 아무것도 안 함
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


/* 발견 항목 하나를 HTML 로.

   ★ IGNORE 를 반드시 남긴다
     지나친 물체를 화면에서 빼면 Odi 가 '눈에 띄는 걸 다 찍는 로봇'으로 보인다.
     지나친 게 보여야 '골라서 관찰한다'는 게 전달된다.
     이 프로젝트의 핵심이 호기심 판단인데, 그게 드러나는 자리가 여기뿐이다.

     대신 흐리고 작게 그린다. 시각적 무게 차이 자체가 판단을 보여준다.

   ★ 사진은 지금 보고 있는 것에만
     관찰이 끝난 항목까지 사진을 달면 오른쪽 컬럼만 계속 길어져서
     왼쪽과 높이가 어긋난다. 그리고 사진이 화면에 하나만 있으면
     시선이 자동으로 '지금 Odi 가 보고 있는 것'으로 간다. */
function entryHtml(d){
  const a = d.decision?.action;   // ?. 는 decision 이 null 이어도 안전하게 접근

  const cls = a === 'IGNORE' ? 'ignore' : (d.observed ? 'done' : 'observe');
  const tag = a === 'IGNORE'  ? ''
            : d.observed      ? '<span class="tag done">관찰 완료</span>'
            : a === 'OBSERVE' ? '<span class="tag observe">관찰 중</span>'
                              : '<span class="tag observe">살펴보는 중</span>';

  const live = a !== 'IGNORE' && !d.observed;
  const shot = live
    ? `<div class="photo">${d.photo_url ? `<img src="${d.photo_url}" alt="">` : '사진'}</div>`
    : '';

  const reason = why(d);   // "유사도 0.88 · 2번째 · 상태 다름 · 호기심 0.67"

  /* freshOf 의 키에 판단과 관찰 여부를 넣는 이유 :
     같은 물체라도 '판단 전 → 관찰 중 → 완료' 로 바뀔 때마다
     새로 나타난 것처럼 한 번씩 애니메이션되게 하려는 것이다. */
  return `
  <div class="entry ${cls}${freshOf(d.detection_id + ':' + (a || 'new') + ':' + (d.observed ? 1 : 0))}">
    <div class="name mono">${nameOf(d)}</div>
    <div class="said">${describe(d)}</div>
    ${shot}${tag}
    ${a === 'IGNORE' ? '' : `<div class="meta">${d.at}${reason ? ' · ' + reason : ''}</div>`}
  </div>`;
}


/* ============================================================
   브리지 연결

   ★ 원칙 : 상태의 주인은 로봇이다. 웹은 받은 것만 그린다.

     시작 버튼을 눌렀다고 화면을 바로 EXPLORING 으로 바꾸면 안 된다.
     로봇이 실제로 못 뜨면 화면만 거짓말을 하게 된다.
     명령은 보내되, 표시는 로봇이 보고한 것만.
   ============================================================ */

/* location.host 는 지금 보고 있는 주소의 '호스트:포트' 다.
   localhost:8000 으로 열었으면 "localhost:8000",
   192.168.0.17:8000 으로 열었으면 "192.168.0.17:8000".

   덕분에 주소를 코드에 박아넣지 않아도 되고,
   폰에서 접속해도 알아서 로봇 IP 로 붙는다. */
const WS_URL = `ws://${location.host || 'localhost:8000'}/ws`;

let lastMsgAt = 0;         // 마지막으로 메시지를 받은 시각
let everConnected = false; // 한 번이라도 붙은 적 있는지

function connect(){
  let ws;
  try {
    ws = new WebSocket(WS_URL);
  } catch(e){
    return setTimeout(connect, 2000);   // 2 초 뒤 재시도
  }

  ws.onopen = () => { everConnected = true; };

  ws.onmessage = e => {
    lastMsgAt = Date.now();
    try {
      applyState(JSON.parse(e.data));
    } catch(err){
      console.error('bad payload', err);
    }
  };

  /* 연결이 끊기면 2 초 뒤 다시 시도한다.
     서버를 재시작해도 브라우저 새로고침 없이 알아서 붙는다. */
  ws.onclose = () => setTimeout(connect, 2000);
  ws.onerror = () => {};   // onclose 가 뒤따라 오므로 여기선 아무것도 안 한다
}


/* 받은 상태를 반영하고 화면을 다시 그린다.

   Object.assign(대상, 출처) — 출처의 속성을 대상에 덮어쓴다.
   서버가 전체 상태를 보내주므로 통째로 덮어쓰면 된다.
   S = JSON.parse(...) 라고 하면 안 된다 —
   S 는 const 이기도 하고, 다른 함수들이 참조하는 객체가 바뀌어버린다. */
function applyState(data){
  Object.assign(S, data);
  gotData = true;
  paint();
}


/* 연결 상태 감시.

   ★ 왜 ws.readyState 를 안 보고 시각으로 판단하는가
     연결은 살아있는데 서버가 멈춰서 아무것도 안 보내는 경우가 있다.
     그때 readyState 는 OPEN 이라 정상으로 보인다.
     '마지막으로 뭔가 받은 지 얼마나 됐나'가 더 정확한 신호다.

   ★ 왜 두 문구를 구분하는가
     한 번도 못 붙은 것과 붙었다 끊긴 것은 원인이 완전히 다르다.
     전자는 서버가 안 켜졌거나 주소가 틀린 것,
     후자는 로봇/네트워크 문제.
     디버깅할 때 이 구분이 시간을 크게 줄여준다. */
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


/* 시작.
   화면은 첫 상태를 받은 뒤에 그려진다 (applyState → paint).
   그전에 그리면 초기값 기준의 엉뚱한 화면이 잠깐 스친다. */
if(FORCED) paint();     // ?screen=... 로 강제한 경우만 즉시 그린다
connect();