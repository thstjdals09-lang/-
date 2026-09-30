// CEO Review, completed results, logs, settings and login views.

import { esc, fmtTime, pill, empty, publicationBlock } from "./ui.js";
import { POLICIES } from "./router.js";

export function review(app) {
  const { state, ctx } = app;
  if (!state.reviews.length) return empty("Vertical Slice와 Release Build가 끝나면 빌드·QA 결과가 이곳에 도착합니다.");
  const pending = state.reviews.filter((r) => r.status === "pending");
  const done = state.reviews.filter((r) => r.status !== "pending");
  const card = (r) => {
    const line = state.lines.find((l) => l.id === r.lineId);
    const stage = line && line.stages[r.stageId];
    const qaTasks = stage ? stage.tasks.filter((t) => t.qa) : [];
    return (
      '<article class="panel reviewCard">' +
      '<div class="thumb" data-thumb="' + esc(r.lineId) + '"><span>빌드 미리보기 (라이브 렌더)</span></div>' +
      '<div class="reviewBody"><div class="panelHead"><div><div class="eyebrow">' + (r.blocking ? "RELEASE CANDIDATE · 승인 필요" : "MILESTONE BUILD · 참고 검토") + "</div><h2>" + esc(r.title) + " <small>v" + esc(r.version) + "</small></h2></div>" + pill(r.status) + "</div>" +
      '<ul class="checks">' + r.qa.checks.map((c) => '<li class="' + (c.ok ? "ok" : "bad") + '">' + (c.ok ? "✓" : "✕") + " smoke · " + esc(c.id) + "</li>").join("") +
      qaTasks.map((t) => '<li class="' + (t.qa === "failed" ? "bad" : "ok") + '">' + (t.qa === "failed" ? "✕" : "✓") + " " + esc(t.name) + "</li>").join("") + "</ul>" +
      '<p class="muted small">' + esc(fmtTime(r.createdAt)) + (r.note ? " · 수정요청: " + esc(r.note) : "") + "</p>" +
      '<div class="actions wrap"><button class="btn primary" data-action="play" data-id="' + esc(r.lineId) + '">게임 테스트 실행</button><button class="btn" data-action="gdd" data-id="' + esc(r.lineId) + '">GDD</button><button class="btn" data-action="open-line" data-id="' + esc(r.lineId) + '">생산라인</button></div>' +
      (r.status === "pending"
        ? '<form class="inlineForm" data-form="revision" data-id="' + esc(r.id) + '"><input name="text" maxlength="200" placeholder="수정이 필요하면 지시 입력"><button class="btn" type="submit">수정 요청</button><button class="btn primary" type="button" data-action="approve" data-id="' + esc(r.id) + '">승인</button></form>'
        : "") +
      "</div></article>"
    );
  };
  return (
    '<section class="stack"><div class="sectionTitle"><h2>검토 대기 ' + pending.length + '</h2><span class="muted">Release Candidate는 승인해야 Live Ops로 넘어갑니다.</span></div>' +
    (pending.length ? pending.map(card).join("") : empty("대기 중인 검토가 없습니다.")) +
    (done.length ? '<div class="sectionTitle"><h2>처리됨 ' + done.length + "</h2></div>" + done.map(card).join("") : "") +
    "</section>"
  );
}

