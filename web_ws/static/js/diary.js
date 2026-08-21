/* ============================================================
   diary.js — 일기 화면

   ────────────────────────────────────────────────────────────
   탐험 화면과 뭐가 다른가
   ────────────────────────────────────────────────────────────

   exploring.js 는 1 초마다 갱신되는 실시간 화면이라
   DOM 을 다시 만들지 않고 값만 바꾼다.

   일기는 한 번 받아서 한 번 그리고 끝이다.
   그래서 innerHTML 로 통째로 그려도 아무 문제가 없다.
   (일기 쓰는 중일 때만 폴링하는데, 그때도 화면이 통으로 바뀐다)

   같은 규칙을 기계적으로 적용하지 않고, 화면 성격에 맞춘 것이다.

   ────────────────────────────────────────────────────────────
   주소 규칙
   ────────────────────────────────────────────────────────────

     /diary        →  지난 일기 목록
     /diary/3      →  3 번 탐험의 일기

   별도 페이지로 만든 이유 :
     발표 중에 "3 번 탐험 일기 보여주세요" 하면 주소로 바로 띄울 수 있다.
     탐험이 끝나면 exploring.js 가 이 주소로 넘겨주면 되므로
     자동 전환도 그대로 가능하다.
   ============================================================ */


/* location.pathname 은 "/diary/3" 같은 문자열이다.
   정규식으로 끝의 숫자만 뽑는다. 없으면 null → 목록 화면. */
const SESSION_ID = (location.pathname.match(/\/diary\/(\d+)/) || [])[1] || null;

const page = document.getElementById('page');


/* ============================================================
   진입점
   ============================================================ */

async function boot(){
  if(!SESSION_ID){
    return renderList();      // /diary  → 목록
  }

  try{
    const res = await fetch(`/api/sessions/${SESSION_ID}`);
    if(!res.ok) throw new Error(res.status);
    const data = await res.json();
    render(data.session, data.observations);
  }catch(e){
    renderError('일기를 불러오지 못했어요.', String(e));
  }
}


/* ============================================================
   지난 일기 목록  ( /diary )
   ============================================================ */

async function renderList(){
  let items = [];
  try{
    items = await (await fetch('/api/sessions')).json();
  }catch(e){
    return renderError('목록을 불러오지 못했어요.', String(e));
  }

  if(!items.length){
    return renderError('아직 일기가 없어요.', 'Odi 를 한 번 내보내 보세요.');
  }

  page.innerHTML = `
    <div class="past">
      <h2>지난 일기</h2>
      ${items.map(s => `
        <a href="/diary/${s.id}">
          <span class="d">${s.date}</span>
          <span class="t">${s.line || '(일기 없음)'}</span>
          <span class="n">관찰 ${s.observed_count}</span>
        </a>`).join('')}
    </div>`;
}


/* ============================================================
   일기 한 편  ( /diary/3 )
   ============================================================ */

function render(s, obs){
  /* ── 아직 쓰는 중이면 ──────────────────────────────
     AI 호출이 몇 초 걸린다. 그동안 빈 화면이나 스피너를 보여주는 대신
     하나의 '장면'으로 만든다. 문서의 REFLECTING 상태가 그대로 화면이 된다.

     2 초마다 다시 확인해서 준비되면 자동으로 일기로 바뀐다. */
  if(s.diary_status === 'generating'){
    page.innerHTML = `
      <div class="interlude">
        <div class="dots"><i></i><i></i><i></i></div>
        <h2>오늘 있었던 일을 정리하는 중</h2>
        <p>사진을 고르고 있어요. 잠시만요.</p>
      </div>`;
    setTimeout(boot, 2000);
    return;
  }

  /* ── 관찰(OBSERVE) 과 지나침(IGNORE) 을 가른다 ────
     화면에서 완전히 다르게 취급되기 때문이다.
     관찰한 것 → 사진 + 글 블록
     지나친 것 → 맨 아래 한 줄 요약 */
  const observed = obs.filter(o => o.decision?.action === 'OBSERVE');
  const skipped  = obs.filter(o => o.decision?.action === 'IGNORE');

  /* AI 가 만든 일기. 통째로 실패했을 수도 있으므로 안전하게 꺼낸다. */
  const d = s.diary || {};
  const entries = d.entries || [];

  /* ── 블록 순서를 정한다 ───────────────────────────
     ★ AI 가 쓴 순서를 따르되, AI 가 빠뜨린 관찰도 빠짐없이 넣는다.

     AI 응답이 불완전할 수 있다 — 관찰 3 건인데 entries 가 2 개만 오는 식.
     그때 나머지 하나를 조용히 버리면 사진이 사라진다.
     사진과 시각만이라도 남기는 게 낫다. */
  const byId = new Map(observed.map(o => [o.id, o]));
  const blocks = [];

  // ① AI 가 쓴 순서대로
  for(const e of entries){
    const o = byId.get(e.observation_id);
    if(o){
      blocks.push({ obs: o, text: e.text });
      byId.delete(e.observation_id);     // 처리했다고 표시
    }
  }
  // ② AI 가 빠뜨린 관찰 — 글 없이 사진만
  for(const o of byId.values()){
    blocks.push({ obs: o, text: null });
  }
  // ②는 시간순으로 뒤에 붙는다. 순서가 어색할 수 있지만
  // 사진이 통째로 사라지는 것보다는 낫다.

  page.innerHTML = `
    <div class="diary">

      <div class="cover">
        <div class="d">${s.started_at}</div>
        <h1>Odi의 ${ordinal(s.id)} 탐험</h1>
        <div class="stats">
          <span>${s.minutes}분</span>
          <span>발견 ${s.found_count}</span>
          <span>관찰 ${s.observed_count}</span>
        </div>
      </div>

      <p class="said-big">${d.opening || '오늘의 탐험을 마쳤다.'}</p>

      ${blocks.map(blockHtml).join('')}

      ${skipped.length ? `<p class="passed">${passedLine(skipped)}</p>` : ''}

      <p class="said-big close">${d.closing || closingFallback(s)}</p>

      <div class="route">
        <h3>오늘 다닌 길</h3>
        <div class="frame">
          <div class="wait">지도는 아직 준비 중이에요</div>
        </div>
      </div>

      <div class="footer">
        <a href="/diary">지난 일기</a>
        <a href="/">탐험 화면</a>
      </div>

    </div>`;
}


