// Standalone HTML5 game generators. Pure string builders: no DOM access.

function jsonForScript(value) {
  return JSON.stringify(String(value == null ? "" : value)).replace(/</g, "\\u003c");
}

function buildStrategyGame(line) {
  var gameTitle = jsonForScript(line.title);
  var topic = jsonForScript(line.topicName);
  var gameType = jsonForScript(line.gameType || "Arcade Score");
  return `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Factory Game</title>
<style>
  :root{color-scheme:dark;--bg:#070b12;--panel:#101827;--line:#29384f;--accent:#7c6cff;--good:#49dc8c;--bad:#ff6f7d}
  *{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px;background:radial-gradient(circle at 50% 0,#20255a 0,transparent 40%),var(--bg);color:#f6f8fc;font-family:Inter,system-ui,sans-serif}
  .game{width:min(760px,100%);padding:24px;border:1px solid var(--line);border-radius:20px;background:rgba(13,20,32,.96);box-shadow:0 30px 80px #0008}h1{margin:4px 0 6px;font-size:clamp(25px,5vw,42px)}.sub{margin:0 0 20px;color:#93a5bb}.hud{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.stat{padding:12px;border:1px solid var(--line);border-radius:12px;background:#0a111c}.stat small,.stat strong{display:block}.stat small{color:#73869d;font-size:10px;text-transform:uppercase;letter-spacing:.12em}.stat strong{margin-top:4px;font-size:21px}.arena{min-height:300px;margin-top:12px;padding:20px;border:1px solid var(--line);border-radius:16px;background:linear-gradient(145deg,#111b2c,#0b111b);text-align:center}.prompt{color:#aebbd0}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:25px 0}.card{min-height:125px;border:1px solid #394b66;border-radius:16px;background:linear-gradient(160deg,#1d2940,#101827);color:white;font-size:38px;font-weight:900;cursor:pointer;transition:.16s transform,.16s border-color}.card:hover{transform:translateY(-4px);border-color:#8c82ff}.card.good{border-color:var(--good);background:#103021}.card.bad{border-color:var(--bad);background:#35151b}.message{min-height:28px;color:#9eacc0}.primary{width:100%;padding:14px;border:0;border-radius:12px;background:linear-gradient(135deg,#8577ff,#5a48ec);color:white;font-weight:900;cursor:pointer}.hidden{display:none}@media(max-width:560px){.hud{grid-template-columns:repeat(2,1fr)}.cards{grid-template-columns:1fr}.card{min-height:72px}}
</style>
</head>
<body data-ai-factory-game="v2" data-family="strategy">
<main class="game">
  <small id="mode"></small><h1 id="title"></h1><p class="sub">매 라운드 바뀌는 작전 규칙을 읽고 제한된 집중력을 운용하세요.</p>
  <section class="hud"><div class="stat"><small>Score</small><strong id="score">0</strong></div><div class="stat"><small>Round</small><strong id="round">0/12</strong></div><div class="stat"><small>Focus</small><strong id="focus">2</strong></div><div class="stat"><small>Lives / Time</small><strong><span id="lives">3</span> / <span id="time">60</span></strong></div></section>
  <section class="arena"><p class="prompt" id="prompt">높음·낮음·목표 근접 규칙이 교대로 등장합니다.</p><div class="cards" id="cards"></div><p class="message" id="message">분석은 오답 하나를 제거하지만 집중력 1을 소비합니다.</p><div style="display:flex;gap:8px"><button class="primary" id="analyze" style="background:#26334a" disabled>분석 사용</button><button class="primary" id="start">작전 시작</button></div></section>
</main>
<script>
  const GAME_TITLE=${gameTitle}; const TOPIC=${topic}; const GAME_TYPE=${gameType};
  const $=id=>document.getElementById(id); let score=0,combo=0,lives=3,time=60,focus=2,active=false,timer=null,round=0,target=0,answer=0;
  $("title").textContent=GAME_TITLE; $("mode").textContent=TOPIC+" · "+GAME_TYPE;
  function sync(){ $("score").textContent=score; $("round").textContent=round+"/12"; $("focus").textContent=focus; $("lives").textContent=lives; $("time").textContent=time; $("analyze").disabled=!active||focus<1; }
  function makeRound(){
    if(!active)return; round+=1; const values=[]; while(values.length<3){const n=1+Math.floor(Math.random()*(20+round));if(!values.includes(n))values.push(n)}
    const rule=(round-1)%3; target=5+Math.floor(Math.random()*(15+round)); answer=rule===0?Math.max(...values):rule===1?Math.min(...values):values.reduce((a,b)=>Math.abs(b-target)<Math.abs(a-target)?b:a);
    $("prompt").textContent="ROUND "+round+" · "+(rule===0?"가장 높은 신호 선택":rule===1?"가장 낮은 위험 선택":"목표 "+target+"에 가장 가까운 값 선택"); const wrap=$("cards"); wrap.innerHTML="";
    values.sort(()=>Math.random()-.5).forEach(value=>{const b=document.createElement("button");b.className="card";b.dataset.value=value;b.textContent=value;b.onclick=()=>choose(value,b);wrap.appendChild(b)});sync();
  }
  function choose(value,button){
    if(!active)return; document.querySelectorAll(".card").forEach(x=>x.disabled=true);
    if(value===answer){combo+=1;score+=100+combo*25;if(combo%3===0)focus=Math.min(3,focus+1);button.classList.add("good");$("message").textContent="정확한 판단 · 콤보 "+combo}
    else{combo=0;lives-=1;button.classList.add("bad");$("message").textContent="오판입니다. 정답은 "+answer}
    sync();if(lives<=0||round>=12){setTimeout(endGame,400);return}setTimeout(makeRound,400);
  }
  function analyze(){if(!active||focus<1)return;focus-=1;const wrong=[...document.querySelectorAll(".card")].filter(b=>Number(b.dataset.value)!==answer&&!b.disabled);if(wrong.length){const removed=wrong[Math.floor(Math.random()*wrong.length)];removed.disabled=true;removed.style.opacity=.28}$("message").textContent="분석 완료: 오답 후보를 제거했습니다.";sync()}
  function startGame(){score=0;combo=0;lives=3;time=60;focus=2;round=0;active=true;clearInterval(timer);$("start").classList.add("hidden");$("message").textContent="판정 규칙을 읽고 작전을 수행하세요.";sync();makeRound();timer=setInterval(()=>{time-=1;sync();if(time<=0)endGame()},1000)}
  function endGame(){if(!active)return;active=false;clearInterval(timer);$("cards").innerHTML="";const win=round>=12&&lives>0&&time>0;$("prompt").textContent=win?"MISSION COMPLETE":"MISSION FAILED";$("message").textContent="최종 점수 "+score+" · 도달 라운드 "+round;$("start").textContent="다시 플레이";$("start").classList.remove("hidden");sync()}
  $("start").onclick=startGame; $("analyze").onclick=analyze;
</script>
</body>
</html>`;
}

