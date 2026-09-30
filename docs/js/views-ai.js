// AI Employees (installed workers, quota, usage) and AI Marketplace views.

import { esc, fmtNum, fmtTime, until, pill, meter, empty, LABEL } from "./ui.js";
import { remainingRatio, atReserve, exhausted } from "./router.js";

const SKILLS = [["coding", "코딩"], ["planning", "기획"], ["debugging", "디버깅"], ["design", "디자인"], ["vision", "비전"], ["qa", "QA"]];

function employeeState(e, now) {
  if (e.status !== "online") return e.status;
  if (e.cooldownUntil > now) return "cooldown";
  if (exhausted(e)) return "failed";
  if (atReserve(e)) return "reserve";
  return "online";
}

export function team(app) {
  const { state, ctx } = app;
  const now = ctx.now;
  const cards = state.employees.map((e) => {
    const s = employeeState(e, now);
    const unlimited = !e.quota.limit;
    const avgLatency = e.stats.requests ? Math.round(e.stats.latencyTotal / e.stats.requests) : 0;
    const errRate = e.stats.requests ? Math.round((e.stats.errors / e.stats.requests) * 100) : 0;
    const localCount = state.employees.filter((x) => x.authType === "local").length;
    return (
      '<article class="employee">' +
      '<div class="empHead"><div><strong>' + esc(e.name) + "</strong><small>" + esc(e.vendor) + " · " + esc(e.model) + "</small></div>" +
      pill(s, s === "failed" ? "쿼터 소진" : undefined) + "</div>" +
      '<div class="chips">' + '<span class="chip">' + esc(e.authType) + "</span>" + pill(e.connectionMode === "backend" ? "online" : e.connectionMode === "verified" ? "online" : "neutral", LABEL[e.connectionMode]) +
      '<span class="chip">' + (e.costTier === 0 ? "로컬 무료" : e.free ? "무료 티어" : "유료") + '</span><span class="chip">ctx ' + fmtNum(e.contextLength) + "</span></div>" +
      '<div class="quotaBlock"><div class="split"><span>쿼터 ' + esc(e.quota.unit) + (e.quota.window ? " / " + esc(e.quota.window) : "") + "</span><strong>" +
      (unlimited ? "∞" : fmtNum(e.quota.limit - e.quota.used) + " / " + fmtNum(e.quota.limit)) + "</strong></div>" +
      meter(unlimited ? 100 : remainingRatio(e) * 100, { reserve: unlimited ? null : e.quota.reserve, label: e.name + " 남은 쿼터" }) +
      '<div class="split muted"><span>예약선 ' + Math.round(e.quota.reserve * 100) + "%</span><span>다음 리셋 " + esc(until(e.quota.resetAt, now)) + "</span></div></div>" +
      '<div class="skills">' + SKILLS.map(([k, label]) => "<div><small>" + label + "</small>" + meter(e.skills[k] || 0, { tone: "info" }) + "<b>" + (e.skills[k] || 0) + "</b></div>").join("") + "</div>" +
      '<dl class="facts"><div><dt>요청</dt><dd>' + fmtNum(e.stats.requests) + "</dd></div><div><dt>토큰</dt><dd>" + fmtNum(e.stats.tokens) + "</dd></div>" +
      "<div><dt>완료 작업</dt><dd>" + e.stats.tasksDone + "</dd></div><div><dt>오류율</dt><dd>" + errRate + "%</dd></div>" +
      "<div><dt>지연</dt><dd>" + (avgLatency ? avgLatency + "ms" : "-") + "</dd></div><div><dt>Failover</dt><dd>" + e.stats.failovers + "</dd></div>" +
      "<div><dt>속도</dt><dd>" + e.speed + "</dd></div><div><dt>신뢰도</dt><dd>" + e.reliability + "</dd></div>" +
      "<div><dt>검증</dt><dd>" + (e.lastVerified ? esc(fmtTime(e.lastVerified)) : "미검증") + "</dd></div></dl>" +
      '<label class="reserve">예약선 <input type="range" min="0" max="50" step="5" value="' + Math.round(e.quota.reserve * 100) + '" data-change="reserve" data-id="' + esc(e.id) + '" ' + (unlimited ? "disabled" : "") + "></label>" +
      '<div class="actions wrap">' +
      (e.status === "paused"
        ? '<button class="btn small" data-action="emp-resume" data-id="' + esc(e.id) + '">배정 재개</button>'
        : '<button class="btn small" data-action="emp-pause" data-id="' + esc(e.id) + '">배정 중지</button>') +
      (e.status === "auth_required" ? '<button class="btn small primary" data-action="emp-reauth" data-id="' + esc(e.id) + '">재인증</button>' : "") +
      (!unlimited ? '<button class="btn small" data-action="emp-drain" data-id="' + esc(e.id) + '" title="예약선까지 사용량을 채워 failover를 시험">쿼터 소진 테스트</button><button class="btn small" data-action="emp-reset" data-id="' + esc(e.id) + '">사용량 리셋</button>' : "") +
      (e.authType === "local" && localCount <= 1 ? "" : '<button class="btn small danger" data-action="emp-remove" data-id="' + esc(e.id) + '">해고</button>') +
      "</div></article>"
    );
  });
  return (
    '<section class="panel"><div class="panelHead"><div><div class="eyebrow">AI EMPLOYEES</div><h2>설치된 AI 사원 ' + state.employees.length + "명</h2>" +
    '<p class="muted">라우팅 정책: <strong>' + esc(state.settings.policy) + "</strong> · 예약선 이하 AI는 critical 작업에만 배정 · 모든 외부 AI가 막히면 Local Worker가 공장을 유지합니다.</p></div>" +
    '<button class="btn primary" data-action="tab" data-id="market">+ AI 추가</button></div>' +
    '<div class="employeeGrid">' + cards.join("") + "</div></section>"
  );
}

