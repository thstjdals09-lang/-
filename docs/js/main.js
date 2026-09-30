// AI Factory web console bootstrap: state, render loop, and event delegation.

import {
  STATE_VERSION, createState, createProject, tickFactory, tickLine, fastForward, startBacklogIdea, addFeedback,
  approveReview, requestRevision, setLineStatus, employeeFromCatalog, addLog, slugify,
} from "./engine.js";
import { buildGame, loadGameTemplates } from "./games.js";
import { gddMarkdown, qaMarkdown } from "./artifacts.js";
import { esc, download } from "./ui.js";
import { createApi, probeLocalEndpoint } from "./api.js";
import { fromSnapshot } from "./remote.js";
import * as floor from "./views-floor.js";
import * as ai from "./views-ai.js";
import * as ops from "./views-ops.js";

const STATE_KEY = "ai-factory-studio-v5";
// Earlier builds' test data (lines, games, logs) is discarded so the console starts clean.
const OBSOLETE_KEYS = ["ai-factory-studio-v3", "ai-factory-studio-v4"];
const UI_KEY = "ai-factory-ui-v1";
const TICK_MS = 1600;
const LIVE_TABS = new Set(["dashboard", "lines", "team", "logs"]);

const TABS = [
  ["dashboard", "대시보드", "대표 대시보드"],
  ["ideas", "아이디어", "아이디어 포트폴리오"],
  ["lines", "생산라인", "게임 생산라인"],
  ["review", "CEO Review", "CEO Review"],
  ["results", "결과물", "완성 빌드"],
  ["team", "AI 사원", "AI 사원 · 쿼터"],
  ["market", "AI 마켓", "AI 플러그인 마켓"],
  ["logs", "로그", "공장 로그"],
  ["settings", "설정", "설정"],
];

const app = { state: null, ctx: null, ui: null };
let catalog = null;
let previewState = null; // the browser simulation, set aside while signed in to the backend
let syncing = false;
let tickCount = 0;
const api = createApi(() => app.state && app.state.settings.backendUrl);

// ---------- persistence (non-secret production state only) ----------

function readJson(key) {
  try { return JSON.parse(localStorage.getItem(key)); } catch { return null; }
}
function writeJson(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage full or blocked */ }
}
function isRemote() {
  return !!(app.state && app.state.user.mode === "backend");
}

function save() {
  if (!isRemote()) writeJson(STATE_KEY, app.state);
  else if (previewState) {
    previewState.settings.backendUrl = app.state.settings.backendUrl;
    writeJson(STATE_KEY, previewState);
  }
  writeJson(UI_KEY, { tab: app.ui.tab, lineId: app.ui.lineId, marketFilter: app.ui.marketFilter });
}

function makeCtx() {
  return { studio: catalog.studio, providers: catalog.providers, catalogUpdated: catalog.updated, now: Date.now(), rng: Math.random };
}

// ---------- backend mode ----------

async function sync() {
  if (syncing) return;
  syncing = true;
  try {
    app.state = fromSnapshot(await api.state(), app.state, makeCtx());
  } finally {
    syncing = false;
  }
}

async function enterRemote(me) {
  if (!previewState) previewState = app.state;
  const base = createState(makeCtx());
  app.state = { ...base, user: { signedIn: true, mode: "backend", email: me.email, name: me.name }, settings: { ...base.settings, ...previewState.settings } };
  await sync();
}

function leaveRemote() {
  if (previewState) app.state = previewState;
  previewState = null;
  app.state.user = { signedIn: false, mode: null, email: null, name: null };
}

// Runs a backend call, resyncs and re-renders; failures are shown, never swallowed.
async function remote(call, { full = false } = {}) {
  try {
    await call();
    await sync();
  } catch (err) {
    if (err.status === 401) { leaveRemote(); render(); return; }
    alert("백엔드 요청 실패: " + (err.detail || err.message));
  }
  commit({ full });
}

// ---------- rendering ----------

