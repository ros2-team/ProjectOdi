// Minimal DOM harness: validates PNG display and missing-map fallback.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
function element(tag){return {tag, attrs:{}, style:{}, children:[],
 setAttribute(k,v){this.attrs[k]=String(v)}, append(...c){this.children.push(...c)},
 replaceChildren(...c){this.children=c}, addEventListener(){}};}
const frame=element('div'), page=element('main');
frame.textContent='이 탐험의 지도 기록이 없어요.';
const ctx={location:{pathname:'/diary/one'}, document:{
 getElementById:id=>id==='diaryRoute'?frame:id==='page'?page:null,
 createElementNS:(_,tag)=>element(tag),createElement:element}, console};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('web_ws/static/js/diary.js','utf8').replace(/^boot\(\);$/m,''),ctx);
ctx.paintDiaryRoute(null);
assert.equal(frame.children.length,0);
const route={width:100,height:80,image:'data:image/png;base64,aGVsbG8=',
 segments:[[[1,2],[3,4]],[[70,60],[72,61]]],start:[1,2],end:[72,61],complete:true};
ctx.paintDiaryRoute(route);
assert.equal(frame.children[0].tag,'img');
assert.equal(frame.children[0].src,route.image);
assert.equal(frame.children.length,2);
assert(!frame.children.some(n=>n.tag==='svg'));
ctx.render({diary:{opening:'본문',closing:'생성한 소감'},route,diary_status:'ready'},[]);
assert(page.innerHTML.includes('생성한 소감'));
ctx.render({diary:{opening:'옛 일기'},diary_status:'ready'},[]);
assert(!page.innerHTML.includes('돌아오는 길은 금방이었다'));
console.log('Diary DOM checks passed: PNG image, closing and legacy fallback');