// ---------- marketplace ----------

const FILTERS = [
  ["recommended", "추천"], ["installed", "설치됨"], ["free", "무료"], ["coding", "코딩"], ["planning", "기획"],
  ["vision", "비전"], ["image", "이미지"], ["audio", "오디오"], ["local", "로컬"], ["login", "로그인 필요"], ["all", "전체"],
];

function matches(p, filter, installed) {
  switch (filter) {
    case "all": return true;
    case "recommended": return p.recommended;
    case "installed": return installed;
    case "free": return p.free;
    case "login": return p.requires_login;
    default: return p.categories.includes(filter);
  }
}

export function market(app) {
  const { state, ctx } = app;
  const filter = app.ui.marketFilter || "recommended";
  const installedIds = new Set(state.employees.map((e) => e.catalogId));
  const list = ctx.providers.filter((p) => matches(p, filter, installedIds.has(p.id)));
  const backend = state.user.mode === "backend";
  return (
    '<section class="panel"><div class="panelHead"><div><div class="eyebrow">AI MARKETPLACE · catalog ' + esc(ctx.catalogUpdated) + "</div><h2>AI 플러그인 마켓</h2>" +
    '<p class="muted">+ AI 추가 → Provider Adapter 설치 → 인증(OAuth · API key · Local · Custom endpoint). ' +
    (backend ? "자격증명은 백엔드 암호화 Vault에만 저장되고 브라우저에는 참조값만 남습니다." : "현재 프리뷰 모드: 실제 자격증명은 받지 않으며 시뮬레이션 사원으로 설치됩니다.") + "</p></div></div>" +
    '<div class="filters" role="tablist">' + FILTERS.map(([id, label]) => {
      const count = ctx.providers.filter((p) => matches(p, id, installedIds.has(p.id))).length;
      return '<button role="tab" aria-selected="' + (id === filter) + '" class="' + (id === filter ? "on" : "") + '" data-action="market-filter" data-id="' + id + '">' + label + " <small>" + count + "</small></button>";
    }).join("") + "</div>" +
    (list.length ? '<div class="marketGrid">' + list.map((p) => {
      const installed = installedIds.has(p.id);
      return (
        '<article class="provider">' +
        '<div class="empHead"><div><strong>' + esc(p.name) + "</strong><small>" + esc(p.vendor) + " · " + esc(p.default_model || "") + "</small></div>" +
        (p.free ? '<span class="pill good">' + (p.cost_tier === 0 ? "LOCAL" : "FREE") + "</span>" : '<span class="pill warn">PAID</span>') + "</div>" +
        "<p>" + esc(p.summary) + "</p>" +
        '<div class="chips">' + p.categories.map((c) => '<span class="chip">' + esc(c) + "</span>").join("") + p.auth_types.map((a) => '<span class="chip outline">' + esc(a) + "</span>").join("") + "</div>" +
        '<dl class="facts compact"><div><dt>무료량</dt><dd>' + (p.quota.limit ? fmtNum(p.quota.limit) + " " + esc(p.quota.unit) + "/" + esc(p.quota.window) : esc(p.quota.unit)) + "</dd></div>" +
        "<div><dt>출처</dt><dd>" + esc(p.quota_source) + "</dd></div><div><dt>검증</dt><dd>" + (p.last_verified ? esc(p.last_verified) : "미검증") + "</dd></div>" +
        "<div><dt>어댑터</dt><dd>" + esc(p.adapter) + (p.adapter_status === "planned" ? " (예정)" : "") + "</dd></div></dl>" +
        '<div class="actions">' +
        (installed ? '<button class="btn" disabled>설치됨</button>' : '<button class="btn primary" data-action="connect" data-id="' + esc(p.id) + '">+ AI 추가</button>') +
        (p.docs_url ? '<a class="btn ghost" href="' + esc(p.docs_url) + '" target="_blank" rel="noopener">문서 ↗</a>' : "") +
        "</div></article>"
      );
    }).join("") + "</div>" : empty("이 필터에 해당하는 AI가 없습니다.")) +
    "</section>"
  );
}