function navCounts() {
  const s = app.state;
  return {
    lines: s.lines.filter((l) => l.status === "running").length,
    review: s.reviews.filter((r) => r.status === "pending").length,
    team: s.employees.length,
  };
}

function renderNav() {
  const nav = document.getElementById("nav");
  if (!nav) return;
  const counts = navCounts();
  nav.innerHTML = TABS.map(([id, label]) =>
    '<button class="' + (id === app.ui.tab ? "on" : "") + '" data-action="tab" data-id="' + id + '"' + (id === app.ui.tab ? ' aria-current="page"' : "") + ">" +
    esc(label) + (counts[id] ? '<span class="count">' + counts[id] + "</span>" : "") + "</button>").join("");
}

function renderView() {
  app.ctx = makeCtx();
  const view = document.getElementById("view");
  const title = document.getElementById("pageTitle");
  if (!view) return;
  const tab = TABS.find((t) => t[0] === app.ui.tab) || TABS[0];
  title.textContent = tab[2];
  const fn = {
    dashboard: floor.dashboard, ideas: floor.ideas, lines: floor.lines,
    team: ai.team, market: ai.market,
    review: ops.review, results: ops.results, logs: ops.logs, settings: ops.settings,
  }[tab[0]];
  view.innerHTML = fn(app);
  mountThumbs(view);
  renderNav();
}

function render() {
  const root = document.getElementById("app");
  app.ctx = makeCtx();
  if (!app.state.user.signedIn) {
    root.innerHTML = ops.login(app);
    return;
  }
  const u = app.state.user;
  root.innerHTML =
    '<div class="shell"><aside class="sidebar"><div class="brand"><div class="brandMark" aria-hidden="true">AF</div><div><strong>AI Factory</strong><span>Game Studio OS</span></div></div>' +
    '<nav class="nav" id="nav" aria-label="주요 메뉴"></nav>' +
    '<div class="sidebarFoot"><span class="dot ' + (u.mode === "backend" ? "live" : "") + '"></span>' + (u.mode === "backend" ? "Backend 연결" : "Preview 모드") + "<small>" + esc(u.email || "") + "</small></div></aside>" +
    '<main class="content"><header class="topbar"><div><div class="eyebrow">AUTONOMOUS GAME STUDIO · CEO</div><h1 id="pageTitle"></h1></div>' +
    '<div class="actions"><span class="chip">' + esc(app.state.settings.policy.toUpperCase()) + '</span><button class="btn small" data-action="logout">로그아웃</button></div></header>' +
    '<div id="view"></div></main></div>';
  renderView();
}

function mountThumbs(root) {
  root.querySelectorAll("[data-thumb]").forEach((el) => {
    const line = app.state.lines.find((l) => l.id === el.dataset.thumb);
    if (!line) return;
    const frame = document.createElement("iframe");
    frame.setAttribute("sandbox", "allow-scripts");
    frame.setAttribute("title", line.title + " 미리보기");
    frame.setAttribute("tabindex", "-1");
    frame.srcdoc = buildGame(line);
    el.appendChild(frame);
  });
}

function openModal(html) {
  const root = document.getElementById("modalRoot");
  root.innerHTML = html;
  const first = root.querySelector("input:not([disabled]),button");
  if (first) first.focus();
}
function closeModal() {
  document.getElementById("modalRoot").innerHTML = "";
  app.ui.connectId = null;
  app.ui.connectAuth = null;
}

function playModal(line) {
  const build = line.builds[0];
  if (isRemote() && build && build.id) {
    // Served by the backend under a CSP sandbox: generated code never gets the console's origin.
    openModal('<div class="modal play" role="dialog" aria-modal="true" aria-label="' + esc(line.title) + '"><div class="playBar"><strong>' + esc(line.title) + " · v" + esc(build.version) + '</strong><button class="btn small" data-action="close-modal">닫기</button></div><iframe sandbox="allow-scripts" title="' + esc(line.title) + '"></iframe></div>');
    document.querySelector("#modalRoot iframe").src = app.state.settings.backendUrl.replace(/\/+$/, "") + "/builds/" + encodeURIComponent(build.id) + "/play";
    return;
  }
  openModal('<div class="modal play" role="dialog" aria-modal="true" aria-label="' + esc(line.title) + '"><div class="playBar"><strong>' + esc(line.title) + " · v" + esc(line.builds[0] ? line.builds[0].version : "-") + '</strong><button class="btn small" data-action="close-modal">닫기</button></div><iframe sandbox="allow-scripts" title="' + esc(line.title) + '"></iframe></div>');
  document.querySelector("#modalRoot iframe").srcdoc = buildGame(line);
}

