// Small rendering helpers shared by every view.

export function esc(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[m]);
}

export function fmtTime(ms) {
  if (!ms) return "-";
  const d = new Date(ms);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return sameDay
    ? d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : d.toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function fmtNum(n) {
  if (n === Infinity) return "∞";
  if (n == null || Number.isNaN(n)) return "-";
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "K";
  return String(Math.round(n * 100) / 100);
}

export function until(ms, now) {
  if (!ms) return "리셋 없음";
  const diff = Math.max(0, ms - now);
  const h = Math.floor(diff / 3600000);
  const m = Math.floor((diff % 3600000) / 60000);
  if (h >= 48) return Math.floor(h / 24) + "일 후";
  return h ? h + "시간 " + m + "분 후" : m + "분 후";
}

export const TONE = {
  running: "info", in_progress: "info", review: "violet", dispatching: "info",
  completed: "good", complete: "good", passed: "good", approved: "good", online: "good", playable: "good",
  ready: "neutral", pending: "neutral", planning: "neutral", idle: "neutral", candidate: "neutral", backlog: "neutral",
  awaiting_ceo: "warn", waiting: "warn", gate: "warn", paused: "warn", revision_requested: "warn", shortlisted: "violet", in_production: "info",
  blocked: "bad", failed: "bad", offline: "bad", auth_required: "bad", cooldown: "warn", reserve: "warn",
};

export const LABEL = {
  running: "진행중", paused: "일시정지", awaiting_ceo: "CEO 승인 대기", complete: "완료",
  pending: "대기", ready: "준비", in_progress: "작업중", review: "리뷰", completed: "완료", blocked: "막힘", failed: "실패",
  planning: "계획", dispatching: "배정중", waiting: "대기", gate: "게이트", idle: "유휴",
  approved: "승인", revision_requested: "수정요청",
  online: "온라인", offline: "오프라인", auth_required: "재인증 필요", cooldown: "쿨다운", reserve: "예약보호",
  candidate: "후보", shortlisted: "Shortlist", backlog: "Backlog", in_production: "생산중",
  simulated: "시뮬레이션", backend: "Vault 연결", verified: "검증됨",
  passed: "통과", tests_passed: "테스트 통과",
};

export function pill(status, text) {
  return '<span class="pill ' + (TONE[status] || "neutral") + '">' + esc(text || LABEL[status] || status) + "</span>";
}

export function meter(pct, { reserve = null, tone = null, label = "" } = {}) {
  const p = Math.max(0, Math.min(100, Math.round(pct)));
  const t = tone || (reserve != null && p <= reserve * 100 ? "warn" : p < 10 ? "bad" : "good");
  return (
    '<div class="meter ' + t + '" role="meter" aria-valuenow="' + p + '" aria-valuemin="0" aria-valuemax="100"' + (label ? ' aria-label="' + esc(label) + '"' : "") + ">" +
    '<i style="width:' + p + '%"></i>' +
    (reserve ? '<b style="left:' + Math.round(reserve * 100) + '%" title="예약선"></b>' : "") +
    "</div>"
  );
}

export function empty(text, action = "") {
  return '<div class="empty"><p>' + esc(text) + "</p>" + action + "</div>";
}

export function download(name, body, type = "text/plain;charset=utf-8") {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// Deployment links: real links only once the server verified the Pages URL answers 200.
export function publicationBlock(line, mode) {
  const pub = line.publication;
  if (mode !== "backend") {
    return '<p class="muted small">GitHub 배포는 백엔드 모드에서 동작합니다 (프리뷰는 서버·토큰이 없어 게시하지 않음).</p>';
  }
  if (!pub) return '<p class="muted small">첫 플레이 빌드(Prototype)가 나오면 GitHub 저장소 생성 → 푸시 → Pages 배포가 자동으로 시작됩니다.</p>';
  const repo = pub.repositoryUrl ? '<a class="btn" href="' + esc(pub.repositoryUrl) + '" target="_blank" rel="noopener">GitHub 저장소 ↗</a>' : "";
  const version = pub.version ? " v" + esc(pub.version) : "";
  const kind = pub.kind === "release" ? "정식 릴리즈" : "플레이 빌드";
  let html;
  if (pub.status === "live") {
    html = '<div class="deploy live"><span class="pill good">배포 완료 · 접속 확인됨</span><strong>' + kind + version + '</strong>' +
      '<div class="actions wrap"><a class="btn primary" href="' + esc(pub.pagesUrl) + '" target="_blank" rel="noopener">플레이 링크 ↗</a>' + repo + "</div>" +
      '<code class="url">' + esc(pub.pagesUrl) + "</code></div>";
  } else if (pub.status === "deploying") {
    html = '<div class="deploy"><span class="pill info">배포 확인 중</span><strong>' + kind + version + '</strong><p class="muted small">GitHub Pages 빌드와 접속(200)을 확인한 뒤 링크가 열립니다. 보통 1–2분.</p><div class="actions wrap">' + repo + "</div></div>";
  } else if (pub.status === "not_configured") {
    html = '<div class="deploy"><span class="pill warn">GitHub 미설정</span><p class="muted small">서버에 AI_FACTORY_GITHUB_TOKEN이 없어 로컬 저장소에만 커밋했습니다.</p></div>';
  } else if (pub.status === "failed") {
    html = '<div class="deploy"><span class="pill bad">배포 실패</span><strong>' + kind + version + '</strong><p class="muted small">' + esc(pub.detail || "") + '</p><div class="actions wrap">' + repo + "</div></div>";
  } else {
    html = '<div class="deploy"><span class="pill neutral">저장소 동기화 ' + esc(pub.status) + '</span><div class="actions wrap">' + repo + "</div></div>";
  }
  if (pub.next && pub.next.status !== "live") {
    html += '<p class="muted small">새 빌드 v' + esc(pub.next.version || "") + " " + (pub.next.status === "deploying" ? "배포 확인 중" : "배포 실패: " + esc(pub.next.detail || "")) + "</p>";
  }
  return html;
}