export function connectModal(app, providerId) {
  const p = app.ctx.providers.find((x) => x.id === providerId);
  if (!p) return "";
  const backend = app.state.user.mode === "backend";
  const auth = app.ui.connectAuth && p.auth_types.includes(app.ui.connectAuth) ? app.ui.connectAuth : p.auth_types[0];
  const step = (n, text, on) => '<li class="' + (on ? "on" : "") + '"><span>' + n + "</span>" + text + "</li>";
  let body = "";
  if (auth === "local") {
    body =
      '<label>로컬 엔드포인트<input name="endpoint" value="' + esc(p.base_url || "") + '" placeholder="http://127.0.0.1:8080/v1"></label>' +
      '<p class="muted small">이 PC에서 실행 중인 서버에 브라우저가 직접 /models 헬스체크를 시도합니다. 응답이 없으면 시뮬레이션 사원으로 설치됩니다.</p>';
  } else if (auth === "api_key" || auth === "custom_endpoint") {
    body =
      (auth === "custom_endpoint" || p.id === "cloudflare"
        ? '<label>' + (p.id === "cloudflare" ? "Account ID" : "Base URL") + '<input name="endpoint" value="' + esc(p.id === "cloudflare" ? "" : p.base_url || "") + '" placeholder="' + (p.id === "cloudflare" ? "Cloudflare account id" : "https://my-gateway.example.com/v1") + '"></label>'
        : "") +
      '<label>API Key<input name="api_key" type="password" autocomplete="off" ' + (backend ? 'placeholder="백엔드 Vault로 즉시 전송, 브라우저에 저장 안 함"' : 'disabled placeholder="프리뷰 모드에서는 입력 불가"') + "></label>" +
      (backend
        ? '<p class="muted small">키는 HTTPS로 AI Factory 백엔드에 한 번 전송되어 암호화 Vault에 저장됩니다. 화면·localStorage·로그에는 credential reference만 남습니다.</p>'
        : '<p class="notice">GitHub Pages 프리뷰는 API Key를 받지 않습니다. 설정에서 백엔드 주소를 연결하고 Google 로그인하면 실제 키 등록이 활성화됩니다.</p>');
  } else if (auth === "oauth") {
    body = backend
      ? '<p class="muted small">' + esc(p.vendor) + " 로그인 화면으로 이동해 권한을 승인합니다. 발급된 토큰은 백엔드 Vault에만 저장됩니다.</p>"
      : '<p class="notice">프리뷰 모드에서는 실제 OAuth 대신 시뮬레이션으로 설치됩니다.</p>';
  }
  return (
    '<div class="modal" role="dialog" aria-modal="true" aria-label="' + esc(p.name) + ' 연결"><form class="sheet" data-form="connect" data-id="' + esc(p.id) + '">' +
    '<div class="panelHead"><div><div class="eyebrow">+ AI 추가 · ' + esc(p.adapter) + " adapter</div><h2>" + esc(p.name) + "</h2></div>" +
    '<button type="button" class="btn small" data-action="close-modal">닫기</button></div>' +
    '<ol class="steps">' + step(1, "Adapter 설치", true) + step(2, "인증", true) + step(3, "health_check · list_models", false) + step(4, "quota_probe", false) + "</ol>" +
    '<div class="segmented">' + p.auth_types.map((a) => '<button type="button" class="' + (a === auth ? "on" : "") + '" data-action="connect-auth" data-id="' + esc(a) + '">' + esc(a) + "</button>").join("") + "</div>" +
    '<input type="hidden" name="auth" value="' + esc(auth) + '">' + body +
    '<div class="actions"><button class="btn primary" type="submit">' + (backend && auth !== "local" ? "연결" : auth === "local" ? "헬스체크 후 설치" : "시뮬레이션으로 설치") + "</button></div>" +
    '<p class="status" data-connect-status></p>' +
    "</form></div>"
  );
}
