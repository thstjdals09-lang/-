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

export function realCount(state) {
  return state.employees.filter((e) => e.connectionMode !== "simulated").length;
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
      (e.connectionMode === "simulated" ? '<span class="pill bad fake">가짜 · 시뮬레이션</span>' : pill(s, s === "failed" ? "쿼터 소진" : undefined)) + "</div>" +
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
      (e.synthetic
        ? '<p class="muted small">연결된 AI가 없어 서버의 시뮬레이션 워커가 공장을 유지하고 있습니다. AI 마켓에서 실제 AI를 연결하세요.</p><div>'
        : e.connectionMode === "backend"
          ? (e.lastError ? '<p class="muted small">마지막 오류: ' + esc(e.lastError) + "</p>" : "") +
            '<div class="actions wrap"><button class="btn small" data-action="emp-reauth" data-id="' + esc(e.id) + '">재검증 · quota_probe</button>' +
            '<button class="btn small danger" data-action="emp-remove" data-id="' + esc(e.id) + '">연결 삭제</button>'
          : '<label class="reserve">예약선 <input type="range" min="0" max="50" step="5" value="' + Math.round(e.quota.reserve * 100) + '" data-change="reserve" data-id="' + esc(e.id) + '" ' + (unlimited ? "disabled" : "") + "></label>" +
            '<div class="actions wrap">' +
            (e.status === "paused"
              ? '<button class="btn small" data-action="emp-resume" data-id="' + esc(e.id) + '">배정 재개</button>'
              : '<button class="btn small" data-action="emp-pause" data-id="' + esc(e.id) + '">배정 중지</button>') +
            (e.status === "auth_required" ? '<button class="btn small primary" data-action="emp-reauth" data-id="' + esc(e.id) + '">재인증</button>' : "") +
            (!unlimited ? '<button class="btn small" data-action="emp-drain" data-id="' + esc(e.id) + '" title="예약선까지 사용량을 채워 failover를 시험">쿼터 소진 테스트</button><button class="btn small" data-action="emp-reset" data-id="' + esc(e.id) + '">사용량 리셋</button>' : "") +
            (e.authType === "local" && localCount <= 1 ? "" : '<button class="btn small danger" data-action="emp-remove" data-id="' + esc(e.id) + '">해고</button>')) +
      "</div></article>"
    );
  });
  return (
    (realCount(state) === 0
      ? '<p class="notice">실제로 연결된 AI가 없습니다. 아래 사원은 모두 가짜(시뮬레이션)이며 AI를 호출하지 않습니다. ' +
        (state.user.mode === "backend" ? "AI 마켓에서 로그인·키 연결을 하면 실제 AI가 작업합니다." : "실제 AI 연결은 백엔드 모드(start-backend.cmd 실행 → http://127.0.0.1:8000/console/)에서 할 수 있습니다.") + "</p>"
      : "") +
    '<section class="panel"><div class="panelHead"><div><div class="eyebrow">AI EMPLOYEES</div><h2>실제 연결 AI ' + realCount(state) + "명 · 전체 " + state.employees.length + "명</h2>" +
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
  const result = app.ui.connectResult && app.ui.connectResult.providerId === p.id ? app.ui.connectResult : null;
  const step = (n, text, state) => '<li class="' + state + '"><span>' + n + "</span>" + text + "</li>";
  const stepState = (n) => (result ? (result.ok || n < 3 ? "on" : n === 3 ? "bad" : "") : n <= 2 ? "on" : "");
  const guide = (p.key_steps || []).map((t, i) => "<li>" + esc(t) + "</li>").join("");
  const keyLink = p.key_url ? '<a class="btn" href="' + esc(p.key_url) + '" target="_blank" rel="noopener">① ' + esc(p.vendor) + (auth === "local" ? " 설치 안내" : " 로그인 · 키 발급 페이지 열기") + " ↗</a>" : "";

  let body = "";
  if (result) {
    body = result.ok
      ? '<div class="deploy live"><span class="pill good">연결 완료 · 실제 AI</span><strong>' + esc(p.name) + "</strong>" +
        '<p class="muted small">서버가 키를 암호화 Vault에 저장하고 실제로 호출해 확인했습니다.</p>' +
        '<dl class="facts compact"><div><dt>사용 가능 모델</dt><dd>' + (result.models || []).length + "개</dd></div>" +
        "<div><dt>쿼터</dt><dd>" + (result.quotaLimit ? fmtNum(result.quotaLimit - (result.quotaUsed || 0)) + " / " + fmtNum(result.quotaLimit) + " " + esc(result.quotaUnit || "") : "확인 불가") + "</dd></div>" +
        "<div><dt>Vault 참조</dt><dd>" + esc(result.credentialRef || "-") + "</dd></div>" +
        "<div><dt>키 지문</dt><dd>" + esc(result.fingerprint || "-") + "</dd></div></dl></div>"
      : '<div class="deploy"><span class="pill bad">연결 실패</span><p class="muted small">' + esc(result.message) + "</p></div>";
  } else if (auth === "oauth") {
    body = backend
      ? '<p class="muted small">' + esc(p.vendor) + " 로그인 화면으로 이동합니다. 승인하면 API 키가 자동으로 발급되어 서버 Vault에 저장되고, 이 화면으로 돌아옵니다. 키를 복사할 필요가 없습니다.</p>"
      : '<p class="notice">로그인 연결은 백엔드 모드에서만 됩니다. 프리뷰에서는 가짜(시뮬레이션) 사원만 추가할 수 있습니다.</p>';
  } else if (auth === "local") {
    body = '<ol class="guide">' + guide + "</ol>" + keyLink +
      '<label>로컬 엔드포인트<input name="endpoint" value="' + esc(p.base_url || "") + '" placeholder="http://127.0.0.1:8080/v1"></label>';
  } else {
    const needsAccount = p.id === "cloudflare";
    body = '<ol class="guide">' + guide + "</ol>" + '<div class="actions wrap">' + keyLink + "</div>" +
      (auth === "custom_endpoint" || needsAccount
        ? "<label>" + (needsAccount ? "② Account ID" : "Base URL") + '<input name="endpoint" placeholder="' + (needsAccount ? "Cloudflare account id" : "https://my-gateway.example.com/v1") + '"></label>'
        : "") +
      "<label>② 발급받은 API Key 붙여넣기" + '<input name="api_key" type="password" autocomplete="off" data-prefix="' + esc(p.key_prefix || "") + '" ' +
      (backend ? 'placeholder="' + esc(p.key_prefix ? p.key_prefix + "… 로 시작" : "API key") + '"' : 'disabled placeholder="프리뷰 모드에서는 키를 받지 않습니다"') + "></label>" +
      '<p class="muted small" data-key-hint></p>' +
      (backend
        ? '<p class="muted small">③ 연결을 누르면 키가 HTTPS로 서버에 한 번 전송되어 암호화 Vault에 저장되고, 서버가 실제로 모델 목록·쿼터를 조회해 검증합니다. 브라우저에는 참조값만 남습니다.</p>'
        : '<p class="notice">프리뷰 사이트는 키를 받지 않습니다. 이 PC에서 <strong>start-backend.cmd</strong>를 실행해 http://127.0.0.1:8000/console/ 에서 연결하세요.</p>');
  }

  const submitLabel = result
    ? ""
    : backend
      ? (auth === "oauth" ? esc(p.vendor) + "로 로그인해서 자동 연결" : auth === "local" ? "헬스체크 후 연결" : "③ 연결하고 검증")
      : "가짜(시뮬레이션)로 추가";
  return (
    '<div class="modal" role="dialog" aria-modal="true" aria-label="' + esc(p.name) + ' 연결"><form class="sheet" data-form="connect" data-id="' + esc(p.id) + '">' +
    '<div class="panelHead"><div><div class="eyebrow">+ AI 추가 · ' + esc(p.adapter) + " adapter</div><h2>" + esc(p.name) + "</h2></div>" +
    '<button type="button" class="btn small" data-action="close-modal">닫기</button></div>' +
    '<ol class="steps">' + step(1, auth === "oauth" ? "로그인" : "로그인·키 발급", stepState(1)) + step(2, auth === "oauth" ? "승인" : "키 입력", stepState(2)) +
    step(3, "서버 검증", stepState(3)) + step(4, "완료", result && result.ok ? "on" : "") + "</ol>" +
    (p.auth_types.length > 1 && !result
      ? '<div class="segmented">' + p.auth_types.map((a) => '<button type="button" class="' + (a === auth ? "on" : "") + '" data-action="connect-auth" data-id="' + esc(a) + '">' +
          esc({ oauth: "로그인으로 연결", api_key: "API 키 붙여넣기", local: "로컬", custom_endpoint: "직접 지정" }[a] || a) + "</button>").join("") + "</div>"
      : "") +
    '<input type="hidden" name="auth" value="' + esc(auth) + '">' + body +
    '<div class="actions">' + (submitLabel ? '<button class="btn primary" type="submit">' + submitLabel + "</button>" : '<button class="btn primary" type="button" data-action="connect-done">' + (result && result.ok ? "AI 사원 보기" : "닫기") + "</button>") + "</div>" +
    '<p class="status" data-connect-status></p>' +
    "</form></div>"
  );
}
