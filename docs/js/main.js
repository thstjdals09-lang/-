// AI Factory web console bootstrap: state, render loop, and event delegation.

import {
  STATE_VERSION, createState, createProject, tickFactory, tickLine, fastForward, startBacklogIdea, addFeedback,
  approveReview, requestRevision, setLineStatus, employeeFromCatalog, addLog, slugify,
  deleteLine, deleteProject, deleteIdea, clearLogs,
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
  ["account", "내 계정", "내 계정"],
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
    const account = app.state.account;
    app.state = fromSnapshot(await api.state(), app.state, makeCtx());
    app.state.account = account;
  } finally {
    syncing = false;
  }
}

async function enterRemote(me) {
  if (!previewState) previewState = app.state;
  const base = createState(makeCtx());
  app.state = { ...base, user: { signedIn: true, mode: "backend", email: me.email, name: me.name }, settings: { ...base.settings, ...previewState.settings } };
  await sync();
  await refreshAccount();
}

async function refreshAccount() {
  try { app.state.account = await api.account(); } catch { /* shown as loading */ }
}

function leaveRemote() {
  app.ui.authMode = "login";
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
    review: ops.review, results: ops.results, logs: ops.logs, settings: ops.settings, account: ops.account,
  }[tab[0]];
  view.innerHTML = (app.ui.flash ? '<p class="notice flash">' + esc(app.ui.flash) + "</p>" : "") + fn(app);
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
    '<div class="actions"><span class="chip">' + esc(app.state.settings.policy.toUpperCase()) + "</span>" +
    '<button class="accountChip" data-action="tab" data-id="account" title="내 계정"><span class="avatar">' + esc((u.name || u.email || "?").slice(0, 1).toUpperCase()) + "</span>" +
    (u.mode === "backend" ? esc(u.email || "") : "게스트 · 계정 없음") + "</button></div></header>" +
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

function confirmLineDelete(id) {
  const l = lineById(id);
  return !!l && confirm("'" + l.title + "' 생산라인을 삭제할까요?\n작업·빌드·기록이 지워지고, 아이디어는 Backlog로 돌아갑니다.\n(이미 GitHub에 올라간 저장소는 그대로 남습니다.)");
}
function confirmProjectDelete(id) {
  const p = app.state.projects.find((x) => x.id === id);
  const n = app.state.lines.filter((l) => l.projectId === id).length;
  return !!p && confirm("주제 '" + p.topic + "'를 삭제할까요?\n아이디어 전부와 생산라인 " + n + "개가 함께 삭제됩니다.");
}
function afterProjectDelete(id) {
  if (app.ui.projectId === id) app.ui.projectId = null;
}