function textModal(title, body, filename) {
  openModal('<div class="modal" role="dialog" aria-modal="true" aria-label="' + esc(title) + '"><div class="sheet"><div class="panelHead"><div><div class="eyebrow">ARTIFACT</div><h2>' + esc(title) + '</h2></div><div class="actions"><button class="btn small primary" data-action="download-text">다운로드</button><button class="btn small" data-action="close-modal">닫기</button></div></div><pre class="doc"></pre></div></div>');
  document.querySelector("#modalRoot pre").textContent = body;
  app.ui.pendingDownload = { filename, body };
}

// ---------- actions ----------

function lineById(id) { return app.state.lines.find((l) => l.id === id); }
function empById(id) { return app.state.employees.find((e) => e.id === id); }

function commit(opts = {}) {
  save();
  if (opts.full) render();
  else renderView();
}

const actions = {
  tab(id) { app.ui.tab = id; app.ui.editingTopic = false; commit(); window.scrollTo(0, 0); },
  "new-topic"() { app.ui.editingTopic = true; commit(); },
  "cancel-topic"() { app.ui.editingTopic = false; commit(); },
  "open-line"(id) { app.ui.tab = "lines"; app.ui.lineId = id; app.ui.stageId = null; commit(); window.scrollTo(0, 0); },
  stage(id) { app.ui.stageId = id; commit(); },
  project(id) { app.ui.projectId = id; commit(); },
  "build-idea"(id) {
    const res = startBacklogIdea(app.state, id, app.ctx);
    if (!res.ok && res.reason === "capacity") {
      alert("병렬 생산라인 한도(" + app.state.settings.maxParallel + ")에 도달했습니다. 설정에서 한도를 늘리거나 라인을 일시정지하세요.");
      return;
    }
    if (res.line) { app.ui.tab = "lines"; app.ui.lineId = res.line.id; }
    commit();
  },
  "line-autopilot"(id) { const l = lineById(id); setLineStatus(app.state, id, l.autopilot ? "pause" : "resume", app.ctx); commit(); },
  "line-resume"(id) {
    const res = setLineStatus(app.state, id, "resume", app.ctx);
    if (!res.ok && res.reason === "capacity") alert("병렬 생산라인 한도에 도달했습니다.");
    commit();
  },
  "line-step"(id) { tickLine(app.state, lineById(id), app.ctx); commit(); },
  "line-ff"(id) { fastForward(app.state, lineById(id), app.ctx); commit(); },
  play(id) { const l = lineById(id); if (l) playModal(l); },
  gdd(id) {
    const l = lineById(id);
    const idea = l && app.state.ideas.find((i) => i.id === l.ideaId);
    if (l) textModal(l.title + " · GDD", gddMarkdown(l, idea), slugify(l.title) + "-GDD.md");
  },
  "download-qa"(id) { const l = lineById(id); if (l) download(slugify(l.title) + "-QA.md", qaMarkdown(l), "text/markdown;charset=utf-8"); },
  "download-build"(id) {
    const l = lineById(id);
    if (l) download(slugify(l.title) + "-v" + (l.builds[0] ? l.builds[0].version : "0") + ".html", buildGame(l), "text/html;charset=utf-8");
  },
  "download-text"() { const d = app.ui.pendingDownload; if (d) download(d.filename, d.body, "text/markdown;charset=utf-8"); },
  "close-modal"() { closeModal(); },
  approve(id) { approveReview(app.state, id, app.ctx); commit(); },
  "market-filter"(id) { app.ui.marketFilter = id; commit(); },
  connect(id) { app.ui.connectId = id; app.ui.connectAuth = null; openModal(ai.connectModal(app, id)); },
  "connect-auth"(auth) { app.ui.connectAuth = auth; openModal(ai.connectModal(app, app.ui.connectId)); },
  "emp-pause"(id) { empById(id).status = "paused"; addLog(app.state, app.ctx, "HR", empById(id).name + " 신규 배정 중지"); commit(); },
  "emp-resume"(id) { empById(id).status = "online"; addLog(app.state, app.ctx, "HR", empById(id).name + " 배정 재개"); commit(); },
  "emp-reauth"(id) { const e = empById(id); e.status = "online"; e.cooldownUntil = 0; addLog(app.state, app.ctx, "AUTH", e.name + " 재인증 완료 (시뮬레이션)"); commit(); },
  "emp-drain"(id) {
    const e = empById(id);
    e.quota.used = Math.round(e.quota.limit * (1 - e.quota.reserve) * 100) / 100;
    addLog(app.state, app.ctx, "QUOTA WARNING", e.name + " 쿼터 소진 테스트 → 예약선 도달, 비핵심 작업은 다른 AI로 failover");
    commit();
  },
  "emp-reset"(id) { const e = empById(id); e.quota.used = 0; e.cooldownUntil = 0; addLog(app.state, app.ctx, "QUOTA RESET", e.name + " 사용량 테스트 리셋"); commit(); },
  "emp-remove"(id) {
    const e = empById(id);
    if (!confirm(e.name + "을(를) 해고할까요? 진행 중인 작업은 다른 AI로 재배정됩니다.")) return;
    app.state.employees = app.state.employees.filter((x) => x.id !== id);
    addLog(app.state, app.ctx, "HR", e.name + " 해고");
    commit();
  },
  "log-type"(id) { app.ui.logType = id; commit(); },
  "reset-all"() {
    if (!confirm("브라우저에 저장된 프리뷰 생산 데이터를 모두 지울까요?")) return;
    const keep = { user: app.state.user, backendUrl: app.state.settings.backendUrl };
    app.state = createState(app.ctx);
    app.state.user = keep.user;
    app.state.settings.backendUrl = keep.backendUrl;
    app.ui.tab = "dashboard";
    commit({ full: true });
  },
  "preview-login"() {
    app.state.user = { signedIn: true, mode: "preview", email: "preview@local", name: "CEO (Preview)" };
    addLog(app.state, app.ctx, "AUTH", "프리뷰 세션 시작 · 서버·자격증명 없이 브라우저 시뮬레이션");
    // Seed the recommended free AIs as simulated employees so routing and failover are visible.
    if (app.state.employees.length <= 1) {
      for (const p of app.ctx.providers.filter((x) => x.recommended && x.auth_types[0] !== "local")) {
        if (!app.state.employees.some((e) => e.catalogId === p.id)) app.state.employees.push(employeeFromCatalog(p, app.ctx));
      }
      addLog(app.state, app.ctx, "HIRE", "추천 무료 AI 스타터 팀을 시뮬레이션 사원으로 배치");
    }
    commit({ full: true });
  },
  async "google-login"() {
    const status = document.querySelector("[data-login-status]");
    if (!api.configured()) { actions["preview-login"](); return; }
    status.textContent = "백엔드 확인 중…";
    try {
      const health = await api.health();
      if (health.google_oauth) {
        location.href = api.loginUrl(location.origin + location.pathname);
        return;
      }
      if (!health.dev_login) {
        status.textContent = "백엔드에 Google OAuth가 아직 설정되지 않았습니다 (AI_FACTORY_GOOGLE_CLIENT_ID/SECRET).";
        return;
      }
      const email = prompt("개발용 로그인 (AI_FACTORY_DEV_LOGIN=1) 이메일", "ceo@localhost");
      if (!email) return;
      await enterRemote(await api.devLogin(email));
      commit({ full: true });
    } catch (err) {
      status.textContent = "백엔드에 연결할 수 없습니다 (" + err.detail + "). 프리뷰로 둘러볼 수 있습니다.";
    }
  },
  async logout() {
    if (app.state.user.mode === "backend") { try { await api.logout(); } catch { /* already signed out */ } }
    app.state.user = { signedIn: false, mode: null, email: null, name: null };
    commit({ full: true });
  },
};

