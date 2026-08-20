/* ============================================================
   schema.js — 탐험 화면과 일기 화면이 공유한다.

   SemanticLabel / CuriosityDecision 필드를 Odi의 말로 바꾸는 곳.
   두 화면에 복사해두면 문구 다듬을 때 한쪽만 고치고 넘어가게 되므로
   반드시 여기 한 군데만 둔다.

   ES 모듈을 쓰지 않는다. import/export 를 쓰면 file:// 로 열 때
   CORS 로 막혀서 서버 없이 화면 확인이 안 된다.
   ============================================================ */

/* 미션 상태 · 행동 → 사람 말.
   FIRST_ENCOUNTER 를 그대로 띄우면 로그고, 번역하면 캐릭터다. */
const SAY = {
  PREPARING:          '나갈 준비를 하고 있어요',
  EXPLORE:            '가보지 않은 쪽으로 가는 중',
  FIRST_ENCOUNTER:    '처음 보는 물체 앞에 섰어요',
  EVALUATE_CURIOSITY: '전에 본 적이 있는지 떠올리는 중',
  OBSERVE:            '가까이서 살펴보는 중',
  RETURNING:          '집으로 돌아가는 중',
  REFLECTING:         '오늘 있었던 일을 정리하는 중'
};

/* SemanticLabel 필드명 → 사람 말.
   novel_features / duplicated_features 가 이 키로 내려온다. */
const FEAT = {
  object_primary_color:   '색',
  object_secondary_color: '무늬',
  object_material:        '재질',
  object_shape:           '모양',
  object_condition:       '상태',
  object_special_features:'특징'
};

const kr = ks => ks.map(k => FEAT[k] || k).join('·');

/* 받침에 따라 이/가. '상태이 달라요' 가 나오면 캐릭터가 깨진다. */
const iga = w => {
  const c = w.charCodeAt(w.length - 1);
  return (c >= 0xAC00 && c <= 0xD7A3 && (c - 0xAC00) % 28) ? '이' : '가';
};

/* Odi의 한마디를 CuriosityDecision 에서 만든다.
   대사를 하드코딩하지 않으므로, 판단이 바뀌면 말도 같이 바뀐다. */
function describe(d){
  const c = d.decision;
  if(!c) return '저기 뭔가 있어요. 가까이 가볼게요.';

  const novel = c.novel_features || [];

  if(c.action === 'IGNORE'){
    /* IGNORE_CLASSES 로 걸러진 경우 — 비교를 아예 안 했다 */
    if(c.compared_record_count === 0) return '이런 건 굳이 안 봐도 돼요.';
    if(novel.length)                  return '조금 다르긴 한데, 지나갈게요.';
    return `${c.visit_count}번째 보는 거예요. 그냥 지나갈게요.`;
  }

  if(c.visit_count === 0) return '처음 보는 물체예요. 더 가까이 가볼게요.';
  if(novel.length){
    const f = kr(novel);
    return `전에도 봤는데 ${f}${iga(f)} 달라요. 다시 볼게요.`;
  }
  return '뭔가 걸려요. 한 번 더 볼게요.';
}

/* 판단 근거 한 줄. 문장은 캐릭터, 이 줄은 발표용 근거.
   필터로 걸러진 건 점수가 전부 0이라 보여줄 게 없다. */
function why(d){
  const c = d.decision;
  if(!c || c.compared_record_count === 0) return '';
  const bits = [`유사도 ${c.similarity_score.toFixed(2)}`];
  if(c.visit_count > 0) bits.push(`${c.visit_count}번째`);
  if(c.novel_features?.length) bits.push(`${kr(c.novel_features)} 다름`);
  bits.push(`호기심 ${c.curiosity_score.toFixed(2)}`);
  return bits.join(' · ');
}

const nameOf = d => d.label.object_name;
const clock  = s => `${String(s/60|0).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;