export function results(app) {
  const { state } = app;
  const mode = state.user.mode;
  const lines = state.lines.filter((l) => l.builds.length);
  if (!lines.length) return empty("아직 플레이 가능한 빌드가 없습니다. Prototype 단계 완료 시 첫 빌드가 생성됩니다.");
  const live = lines.filter((l) => l.publication && l.publication.status === "live");
  return (
    (mode === "backend"
      ? '<section class="panel"><div class="panelHead"><div><div class="eyebrow">DEPLOYED GAMES</div><h2>배포 링크 ' + live.length + "</h2></div></div>" +
        (live.length
          ? '<ul class="plainList">' + live.map((l) => '<li><div><strong>' + esc(l.title) + '</strong><small>v' + esc(l.publication.version || "") + " · " + (l.publication.kind === "release" ? "정식 릴리즈" : "플레이 빌드") + '</small></div><a class="btn small primary" href="' + esc(l.publication.pagesUrl) + '" target="_blank" rel="noopener">플레이 ↗</a><a class="btn small" href="' + esc(l.publication.repositoryUrl) + '" target="_blank" rel="noopener">저장소 ↗</a></li>').join("") + "</ul>"
          : '<p class="muted">접속 확인이 끝난 배포 링크가 여기에 모입니다.</p>') +
        "</section>"
      : '<p class="notice">프리뷰 모드: 빌드는 이 브라우저에서 sandbox iframe으로 실행·다운로드할 수 있습니다. GitHub 저장소 생성과 배포 링크는 백엔드 모드에서 만들어집니다.</p>') +
    '<div class="resultGrid">' +
    lines.map((l) => {
      const b = l.builds[0];
      return (
        '<article class="panel result"><div class="cover ' + esc(l.family) + '"><span>' + esc(l.family.toUpperCase()) + " · v" + esc(b.version) + "</span><strong>" + esc(l.title) + "</strong></div>" +
        '<div class="panelHead"><div><div class="eyebrow">' + esc(l.topic) + "</div><h2>" + esc(l.gameType) + "</h2></div>" + pill(l.status) + "</div>" +
        '<div class="actions wrap"><button class="btn primary" data-action="play" data-id="' + esc(l.id) + '">실행</button><button class="btn" data-action="download-build" data-id="' + esc(l.id) + '">HTML 다운로드</button><button class="btn" data-action="gdd" data-id="' + esc(l.id) + '">GDD</button><button class="btn" data-action="download-qa" data-id="' + esc(l.id) + '">QA 리포트</button></div>' +
        publicationBlock(l, mode) +
        "</article>"
      );
    }).join("") +
    "</div>"
  );
}

export function logs(app) {
  const { state } = app;
  const types = Array.from(new Set(state.logs.map((l) => l.type))).sort();
  const type = app.ui.logType || "ALL";
  const lineId = app.ui.logLine || "";
  const q = (app.ui.logQuery || "").toLowerCase();
  const rows = state.logs.filter((l) => (type === "ALL" || l.type === type) && (!lineId || l.lineId === lineId) && (!q || l.text.toLowerCase().includes(q)));
  return (
    '<section class="panel"><div class="panelHead"><div><div class="eyebrow">FACTORY STREAM</div><h2>생산 로그</h2></div><div class="actions"><span class="chip">' + rows.length + " / " + state.logs.length + "</span>" +
    (state.logs.length ? '<button class="btn danger small" data-action="logs-clear">로그 비우기</button>' : "") + "</div></div>" +
    '<div class="filters">' + ["ALL"].concat(types).map((t) => '<button class="' + (t === type ? "on" : "") + '" data-action="log-type" data-id="' + esc(t) + '">' + esc(t) + "</button>").join("") + "</div>" +
    '<div class="formRow"><label>생산라인<select data-change="log-line"><option value="">전체</option>' + state.lines.map((l) => '<option value="' + esc(l.id) + '"' + (l.id === lineId ? " selected" : "") + ">" + esc(l.title) + "</option>").join("") + "</select></label>" +
    '<label>검색<input data-change="log-query" value="' + esc(app.ui.logQuery || "") + '" placeholder="텍스트 검색"></label></div>' +
    (rows.length
      ? '<ul class="logList">' + rows.slice(0, 250).map((l) => '<li><small>' + esc(fmtTime(l.time)) + '</small><span class="evType t-' + esc(l.type.split(" ")[0].toLowerCase()) + '">' + esc(l.type) + "</span><p>" + esc(l.text) + "</p></li>").join("") + "</ul>"
      : empty("조건에 맞는 로그가 없습니다.")) +
    "</section>"
  );
}