// Backend-mode overrides: the server Leader owns production state.
const remoteActions = {
  "build-idea"(id) {
    remote(async () => {
      try {
        const res = await api.buildIdea(id);
        app.ui.tab = "lines";
        app.ui.lineId = res.lineId;
      } catch (err) {
        if (err.status === 409) { alert("병렬 생산라인 한도에 도달했습니다."); return; }
        throw err;
      }
    });
  },
  "line-autopilot"(id) { const l = lineById(id); remote(() => api.setAutopilot(id, !l.autopilot)); },
  "line-resume"(id) { remote(() => api.setAutopilot(id, true)); },
  "line-step"(id) { remote(() => api.tickLine(id)); },
  "line-ff"(id) { remote(() => api.runLine(id)); },
  approve(id) { remote(() => api.approve(id)); },
  "emp-reauth"(id) { remote(() => api.verifyConnection(id)); },
  "emp-remove"(id) {
    const e = empById(id);
    if (!confirm(e.name + " 연결과 Vault 자격증명을 삭제할까요?")) return;
    remote(() => api.deleteConnection(id));
  },
  async logout() {
    try { await api.logout(); } catch { /* already signed out */ }
    leaveRemote();
    commit({ full: true });
  },
};

const remoteForms = {
  topic(form) {
    const fd = new FormData(form);
    const topic = String(fd.get("topic") || "").trim();
    if (!topic) return;
    app.ui.editingTopic = false;
    remote(() => api.createProject({ topic, genre: fd.get("genre"), platform: fd.get("platform"), notes: fd.get("notes") || "" }));
  },
  feedback(form) {
    const text = String(new FormData(form).get("text") || "").trim();
    if (text) remote(() => api.feedback(form.dataset.id, text));
  },
  revision(form) {
    const text = String(new FormData(form).get("text") || "").trim();
    if (!text) { form.querySelector("input").focus(); return; }
    remote(() => api.revise(form.dataset.id, text));
  },
  settings(form) {
    const fd = new FormData(form);
    remote(() => api.patchSettings({
      policy: fd.get("policy"),
      max_parallel: clampInt(fd.get("maxParallel"), 1, 10),
      auto_shortlist: clampInt(fd.get("autoShortlist"), 1, 10),
      workers_per_line: clampInt(fd.get("workersPerLine"), 1, 8),
    }));
  },
};

