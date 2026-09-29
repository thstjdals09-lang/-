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
        line.handoffs = line.handoffs || [];
        line.topicName = line.topicName || (x.topic && x.topic.name) || "game";
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
      var quality = 82 + ((i * 7 + topic.length * 3) % 17);
      var cost = 75 + ((i * 11 + topic.length) % 20);
      var novelty = 70 + ((i * 13 + topic.length * 5) % 27);
      var score = Math.round(quality * .45 + cost * .35 + novelty * .20);
      return {
        id:"idea-"+Date.now()+"-"+i,
        title:topic+" · "+pattern[0],
        type:pattern[0],
        pitch:topic+"를 "+pattern[1],
        loop:pattern[2],
        genre:genre||"자동선택",
        score:score,
        quality:quality,
        cost:cost,
        novelty:novelty,
        status:"candidate"
      };
    }).sort(function (a,b) { return b.score - a.score; });
  }

  function createLine(idea, automatic) {
    if (state.lines.some(function (l) { return l.ideaId === idea.id; })) return;

    state.lines.push({
      id:"line-"+Date.now()+"-"+Math.random().toString(36).slice(2,7),
      ideaId:idea.id,
      title:idea.title,
      topicName:state.topic ? state.topic.name : "game",
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

    state.topic = {
      name:topic,
      genre:String(fd.get("genre") || "자동선택"),
      platform:String(fd.get("platform") || "Windows PC"),
      notes:String(fd.get("notes") || ""),
      createdAt:now()
    };

    state.ideas = generateIdeas(topic, state.topic.genre);
    state.lines = state.lines.filter(function (line) { return line.status === "complete"; });
    state.backlog = [];

    var n = Math.min(state.settings.autoShortlist, state.settings.maxParallel, state.ideas.length);
    state.ideas.forEach(function (idea, i) {
      if (i < n) createLine(idea, true);
      else {
        idea.status = "backlog";
        state.backlog.push(idea);
      }
    });

    addLog("IDEATION","아이디어 10개 생성 · 상위 "+n+"개 자동 shortlist · "+(10-n)+"개 Backlog 보관");
    save();
    render();
  }

  function queueCompletedLine(line) {
    if (state.reviews.some(function (review) { return review.lineId === line.id; })) return;
    var repository = slugify(line.topicName || "game")+"-"+slugify(line.title.split("·").pop());
    var owner = state.settings.githubOwner || "thstjdals09-lang";
    var repositoryUrl = "https://github.com/"+owner+"/"+encodeURIComponent(repository);
    var pagesUrl = "https://"+owner+".github.io/"+encodeURIComponent(repository)+"/";
    line.publication = {
      status:state.settings.autoPublish ? "queued" : "waiting_for_approval",
      repository:repository,
      repositoryUrl:repositoryUrl,
      pagesUrl:pagesUrl
    };
    state.reviews.unshift({
      id:"review-"+Date.now()+"-"+Math.random().toString(36).slice(2,6),
      lineId:line.id,
      title:line.title,
      status:"pending",
      qaStatus:"passed",
      build:"release-build.zip",
      repository:repository,
      repositoryUrl:repositoryUrl,
      pagesUrl:pagesUrl,
      createdAt:now()
    });
    addLog("BUILD READY",line.title+" · QA 통과 · CEO Review 대기",line.id);
    if (state.settings.autoPublish) {
      addLog("PUBLISH QUEUED",repository+" 저장소 생성·commit·push 작업을 보안 백엔드에 예약",line.id);
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
      results:"완성 게임 결과물",
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

    if (!state.topic) {
      html +=
        '<div class="panel">'+
          '<div class="eyebrow">NEW FACTORY RUN</div>'+
          '<h2>주제만 주면 아이디어 10개부터 시작합니다</h2>'+
          '<form class="form" id="topicForm">'+
            '<input name="topic" placeholder="예: 홀덤, 좀비, 타이핑, 카페 운영" required>'+
            '<div class="formRow">'+
              '<select name="genre"><option>자동선택</option><option>Roguelike</option><option>Deckbuilder</option><option>Tycoon</option><option>Strategy</option><option>Party</option></select>'+
              '<select name="platform"><option>Windows PC</option><option>Web</option><option>Mobile</option><option>Steam PC</option></select>'+
            '</div>'+
            '<textarea name="notes" rows="4" placeholder="선택: 분위기, 레퍼런스, 금지사항"></textarea>'+
            '<button class="button primary">AI 공장 가동</button>'+
          '</form>'+
        '</div>';
    } else {
      html +=
        '<div class="panel">'+
          '<div class="panelHeader"><div><div class="eyebrow">ACTIVE BRIEF</div><h2>'+esc(state.topic.name)+'</h2></div><span class="badge">'+esc(state.topic.platform)+'</span></div>'+
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
      form.onsubmit = function (e) {
        e.preventDefault();
        startFactory(form);
      };
    }

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
            return '<div class="idea '+(i.status === "in-production" ? "selected" : "")+'">'+
              '<div class="ideaTop"><span class="ideaScore">'+i.score+'</span><span class="chip">'+(i.status === "in-production" ? "생산중" : "Backlog")+'</span></div>'+
              '<h3>'+esc(i.title)+'</h3>'+
              '<p>'+esc(i.pitch)+'</p>'+
              '<small>품질 '+i.quality+' · 비용효율 '+i.cost+' · 참신성 '+i.novelty+'</small>'+
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
        '<div class="lineActions">'+
          (line.status === "running" ? '<button class="button" data-auto="'+esc(line.id)+'">'+(line.autopilot ? "자동진행 일시정지" : "자동진행 재개")+'</button><button class="button primary" data-finish="'+esc(line.id)+'">완성까지 즉시 실행</button>' : '<button class="button primary" data-results="1">결과물 보기</button>')+
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

    v.querySelectorAll("[data-results]").forEach(function (b) {
      b.onclick = function () { activeTab = "results"; renderView(); };
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
        '<div class="reviewFacts"><span>빌드 <strong>'+esc(review.build)+'</strong></span><span>QA <strong>'+esc(review.qaStatus.toUpperCase())+'</strong></span><span>게시 <strong>AUTO QUEUED</strong></span></div>'+
        '<p class="muted">'+esc(review.createdAt)+' · 저장소 '+esc(review.repository)+'</p>'+
        (review.status === "pending" ? '<div class="feedbackBox"><input id="revision-'+esc(review.id)+'" placeholder="수정이 필요하면 지시를 입력"><button class="button" data-revise="'+esc(review.id)+'">수정 요청</button><button class="button primary" data-approve="'+esc(review.id)+'">승인</button></div>' : '')+
      '</div>';
    }).join("")+'</div>';

    v.querySelectorAll("[data-approve]").forEach(function (b) {
      b.onclick = function () { approveReview(b.getAttribute("data-approve")); };
    });
    v.querySelectorAll("[data-revise]").forEach(function (b) {
      b.onclick = function () { reviseReview(b.getAttribute("data-revise")); };
    });
  }

  function renderResults() {
    var v = document.getElementById("view");
    var completed = state.lines.filter(function (line) { return line.status === "complete" || line.publication.status !== "not_ready"; });
    if (!completed.length) {
      v.innerHTML = '<div class="empty">완성된 게임이 아직 없습니다. 생산라인은 Autopilot으로 계속 진행됩니다.</div>';
      return;
    }

    v.innerHTML = '<div class="resultGrid">'+completed.map(function (line) {
      var publication = line.publication || {};
      var isLive = publication.status === "published";
      return '<div class="panel resultCard">'+
        '<div class="resultCover"><span>GAME BUILD</span><strong>'+esc(line.title)+'</strong></div>'+
        '<div class="panelHeader"><div><div class="eyebrow">GITHUB DELIVERY</div><h2>'+esc(publication.repository || line.title)+'</h2></div><span class="badge">'+esc((publication.status || "queued").toUpperCase())+'</span></div>'+
        '<div class="artifactMini"><strong>Release Build</strong><small>release-build.zip · QA passed · '+line.artifacts.length+' artifacts</small></div>'+
        '<div class="resultLinks">'+
          '<a class="button" href="'+esc(publication.repositoryUrl || "#")+'" target="_blank" rel="noopener">GitHub 저장소</a>'+
          '<a class="button primary '+(isLive ? '' : 'disabledLink')+'" href="'+esc(publication.pagesUrl || "#")+'" target="_blank" rel="noopener">'+(isLive ? '게임 실행하기 ↗' : 'Pages 주소 보기 ↗')+'</a>'+
        '</div>'+
        (!isLive ? '<p class="muted smallCopy">예정 주소입니다. 백엔드 게시 Worker가 저장소 생성·commit·push·Pages 활성화를 마치면 자동으로 LIVE로 바뀝니다.</p>' : '')+
      '</div>';
    }).join("")+'</div>';
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
            '<label class="checkLabel"><input id="autoPublish" type="checkbox" '+(state.settings.autoPublish ? "checked" : "")+'> 완성 게임 GitHub 자동 게시</label>'+
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