export function settings(app) {
  const s = app.state.settings;
  const u = app.state.user;
  const opt = (obj, cur) => Object.entries(obj).map(([k, v]) => '<option value="' + k + '"' + (k === cur ? " selected" : "") + ">" + esc(v) + "</option>").join("");
  return (
    '<div class="twoCol"><section class="panel"><div class="eyebrow">PRODUCTION POLICY</div><h2>생산 최적화</h2>' +
    '<form class="form" data-form="settings">' +
    '<label>라우팅 정책<select name="policy">' + opt(POLICIES, s.policy) + "</select></label>" +
    '<div class="formRow"><label>최대 동시 생산라인<input name="maxParallel" type="number" min="1" max="10" value="' + s.maxParallel + '"></label>' +
    '<label>자동 shortlist 수<input name="autoShortlist" type="number" min="1" max="10" value="' + s.autoShortlist + '"></label>' +
    '<label>라인당 병렬 워커<input name="workersPerLine" type="number" min="1" max="8" value="' + s.workersPerLine + '"></label></div>' +
    '<label class="check"><input name="autopilot" type="checkbox"' + (s.autopilot ? " checked" : "") + "> 생산라인 Autopilot (Leader가 자동 진행)</label>" +
    (u.mode === "backend" ? "" : '<div class="formRow"><label>Provider 오류 시뮬레이션 ' + Math.round(s.failureRate * 100) + '%<input name="failureRate" type="range" min="0" max="60" step="2" value="' + Math.round(s.failureRate * 100) + '"></label>' +
    '<label>QA 실패 시뮬레이션 ' + Math.round(s.qaFailRate * 100) + '%<input name="qaFailRate" type="range" min="0" max="80" step="5" value="' + Math.round(s.qaFailRate * 100) + '"></label></div>') +
    '<button class="btn primary">저장</button></form></section>' +
    '<section class="panel"><div class="eyebrow">ACCOUNT · BACKEND</div><h2>계정과 서버</h2>' +
    '<p class="muted">로그인: <strong>' + esc(u.email || "-") + "</strong> · 모드 <strong>" + (u.mode === "backend" ? "백엔드 연결" : "프리뷰 (브라우저 시뮬레이션)") + "</strong></p>" +
    '<form class="form" data-form="backend"><label>AI Factory 백엔드 URL<input name="backendUrl" type="url" placeholder="https://ai-factory.example.com" value="' + esc(s.backendUrl || "") + '"></label>' +
    '<div class="actions"><button class="btn">저장 · 연결 확인</button></div><p class="status" data-backend-status></p></form>' +
    '<p class="muted small">구조: Browser → Google Login → AI Factory Backend → Encrypted Secret Vault → Provider API. 브라우저에는 credential reference만 저장합니다. 이 페이지의 localStorage에는 생산 시뮬레이션 상태만 있고 비밀값은 없습니다.</p>' +
    '<div class="actions"><button class="btn danger" data-action="reset-all">프리뷰 데이터 초기화</button></div></section></div>'
  );
}