const forms = {
  topic(form) {
    const fd = new FormData(form);
    const topic = String(fd.get("topic") || "").trim();
    if (!topic) return;
    const project = createProject(app.state, { topic, genre: fd.get("genre"), platform: fd.get("platform"), notes: fd.get("notes") }, app.ctx);
    app.ui.editingTopic = false;
    app.ui.projectId = project.id;
    commit();
  },
  feedback(form) {
    const text = new FormData(form).get("text");
    if (addFeedback(app.state, form.dataset.id, text, app.ctx)) commit();
  },
  revision(form) {
    const text = String(new FormData(form).get("text") || "").trim();
    if (!text) { form.querySelector("input").focus(); return; }
    requestRevision(app.state, form.dataset.id, text, app.ctx);
    commit();
  },
  settings(form) {
    const fd = new FormData(form);
    const s = app.state.settings;
    s.policy = fd.get("policy");
    s.maxParallel = clampInt(fd.get("maxParallel"), 1, 10);
    s.autoShortlist = clampInt(fd.get("autoShortlist"), 1, 10);
    s.workersPerLine = clampInt(fd.get("workersPerLine"), 1, 8);
    s.autopilot = fd.get("autopilot") === "on";
    s.failureRate = clampInt(fd.get("failureRate"), 0, 60) / 100;
    s.qaFailRate = clampInt(fd.get("qaFailRate"), 0, 80) / 100;
    for (const l of app.state.lines) if (l.status === "running") l.autopilot = s.autopilot;
    addLog(app.state, app.ctx, "SETTINGS", "정책 " + s.policy + " · 병렬 " + s.maxParallel + " · 워커 " + s.workersPerLine);
    commit();
  },
  async backend(form) {
    app.state.settings.backendUrl = String(new FormData(form).get("backendUrl") || "").trim();
    save();
    const status = form.querySelector("[data-backend-status]");
    if (!api.configured()) { status.textContent = "백엔드 URL을 비웠습니다. 프리뷰 모드로 동작합니다."; return; }
    status.textContent = "연결 확인 중…";
    try {
      const h = await api.health();
      status.textContent = "연결됨 · " + JSON.stringify(h) + " · 로그아웃 후 Google 로그인하면 계정 모드로 전환됩니다.";
    } catch (err) {
      status.textContent = "연결 실패: " + err.detail;
    }
  },
  "login-backend"(form) {
    app.state.settings.backendUrl = String(new FormData(form).get("backendUrl") || "").trim();
    save();
    render();
  },
  async connect(form) {
    const p = app.ctx.providers.find((x) => x.id === form.dataset.id);
    const fd = new FormData(form);
    const auth = fd.get("auth");
    const endpoint = String(fd.get("endpoint") || "").trim();
    const keyInput = form.querySelector('input[name="api_key"]');
    const apiKey = keyInput ? keyInput.value : "";
    if (keyInput) keyInput.value = ""; // never keep the secret in the DOM longer than needed
    const status = form.querySelector("[data-connect-status]");
    const install = (overrides, note) => {
      if (app.state.employees.some((e) => e.catalogId === p.id)) return;
      const e = employeeFromCatalog(p, app.ctx, { authType: auth, ...overrides });
      if (endpoint && auth !== "api_key") e.endpoint = endpoint;
      app.state.employees.push(e);
      addLog(app.state, app.ctx, "HIRE", p.name + " 설치 · " + auth + " · " + note);
      closeModal();
      commit();
    };

    if (auth === "local" && !isRemote()) {
      status.textContent = "로컬 엔드포인트 헬스체크 중…";
      const probe = await probeLocalEndpoint(endpoint || p.base_url);
      if (probe.ok) install({ connectionMode: "verified", endpoint }, "health_check 통과 · 모델 " + probe.models.length + "개");
      else install({ connectionMode: "simulated", endpoint }, "엔드포인트 응답 없음(" + probe.reason + ") → 시뮬레이션");
      const e = empById(p.id);
      if (e && probe.ok) e.lastVerified = Date.now();
      return;
    }
    if (app.state.user.mode !== "backend") {
      install({ connectionMode: "simulated" }, "프리뷰 시뮬레이션 (자격증명 없음)");
      return;
    }
    try {
      if (auth === "oauth") {
        status.textContent = "OAuth 시작 중…";
        const res = await api.oauthStart(p.id, location.origin + location.pathname);
        location.href = res.authorize_url;
        return;
      }
      if (!apiKey && auth === "api_key") { status.textContent = "API Key를 입력하세요."; return; }
      status.textContent = "Vault 저장 · health_check · quota_probe 중…";
      const res = await api.connectProvider({ catalog_id: p.id, auth_type: auth, api_key: apiKey || null, endpoint: endpoint || null });
      await sync();
      closeModal();
      commit();
      if (res.status !== "online") alert(p.name + " 연결 상태: " + res.status + (res.last_error ? " · " + res.last_error : ""));
    } catch (err) {
      status.textContent = err.status === 501 ? "이 provider의 OAuth adapter는 아직 준비 중입니다. API key 방식을 사용하세요." : "연결 실패: " + (err.detail || err.message);
    }
  },
};

