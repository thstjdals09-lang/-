(function () {
  "use strict";

  var STORAGE_KEY = "ai-factory-studio-v3";
  var AUTOMATION_INTERVAL_MS = 1600;

  var STAGES = [
    ["brief","Brief / Theme Intake","주제·플랫폼·제약조건 정리"],
    ["ideation","Ideation Room","10개 아이디어 생성·비평·자동 선별"],
    ["greenlight","Greenlight / Feasibility","재미·범위·기술 리스크 검증"],
    ["preproduction","Pre-Production","GDD·아키텍처·UX·아트 방향 확정"],
    ["prototype","Playable Prototype","핵심 재미를 증명하는 최소 플레이 버전"],
    ["vertical","Vertical Slice","최종 품질에 가까운 대표 구간 제작"],
    ["production","Full Production","기능·콘텐츠·도구·저장·UI 본개발"],
    ["qa","Internal QA / Integration","통합·회귀·성능·호환성 검증"],
    ["alpha","Alpha","기능 완성도 확보·안정화"],
    ["beta","Beta","콘텐츠 완성·밸런스·출시후보 준비"],
    ["polish","Polish / Certification","UX·접근성·현지화·스토어 요건 마감"],
    ["release","Release Build","배포파일·버전 태그·릴리즈노트 생성"],
    ["live","Live Operations","피드백·크래시·패치·업데이트 운영"]
  ];

  var MARKET = [
    {id:"local",name:"Local Unlimited Worker",provider:"Local",model:"llama.cpp",auth:"local",tag:"무제한 안전망 · 반복작업",quota:{unit:"unlimited",limit:null,remaining:null,reserve:0},skills:{coding:72,planning:68,design:35,vision:0,qa:84,speed:55,reliability:95}},
    {id:"cerebras",name:"Cerebras Coder",provider:"Cerebras",model:"gpt-oss-120b",auth:"api_key",tag:"고속 코딩/구현",quota:{unit:"tokens/day",limit:1000000,remaining:1000000,reserve:.12},skills:{coding:98,planning:82,design:52,vision:0,qa:82,speed:99,reliability:89}},
    {id:"groq",name:"Groq Fast Worker",provider:"Groq",model:"gpt-oss-120b",auth:"api_key",tag:"빠른 보조 코딩·QA",quota:{unit:"tokens/day",limit:200000,remaining:200000,reserve:.15},skills:{coding:87,planning:73,design:40,vision:0,qa:91,speed:100,reliability:88}},
    {id:"gemini",name:"Gemini Planner",provider:"Google",model:"Gemini API",auth:"google_or_key",tag:"기획·멀티모달·UX 검토",quota:{unit:"requests",limit:100,remaining:100,reserve:.15},skills:{coding:90,planning:98,design:93,vision:99,qa:88,speed:90,reliability:92}},
    {id:"openrouter",name:"OpenRouter Free Pool",provider:"OpenRouter",model:"Free Pool",auth:"api_key",tag:"무료모델 비상 대체 풀",quota:{unit:"requests/day",limit:50,remaining:50,reserve:.20},skills:{coding:81,planning:83,design:68,vision:52,qa:80,speed:74,reliability:78}},
    {id:"cloudflare",name:"Cloudflare AI Worker",provider:"Cloudflare",model:"Workers AI",auth:"api_key",tag:"일일 무료량 · 범용 잡무",quota:{unit:"neurons/day",limit:10000,remaining:10000,reserve:.12},skills:{coding:76,planning:73,design:63,vision:60,qa:80,speed:85,reliability:87}},
    {id:"mistral",name:"Mistral Worker",provider:"Mistral",model:"Mistral API",auth:"api_key",tag:"코딩·기획 보조",quota:{unit:"credits",limit:10,remaining:10,reserve:.15},skills:{coding:91,planning:86,design:62,vision:50,qa:84,speed:84,reliability:87}}
  ];

  var IDEA_PATTERNS = [
    ["Roguelike Core","매 판 다른 조합과 위험/보상으로 반복 플레이를 만든다.","선택 → 전투/판정 → 보상 → 성장 → 보스"],
    ["Deckbuilder","규칙을 카드와 능력 조합으로 표현해 빌드 연구가 핵심이 된다.","획득 → 덱 구성 → 판정 → 시너지 → 강화"],
    ["Tycoon","운영·배치·자동화의 최적화를 즐긴다.","배치 → 운영 → 수익 → 확장 → 자동화"],
    ["Tactical","제한된 정보에서 읽기·예측·리스크 관리로 승부한다.","정보 → 선택 → 상대 반응 → 결과 → 적응"],
    ["Survivor","짧은 조작과 빠른 성장으로 대량의 적을 버틴다.","이동 → 처치 → 경험치 → 업그레이드 → 웨이브"],
    ["Puzzle Strategy","간단한 규칙 조합으로 깊은 의사결정을 만든다.","관찰 → 배치 → 연쇄 → 해결 → 난이도 상승"],
    ["Social Party","짧은 라운드와 심리전으로 반복 플레이한다.","규칙 → 선택/블러프 → 공개 → 점수 → 다음 라운드"],
    ["Management RPG","캐릭터 육성과 운영을 결합한다.","영입 → 훈련 → 배치 → 임무 → 성장"],
    ["Extraction Lite","더 가져갈지 탈출할지를 계속 결정한다.","진입 → 탐색 → 위험 상승 → 전리품 → 탈출"],
    ["Arcade Score","한 가지 핵심 조작과 점수 경쟁에 집중한다.","조작 → 콤보 → 위험 증가 → 기록 → 재도전"]
  ];

  var activeTab = "dashboard";
  var editingTopic = false;

  function clone(x) {
    return JSON.parse(JSON.stringify(x));
  }

  function defaultState() {
    return {
      user:{signedIn:false,email:null,name:null},
      employees:[clone(MARKET[0])],
      ideas:[],
      lines:[],
      backlog:[],
      reviews:[],
      logs:[],
      topic:null,
      settings:{policy:"cheapest_viable",maxParallel:3,autoShortlist:3,quotaGuard:true,autopilot:true,autoPublish:true,githubOwner:"thstjdals09-lang"}
    };
  }

  function load() {
    try {
      var x = JSON.parse(localStorage.getItem(STORAGE_KEY));
      if (!x) return defaultState();
      x.reviews = x.reviews || [];
      x.settings = Object.assign(defaultState().settings, x.settings || {});
      (x.lines || []).forEach(function (line) {
        if (typeof line.autopilot !== "boolean") line.autopilot = x.settings.autopilot;
        if (!line.publication) line.publication = {status:"not_ready",repository:null};
        if (line.publication.status === "queued") line.publication.status = "awaiting_backend";
        line.handoffs = line.handoffs || [];
        line.topicName = line.topicName || (x.topic && x.topic.name) || "game";
        line.gameType = line.gameType || String(line.title || "").split("·").pop().trim() || "Arcade Score";
        ensureLinePlan(line);
        if (line.status === "complete") ensurePlayableBuild(line);
      });
      return x;
    } catch (e) {
      return defaultState();
    }
  }

  var state = load();

  function save() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }

  function esc(value) {
    var s = String(value == null ? "" : value);
    return s.replace(/[&<>"']/g, function (m) {
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m];
    });
  }

  function now() {
    return new Date().toLocaleString("ko-KR");
  }

  function slugify(value) {
    var slug = String(value || "game")
      .toLowerCase()
      .normalize("NFC")
      .replace(/[^a-z0-9가-힣]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 48);
    return slug || "ai-factory-game";
  }

  function addLog(type, text, lineId) {
    state.logs.unshift({id:Date.now()+Math.random(),time:now(),type:type,text:text,lineId:lineId||null});
    state.logs = state.logs.slice(0, 200);
  }

  function quotaPct(employee) {
    var q = employee.quota;
    if (q.unit === "unlimited" || q.limit == null) return 100;
    if (!q.limit) return 0;
    return Math.max(0, Math.min(100, Math.round((q.remaining / q.limit) * 100)));
  }

  function isUsable(employee) {
    var q = employee.quota;
    if (q.unit === "unlimited") return true;
    var floor = q.limit * q.reserve;
    return q.remaining > floor;
  }

  function costScore(employee) {
    if (employee.quota.unit === "unlimited") return 100;
    return 55 + quotaPct(employee) * .45;
  }

  function roleSkillKey(role) {
    if (/QA|Build|Release/.test(role)) return "qa";
    if (/Art|UI|UX/.test(role)) return "design";
    if (/Vision/.test(role)) return "vision";
    if (/Game|Lead|Producer|Research|Director/.test(role)) return "planning";
    return "coding";
  }

  function routeRole(role) {
    var candidates = state.employees.filter(isUsable);
    if (!candidates.length) return null;

    var ranked = candidates.map(function (e) {
      var key = roleSkillKey(role);
      var quality = e.skills[key] || 50;
      var free = costScore(e);
      var score;
      if (state.settings.policy === "quality") {
        score = quality * .78 + free * .12 + e.skills.reliability * .10;
      } else if (state.settings.policy === "speed") {
        score = quality * .45 + e.skills.speed * .40 + free * .15;
      } else {
        score = quality * .42 + free * .43 + e.skills.reliability * .15;
      }
      return {employee:e,score:score};
    }).sort(function (a,b) { return b.score - a.score; });

    var blocked = state.employees
      .filter(function (e) { return !isUsable(e) && e.quota.unit !== "unlimited"; })
      .sort(function (a,b) {
        var key = roleSkillKey(role);
        return (b.skills[key] || 0) - (a.skills[key] || 0);
      })[0];

    ranked[0].failoverFrom = blocked || null;
    return ranked[0];
  }

  function consume(employee, weight, lineId) {
    if (!employee) return;
    var q = employee.quota;
    if (q.unit === "unlimited" || q.limit == null) return;
    var wasUsable = isUsable(employee);
    var use = Math.max(1, Math.ceil((q.limit / 100) * weight * .08));
    q.remaining = Math.max(0, q.remaining - use);
    if (wasUsable && !isUsable(employee)) {
      addLog("QUOTA WARNING",employee.name+" 예약선 도달 · 신규 비핵심 작업 배정 중단",lineId);
    }
  }

  function ensureContinuity() {
    if (state.employees.some(isUsable)) return;
    var hasLocal = state.employees.some(function (e) { return e.id === "local"; });
    if (!hasLocal) {
      state.employees.push(clone(MARKET[0]));
      addLog("AUTO HIRE", "모든 외부 무료쿼터가 예약선 이하라 Local Unlimited Worker를 자동 투입");
    }
  }

  function generateIdeas(topic, genre) {
    return IDEA_PATTERNS.map(function (pattern, i) {
      var metrics = {
        fun:72+((i*7+topic.length*3)%27),
        coreLoop:74+((i*5+topic.length*4)%25),
        costEfficiency:70+((i*11+topic.length)%28),
        scheduleFit:68+((i*9+topic.length*2)%30),
        differentiation:66+((i*13+topic.length*5)%32),
        technicalFeasibility:71+((i*6+topic.length*3)%27),
        marketability:67+((i*8+topic.length*4)%31),
        scalability:65+((i*10+topic.length*2)%33),
        riskSafety:69+((i*4+topic.length*5)%29)
      };
      var score = Math.round(
        metrics.fun*.20+metrics.coreLoop*.15+metrics.costEfficiency*.12+metrics.scheduleFit*.08+
        metrics.differentiation*.13+metrics.technicalFeasibility*.10+metrics.marketability*.10+
        metrics.scalability*.06+metrics.riskSafety*.06
      );
      return {
        id:"idea-"+Date.now()+"-"+i,
        title:topic+" · "+pattern[0],
        type:pattern[0],
        pitch:topic+"를 "+pattern[1],
        loop:pattern[2],
        genre:genre||"자동선택",
        score:score,
        quality:metrics.fun,
        cost:metrics.costEfficiency,
        novelty:metrics.differentiation,
        metrics:metrics,
        critiques:[
          "Creative Director: "+pattern[0]+"의 플레이 판타지와 반복 동기를 강화",
          "Technical Director: Web 단일 빌드에서 핵심 루프를 먼저 검증",
          "QA Lead: 3분 안에 규칙 학습·첫 성공·재도전이 가능한지 측정"
        ],
        status:"candidate"
      };
    }).sort(function (a,b) { return b.score - a.score; });
  }

  function gameFamily(type) {
    if (/Tycoon|Management/.test(type)) return "management";
    if (/Roguelike|Survivor|Extraction|Arcade/.test(type)) return "action";
    return "strategy";
  }

  function makeProductionPlan(idea, topic) {
    var family = gameFamily(idea.type);
    var variants = {
      strategy:{
        fantasy:"불완전한 정보를 읽고 결정적인 수를 설계하는 지휘관",
        audience:"짧은 세션에서도 생각할 거리를 원하는 전략·퍼즐 플레이어",
        session:"5–8분",
        controls:["카드 선택","분석 능력 사용","재시작"],
        systems:["매 라운드 변경되는 판정 규칙","콤보와 집중력 자원","난이도 상승과 제한 시간"],
        progression:"정답 연속 성공으로 집중력을 얻고 분석 능력을 해금",
        win:"12라운드를 제한 시간과 생명 안에 해결",
        lose:"생명 0 또는 제한 시간 종료",
        content:"3개 판정 규칙, 12라운드, 분석 능력, 반응형 UI"
      },
      action:{
        fantasy:"위험 지역을 돌파하며 자원을 회수하는 생존 파일럿",
        audience:"즉각적인 조작과 짧은 성장 루프를 선호하는 액션 플레이어",
        session:"3–5분",
        controls:["WASD/방향키 이동","포인터 이동","재시작"],
        systems:["추적 적 회피","에너지 코어 수집","보호막과 난이도 상승"],
        progression:"코어 수집으로 점수·속도·보호막이 단계적으로 강화",
        win:"제한 시간 동안 목표 코어를 수집하고 생존",
        lose:"적과 충돌해 내구도 0",
        content:"실시간 캔버스 맵, 적 스폰, 수집물, 보호막, 난이도 곡선"
      },
      management:{
        fantasy:"제한된 자원으로 조직을 성장시키는 운영 책임자",
        audience:"계획·효율화·숫자 성장에 만족을 느끼는 경영 플레이어",
        session:"6–10분",
        controls:["운영 행동 선택","연구/확장 구매","다음 날 진행"],
        systems:["크레딧·에너지·평판 경제","영구 업그레이드","12일 목표와 랜덤 이벤트"],
        progression:"연구 배수와 시설 확장으로 일일 자동 수익 증가",
        win:"12일 종료 시 목표 크레딧과 평판 달성",
        lose:"에너지·자금 운용 실패로 목표 미달",
        content:"4개 운영 행동, 3단계 연구, 시설 확장, 사건 로그, 결산"
      }
    };
    var spec = variants[family];
    return {
      version:"1.0",
      family:family,
      title:idea.title,
      elevatorPitch:topic+"의 테마를 "+idea.type+" 구조로 압축한 짧지만 완결된 웹게임",
      playerFantasy:spec.fantasy,
      audience:spec.audience,
      session:spec.session,
      coreLoop:String(idea.loop || "관찰 → 선택 → 결과 → 성장 → 재도전").split(" → "),
      controls:spec.controls,
      systems:spec.systems,
      progression:spec.progression,
      winCondition:spec.win,
      loseCondition:spec.lose,
      contentScope:spec.content,
      artDirection:"짙은 생산 콘솔 위에 "+topic+"을 상징하는 고대비 네온 색상과 명확한 상태 피드백",
      audioDirection:"외부 파일 없이도 동작하도록 시각 피드백 우선, 후속 빌드에서 WebAudio 효과음 추가",
      risks:["주제와 핵심 조작의 연결 약화","첫 30초 규칙 설명 부족","후반 난이도 급상승"],
      qaCriteria:["첫 입력 후 3초 안에 플레이 시작","모든 승패 상태에서 재시작 가능","모바일 360px와 데스크톱에서 조작 가능","콘솔 오류 0건","완전 오프라인 실행"],
      taskGraph:[
        {id:"T1",name:"핵심 루프 사양",depends:[],owner:"Game Designer"},
        {id:"T2",name:"경제·진행 설계",depends:["T1"],owner:"Systems Designer"},
        {id:"T3",name:"플레이어 입력·상태 머신",depends:["T1"],owner:"Gameplay Programmer"},
        {id:"T4",name:"콘텐츠·난이도 곡선",depends:["T2","T3"],owner:"Game Designer"},
        {id:"T5",name:"통합 HTML5 빌드",depends:["T3","T4"],owner:"Build Engineer"},
        {id:"T6",name:"브라우저 smoke QA",depends:["T5"],owner:"QA"}
      ]
    };
  }

  function ensureLinePlan(line) {
    if (!line.plan) {
      line.plan = makeProductionPlan({
        title:line.title,
        type:line.gameType || "Arcade Score",
        loop:"관찰 → 선택 → 결과 → 성장 → 재도전"
      }, line.topicName || "game");
    }
    return line.plan;
  }

  function createLine(idea, automatic) {
    if (state.lines.some(function (l) { return l.ideaId === idea.id; })) return;

    state.lines.push({
      id:"line-"+Date.now()+"-"+Math.random().toString(36).slice(2,7),
      ideaId:idea.id,
      title:idea.title,
      topicName:state.topic ? state.topic.name : "game",
      gameType:idea.type,
      plan:makeProductionPlan(idea, state.topic ? state.topic.name : "game"),
      stage:2,
      status:"running",
      autopilot:state.settings.autopilot,
      publication:{status:"not_ready",repository:null},
      handoffs:[],
      artifacts:["project-brief.md","idea-review.json","greenlight-draft.md"],
      history:[{time:now(),text:automatic ? "자동 shortlist로 생산라인 개설" : "CEO 지시로 생산라인 개설"}]
    });

    idea.status = "in-production";
    state.backlog = state.backlog.filter(function (x) { return x.id !== idea.id; });
    addLog("LINE START", idea.title+" 생산라인 개설");
  }

  function startFactory(form) {
    var fd = new FormData(form);
    var topic = String(fd.get("topic") || "").trim();
    if (!topic) return;

    var previousTopic = state.topic && state.topic.name;
    state.lines.forEach(function (line) {
      if (line.status === "running") {
        line.status = "paused";
        line.autopilot = false;
      }
    });

    state.topic = {
      name:topic,
      genre:String(fd.get("genre") || "자동선택"),
      platform:String(fd.get("platform") || "Windows PC"),
      notes:String(fd.get("notes") || ""),
      createdAt:now()
    };

    state.ideas = generateIdeas(topic, state.topic.genre);
    state.backlog = [];

    var n = Math.min(state.settings.autoShortlist, state.settings.maxParallel, state.ideas.length);
    state.ideas.forEach(function (idea, i) {
      if (i < n) createLine(idea, true);
      else {
        idea.status = "backlog";
        state.backlog.push(idea);
      }
    });

    if (previousTopic) addLog("TOPIC CHANGE",previousTopic+" → "+topic+" · 기존 진행라인 일시정지");
    addLog("IDEATION","아이디어 10개 생성 · 상위 "+n+"개 자동 shortlist · "+(10-n)+"개 Backlog 보관");
    editingTopic = false;
    save();
    render();
  }

  function jsonForScript(value) {
    return JSON.stringify(String(value == null ? "" : value)).replace(/</g, "\\u003c");
  }

  function planToMarkdown(line) {
    var p = ensureLinePlan(line);
    var taskRows = p.taskGraph.map(function (task) {
      return "| "+task.id+" | "+task.name+" | "+task.owner+" | "+(task.depends.length ? task.depends.join(", ") : "-")+" |";
    }).join("\n");
    return "# "+p.title+" — Game Design Document\n\n"+
      "- Version: "+p.version+"\n- Game family: "+p.family+"\n- Target session: "+p.session+"\n\n"+
      "## High concept\n\n"+p.elevatorPitch+"\n\n"+
      "**Player fantasy:** "+p.playerFantasy+"\n\n**Audience:** "+p.audience+"\n\n"+
      "## Core loop\n\n"+p.coreLoop.map(function (x, i) { return (i+1)+". "+x; }).join("\n")+"\n\n"+
      "## Controls\n\n"+p.controls.map(function (x) { return "- "+x; }).join("\n")+"\n\n"+
      "## Systems\n\n"+p.systems.map(function (x) { return "- "+x; }).join("\n")+"\n\n"+
      "## Progression and outcome\n\n- Progression: "+p.progression+"\n- Win: "+p.winCondition+"\n- Loss: "+p.loseCondition+"\n\n"+
      "## Production scope\n\n- Content: "+p.contentScope+"\n- Art: "+p.artDirection+"\n- Audio: "+p.audioDirection+"\n\n"+
      "## Risks\n\n"+p.risks.map(function (x) { return "- "+x; }).join("\n")+"\n\n"+
      "## Task graph\n\n| ID | Task | Owner | Dependencies |\n| --- | --- | --- | --- |\n"+taskRows+"\n";
  }

  function qaToMarkdown(line) {
    var p = ensureLinePlan(line);
    return "# "+p.title+" — QA Acceptance\n\n"+p.qaCriteria.map(function (x, i) {
      return "- [ ] QA-"+(i+1)+" "+x;
    }).join("\n")+"\n\n## Automated smoke\n\n- [x] Standalone HTML document\n- [x] Start/restart entry point\n- [x] No external runtime dependency\n";
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

  function buildPlayableGame(line) {
    var family = ensureLinePlan(line).family;
    if (family === "action") return buildActionGame(line);
    if (family === "management") return buildManagementGame(line);
    return buildStrategyGame(line);
  }

  function ensurePlayableBuild(line) {
    ensureLinePlan(line);
    if (!line.gameFiles || !line.gameFiles["index.html"] || !line.build || line.build.version !== "2.1") line.gameFiles = {"index.html":buildPlayableGame(line)};
    line.gameFiles["GDD.md"] = planToMarkdown(line);
    line.gameFiles["QA.md"] = qaToMarkdown(line);
    var html = line.gameFiles["index.html"];
    var smokePassed = /<!doctype html>/i.test(html) && html.indexOf("startGame") !== -1 && html.indexOf('data-ai-factory-game="v2"') !== -1;
    line.build = {
      version:"2.1",
      status:smokePassed ? "playable" : "failed",
      smokeTest:smokePassed ? "passed" : "failed",
      createdAt:line.build && line.build.createdAt ? line.build.createdAt : now()
    };
    ["GDD.md","QA.md","index.html"].forEach(function (name) { if (line.artifacts.indexOf(name) === -1) line.artifacts.push(name); });
    return smokePassed;
  }

  function openPlayableGame(lineId) {
    var line = state.lines.find(function (x) { return x.id === lineId; });
    if (!line || !ensurePlayableBuild(line)) return;
    var modal = document.createElement("div");
    modal.className = "gameModal";
    modal.innerHTML = '<div class="gameModalBar"><strong>'+esc(line.title)+'</strong><button class="button" data-close-game>닫기</button></div><iframe title="'+esc(line.title)+'" sandbox="allow-scripts"></iframe>';
    document.body.appendChild(modal);
    modal.querySelector("iframe").srcdoc = line.gameFiles["index.html"];
    modal.querySelector("[data-close-game]").onclick = function () { modal.remove(); };
  }

  function downloadPlayableGame(lineId) {
    var line = state.lines.find(function (x) { return x.id === lineId; });
    if (!line || !ensurePlayableBuild(line)) return;
    var url = URL.createObjectURL(new Blob([line.gameFiles["index.html"]], {type:"text/html;charset=utf-8"}));
    var anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = slugify(line.title)+".html";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function downloadTextArtifact(lineId, name) {
    var line = state.lines.find(function (x) { return x.id === lineId; });
    if (!line) return;
    ensurePlayableBuild(line);
    var body = line.gameFiles[name];
    if (!body) return;
    var url = URL.createObjectURL(new Blob([body], {type:"text/markdown;charset=utf-8"}));
    var anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = slugify(line.title)+"-"+name;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function showPlan(lineId) {
    var line = state.lines.find(function (x) { return x.id === lineId; });
    if (!line) return;
    var p = ensureLinePlan(line);
    var list = function (items) { return '<ul>'+items.map(function (x) { return '<li>'+esc(x)+'</li>'; }).join("")+'</ul>'; };
    var modal = document.createElement("div");
    modal.className = "planModal";
    modal.innerHTML = '<div class="planSheet">'+
      '<div class="planHead"><div><div class="eyebrow">PRODUCTION GDD · '+esc(p.family.toUpperCase())+'</div><h2>'+esc(p.title)+'</h2><p>'+esc(p.elevatorPitch)+'</p></div><button class="button" data-close-plan>닫기</button></div>'+
      '<div class="planGrid">'+
        '<section><h3>플레이 경험</h3><dl><dt>플레이어 판타지</dt><dd>'+esc(p.playerFantasy)+'</dd><dt>대상 플레이어</dt><dd>'+esc(p.audience)+'</dd><dt>세션</dt><dd>'+esc(p.session)+'</dd></dl></section>'+
        '<section><h3>핵심 루프</h3><ol>'+p.coreLoop.map(function (x) { return '<li>'+esc(x)+'</li>'; }).join("")+'</ol></section>'+
        '<section><h3>조작과 시스템</h3><h4>Controls</h4>'+list(p.controls)+'<h4>Systems</h4>'+list(p.systems)+'</section>'+
        '<section><h3>진행과 승패</h3><dl><dt>성장</dt><dd>'+esc(p.progression)+'</dd><dt>승리</dt><dd>'+esc(p.winCondition)+'</dd><dt>패배</dt><dd>'+esc(p.loseCondition)+'</dd></dl></section>'+
        '<section><h3>콘텐츠·표현 범위</h3><p>'+esc(p.contentScope)+'</p><p><strong>Art</strong> · '+esc(p.artDirection)+'</p><p><strong>Audio</strong> · '+esc(p.audioDirection)+'</p></section>'+
        '<section><h3>리스크와 QA</h3><h4>Risks</h4>'+list(p.risks)+'<h4>Acceptance</h4>'+list(p.qaCriteria)+'</section>'+
      '</div><section class="taskGraph"><h3>의존성 작업 그래프</h3>'+p.taskGraph.map(function (task) { return '<div><strong>'+esc(task.id)+' · '+esc(task.name)+'</strong><span>'+esc(task.owner)+' · depends on '+esc(task.depends.join(", ") || "none")+'</span></div>'; }).join("")+'</section>'+
      '<div class="lineActions"><button class="button primary" data-download-gdd="'+esc(line.id)+'">GDD.md 다운로드</button><button class="button" data-download-qa="'+esc(line.id)+'">QA.md 다운로드</button></div>'+
    '</div>';
    document.body.appendChild(modal);
    modal.querySelector("[data-close-plan]").onclick = function () { modal.remove(); };
    modal.querySelector("[data-download-gdd]").onclick = function () { downloadTextArtifact(line.id, "GDD.md"); };
    modal.querySelector("[data-download-qa]").onclick = function () { downloadTextArtifact(line.id, "QA.md"); };
  }

  function queueCompletedLine(line) {
    var existingReview = state.reviews.find(function (review) { return review.lineId === line.id; });
    var smokePassed = ensurePlayableBuild(line);
    var repository = slugify(line.topicName || "game")+"-"+slugify(line.title.split("·").pop());
    var owner = state.settings.githubOwner || "thstjdals09-lang";
    var repositoryUrl = "https://github.com/"+owner+"/"+encodeURIComponent(repository);
    var pagesUrl = "https://"+owner+".github.io/"+encodeURIComponent(repository)+"/";
    line.publication = {
      status:state.settings.autoPublish ? "awaiting_backend" : "waiting_for_approval",
      repository:repository,
      repositoryUrl:repositoryUrl,
      pagesUrl:pagesUrl
    };
    var reviewPayload = existingReview || {
      id:"review-"+Date.now()+"-"+Math.random().toString(36).slice(2,6),
      lineId:line.id
    };
    Object.assign(reviewPayload, {
      title:line.title,
      status:"pending",
      qaStatus:smokePassed ? "browser_smoke_passed" : "failed",
      build:"index.html",
      repository:repository,
      repositoryUrl:repositoryUrl,
      pagesUrl:pagesUrl,
      createdAt:now()
    });
    if (!existingReview) state.reviews.unshift(reviewPayload);
    addLog("BUILD READY",line.title+" · 실제 HTML5 빌드 생성 · 브라우저 smoke test "+(smokePassed ? "통과" : "실패"),line.id);
    if (state.settings.autoPublish) {
      addLog("PUBLISH WAITING",repository+" · Backend Publisher 연결 전이라 실제 GitHub 게시되지 않음",line.id);
    }
  }

  function runLine(lineId, automated) {
    ensureContinuity();
    var line = state.lines.find(function (x) { return x.id === lineId; });
    if (!line || line.status !== "running") return;

    var stage = STAGES[line.stage];
    if (!stage) return;

    var roleSets = {
      greenlight:["Producer","Technical Director","Lead Designer","QA"],
      preproduction:["Game Director","Lead Designer","Technical Director","UI/UX","Art Director"],
      prototype:["Gameplay Programmer","Systems Programmer","Game Designer","QA"],
      vertical:["Gameplay Programmer","UI/UX","Art Director","QA","Build Engineer"],
      production:["Gameplay Programmer","Systems Programmer","UI/UX","Art Director","QA"],
      qa:["QA","Build Engineer","Technical Director"],
      alpha:["Game Director","Gameplay Programmer","QA"],
      beta:["Game Designer","QA","Build Engineer"],
      polish:["UI/UX","QA","Release Manager"],
      release:["Build Engineer","Release Manager","QA"],
      live:["Live Ops","Analytics","QA"]
    };

    var weights = {greenlight:4,preproduction:8,prototype:12,vertical:15,production:20,qa:10,alpha:10,beta:9,polish:7,release:6,live:4};
    var roles = roleSets[stage[0]] || ["Producer","QA"];
    var assignments = [];

    roles.forEach(function (role) {
      var routed = routeRole(role);
      if (!routed) {
        assignments.push(role+" → 대기");
        return;
      }
      if (routed.failoverFrom) {
        var handoffKey = stage[0]+":"+role+":"+routed.failoverFrom.id+":"+routed.employee.id;
        if (line.handoffs.indexOf(handoffKey) === -1) {
          line.handoffs.push(handoffKey);
          addLog("FAILOVER",routed.failoverFrom.name+" 예약선 보호 → "+routed.employee.name+"에게 "+role+" handoff",line.id);
        }
      }
      consume(routed.employee, weights[stage[0]] || 4, line.id);
      assignments.push(role+" → "+routed.employee.name);
    });

    ensureContinuity();

    var artifactMap = {
      greenlight:["greenlight-report.md","risk-register.json"],
      preproduction:["GDD.md","architecture.md","ux-flow.md","art-bible.md"],
      prototype:["prototype-build.zip","prototype-findings.md"],
      vertical:["vertical-slice.zip","visual-review.md"],
      production:["production-build.zip","feature-status.json"],
      qa:["qa-report.md","regression-report.json"],
      alpha:["alpha-build.zip"],
      beta:["beta-build.zip","balance-report.md"],
      polish:["release-checklist.md"],
      release:["release-build.zip","release-notes.md"],
      live:["live-ops-plan.md"]
    };

    (artifactMap[stage[0]] || [stage[0]+"-output.md"]).forEach(function (a) {
      if (line.artifacts.indexOf(a) === -1) line.artifacts.push(a);
    });

    line.history.unshift({time:now(),text:stage[1]+": "+assignments.join(", ")});
    addLog("PRODUCTION",line.title+" · "+stage[1]+" 완료",line.id);

    if (line.stage < STAGES.length - 1) line.stage += 1;
    else {
      line.status = "complete";
      line.autopilot = false;
      queueCompletedLine(line);
    }

    save();
    if (!automated) render();
  }

  function automationTick() {
    if (!state.user.signedIn || !state.settings.autopilot) return;
    var running = state.lines.filter(function (line) {
      return line.status === "running" && line.autopilot;
    });
    if (!running.length) return;
    running.forEach(function (line) { runLine(line.id, true); });
    if (activeTab === "dashboard" || activeTab === "lines" || activeTab === "review" || activeTab === "results") render();
  }

  function finishLine(lineId) {
    var guard = STAGES.length + 2;
    var line = state.lines.find(function (x) { return x.id === lineId; });
    while (line && line.status === "running" && guard-- > 0) runLine(lineId, true);
    render();
  }

  function hire(id) {
    if (state.employees.some(function (e) { return e.id === id; })) return;
    var item = MARKET.find(function (x) { return x.id === id; });
    if (!item) return;
    state.employees.push(clone(item));
    addLog("HIRE",item.name+" 채용 완료");
    save();
    render();
  }

  function removeEmployee(id) {
    if (id === "local") return;
    state.employees = state.employees.filter(function (e) { return e.id !== id; });
    addLog("HR",id+" 사원 제거");
    save();
    render();
  }

  function resetQuota(id) {
    var e = state.employees.find(function (x) { return x.id === id; });
    var m = MARKET.find(function (x) { return x.id === id; });
    if (!e || !m) return;
    e.quota.remaining = m.quota.remaining;
    addLog("QUOTA",e.name+" 무료사용량 테스트 리셋");
    save();
    render();
  }

  function startBacklog(id) {
    var idea = state.backlog.find(function (x) { return x.id === id; });
    if (!idea) return;
    var running = state.lines.filter(function (x) { return x.status === "running"; }).length;
    if (running >= state.settings.maxParallel) {
      alert("현재 병렬 생산라인 한도에 도달했습니다.");
      return;
    }
    createLine(idea, false);
    save();
    render();
  }

  function addFeedback(lineId, text) {
    text = String(text || "").trim();
    if (!text) return;
    var line = state.lines.find(function (x) { return x.id === lineId; });
    if (!line) return;
    line.history.unshift({time:now(),text:"CEO 수정명령: "+text});
    addLog("CEO FEEDBACK",line.title+": "+text,line.id);
    save();
    render();
  }

  function toggleLineAutopilot(lineId) {
    var line = state.lines.find(function (x) { return x.id === lineId; });
    if (!line || line.status !== "running") return;
    line.autopilot = !line.autopilot;
    addLog("AUTOPILOT",line.title+" · "+(line.autopilot ? "자동 진행 재개" : "자동 진행 일시정지"),line.id);
    save();
    render();
  }

  function resumeLine(lineId) {
    var line = state.lines.find(function (x) { return x.id === lineId; });
    if (!line || line.status !== "paused") return;
    var running = state.lines.filter(function (x) { return x.status === "running"; }).length;
    if (running >= state.settings.maxParallel) {
      alert("현재 병렬 생산라인 한도에 도달했습니다.");
      return;
    }
    line.status = "running";
    line.autopilot = true;
    addLog("LINE RESUME",line.title+" · 생산라인 자동 진행 재개",line.id);
    save();
    render();
  }

  function approveReview(reviewId) {
    var review = state.reviews.find(function (x) { return x.id === reviewId; });
    if (!review) return;
    review.status = "approved";
    review.reviewedAt = now();
    addLog("CEO APPROVED",review.title+" 출시 빌드 승인",review.lineId);
    save();
    render();
  }

  function reviseReview(reviewId) {
    var review = state.reviews.find(function (x) { return x.id === reviewId; });
    var line = review && state.lines.find(function (x) { return x.id === review.lineId; });
    var input = document.getElementById("revision-"+reviewId);
    var note = input ? String(input.value || "").trim() : "";
    if (!review || !line || !note) return;
    review.status = "revision_requested";
    review.reviewedAt = now();
    line.status = "running";
    line.stage = 10;
    line.autopilot = true;
    line.publication.status = "held_for_revision";
    delete line.gameFiles;
    delete line.build;
    line.history.unshift({time:now(),text:"CEO 수정명령: "+note});
    addLog("CEO REVISION",line.title+" · "+note,line.id);
    save();
    activeTab = "lines";
    render();
  }

  function fakeGoogleLogin() {
    state.user = {signedIn:true,email:"ceo@example.com",name:"CEO (Preview)"};
    addLog("AUTH","Google 로그인 프리뷰 세션 생성");
    save();
    render();
  }

  function logout() {
    state.user = {signedIn:false,email:null,name:null};
    save();
    render();
  }

  function resetAll() {
    if (!confirm("웹 프리뷰 데이터를 전부 초기화할까요?")) return;
    state = defaultState();
    save();
    render();
  }

  function quotaBar(employee) {
    var p = quotaPct(employee);
    var danger = employee.quota.unit !== "unlimited" && p <= Math.round(employee.quota.reserve * 100);
    return '<div class="quota"><div class="quotaTop"><span>'+
      esc(employee.quota.unit === "unlimited" ? "무제한" : employee.quota.unit)+
      '</span><strong class="'+(danger ? "dangerText" : "")+'">'+
      (employee.quota.unit === "unlimited" ? "∞" : p+"%")+
      '</strong></div><div class="quotaTrack"><i style="width:'+p+'%"></i></div></div>';
  }

  function loginView() {
    var app = document.getElementById("app");
    app.innerHTML =
      '<div class="loginShell">'+
        '<div class="loginCard">'+
          '<div class="brandMark big">AF</div>'+
          '<div class="eyebrow">AI SOFTWARE FACTORY</div>'+
          '<h1>대표 로그인</h1>'+
          '<p>한 번 로그인하면 AI 사원·프로젝트·생산라인을 계정 기준으로 동기화하는 구조입니다.</p>'+
          '<button class="googleBtn" id="googleLogin"><span>G</span> Google로 계속하기</button>'+
          '<small>현재 GitHub Pages 프리뷰는 실제 OAuth 서버가 아직 연결되지 않아 데모 세션으로 진입합니다. 실제 버전에서는 서버측 Google OAuth + 암호화 Vault로 교체됩니다.</small>'+
        '</div>'+
      '</div>';

    document.getElementById("googleLogin").onclick = fakeGoogleLogin;
  }

  var TABS = [
    ["dashboard","대시보드"],
    ["ideas","아이디어"],
    ["lines","생산라인"],
    ["review","CEO Review"],
    ["results","결과물"],
    ["team","AI 사원"],
    ["market","AI 마켓"],
    ["logs","로그"],
    ["settings","설정"]
  ];

  function shell() {
    var app = document.getElementById("app");
    app.innerHTML =
      '<div class="shell">'+
        '<aside class="sidebar">'+
          '<div class="brand"><div class="brandMark">AF</div><div><strong>AI Factory</strong><span>Game Studio OS</span></div></div>'+
          '<div class="nav" id="nav"></div>'+
          '<div class="sidebarBottom"><span class="dot"></span>Factory Online<br><small>'+esc(state.user.email || "preview")+'</small></div>'+
        '</aside>'+
        '<main class="content">'+
          '<div class="topbar">'+
            '<div><div class="eyebrow">AUTONOMOUS GAME STUDIO</div><h1 id="pageTitle"></h1></div>'+
            '<div class="topActions"><span class="badge">LOWEST COST FIRST</span><button class="button small" id="logoutBtn">로그아웃</button></div>'+
          '</div>'+
          '<div id="view"></div>'+
        '</main>'+
      '</div>';

    var nav = document.getElementById("nav");
    TABS.forEach(function (tab) {
      var b = document.createElement("button");
      b.textContent = tab[1];
      b.className = tab[0] === activeTab ? "active" : "";
      b.onclick = function () {
        activeTab = tab[0];
        renderView();
      };
      nav.appendChild(b);
    });

    document.getElementById("logoutBtn").onclick = logout;
  }

  function render() {
    if (!state.user.signedIn) {
      loginView();
      return;
    }
    shell();
    renderView();
  }

  function titleFor(tab) {
    return {
      dashboard:"대표 대시보드",
      ideas:"아이디어 포트폴리오",
      lines:"게임 생산라인",
      review:"CEO Review",
      results:"게임 결과물 / 배포 현황",
      team:"AI 사원 / 사용량",
      market:"AI 플러그인 마켓",
      logs:"공장 로그",
      settings:"설정"
    }[tab] || "AI Factory";
  }

  function renderView() {
    document.querySelectorAll(".nav button").forEach(function (b, i) {
      b.classList.toggle("active", TABS[i][0] === activeTab);
    });
    document.getElementById("pageTitle").textContent = titleFor(activeTab);

    if (activeTab === "dashboard") renderDashboard();
    else if (activeTab === "ideas") renderIdeas();
    else if (activeTab === "lines") renderLines();
    else if (activeTab === "review") renderReview();
    else if (activeTab === "results") renderResults();
    else if (activeTab === "team") renderTeam();
    else if (activeTab === "market") renderMarket();
    else if (activeTab === "logs") renderLogs();
    else if (activeTab === "settings") renderSettings();
  }

  function lineCard(line) {
    var stage = STAGES[line.stage] || STAGES[STAGES.length-1];
    var idea = state.ideas.find(function (i) { return i.id === line.ideaId; });
    var progress = Math.round((line.stage / (STAGES.length - 1)) * 100);

    return '<div class="lineCard">'+
      '<div class="lineTop"><div><strong>'+esc(line.title)+'</strong><small>'+esc(stage[1])+'</small></div><span class="badge">'+progress+'%</span></div>'+
      '<div class="progressOuter"><div class="progressInner" style="width:'+progress+'%"></div></div>'+
      '<p>'+esc(idea ? idea.pitch : "")+'</p>'+
      '<div class="lineActions"><button class="button primary small" data-run="'+esc(line.id)+'">현재 공정 실행</button></div>'+
    '</div>';
  }

  function topicFormMarkup(isEdit) {
    return '<div class="panel">'+
      '<div class="eyebrow">'+(isEdit ? "CHANGE FACTORY THEME" : "NEW FACTORY RUN")+'</div>'+
      '<h2>'+(isEdit ? "새 주제로 생산 포트폴리오 전환" : "주제만 주면 아이디어 10개부터 시작합니다")+'</h2>'+
      (isEdit ? '<p class="muted">완료 결과는 보존하고, 현재 진행 중인 라인은 일시정지한 뒤 새 주제의 생산라인을 시작합니다.</p>' : '')+
      '<form class="form" id="topicForm">'+
        '<input name="topic" placeholder="예: 홀덤, 좀비, 타이핑, 카페 운영" required>'+
        '<div class="formRow">'+
          '<select name="genre"><option>자동선택</option><option>Roguelike</option><option>Deckbuilder</option><option>Tycoon</option><option>Strategy</option><option>Party</option></select>'+
          '<select name="platform"><option>Windows PC</option><option>Web</option><option>Mobile</option><option>Steam PC</option></select>'+
        '</div>'+
        '<textarea name="notes" rows="4" placeholder="선택: 분위기, 레퍼런스, 금지사항"></textarea>'+
        '<div class="lineActions"><button class="button primary">'+(isEdit ? "새 주제로 공장 전환" : "AI 공장 가동")+'</button>'+(isEdit ? '<button class="button" type="button" id="cancelTopicEdit">취소</button>' : '')+'</div>'+
      '</form>'+
    '</div>';
  }

  function renderDashboard() {
    var v = document.getElementById("view");
    var running = state.lines.filter(function (x) { return x.status === "running"; });
    var complete = state.lines.filter(function (x) { return x.status === "complete"; });
    var avgQuota = state.employees.length ?
      Math.round(state.employees.map(quotaPct).reduce(function (a,b) { return a+b; },0) / state.employees.length) : 0;

    var html =
      '<div class="grid4">'+
        '<div class="stat"><span>동시 생산라인</span><strong>'+running.length+'</strong><small>최대 '+state.settings.maxParallel+'</small></div>'+
        '<div class="stat"><span>아이디어 Backlog</span><strong>'+state.backlog.length+'</strong><small>언제든 생산 전환</small></div>'+
        '<div class="stat"><span>AI 사원</span><strong>'+state.employees.length+'</strong><small>평균 가용량 '+avgQuota+'%</small></div>'+
        '<div class="stat accent"><span>완료 게임</span><strong>'+complete.length+'</strong><small>검토 후 배포</small></div>'+
      '</div>';

    if (!state.topic || editingTopic) {
      html += topicFormMarkup(Boolean(state.topic));
    } else {
      html +=
        '<div class="panel">'+
          '<div class="panelHeader"><div><div class="eyebrow">ACTIVE BRIEF</div><h2>'+esc(state.topic.name)+'</h2></div><div class="headerActions"><span class="badge">'+esc(state.topic.platform)+'</span><button class="button small" id="changeTopic">주제 변경</button></div></div>'+
          '<p class="muted">아이디어 10개 생성 → 상위 '+state.settings.autoShortlist+'개 자동 생산 → 나머지 Backlog</p>'+
        '</div>'+
        '<div class="panel">'+
          '<div class="panelHeader"><div><div class="eyebrow">RUNNING LINES</div><h2>현재 생산중</h2></div><button class="button small" id="goLines">전체 보기</button></div>'+
          '<div class="cards">'+(running.length ? running.map(lineCard).join("") : '<div class="empty">진행중인 생산라인이 없습니다.</div>')+'</div>'+
        '</div>';
    }

    html +=
      '<div class="panel">'+
        '<div class="panelHeader"><div><div class="eyebrow">COST CONTROL</div><h2>최저비용 우선 라우팅</h2></div><span class="badge">AUTO FAILOVER</span></div>'+
        '<p class="muted">무료/무제한 자원을 우선 사용하고, 예약량 이하로 내려간 AI는 자동 제외합니다. 모든 외부 쿼터가 부족하면 Local Worker가 공장을 계속 유지합니다.</p>'+
      '</div>';

    v.innerHTML = html;

    var form = document.getElementById("topicForm");
    if (form) {
      if (state.topic) {
        form.elements.topic.value = state.topic.name || "";
        form.elements.genre.value = state.topic.genre || "자동선택";
        form.elements.platform.value = state.topic.platform || "Windows PC";
        form.elements.notes.value = state.topic.notes || "";
      }
      form.onsubmit = function (e) {
        e.preventDefault();
        startFactory(form);
      };
    }

    var changeTopic = document.getElementById("changeTopic");
    if (changeTopic) changeTopic.onclick = function () { editingTopic = true; renderView(); };
    var cancelTopicEdit = document.getElementById("cancelTopicEdit");
    if (cancelTopicEdit) cancelTopicEdit.onclick = function () { editingTopic = false; renderView(); };

    var go = document.getElementById("goLines");
    if (go) {
      go.onclick = function () {
        activeTab = "lines";
        renderView();
      };
    }

    v.querySelectorAll("[data-run]").forEach(function (b) {
      b.onclick = function () { runLine(b.getAttribute("data-run")); };
    });
  }

  function renderIdeas() {
    var v = document.getElementById("view");
    if (!state.topic) {
      v.innerHTML = '<div class="empty">먼저 대시보드에서 주제를 입력하세요.</div>';
      return;
    }

    v.innerHTML =
      '<div class="panel">'+
        '<div class="panelHeader"><div><div class="eyebrow">IDEATION PORTFOLIO</div><h2>AI가 만든 10개 아이디어</h2></div><span class="badge">TOP '+state.settings.autoShortlist+' AUTO-LINES</span></div>'+
        '<div class="ideaGrid">'+
          state.ideas.map(function (i) {
            var m = i.metrics || {fun:i.quality,coreLoop:i.quality,costEfficiency:i.cost,scheduleFit:i.cost,differentiation:i.novelty,technicalFeasibility:i.cost,marketability:i.quality,scalability:i.novelty,riskSafety:i.cost};
            var metricLabels = [["재미",m.fun],["핵심루프",m.coreLoop],["비용",m.costEfficiency],["일정",m.scheduleFit],["차별성",m.differentiation],["기술",m.technicalFeasibility],["시장성",m.marketability],["확장성",m.scalability],["리스크",m.riskSafety]];
            var critiques = i.critiques || ["Creative Director: 플레이 판타지 강화","Technical Director: 핵심 루프 우선 검증","QA Lead: 첫 성공까지의 시간을 측정"];
            return '<div class="idea '+(i.status === "in-production" ? "selected" : "")+'">'+
              '<div class="ideaTop"><span class="ideaScore">'+i.score+'</span><span class="chip">'+(i.status === "in-production" ? "생산중" : "Backlog")+'</span></div>'+
              '<h3>'+esc(i.title)+'</h3>'+
              '<p>'+esc(i.pitch)+'</p>'+
              '<div class="metricGrid">'+metricLabels.map(function (x) { return '<span><small>'+esc(x[0])+'</small><strong>'+esc(x[1])+'</strong></span>'; }).join("")+'</div>'+
              '<div class="critiqueList">'+critiques.map(function (x) { return '<small>'+esc(x)+'</small>'; }).join("")+'</div>'+
              '<div class="lineActions">'+(i.status !== "in-production" ? '<button class="button primary small" data-start="'+esc(i.id)+'">이 아이디어 제작</button>' : "")+'</div>'+
            '</div>';
          }).join("")+
        '</div>'+
      '</div>';

    v.querySelectorAll("[data-start]").forEach(function (b) {
      b.onclick = function () { startBacklog(b.getAttribute("data-start")); };
    });
  }

  function renderLines() {
    var v = document.getElementById("view");
    if (!state.lines.length) {
      v.innerHTML = '<div class="empty">생산라인이 아직 없습니다.</div>';
      return;
    }

    v.innerHTML = '<div class="cards">'+state.lines.map(function (line) {
      var stage = STAGES[line.stage];
      var roleNames = ["Leader","Designer","Engineer","QA"];
      var assignments = roleNames.map(function (role) {
        var routed = routeRole(role);
        return role+" → "+(routed ? routed.employee.name : "대기");
      }).join("<br>");

      return '<div class="panel lineDetail">'+
        '<div class="panelHeader"><div><div class="eyebrow">PRODUCTION LINE</div><h2>'+esc(line.title)+'</h2></div><span class="badge">'+esc(line.status.toUpperCase())+'</span></div>'+
        '<div class="currentStageBox"><strong>'+(line.stage+1)+'. '+esc(stage[1])+'</strong><p>'+esc(stage[2])+'</p><small>'+assignments+'</small></div>'+
        '<div class="stageStrip">'+STAGES.map(function (s, idx) {
          var cls = idx < line.stage ? "done" : (idx === line.stage ? "current" : "");
          return '<div class="miniStage '+cls+'"><span>'+(idx+1)+'</span><small>'+esc(s[1])+'</small></div>';
        }).join("")+'</div>'+
        '<div class="lineActions"><button class="button" data-plan="'+esc(line.id)+'">기획서 보기</button>'+
          (line.status === "running" ? '<button class="button" data-auto="'+esc(line.id)+'">'+(line.autopilot ? "자동진행 일시정지" : "자동진행 재개")+'</button><button class="button primary" data-finish="'+esc(line.id)+'">완성까지 즉시 실행</button>' : line.status === "paused" ? '<button class="button primary" data-resume="'+esc(line.id)+'">생산라인 재개</button>' : '<button class="button primary" data-results="1">결과물 보기</button>')+
        '</div>'+
        '<div class="feedbackBox"><input id="fb-'+esc(line.id)+'" placeholder="CEO 수정명령"><button class="button" data-feedback="'+esc(line.id)+'">피드백 반영</button></div>'+
        '<div class="artifactMini"><strong>산출물</strong><small>'+line.artifacts.map(esc).join(" · ")+'</small></div>'+
      '</div>';
    }).join("")+'</div>';

    v.querySelectorAll("[data-run]").forEach(function (b) {
      b.onclick = function () { runLine(b.getAttribute("data-run")); };
    });

    v.querySelectorAll("[data-auto]").forEach(function (b) {
      b.onclick = function () { toggleLineAutopilot(b.getAttribute("data-auto")); };
    });

    v.querySelectorAll("[data-finish]").forEach(function (b) {
      b.onclick = function () { finishLine(b.getAttribute("data-finish")); };
    });

    v.querySelectorAll("[data-resume]").forEach(function (b) {
      b.onclick = function () { resumeLine(b.getAttribute("data-resume")); };
    });

    v.querySelectorAll("[data-results]").forEach(function (b) {
      b.onclick = function () { activeTab = "results"; renderView(); };
    });

    v.querySelectorAll("[data-plan]").forEach(function (b) {
      b.onclick = function () { showPlan(b.getAttribute("data-plan")); };
    });

    v.querySelectorAll("[data-feedback]").forEach(function (b) {
      b.onclick = function () {
        var id = b.getAttribute("data-feedback");
        addFeedback(id, document.getElementById("fb-"+id).value);
      };
    });
  }

  function renderReview() {
    var v = document.getElementById("view");
    if (!state.reviews.length) {
      v.innerHTML = '<div class="empty">자동 생산이 완료되면 최신 빌드와 QA 결과가 이곳에 도착합니다.</div>';
      return;
    }

    v.innerHTML = '<div class="cards">'+state.reviews.map(function (review) {
      return '<div class="panel reviewCard">'+
        '<div class="panelHeader"><div><div class="eyebrow">RELEASE CANDIDATE</div><h2>'+esc(review.title)+'</h2></div><span class="badge">'+esc(review.status.toUpperCase())+'</span></div>'+
        '<div class="reviewFacts"><span>빌드 <strong>PLAYABLE HTML5</strong></span><span>QA <strong>'+esc(review.qaStatus.toUpperCase())+'</strong></span><span>GitHub 게시 <strong>BACKEND OFFLINE</strong></span></div>'+
        '<p class="muted">'+esc(review.createdAt)+' · 저장소 '+esc(review.repository)+'</p>'+
        '<div class="lineActions"><button class="button" data-plan="'+esc(review.lineId)+'">기획서 보기</button><button class="button primary" data-play="'+esc(review.lineId)+'">게임 테스트 실행</button></div>'+
        (review.status === "pending" ? '<div class="feedbackBox"><input id="revision-'+esc(review.id)+'" placeholder="수정이 필요하면 지시를 입력"><button class="button" data-revise="'+esc(review.id)+'">수정 요청</button><button class="button primary" data-approve="'+esc(review.id)+'">승인</button></div>' : '')+
      '</div>';
    }).join("")+'</div>';

    v.querySelectorAll("[data-approve]").forEach(function (b) {
      b.onclick = function () { approveReview(b.getAttribute("data-approve")); };
    });
    v.querySelectorAll("[data-revise]").forEach(function (b) {
      b.onclick = function () { reviseReview(b.getAttribute("data-revise")); };
    });
    v.querySelectorAll("[data-play]").forEach(function (b) {
      b.onclick = function () { openPlayableGame(b.getAttribute("data-play")); };
    });
    v.querySelectorAll("[data-plan]").forEach(function (b) {
      b.onclick = function () { showPlan(b.getAttribute("data-plan")); };
    });
  }

  function renderResults() {
    var v = document.getElementById("view");
    var completed = state.lines.filter(function (line) { return line.status === "complete" || line.publication.status !== "not_ready"; });
    if (!completed.length) {
      v.innerHTML = '<div class="empty">완성된 게임이 아직 없습니다. 생산라인은 Autopilot으로 계속 진행됩니다.</div>';
      return;
    }

    v.innerHTML =
      '<div class="playableNotice"><strong>HTML5 게임 빌드는 지금 바로 실제 실행할 수 있습니다.</strong><span>게임 테스트·다운로드는 동작합니다. GitHub 저장소와 Pages 링크는 Backend Publisher의 실제 성공 응답 후에만 활성화됩니다.</span></div>'+
      '<div class="resultGrid">'+completed.map(function (line) {
      var publication = line.publication || {};
      var isLive = publication.status === "published";
      var hasBuild = ensurePlayableBuild(line) && line.build.status === "playable";
      return '<div class="panel resultCard">'+
        '<div class="resultCover"><span>GAME BUILD</span><strong>'+esc(line.title)+'</strong></div>'+
        '<div class="panelHeader"><div><div class="eyebrow">PLAYABLE DELIVERY</div><h2>'+esc(publication.repository || line.title)+'</h2></div><span class="badge '+(isLive ? "liveBadge" : "offlineBadge")+'">'+(isLive ? "PAGES LIVE" : hasBuild ? "LOCAL PLAYABLE" : "BUILD FAILED")+'</span></div>'+
        '<div class="artifactMini"><strong>Standalone HTML5 Build</strong><small>index.html · browser smoke '+esc(line.build.smokeTest)+' · '+line.artifacts.length+' artifacts</small></div>'+
        '<div class="resultLinks">'+
          (hasBuild ? '<button class="button primary" data-play="'+esc(line.id)+'">브라우저에서 실행</button><button class="button" data-plan="'+esc(line.id)+'">기획서 보기</button><button class="button" data-download="'+esc(line.id)+'">HTML 게임 다운로드</button><button class="button" data-gdd="'+esc(line.id)+'">GDD 다운로드</button>' : '<button class="button" disabled>빌드 실패</button>')+
          (isLive ? '<a class="button" href="'+esc(publication.repositoryUrl)+'" target="_blank" rel="noopener">GitHub 저장소 ↗</a><a class="button primary" href="'+esc(publication.pagesUrl)+'" target="_blank" rel="noopener">GitHub Pages 실행 ↗</a>' : '<button class="button" disabled>저장소 미생성</button><button class="button" disabled>Pages 미배포</button>')+
        '</div>'+
        (!isLive ? '<div class="expectedUrls"><small>배포 예정 저장소</small><code>'+esc(publication.repositoryUrl || "-")+'</code><small>배포 예정 Pages</small><code>'+esc(publication.pagesUrl || "-")+'</code></div>' : '')+
      '</div>';
    }).join("")+'</div>';

    v.querySelectorAll("[data-play]").forEach(function (b) {
      b.onclick = function () { openPlayableGame(b.getAttribute("data-play")); };
    });
    v.querySelectorAll("[data-download]").forEach(function (b) {
      b.onclick = function () { downloadPlayableGame(b.getAttribute("data-download")); };
    });
    v.querySelectorAll("[data-plan]").forEach(function (b) {
      b.onclick = function () { showPlan(b.getAttribute("data-plan")); };
    });
    v.querySelectorAll("[data-gdd]").forEach(function (b) {
      b.onclick = function () { downloadTextArtifact(b.getAttribute("data-gdd"), "GDD.md"); };
    });
    save();
  }

  function renderTeam() {
    var v = document.getElementById("view");

    v.innerHTML =
      '<div class="panel">'+
        '<div class="panelHeader"><div><div class="eyebrow">EMPLOYEES / QUOTA</div><h2>AI 사원 사용량</h2></div><span class="badge">QUOTA GUARD ON</span></div>'+
        '<div class="employeeGrid">'+
          state.employees.map(function (e) {
            return '<div class="employeeCard">'+
              '<div class="employeeHead"><div><strong>'+esc(e.name)+'</strong><small>'+esc(e.provider)+' · '+esc(e.model)+'</small></div><span class="chip">'+(isUsable(e) ? "AVAILABLE" : "RESERVED")+'</span></div>'+
              quotaBar(e)+
              '<div class="skillRow"><span>코딩 '+e.skills.coding+'</span><span>기획 '+e.skills.planning+'</span><span>QA '+e.skills.qa+'</span></div>'+
              '<div class="lineActions"><button class="button small" data-reset="'+esc(e.id)+'">사용량 테스트 리셋</button>'+(e.id !== "local" ? '<button class="button danger small" data-remove="'+esc(e.id)+'">제거</button>' : "")+'</div>'+
            '</div>';
          }).join("")+
        '</div>'+
      '</div>';

    v.querySelectorAll("[data-reset]").forEach(function (b) {
      b.onclick = function () { resetQuota(b.getAttribute("data-reset")); };
    });

    v.querySelectorAll("[data-remove]").forEach(function (b) {
      b.onclick = function () { removeEmployee(b.getAttribute("data-remove")); };
    });
  }

  function renderMarket() {
    var v = document.getElementById("view");
    v.innerHTML =
      '<div class="panel">'+
        '<div class="panelHeader"><div><div class="eyebrow">AI PLUGIN MARKET</div><h2>추천 AI 사원</h2></div><span class="badge">+ TO HIRE</span></div>'+
        '<p class="muted">무료 정책은 바뀔 수 있으므로 실서비스에서는 provider status와 last_verified를 서버에서 갱신합니다. 현재 화면은 플러그인 UX와 라우팅 구조를 테스트하는 프리뷰입니다.</p>'+
        '<div class="marketGrid">'+MARKET.map(function (m) {
          var hired = state.employees.some(function (e) { return e.id === m.id; });
          return '<div class="marketCard">'+
            '<div class="marketTop"><div><strong>'+esc(m.name)+'</strong><small>'+esc(m.provider)+' · '+esc(m.model)+'</small></div><span class="badge">FREE</span></div>'+
            '<p>'+esc(m.tag)+'</p>'+
            '<div class="chipRow"><span class="chip">'+esc(m.auth)+'</span><span class="chip">'+esc(m.quota.unit)+'</span></div>'+
            '<button class="button '+(hired ? "" : "primary")+'" '+(hired ? "disabled" : "")+' data-hire="'+esc(m.id)+'">'+(hired ? "채용됨" : "+ AI 추가")+'</button>'+
          '</div>';
        }).join("")+'</div>'+
      '</div>';

    v.querySelectorAll("[data-hire]").forEach(function (b) {
      if (!b.disabled) b.onclick = function () { hire(b.getAttribute("data-hire")); };
    });
  }

  function renderLogs() {
    var v = document.getElementById("view");
    v.innerHTML =
      '<div class="panel">'+
        '<div class="panelHeader"><div><div class="eyebrow">FACTORY STREAM</div><h2>생산 로그</h2></div><span class="badge">'+state.logs.length+'</span></div>'+
        '<div class="logList">'+(state.logs.length ? state.logs.map(function (l) {
          return '<div class="logItem"><div><small>'+esc(l.time)+'</small><strong>'+esc(l.type)+'</strong></div><p>'+esc(l.text)+'</p></div>';
        }).join("") : '<div class="empty">로그가 없습니다.</div>')+'</div>'+
      '</div>';
  }

  function renderSettings() {
    var v = document.getElementById("view");
    v.innerHTML =
      '<div class="twoCol">'+
        '<div class="panel">'+
          '<div class="eyebrow">ROUTING POLICY</div><h2>생산 최적화</h2>'+
          '<div class="form">'+
            '<label>기본 정책<select id="policy"><option value="cheapest_viable">최저비용 + 충분한 품질</option><option value="quality">품질 우선</option><option value="speed">속도 우선</option></select></label>'+
            '<label>최대 동시 생산라인<input id="parallel" type="number" min="1" max="10" value="'+state.settings.maxParallel+'"></label>'+
            '<label>자동 shortlist 수<input id="shortlist" type="number" min="1" max="10" value="'+state.settings.autoShortlist+'"></label>'+
            '<label>GitHub 계정<input id="githubOwner" value="'+esc(state.settings.githubOwner || "thstjdals09-lang")+'"></label>'+
            '<label class="checkLabel"><input id="autopilot" type="checkbox" '+(state.settings.autopilot ? "checked" : "")+'> 생산라인 Autopilot</label>'+
            '<label class="checkLabel"><input id="autoPublish" type="checkbox" '+(state.settings.autoPublish ? "checked" : "")+'> Backend 연결 시 GitHub 자동 게시</label>'+
            '<button class="button primary" id="saveSettings">저장</button>'+
          '</div>'+
        '</div>'+
        '<div class="panel">'+
          '<div class="eyebrow">ACCOUNT / SYNC</div><h2>Google 계정 기반 동기화</h2>'+
          '<p class="muted">실서비스에서는 Google 로그인 → 서버측 계정 → 암호화 Vault에 Provider 자격증명 저장 → 모든 기기에서 동일한 AI 사원/프로젝트를 사용합니다. 공개 GitHub Pages에는 API Key를 저장하지 않습니다.</p>'+
          '<button class="button danger" id="resetAll">프리뷰 전체 초기화</button>'+
        '</div>'+
      '</div>';

    document.getElementById("policy").value = state.settings.policy;
    document.getElementById("saveSettings").onclick = function () {
      state.settings.policy = document.getElementById("policy").value;
      state.settings.maxParallel = Number(document.getElementById("parallel").value);
      state.settings.autoShortlist = Number(document.getElementById("shortlist").value);
      state.settings.githubOwner = String(document.getElementById("githubOwner").value || "thstjdals09-lang").trim();
      state.settings.autopilot = document.getElementById("autopilot").checked;
      state.settings.autoPublish = document.getElementById("autoPublish").checked;
      if (state.settings.autopilot) {
        state.lines.forEach(function (line) { if (line.status === "running") line.autopilot = true; });
      }
      save();
      renderView();
    };
    document.getElementById("resetAll").onclick = resetAll;
  }

  render();
  setInterval(automationTick, AUTOMATION_INTERVAL_MS);
})();