export function login(app) {
  const s = app.state.settings;
  const info = app.ui.serverInfo || {};
  const online = !!info.online;
  const mode = app.ui.authMode === "register" ? "register" : "login";
  const flash = app.ui.loginFlash ? '<p class="notice">' + esc(app.ui.loginFlash) + "</p>" : "";
  const accountForm =
    '<div class="segmented"><button type="button" class="' + (mode === "login" ? "on" : "") + '" data-action="auth-mode" data-id="login">로그인</button>' +
    '<button type="button" class="' + (mode === "register" ? "on" : "") + '" data-action="auth-mode" data-id="register">회원가입</button></div>' +
    '<form class="form" data-form="' + (mode === "register" ? "register" : "password-login") + '">' +
    (mode === "register" ? '<label>이름 (선택)<input name="name" maxlength="60" autocomplete="nickname"></label>' : "") +
    '<label>이메일<input name="email" type="email" required autocomplete="email"></label>' +
    '<label>비밀번호' + (mode === "register" ? " (8자 이상)" : "") + '<input name="password" type="password" required minlength="' + (mode === "register" ? 8 : 1) + '" autocomplete="' + (mode === "register" ? "new-password" : "current-password") + '"></label>' +
    '<button class="btn primary">' + (mode === "register" ? "계정 만들기" : "로그인") + "</button>" +
    '<p class="status" data-auth-status></p></form>';
  return (
    '<div class="loginShell"><div class="loginCard">' +
    '<div class="brandMark big" aria-hidden="true">AF</div><div class="eyebrow">AI FACTORY · GAME STUDIO OS</div>' +
    "<h1>" + (mode === "register" ? "회원가입" : "로그인") + "</h1>" +
    "<p>계정마다 자기 AI(키), 프로젝트, 생산라인, 게임 배포가 따로 관리됩니다.</p>" + flash +
    (online
      ? accountForm +
        (info.google ? '<button class="googleBtn" data-action="google-login"><span aria-hidden="true">G</span> Google 계정으로 로그인</button>' : "") +
        (info.dev_login ? '<button class="btn ghost" data-action="google-login">개발용 이메일 로그인 (이 PC 전용)</button>' : "")
      : '<p class="notice">' + (s.backendUrl ? "AI Factory 서버(" + esc(s.backendUrl) + ")에 연결할 수 없습니다." : "AI Factory 서버가 꺼져 있습니다.") +
        " 서버를 운영하는 PC에서 <strong>start-public.cmd</strong>를 실행하면 이 링크로 로그인할 수 있습니다.</p>" +
        '<details><summary>서버 주소 직접 입력</summary><form class="inlineForm" data-form="login-backend"><input name="backendUrl" type="url" placeholder="https://….trycloudflare.com" value="' + esc(s.backendUrl || "") + '"><button class="btn">연결</button></form></details>') +
    '<div class="divider"><span>또는</span></div>' +
    '<button class="btn ghost" data-action="preview-login">게스트로 둘러보기 (계정 없음 · 시뮬레이션)</button>' +
    "</div></div>"
  );
}