function clampInt(v, lo, hi) {
  const n = Math.round(Number(v));
  return Number.isFinite(n) ? Math.max(lo, Math.min(hi, n)) : lo;
}

function bindEvents() {
  document.addEventListener("click", (ev) => {
    const el = ev.target.closest("[data-action]");
    if (!el || el.disabled) return;
    const fn = (isRemote() && remoteActions[el.dataset.action]) || actions[el.dataset.action];
    if (!fn) return;
    ev.preventDefault();
    app.ctx = makeCtx();
    fn(el.dataset.id);
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && document.getElementById("modalRoot").innerHTML) closeModal();
    if (ev.key === "Enter" && ev.target.matches("article[data-action]")) ev.target.click();
  });
  document.addEventListener("submit", (ev) => {
    const form = ev.target;
    const name = form.id === "topicForm" ? "topic" : form.dataset.form;
    const fn = (isRemote() && remoteForms[name]) || forms[name];
    if (!fn) return;
    ev.preventDefault();
    app.ctx = makeCtx();
    fn(form);
  });
  document.addEventListener("change", (ev) => {
    const el = ev.target;
    if (el.dataset.change === "reserve") {
      const e = empById(el.dataset.id);
      e.quota.reserve = Number(el.value) / 100;
      commit();
    } else if (el.dataset.change === "log-line") {
      app.ui.logLine = el.value;
      commit();
    }
  });
  document.addEventListener("input", (ev) => {
    if (ev.target.dataset.change === "log-query") {
      app.ui.logQuery = ev.target.value;
      clearTimeout(bindEvents.t);
      bindEvents.t = setTimeout(() => { renderView(); const q = document.querySelector('[data-change="log-query"]'); if (q) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); } }, 250);
    }
  });
}