function buildActionGame(line) {
  var gameTitle = jsonForScript(line.title);
  var topic = jsonForScript(line.topicName);
  var gameType = jsonForScript(line.gameType || "Action");
  return `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI Factory Action Game</title><style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:16px;background:radial-gradient(circle at top,#17334a,#060b12 65%);color:#f4f8fc;font-family:system-ui,sans-serif}.game{width:min(900px,100%);padding:20px;border:1px solid #294158;border-radius:20px;background:#09111bdd}h1{margin:4px 0;font-size:clamp(25px,5vw,40px)}.sub{margin:0 0 14px;color:#89a5bb}.hud{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:9px}.stat{padding:10px;border:1px solid #283c50;border-radius:10px;background:#0b1824}.stat small,.stat strong{display:block}.stat small{font-size:9px;letter-spacing:.12em;color:#7894aa}.stat strong{font-size:20px}canvas{width:100%;aspect-ratio:16/9;display:block;border:1px solid #34526b;border-radius:14px;background:#06101a;touch-action:none}.bar{display:flex;gap:8px;align-items:center;margin-top:10px}.bar p{flex:1;margin:0;color:#91aabd;font-size:12px}.bar button{padding:11px 18px;border:0;border-radius:10px;background:#46d6a1;color:#04130e;font-weight:900;cursor:pointer}@media(max-width:560px){.hud{grid-template-columns:repeat(2,1fr)}}
</style></head><body data-ai-factory-game="v2" data-family="action"><main class="game"><small id="mode"></small><h1 id="title"></h1><p class="sub">코어를 회수하고 추적 드론을 피하세요. WASD·방향키·포인터 이동을 지원합니다.</p><section class="hud"><div class="stat"><small>CORES</small><strong id="score">0 / 15</strong></div><div class="stat"><small>HULL</small><strong id="hull">3</strong></div><div class="stat"><small>SHIELD</small><strong id="shield">0</strong></div><div class="stat"><small>TIME</small><strong id="time">60</strong></div></section><canvas id="game" width="800" height="450"></canvas><div class="bar"><p id="message">초록 코어 15개를 60초 안에 회수하면 임무 성공입니다.</p><button id="start">출격</button></div></main><script>
const GAME_TITLE=${gameTitle},TOPIC=${topic},GAME_TYPE=${gameType};const $=id=>document.getElementById(id),canvas=$("game"),ctx=canvas.getContext("2d");let player,cores=[],enemies=[],keys={},score=0,hull=3,shield=0,time=60,active=false,last,spawn,timer,raf,pointer=null;$("title").textContent=GAME_TITLE;$("mode").textContent=TOPIC+" · "+GAME_TYPE;
function sync(){$("score").textContent=score+" / 15";$("hull").textContent=hull;$("shield").textContent=shield;$("time").textContent=time}
function randomPoint(){return{x:30+Math.random()*740,y:30+Math.random()*390}}
function startGame(){player={x:400,y:225,r:12,inv:0};cores=[randomPoint(),randomPoint(),randomPoint()];enemies=[{...randomPoint(),r:12,s:55}];keys={};score=0;hull=3;shield=0;time=60;active=true;last=performance.now();spawn=0;clearInterval(timer);cancelAnimationFrame(raf);$("start").textContent="재출격";$("message").textContent="항로가 열렸습니다. 계속 움직이세요.";sync();timer=setInterval(()=>{if(!active)return;time-=1;sync();if(time<=0)endGame(false)},1000);raf=requestAnimationFrame(loop)}
function hit(a,b,dist){return Math.hypot(a.x-b.x,a.y-b.y)<dist}
function update(dt){let dx=(keys.ArrowRight||keys.d?1:0)-(keys.ArrowLeft||keys.a?1:0),dy=(keys.ArrowDown||keys.s?1:0)-(keys.ArrowUp||keys.w?1:0);if(pointer){dx=pointer.x-player.x;dy=pointer.y-player.y;if(Math.hypot(dx,dy)<8)pointer=null}const n=Math.hypot(dx,dy)||1;player.x=Math.max(15,Math.min(785,player.x+dx/n*190*dt));player.y=Math.max(15,Math.min(435,player.y+dy/n*190*dt));player.inv=Math.max(0,player.inv-dt);cores.forEach((c,i)=>{if(hit(player,c,20)){cores.splice(i,1);score+=1;if(score%5===0)shield+=1;cores.push(randomPoint());sync();if(score>=15)endGame(true)}});spawn+=dt;if(spawn>Math.max(1.3,3-score*.1)){spawn=0;enemies.push({...randomPoint(),r:11,s:55+score*5})}enemies.forEach(e=>{let x=player.x-e.x,y=player.y-e.y,n=Math.hypot(x,y)||1;e.x+=x/n*e.s*dt;e.y+=y/n*e.s*dt;if(hit(player,e,22)&&player.inv<=0){player.inv=1.2;if(shield>0)shield-=1;else hull-=1;sync();if(hull<=0)endGame(false)}})}
function draw(){ctx.fillStyle="#06101a";ctx.fillRect(0,0,800,450);ctx.strokeStyle="#10283a";for(let x=0;x<800;x+=40){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,450);ctx.stroke()}for(let y=0;y<450;y+=40){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(800,y);ctx.stroke()}cores.forEach(c=>{ctx.fillStyle="#45e6a3";ctx.beginPath();ctx.arc(c.x,c.y,7,0,7);ctx.fill();ctx.strokeStyle="#45e6a366";ctx.beginPath();ctx.arc(c.x,c.y,14,0,7);ctx.stroke()});enemies.forEach(e=>{ctx.fillStyle="#ff667d";ctx.beginPath();ctx.arc(e.x,e.y,e.r,0,7);ctx.fill()});if(player){ctx.fillStyle=player.inv>0?"#fff":"#78b8ff";ctx.beginPath();ctx.arc(player.x,player.y,player.r,0,7);ctx.fill();if(shield){ctx.strokeStyle="#72f0ff";ctx.beginPath();ctx.arc(player.x,player.y,18,0,7);ctx.stroke()}}}
function loop(now){if(!active)return;const dt=Math.min(.035,(now-last)/1000);last=now;update(dt);draw();raf=requestAnimationFrame(loop)}function endGame(win){if(!active)return;active=false;clearInterval(timer);cancelAnimationFrame(raf);$("message").textContent=win?"회수 완료! 생존 보너스 "+(hull*100):"임무 실패 · "+score+"개 코어를 회수했습니다.";$("start").textContent="다시 출격"}
addEventListener("keydown",e=>{keys[e.key]=true});addEventListener("keyup",e=>{keys[e.key]=false});canvas.addEventListener("pointerdown",e=>{const r=canvas.getBoundingClientRect();pointer={x:(e.clientX-r.left)*800/r.width,y:(e.clientY-r.top)*450/r.height}});$("start").onclick=startGame;draw();
</script></body></html>`;
}

