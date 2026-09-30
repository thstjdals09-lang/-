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
    '<section class="panel"><div class="panelHead"><div><div class="eyebrow">FACTORY STREAM</div><h2>생산 로그</h2></div><span class="chip">' + rows.length + " / " + state.logs.length + "</span></div>" +
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
  return (
    '<div class="loginShell"><div class="loginCard">' +
    '<div class="brandMark big" aria-hidden="true">AF</div><div class="eyebrow">AI FACTORY · GAME STUDIO OS</div>' +
    "<h1>CEO 로그인</h1><p>주제만 입력하면 AI 사원들이 아이디어부터 릴리즈 빌드까지 생산합니다. 계정 기준으로 AI 사원·자격증명 참조·프로젝트·쿼터 기록을 불러옵니다.</p>" +
    '<button class="googleBtn" data-action="google-login"><span aria-hidden="true">G</span> Google로 계속하기</button>' +
    '<p class="status" data-login-status>' + (s.backendUrl ? "백엔드: " + esc(s.backendUrl) : "백엔드 미설정 → Google 버튼은 프리뷰 세션으로 진입합니다.") + "</p>" +
    '<details><summary>백엔드 서버 연결</summary><form class="inlineForm" data-form="login-backend"><input name="backendUrl" type="url" placeholder="https://ai-factory.example.com" value="' + esc(s.backendUrl || "") + '"><button class="btn">저장</button></form></details>' +
    '<button class="btn ghost" data-action="preview-login">서버 없이 프리뷰로 둘러보기</button>' +
    "</div></div>"
  );
}