const actions = {
  "line-delete"(id) {
    if (!confirmLineDelete(id)) return;
    deleteLine(app.state, id, app.ctx);
    app.ui.lineId = null;
    commit();
  },
  "project-delete"(id) {
    if (!confirmProjectDelete(id)) return;
    deleteProject(app.state, id, app.ctx);
    afterProjectDelete(id);
    commit();
  },
  "idea-delete"(id) {
    const res = deleteIdea(app.state, id, app.ctx);
    if (!res.ok && res.reason === "in_production") alert("생산 중인 아이디어입니다. 생산라인을 먼저 삭제하세요.");
    commit();
  },
  "logs-clear"() {
    if (!confirm("생산 로그를 모두 비울까요?")) return;
    clearLogs(app.state);
    commit();
  },
  tab(id) {
    app.ui.tab = id; app.ui.editingTopic = false; app.ui.flash = null; commit(); window.scrollTo(0, 0);
    if (id === "account" && isRemote()) refreshAccount().then(() => renderView());
  },
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
  connect(id) { app.ui.connectId = id; app.ui.connectAuth = null; app.ui.connectResult = null; openModal(ai.connectModal(app, id)); },
  "connect-done"() {
    const ok = app.ui.connectResult && app.ui.connectResult.ok;
    closeModal();
    app.ui.connectResult = null;
    if (ok) app.ui.tab = "team";
    commit();
  },
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
  "auth-mode"(mode) { app.ui.authMode = mode; render(); },
  "preview-login"() {
    app.state.user = { signedIn: true, mode: "preview", email: "preview@local", name: "CEO (Preview)" };
    addLog(app.state, app.ctx, "AUTH", "프리뷰 세션 시작 · 서버·자격증명 없이 브라우저 시뮬레이션");
    commit({ full: true });
  },
  async "google-login"() {
    const status = document.querySelector("[data-login-status]");
    if (!api.configured()) {
      status.textContent = "계정 로그인에는 AI Factory 서버가 필요합니다. 서버 주소를 입력하거나 게스트로 둘러보세요.";
      const details = document.querySelector(".loginCard details");
      if (details) details.open = true;
      return;
    }
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
  "line-delete"(id) {
    if (!confirmLineDelete(id)) return;
    app.ui.lineId = null;
    remote(() => api.deleteLine(id).catch((err) => { if (err.status === 409) alert("AI가 이 라인을 작업 중입니다. 잠시 후 다시 시도하세요."); else throw err; }));
  },
  "project-delete"(id) {
    if (!confirmProjectDelete(id)) return;
    afterProjectDelete(id);
    remote(() => api.deleteProject(id));
  },
  "idea-delete"(id) {
    remote(() => api.deleteIdea(id).catch((err) => { if (err.status === 409) alert("생산 중인 아이디어입니다. 생산라인을 먼저 삭제하세요."); else throw err; }));
  },
  "logs-clear"() {
    if (!confirm("생산 로그를 모두 비울까요?")) return;
    remote(() => api.clearLogs());
  },
  publish(id) {
    remote(() => api.publish(id));
  },
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
  "line-resume"(id) {
    const l = lineById(id);
    remote(() => (l && l.status === "paused" ? api.resumeLine(id) : api.setAutopilot(id, true)));
  },
  "tool-remove"(id) {
    const t = (app.state.searchTools || []).find((x) => x.id === id);
    if (!t || !confirm(t.name + " 연결과 Vault 키를 삭제할까요? 이후 아이디어 회의는 웹 조사 없이 진행됩니다.")) return;
    remote(() => api.deleteConnection(id));
  },
  "tool-verify"(id) { remote(() => api.verifyConnection(id)); },
  "market-search"() { app.ui.tab = "market"; app.ui.marketFilter = "search"; render(); },
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
  async "logout-all"() {
    if (!confirm("이 계정으로 로그인된 모든 기기에서 로그아웃할까요?")) return;
    try { await api.logoutAll(); } catch { /* session already gone */ }
    leaveRemote();
    commit({ full: true });
  },
  "export-account"() { window.open(api.exportUrl(), "_blank", "noopener"); },
  "github-disconnect"() {
    if (!confirm("GitHub 연결을 해제할까요? 이후 게임은 배포되지 않습니다.")) return;
    remote(async () => { app.state.account = await api.disconnectGithub(); });
  },
};

async function signedIn(user) {
  app.ui.loginFlash = null;
  await enterRemote(user);
  commit({ full: true });
}

const authErrors = {
  invalid_credentials: "이메일 또는 비밀번호가 올바르지 않습니다.",
  too_many_attempts: "로그인 시도가 너무 많습니다. 15분 뒤에 다시 시도하세요.",
  email_taken: "이미 가입된 이메일입니다. 로그인하세요.",
  invalid_email: "이메일 형식이 올바르지 않습니다.",
  signup_not_allowed: "이 서버는 초대된 이메일만 가입할 수 있습니다.",
};

const remoteForms = {
  async "github-connect"(form) {
    const input = form.querySelector('input[name="token"]');
    const token = input.value.trim();
    input.value = ""; // the token only lives in this request
    const status = form.parentElement.querySelector("[data-github-status]");
    if (!token) return;
    status.textContent = "GitHub에 토큰 확인 중…";
    try {
      app.state.account = await api.connectGithub(token);
      commit();
    } catch (err) {
      const reasons = { github_token_rejected: "GitHub가 토큰을 거부했습니다.", github_token_needs_repo_scope: "토큰에 repo 권한이 없습니다. 발급 페이지에서 repo를 체크하세요." };
      status.textContent = reasons[err.detail] || "연결 실패: " + (err.detail || err.message);
    }
  },
  async "delete-account"(form) {
    const email = String(new FormData(form).get("email") || "").trim();
    if (!email || !confirm("정말 계정과 모든 데이터를 삭제할까요? 되돌릴 수 없습니다.")) return;
    try {
      await api.deleteAccount(email);
      leaveRemote();
      app.ui.loginFlash = "계정이 삭제되었습니다.";
      commit({ full: true });
    } catch (err) {
      alert(err.detail === "confirmation_mismatch" ? "이메일이 일치하지 않습니다." : "삭제 실패: " + (err.detail || err.message));
    }
  },
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
  async "password-login"(form) {
    const fd = new FormData(form);
    const status = form.querySelector("[data-auth-status]");
    status.textContent = "로그인 중…";
    try {
      await signedIn(await api.passwordLogin(String(fd.get("email")).trim(), String(fd.get("password"))));
    } catch (err) {
      status.textContent = authErrors[err.detail] || "로그인 실패: " + (err.detail || err.message);
    }
  },
  async register(form) {
    const fd = new FormData(form);
    const status = form.querySelector("[data-auth-status]");
    status.textContent = "계정 만드는 중…";
    try {
      await signedIn(await api.register(String(fd.get("email")).trim(), String(fd.get("password")), String(fd.get("name") || "").trim()));
    } catch (err) {
      status.textContent = authErrors[err.detail] || (err.status === 422 ? "비밀번호는 8자 이상이어야 합니다." : "가입 실패: " + (err.detail || err.message));
    }
  },
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
  async "login-backend"(form) {
    app.state.settings.backendUrl = String(new FormData(form).get("backendUrl") || "").trim();
    save();
    await probeServer();
    render();
  },
  async connect(form) {
    const p = app.ctx.providers.find((x) => x.id === form.dataset.id);
    const fd = new FormData(form);
    const auth = fd.get("auth");
    const endpoint = String(fd.get("endpoint") || "").trim();
    const model = String(fd.get("model") || "").trim();
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

    if (p.kind === "search" && app.state.user.mode !== "backend") {
      status.textContent = "검색 API는 로그인한 서버(백엔드)에서만 연결됩니다. 프리뷰에는 키를 저장하지 않습니다.";
      return;
    }
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
        location.href = res.authorize_url; // provider login → key issued → server vault → back here
        return;
      }
      if (!apiKey && auth === "api_key") { status.textContent = "API Key를 입력하세요."; return; }
      status.textContent = "Vault 저장 · health_check · quota_probe 중…";
      const res = await api.connectProvider({ catalog_id: p.id, auth_type: auth, api_key: apiKey || null, endpoint: endpoint || null, model: model || null });
      await sync();
      app.ui.connectResult = res.status === "online"
        ? { providerId: p.id, ok: true, models: res.models, model: res.model, quotaLimit: res.quota_limit, quotaUsed: res.quota_used, quotaUnit: res.quota_unit,
            credentialRef: res.credential_ref, fingerprint: res.credential_fingerprint }
        : { providerId: p.id, ok: false, message: (res.status === "auth_required" ? "키가 거부되었습니다. 키를 다시 확인하세요. " : "서버가 AI에 접속하지 못했습니다. ") + (res.last_error || "") };
      if (res.status !== "online") await api.deleteConnection(res.id).catch(() => {});
      openModal(ai.connectModal(app, p.id));
      commit();
    } catch (err) {
      const reasons = { 409: "이미 연결된 AI입니다.", 501: "이 AI의 로그인 연결은 준비 중입니다. API 키 방식을 사용하세요.", 503: "서버 Vault가 설정되지 않았습니다 (AI_FACTORY_VAULT_KEY)." };
      const details = { local_endpoints_admin_only: "로컬 AI(Ollama 등)와 직접 지정 주소는 서버 소유자 계정만 연결할 수 있습니다. Gemini·Groq 같은 클라우드 AI를 키로 연결하세요." };
      status.textContent = details[err.detail] || reasons[err.status] || "연결 실패: " + (err.detail || err.message);
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
    if (ev.target.name === "api_key" && ev.target.dataset.prefix) {
      const hint = document.querySelector("[data-key-hint]");
      const v = ev.target.value.trim();
      if (hint) hint.textContent = v && !v.startsWith(ev.target.dataset.prefix) ? "보통 " + ev.target.dataset.prefix + "… 로 시작합니다. 다른 키를 붙여넣지 않았는지 확인하세요." : "";
    }
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

// The Pages link forwards to the live server announced in backend.json (written by start-public.cmd).
async function discoverServer() {
  if (location.pathname.startsWith("/console") || /[?&]preview=1/.test(location.search)) return false;
  try {
    const info = await fetch("./backend.json?t=" + Date.now(), { cache: "no-store" }).then((r) => (r.ok ? r.json() : null));
    if (!info || !info.url) return false;
    const res = await fetch(info.url.replace(/\/+$/, "") + "/health", { cache: "no-store" });
    if (!res.ok) return false;
    location.replace(info.url.replace(/\/+$/, "") + "/console/");
    return true;
  } catch {
    return false;
  }
}

async function probeServer() {
  app.ui.serverInfo = { online: false };
  if (!api.configured()) return;
  try {
    const health = await api.health();
    app.ui.serverInfo = { online: true, google: !!health.google_oauth, dev_login: !!health.dev_login };
  } catch { /* offline: the login screen says so */ }
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
  const params = new URLSearchParams(location.search);
  if (params.get("login") === "not_allowed") app.ui.loginFlash = "이 서버는 초대된 계정만 가입할 수 있습니다.";
  if (params.get("connected")) {
    app.ui.tab = "team";
    app.ui.flash = params.get("connected") + " 로그인 연결 완료 · 상태 " + (params.get("status") || "?");
  } else if (params.get("connect_error")) {
    app.ui.tab = "market";
    app.ui.flash = "AI 로그인 연결 실패: " + params.get("connect_error");
  }
  if (/[?&](login|connected|connect_error)=/.test(location.search)) history.replaceState(null, "", location.pathname);
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
  if (await discoverServer()) return; // navigating to the live server
  await probeServer();
  await restoreBackendSession();
  bindEvents();
  render();
  setInterval(tick, TICK_MS);
}

boot().catch((err) => {
  document.getElementById("app").innerHTML = '<div class="loginShell"><div class="loginCard"><h1>로드 실패</h1><p>' + esc(err.message) + "</p><p>catalog/*.json을 불러오려면 http(s)로 열어야 합니다.</p></div></div>";
});