function buildManagementGame(line) {
  var gameTitle = jsonForScript(line.title);
  var topic = jsonForScript(line.topicName);
  var gameType = jsonForScript(line.gameType || "Management");
  return `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI Factory Management Game</title><style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:18px;background:radial-gradient(circle at 20% 0,#293a2c,#090d0a 62%);color:#f4f7f2;font-family:system-ui,sans-serif}.game{width:min(850px,100%);padding:22px;border:1px solid #364b39;border-radius:20px;background:#0e1710ee}h1{margin:4px 0}.sub{color:#8eaa91}.hud{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.stat,.action,.log{padding:12px;border:1px solid #314434;border-radius:11px;background:#111d13}.stat small,.stat strong{display:block}.stat small{font-size:9px;color:#78917b;letter-spacing:.12em}.stat strong{font-size:21px;margin-top:3px}.actions{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:10px}.action{text-align:left;color:#e8f1e8;cursor:pointer}.action:hover{border-color:#74c97c}.action strong,.action small{display:block}.action small{color:#819984;margin-top:4px}.action:disabled{opacity:.4}.log{min-height:108px;margin-top:10px;color:#9db09f;line-height:1.55}.next{width:100%;margin-top:10px;padding:13px;border:0;border-radius:10px;background:#74d780;color:#081109;font-weight:900;cursor:pointer}@media(max-width:560px){.hud,.actions{grid-template-columns:repeat(2,1fr)}}
</style></head><body data-ai-factory-game="v2" data-family="management"><main class="game"><small id="mode"></small><h1 id="title"></h1><p class="sub">12일 동안 운영·연구·확장의 균형을 잡아 2,000 크레딧과 평판 60을 달성하세요.</p><section class="hud"><div class="stat"><small>DAY</small><strong id="day">1 / 12</strong></div><div class="stat"><small>CREDITS</small><strong id="credits">500</strong></div><div class="stat"><small>ENERGY</small><strong id="energy">5</strong></div><div class="stat"><small>REPUTATION</small><strong id="rep">20</strong></div></section><section class="actions"><button class="action" data-act="contract"><strong>계약 수행</strong><small>에너지 -2 · 수익과 평판</small></button><button class="action" data-act="efficient"><strong>효율 운영</strong><small>에너지 -1 · 안정 수익</small></button><button class="action" data-act="research"><strong>연구 투자</strong><small>비용 300 · 영구 수익 +25%</small></button><button class="action" data-act="expand"><strong>시설 확장</strong><small>비용 450 · 매일 자동수익 +100</small></button></section><div class="log" id="log">운영 계획을 선택하세요. 하루에 최대 2회 행동할 수 있습니다.</div><button class="next" id="next">다음 날</button></main><script>
const GAME_TITLE=${gameTitle},TOPIC=${topic},GAME_TYPE=${gameType};const $=id=>document.getElementById(id);let day,credits,energy,rep,research,facilities,actions,active;$("title").textContent=GAME_TITLE;$("mode").textContent=TOPIC+" · "+GAME_TYPE;
function sync(){$("day").textContent=day+" / 12";$("credits").textContent=Math.floor(credits);$("energy").textContent=energy;$("rep").textContent=rep;document.querySelectorAll(".action").forEach(b=>b.disabled=!active||actions>=2)}function note(t){$("log").innerHTML=t+"<br>연구 "+research+"단계 · 시설 "+facilities+"개 · 오늘 행동 "+actions+"/2"}
function act(type){if(!active||actions>=2)return;let msg="";if(type==="contract"){if(energy<2)return note("에너지가 부족합니다.");energy-=2;let gain=Math.round((180+Math.random()*160)*(1+research*.25));credits+=gain;rep+=6;msg="핵심 계약 성공: +"+gain+" 크레딧, 평판 +6"}if(type==="efficient"){if(energy<1)return note("에너지가 부족합니다.");energy-=1;let gain=Math.round(110*(1+research*.25));credits+=gain;rep+=2;msg="효율 운영: +"+gain+" 크레딧, 평판 +2"}if(type==="research"){if(credits<300)return note("연구 비용 300이 필요합니다.");credits-=300;research+=1;msg="연구 완료: 모든 운영 수익 +25%"}if(type==="expand"){if(credits<450)return note("확장 비용 450이 필요합니다.");credits-=450;facilities+=1;msg="시설 확장: 다음 날부터 자동수익 +100"}actions+=1;note(msg);sync()}
function nextDay(){if(!active)return;if(day>=12){endGame();return}day+=1;actions=0;energy=Math.min(6,energy+3);credits+=facilities*100;const roll=Math.random();let event="특별한 사건 없이 운영되었습니다.";if(roll<.18){credits=Math.max(0,credits-140);event="장비 고장: -140 크레딧"}else if(roll>.84){credits+=180;rep+=3;event="호평 기사: +180 크레딧, 평판 +3"}note("DAY "+day+" · "+event);sync();if(day===12)$("next").textContent="최종 결산"}
function startGame(){day=1;credits=500;energy=5;rep=20;research=0;facilities=0;actions=0;active=true;$("next").textContent="다음 날";$("next").onclick=nextDay;note("새 운영 주기가 시작되었습니다.");sync()}function endGame(){active=false;const win=credits>=2000&&rep>=60;note(win?"목표 달성! 지속 가능한 조직을 만들었습니다.":"목표 미달. 2,000 크레딧과 평판 60을 함께 달성해야 합니다.");$("next").textContent="다시 시작";$("next").onclick=startGame;sync()}
document.querySelectorAll("[data-act]").forEach(b=>b.onclick=()=>act(b.dataset.act));$("next").onclick=nextDay;startGame();
</script></body></html>`;
}

export function gameFamily(type) {
  if (/Tycoon|Management/.test(type)) return "management";
  if (/Roguelike|Survivor|Extraction|Arcade/.test(type)) return "action";
  return "strategy";
}

// line: {title, topicName, gameType, family}
export function buildGame(line) {
  const family = line.family || gameFamily(line.gameType || "");
  if (family === "action") return buildActionGame(line);
  if (family === "management") return buildManagementGame(line);
  return buildStrategyGame(line);
}

export function smokeTest(html) {
  const checks = [
    ["doctype", /<!doctype html>/i.test(html)],
    ["entry_point", html.indexOf("startGame") !== -1],
    ["factory_marker", html.indexOf('data-ai-factory-game="v2"') !== -1],
    ["no_external_scripts", !/<script[^>]+src=/i.test(html)],
  ];
  return { passed: checks.every((c) => c[1]), checks: checks.map(([id, ok]) => ({ id, ok })) };
}