function userIsTyping() {
  const a = document.activeElement;
  return a && a.closest("#view") && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName);
}

async function tick() {
  if (!app.state.user.signedIn) return;
  if (isRemote()) {
    // The server autopilot advances lines; the console polls its snapshot.
    if (++tickCount % 3) return;
    try {
      await sync();
    } catch (err) {
      if (err.status === 401) { leaveRemote(); render(); }
      return;
    }
    if (LIVE_TABS.has(app.ui.tab) && !userIsTyping()) renderView();
    else renderNav();
    return;
  }
  app.ctx = makeCtx();
  if (app.state.settings.autopilot) tickFactory(app.state, app.ctx);
  save();
  if (LIVE_TABS.has(app.ui.tab) && !userIsTyping()) renderView();
  else renderNav();
}

async function restoreBackendSession() {
  if (app.state.user.mode === "backend") app.state.user = { signedIn: false, mode: null, email: null, name: null };
  if (api.configured()) {
    try {
      await enterRemote(await api.me());
    } catch {
      /* not signed in to the backend: stay in preview */
    }
  }
  if (/[?&]login=/.test(location.search)) history.replaceState(null, "", location.pathname);
}

async function boot() {
  const [providers, studio] = await Promise.all([
    fetch("./catalog/providers.json").then((r) => r.json()),
    fetch("./catalog/studio.json").then((r) => r.json()),
    loadGameTemplates(),
  ]);
  catalog = { providers: providers.providers, updated: providers.catalog_updated, studio };
  app.ctx = makeCtx();
  for (const key of OBSOLETE_KEYS) {
    try { localStorage.removeItem(key); } catch { /* storage blocked */ }
  }
  const saved = readJson(STATE_KEY);
  app.state = saved && saved.version === STATE_VERSION ? saved : createState(app.ctx);
  if (!app.state.settings.backendUrl && location.pathname.startsWith("/console")) app.state.settings.backendUrl = location.origin;
  app.ui = Object.assign({ tab: "dashboard", lineId: null, marketFilter: "recommended" }, readJson(UI_KEY) || {});
  await restoreBackendSession();
  bindEvents();
  render();
  setInterval(tick, TICK_MS);
}

boot().catch((err) => {
  document.getElementById("app").innerHTML = '<div class="loginShell"><div class="loginCard"><h1>로드 실패</h1><p>' + esc(err.message) + "</p><p>catalog/*.json을 불러오려면 http(s)로 열어야 합니다.</p></div></div>";
});