export function account(app) {
  const { state } = app;
  if (state.user.mode !== "backend") {
    return (
      '<section class="panel"><div class="eyebrow">GUEST</div><h2>게스트 모드 · 계정 없음</h2>' +
      '<p class="muted">지금은 로그인하지 않은 프리뷰입니다. 데이터는 이 브라우저에만 저장되고, AI 키 연결·실제 게임 생성·GitHub 배포는 할 수 없습니다.</p>' +
      '<ol class="guide"><li>이 PC에서 <strong>start-backend.cmd</strong> 실행 → http://127.0.0.1:8000/console/ 에서 로그인</li><li>또는 운영 중인 AI Factory 서버 주소로 접속해 Google 계정으로 로그인</li></ol>' +
      '<div class="actions wrap"><button class="btn primary" data-action="logout">로그인 화면으로</button><button class="btn danger" data-action="reset-all">게스트 데이터 초기화</button></div></section>'
    );
  }
  const a = state.account;
  if (!a) return empty("계정 정보를 불러오는 중입니다…");
  const c = a.counts;
  const stat = (label, value) => "<div><dt>" + esc(label) + "</dt><dd>" + value + "</dd></div>";
  const ghUrl = "https://github.com/settings/tokens/new?scopes=repo&description=" + encodeURIComponent("AI Factory");
  return (
    '<div class="twoCol">' +
    '<section class="panel"><div class="panelHead"><div><div class="eyebrow">PROFILE</div><h2>' + esc(a.name || a.email) + "</h2></div>" +
    '<span class="pill ' + (a.role === "admin" ? "violet" : "neutral") + '">' + (a.role === "admin" ? "관리자" : "멤버") + "</span></div>" +
    '<dl class="facts compact">' + stat("이메일", esc(a.email)) + stat("로그인 방식", a.signIn === "google" ? "Google" : a.signIn === "password" ? "이메일·비밀번호" : "로컬(개발용)") +
    stat("가입", esc(fmtTime(parseServerTime(a.createdAt)))) + stat("최근 로그인", esc(fmtTime(parseServerTime(a.lastLoginAt)))) + "</dl></section>" +
    '<section class="panel"><div class="eyebrow">MY FACTORY</div><h2>내 사용 현황</h2><dl class="facts">' +
    stat("연결한 AI", c.ais + " (온라인 " + c.ais_online + ")") + stat("프로젝트", c.projects) + stat("생산라인", c.lines + " (가동 " + c.running + ")") +
    stat("빌드", c.builds) + stat("배포된 게임", c.deployed) + "</dl>" +
    '<p class="muted small">AI 키·프로젝트·게임은 이 계정에만 보입니다. 다른 사람은 자기 계정으로 로그인해 자기 AI를 연결합니다.</p></section>' +
    "</div>" +
    '<section class="panel"><div class="panelHead"><div><div class="eyebrow">GITHUB · 게임 배포</div><h2>내 GitHub 연결</h2></div>' +
    (a.github.connected ? '<span class="pill good">@' + esc(a.github.login) + " 연결됨</span>" : '<span class="pill warn">미연결</span>') + "</div>" +
    (a.github.connected
      ? '<p class="muted">완성된 게임은 <strong>@' + esc(a.github.login) + "</strong> 계정에 aif-… 저장소로 올라가고 GitHub Pages 링크가 만들어집니다.</p>" +
        '<div class="actions"><button class="btn danger" data-action="github-disconnect">GitHub 연결 해제</button></div>'
      : '<p class="muted">연결하지 않으면 게임은 이 서버에만 저장되고 배포 링크가 만들어지지 않습니다. 게임은 내 GitHub 계정에만 올라갑니다.</p>' +
        '<ol class="guide"><li>GitHub 로그인 후 토큰 발급 페이지 열기 (repo 권한이 미리 선택됨)</li><li>"Generate token" → 토큰 복사</li><li>아래에 붙여넣고 연결 (서버가 GitHub에 확인 후 암호화 저장)</li></ol>' +
        '<div class="actions wrap"><a class="btn" href="' + esc(ghUrl) + '" target="_blank" rel="noopener">① GitHub 로그인 · 토큰 발급 ↗</a></div>' +
        '<form class="inlineForm" data-form="github-connect"><input name="token" type="password" autocomplete="off" placeholder="ghp_… 또는 github_pat_…"><button class="btn primary">② 연결</button></form>' +
        '<p class="status" data-github-status></p>') +
    "</section>" +
    '<section class="panel"><div class="eyebrow">SECURITY · DATA</div><h2>보안과 데이터</h2>' +
    '<div class="actions wrap"><button class="btn" data-action="logout">로그아웃</button><button class="btn" data-action="logout-all">모든 기기에서 로그아웃</button>' +
    '<button class="btn" data-action="export-account">내 데이터 내보내기 (JSON, 키 제외)</button></div>' +
    '<details class="danger-zone"><summary>계정 삭제</summary><p class="muted small">AI 키, 연결한 AI, 프로젝트, 생산라인, 이 서버의 게임 저장소가 모두 삭제되고 되돌릴 수 없습니다. 이미 내 GitHub에 올라간 저장소는 GitHub에 남습니다.</p>' +
    '<form class="inlineForm" data-form="delete-account"><input name="email" placeholder="확인을 위해 ' + esc(a.email) + ' 입력"><button class="btn danger">계정 삭제</button></form></details>' +
    "</section>"
  );
}

function parseServerTime(value) {
  if (!value) return null;
  const ms = Date.parse(String(value).replace(" ", "T") + "Z");
  return Number.isNaN(ms) ? null : ms;
}