/* 관찰 블록 하나 — 사진이 먼저, 글이 아래.

   ★ 순서가 중요하다
     글을 먼저 놓고 사진을 아래 두면 사진이 '증빙'처럼 보인다.
     사진이 먼저여야 이야기의 일부로 읽힌다. */
function blockHtml(b){
  const o = b.obs;

  /* onerror : 파일이 아직 없거나 경로가 틀렸을 때 깨진 이미지 아이콘 대신
     조용히 자리만 남긴다. 발표 중에 깨진 아이콘이 뜨는 것보다 낫다.
     this.parentNode 는 .shot 이고, 거기 텍스트를 넣으면 회색 자리가 된다. */
  const shot = o.photo_url
    ? `<div class="shot"><img src="${o.photo_url}" alt="${nameOf(o)}"
         onerror="this.remove(); this.parentNode.textContent='사진을 찾을 수 없어요';"></div>`
    : `<div class="shot">사진 없음</div>`;

  /* 글이 없는 블록(AI 가 빠뜨림)은 사진과 시각만 남기고 조용히 넘어간다.
     "글 생성 실패" 같은 문구를 띄우면 그게 더 눈에 띈다. */
  const text = b.text ? `<p>${b.text}</p>` : '';

  return `
    <div class="blk${b.text ? '' : ' textless'}">
      ${shot}${text}
      <div class="meta">${o.at} · ${nameOf(o)}</div>
    </div>`;
}


/* 지나친 것들을 한 줄로.

   ★ 왜 빼지 않는가
     지나친 게 안 보이면 Odi 가 '눈에 띄는 걸 다 찍는 로봇'으로 보인다.
     지나친 게 있어야 고른 것에 의미가 생긴다.
     이 프로젝트의 핵심이 호기심 판단인데, 일기에서 그게 드러나는 자리가 여기다.

   ★ 왜 사진+글 블록을 안 주는가
     그러면 관찰한 것과 구분이 안 돼서 "골라서 봤다"가 무너진다. */
function passedLine(skipped){
  /* 같은 이름이 여러 번 나올 수 있으므로 중복을 없앤다.
     Set 은 중복을 자동으로 제거해준다. */
  const names = [...new Set(skipped.map(nameOf))];
  const list = names.join('와 ');
  return `그 밖에 ${list}도 지나쳤지만, 이미 잘 아는 것들이라 눈길만 주고 지나갔다.`;
}


/* AI 가 닫는 문장을 못 만들었을 때의 대체 문구.

   ★ ended_by 로 갈린다
     의욕을 다 써서 끝난 것과 시간이 다 돼서 끝난 것은
     Odi 의 기분이 다르다. 공짜로 얻는 캐릭터라 살려 쓴다. */
function closingFallback(s){
  return s.ended_by === 'TIME_LIMIT'
    ? '아직 더 보고 싶었는데,<br>시간이 다 됐다.'
    : '돌아오는 길은 금방이었다.<br>오늘은 실컷 돌아다녔다.';
}


/* 1 → 첫 번째, 2 → 두 번째 ... 10 이상은 그냥 숫자로. */
function ordinal(n){
  const words = ['', '첫', '두', '세', '네', '다섯', '여섯', '일곱', '여덟', '아홉'];
  return n < words.length ? `${words[n]} 번째` : `${n}번째`;
}


function renderError(title, detail){
  page.innerHTML = `
    <div class="interlude">
      <h2>${title}</h2>
      <p>${detail}</p>
      <div class="footer"><a href="/diary">지난 일기</a><a href="/">탐험 화면</a></div>
    </div>`;
}


boot();