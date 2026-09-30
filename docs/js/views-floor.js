// Dashboard (factory floor), idea portfolio and production-line views.

import { esc, fmtTime, fmtNum, pill, meter, empty, LABEL, publicationBlock } from "./ui.js";
import { lineProgress, activeWorkers } from "./engine.js";
import { remainingRatio, atReserve } from "./router.js";

// ---------- dashboard ----------

function topicForm(app, isEdit) {
  const t = isEdit && app.state.projects[0];
  const opt = (values, selected) => values.map((v) => '<option' + (v === selected ? " selected" : "") + ">" + esc(v) + "</option>").join("");
  return (
    '<section class="panel intake">' +
    '<div class="eyebrow">' + (isEdit ? "NEW BRIEF" : "BRIEF / THEME INTAKE") + "</div>" +
    "<h2>" + (isEdit ? "새 주제로 포트폴리오 추가" : "게임 주제만 입력하세요") + "</h2>" +
    '<p class="muted">아이디어 10개 생성 → AI 비평·점수화 → 상위 ' + app.state.settings.autoShortlist + "개 자동 생산라인 → 나머지 Backlog.</p>" +
    '<form id="topicForm" class="form">' +
    '<input name="topic" required maxlength="60" placeholder="예: 홀덤, 좀비, 타이핑, 카지노 운영" value="">' +
    '<div class="formRow">' +
    '<label>장르<select name="genre">' + opt(["자동선택", "Roguelike", "Deckbuilder", "Tycoon", "Tactical", "Survivor", "Puzzle", "Party"], t && t.genre) + "</select></label>" +
    '<label>플랫폼<select name="platform">' + opt(["Windows PC", "Web", "Mobile", "Steam PC"], t && t.platform) + "</select></label>" +
    "</div>" +
    '<textarea name="notes" rows="2" placeholder="선택: 분위기, 레퍼런스, 금지사항"></textarea>' +
    '<div class="actions"><button class="btn primary" type="submit">AI 공장 가동</button>' +
    (isEdit ? '<button class="btn" type="button" data-action="cancel-topic">취소</button>' : "") +
    "</div></form></section>"
  );
}

function stations(line, app, compact) {
  return (
    '<ol class="stations' + (compact ? " compact" : "") + '">' +
    app.ctx.studio.stages.map((s, i) => {
      const st = line.stages[s.id];
      const cls = line.status === "complete" || (st && st.status === "completed") ? "done" : i === line.stageIndex ? "current" : "";
      const count = st ? st.tasks.filter((t) => t.status === "completed").length + "/" + st.tasks.length : "";
      return '<li class="' + cls + '" title="' + esc(i + 1 + ". " + s.name + (count ? " · " + count : "")) + '"><span>' + (i + 1) + "</span>" + (compact ? "" : "<small>" + esc(s.name) + "</small>") + "</li>";
    }).join("") +
    "</ol>"
  );
}

function floorRow(line, app) {
  const stage = app.ctx.studio.stages[line.stageIndex];
  const pct = lineProgress(line, app.ctx);
  const st = line.stages[stage.id];
  const busy = st ? st.tasks.filter((t) => (t.status === "in_progress" || t.status === "review") && t.assignee) : [];
  return (
    '<article class="floorRow" data-action="open-line" data-id="' + esc(line.id) + '" tabindex="0">' +
    '<div class="floorHead"><div><strong>' + esc(line.title) + "</strong><small>" + esc(line.stageIndex + 1 + ". " + stage.name) + " · " + esc(line.leader.lastDecision) + "</small></div>" +
    '<div class="floorMeta">' + pill(line.status) + '<span class="pct">' + pct + "%</span></div></div>" +
    stations(line, app, true) +
    '<div class="workerChips">' +
    (busy.length
      ? busy.map((t) => '<span class="chip ' + (t.status === "review" ? "violet" : "info") + '">' + esc(t.role) + " · " + esc(t.assignee.name) + "</span>").join("")
      : '<span class="chip">' + esc(line.status === "awaiting_ceo" ? "CEO 승인 대기" : line.status === "complete" ? "Live Ops 운영중" : "다음 작업 배정 대기") + "</span>") +
    "</div></article>"
  );
}

export function dashboard(app) {
  const { state, ctx } = app;
  const running = state.lines.filter((l) => l.status === "running");
  const workers = activeWorkers(state);
  const avg = state.lines.length ? Math.round(state.lines.reduce((s, l) => s + lineProgress(l, ctx), 0) / state.lines.length) : 0;
  const builds = state.lines.flatMap((l) => l.builds);
  const playable = builds.filter((b) => b.smoke.passed).length;
  const pendingReviews = state.reviews.filter((r) => r.status === "pending").length;
  const limited = state.employees.filter((e) => e.quota.limit);
  const health = limited.length ? Math.round((limited.reduce((s, e) => s + remainingRatio(e), 0) / limited.length) * 100) : 100;

  const kpi = (label, value, sub, tone = "") => '<div class="kpi ' + tone + '"><span>' + esc(label) + "</span><strong>" + value + "</strong><small>" + esc(sub) + "</small></div>";
  let html =
    '<section class="kpis">' +
    kpi("가동 생산라인", running.length + "<em>/" + state.lines.length + "</em>", "최대 동시 " + state.settings.maxParallel) +
    kpi("전체 진행률", avg + "<em>%</em>", "13단계 공정 평균") +
    kpi("작업중 AI 워커", workers.length, state.employees.length + "명 채용됨") +
    kpi("Failover", state.counters.failovers, "쿼터경고 " + state.counters.quotaWarnings, state.counters.failovers ? "warn" : "") +
    kpi("빌드", playable + "<em>/" + builds.length + "</em>", "smoke test 통과") +
    kpi("CEO 검토", pendingReviews, "쿼터 여유 평균 " + health + "%", pendingReviews ? "accent" : "") +
    "</section>";

  html += '<div class="dashGrid"><div class="stack">';
  if (!state.projects.length || app.ui.editingTopic) html += topicForm(app, state.projects.length > 0);
  else {
    const p = state.projects[0];
    html +=
      '<section class="panel brief"><div class="panelHead"><div><div class="eyebrow">ACTIVE BRIEF</div><h2>' + esc(p.topic) + "</h2></div>" +
      '<div class="actions"><span class="chip">' + esc(p.platform) + '</span><span class="chip">' + esc(p.genre) + '</span><button class="btn small" data-action="new-topic">새 주제</button></div></div>' +
      '<p class="muted">' + state.ideas.filter((i) => i.projectId === p.id).length + "개 아이디어 · " +
      state.lines.filter((l) => l.projectId === p.id).length + "개 생산라인 · Backlog " + state.ideas.filter((i) => i.projectId === p.id && i.status === "backlog").length + "개</p></section>";
  }
  html +=
    '<section class="panel"><div class="panelHead"><div><div class="eyebrow">FACTORY FLOOR</div><h2>생산 현장</h2></div>' +
    '<button class="btn small" data-action="tab" data-id="lines">전체 생산라인</button></div>' +
    (state.lines.length ? '<div class="floor">' + state.lines.slice().reverse().map((l) => floorRow(l, app)).join("") + "</div>" : empty("주제를 입력하면 생산라인이 여기에 나타납니다.")) +
    "</section></div>";

  html += '<aside class="stack">';
  html +=
    '<section class="panel"><div class="panelHead"><div><div class="eyebrow">AI QUOTA</div><h2>쿼터 게이지</h2></div><button class="btn small" data-action="tab" data-id="team">상세</button></div>' +
    '<div class="quotaList">' +
    state.employees.map((e) => {
      const unlimited = !e.quota.limit;
      const pct = unlimited ? 100 : remainingRatio(e) * 100;
      return '<div class="quotaRow"><div><strong>' + esc(e.name) + "</strong><small>" + (unlimited ? "무제한" : fmtNum(e.quota.limit - e.quota.used) + " " + esc(e.quota.unit) + " 남음") + "</small></div>" +
        (atReserve(e) ? pill("reserve") : e.cooldownUntil > ctx.now ? pill("cooldown") : e.status !== "online" ? pill(e.status) : "") +
        meter(pct, { reserve: unlimited ? null : e.quota.reserve, label: e.name + " 쿼터" }) + "</div>";
    }).join("") +
    "</div></section>";
  const latestBuilds = state.lines.filter((l) => l.builds.length).map((l) => ({ line: l, build: l.builds[0] }));
  html +=
    '<section class="panel"><div class="panelHead"><div><div class="eyebrow">BUILDS</div><h2>빌드 상태</h2></div></div>' +
    (latestBuilds.length
      ? '<ul class="plainList">' + latestBuilds.map(({ line, build }) =>
          '<li><div><strong>' + esc(line.title) + "</strong><small>v" + esc(build.version) + " · " + esc(fmtTime(build.createdAt)) + "</small></div>" +
          pill(build.smoke.passed ? "passed" : "failed", build.smoke.passed ? "smoke 통과" : "smoke 실패") +
          '<button class="btn small" data-action="play" data-id="' + esc(line.id) + '">실행</button></li>').join("") + "</ul>"
      : '<p class="muted">Prototype 단계가 끝나면 첫 플레이 빌드가 나옵니다.</p>') +
    "</section>";
  html +=
    '<section class="panel"><div class="panelHead"><div><div class="eyebrow">EVENTS</div><h2>최근 이벤트</h2></div><button class="btn small" data-action="tab" data-id="logs">로그</button></div>' +
    '<ul class="eventList">' + state.logs.slice(0, 9).map((l) => '<li><span class="evType t-' + esc(l.type.split(" ")[0].toLowerCase()) + '">' + esc(l.type) + "</span><p>" + esc(l.text) + "</p><small>" + esc(fmtTime(l.time)) + "</small></li>").join("") + "</ul>" +
    "</section></aside></div>";
  return html;
}

// ---------- ideas ----------

export function ideas(app) {
  const { state, ctx } = app;
  if (!state.projects.length) return empty("먼저 대시보드에서 주제를 입력하세요.", '<button class="btn primary" data-action="tab" data-id="dashboard">주제 입력</button>');
  const project = state.projects.find((p) => p.id === app.ui.projectId) || state.projects[0];
  const list = state.ideas.filter((i) => i.projectId === project.id);
  const criteria = ctx.studio.idea_criteria;

  const card = (i) =>
    '<article class="idea ' + esc(i.status) + '">' +
    '<div class="ideaTop"><span class="rank">#' + i.rank + '</span><span class="score">' + i.score.toFixed(1) + "</span>" + pill(i.status) + "</div>" +
    "<h3>" + esc(i.title) + '</h3><p class="muted">' + esc(i.pitch) + "</p>" +
    '<p class="loop">' + i.loop.map(esc).join(" → ") + "</p>" +
    '<div class="metrics">' + criteria.map((c) => '<div><small>' + esc(c.label) + "</small>" + meter(i.metrics[c.id], { tone: i.metrics[c.id] >= 80 ? "good" : i.metrics[c.id] >= 65 ? "info" : "warn" }) + "<b>" + i.metrics[c.id] + "</b></div>").join("") + "</div>" +
    '<ul class="reviews">' + i.reviews.map((r) => "<li><strong>" + esc(r.role) + "</strong> " + esc(r.verdict) + " (" + r.score + ") · " + esc(r.note) + "</li>").join("") + "</ul>" +
    (i.status === "backlog" || i.status === "candidate" ? '<button class="btn primary small" data-action="build-idea" data-id="' + esc(i.id) + '">이 아이디어 제작</button>' : "") +
    "</article>";

  const shortlisted = list.filter((i) => i.status !== "backlog" && i.status !== "candidate");
  const backlog = list.filter((i) => i.status === "backlog" || i.status === "candidate");
  return (
    (state.projects.length > 1
      ? '<div class="segmented">' + state.projects.map((p) => '<button class="' + (p.id === project.id ? "on" : "") + '" data-action="project" data-id="' + esc(p.id) + '">' + esc(p.topic) + "</button>").join("") + "</div>"
      : "") +
    '<section class="panel"><div class="panelHead"><div><div class="eyebrow">IDEATION ROOM · ' + esc(project.topic) + "</div><h2>자동 Shortlist</h2></div>" +
    '<span class="chip">가중치: ' + criteria.map((c) => esc(c.label) + " " + Math.round(c.weight * 100) + "%").join(" · ") + "</span></div>" +
    '<div class="portfolioTasks">' + project.portfolio.flatMap((s) => s.tasks).map((t) => '<span class="chip">' + esc(t.name) + " → " + esc(t.assignee) + "</span>").join("") + "</div>" +
    '<div class="ideaGrid">' + shortlisted.map(card).join("") + "</div></section>" +
    '<section class="panel"><div class="panelHead"><div><div class="eyebrow">IDEA BACKLOG</div><h2>보관된 아이디어 ' + backlog.length + "개</h2></div>" +
    '<span class="muted">병렬 한도 ' + state.settings.maxParallel + " · 가동 " + state.lines.filter((l) => l.status === "running").length + "</span></div>" +
    (backlog.length ? '<div class="ideaGrid">' + backlog.map(card).join("") + "</div>" : empty("Backlog가 비었습니다.")) +
    "</section>"
  );
}

// ---------- production lines ----------

function depGraph(stage) {
  const tasks = stage.tasks;
  const depth = {};
  const visit = (t, seen = new Set()) => {
    if (depth[t.id] != null) return depth[t.id];
    if (seen.has(t.id)) return 0;
    seen.add(t.id);
    const ds = t.depends.map((d) => tasks.find((x) => x.id === d)).filter(Boolean);
    depth[t.id] = ds.length ? 1 + Math.max(...ds.map((d) => visit(d, seen))) : 0;
    return depth[t.id];
  };
  tasks.forEach((t) => visit(t));
  const cols = {};
  tasks.forEach((t) => (cols[depth[t.id]] = cols[depth[t.id]] || []).push(t));
  const colCount = Object.keys(cols).length;
  const maxRows = Math.max(...Object.values(cols).map((c) => c.length));
  const W = 170, H = 54, GX = 46, GY = 16;
  const width = colCount * W + (colCount - 1) * GX + 20;
  const height = maxRows * H + (maxRows - 1) * GY + 20;
  const pos = {};
  Object.entries(cols).forEach(([c, list]) => {
    const offset = ((maxRows - list.length) * (H + GY)) / 2;
    list.forEach((t, r) => (pos[t.id] = { x: 10 + c * (W + GX), y: 10 + offset + r * (H + GY) }));
  });
  let edges = "";
  for (const t of tasks) {
    for (const d of t.depends) {
      if (!pos[d]) continue;
      const a = pos[d], b = pos[t.id];
      const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2, mx = (x1 + x2) / 2;
      edges += '<path d="M' + x1 + " " + y1 + " C" + mx + " " + y1 + " " + mx + " " + y2 + " " + x2 + " " + y2 + '" class="edge' + (tasks.find((x) => x.id === d).status === "completed" ? " done" : "") + '"/>';
    }
  }
  const nodes = tasks.map((t) => {
    const p = pos[t.id];
    const name = t.name.length > 15 ? t.name.slice(0, 14) + "…" : t.name;
    return '<g class="node s-' + t.status + '" transform="translate(' + p.x + "," + p.y + ')"><title>' + esc(t.name + " · " + t.role + " · " + (LABEL[t.status] || t.status)) + '</title>' +
      '<rect width="' + W + '" height="' + H + '" rx="10"/>' +
      '<text x="12" y="22" class="nt">' + esc(name) + '</text><text x="12" y="40" class="ns">' + esc((t.assignee ? t.assignee.name : t.role).slice(0, 22)) + "</text></g>";
  }).join("");
  return '<div class="graphWrap"><svg class="depGraph" viewBox="0 0 ' + width + " " + height + '" width="' + width + '" role="img" aria-label="작업 의존성 그래프">' + edges + nodes + "</svg></div>";
}

function taskTable(stage) {
  return (
    '<div class="tableWrap"><table class="tasks"><thead><tr><th>Task</th><th>담당 Role</th><th>AI</th><th>의존성</th><th>상태</th><th>산출물</th><th>Commit</th><th>QA</th><th>Quota</th></tr></thead><tbody>' +
    stage.tasks.map((t) =>
      "<tr><td><strong>" + esc(t.name) + "</strong>" + (t.critical ? ' <span class="tag">critical</span>' : "") + (t.repairOf ? ' <span class="tag warn">repair</span>' : "") + "<small>난이도 " + t.difficulty + " · " + esc(t.kind) + "</small></td>" +
      "<td>" + esc(t.role) + "</td>" +
      "<td>" + (t.assignee ? esc(t.assignee.name) + "<small>" + esc(t.assignee.model || "") + (t.reviewer ? " · 리뷰 " + esc(t.reviewer.name) : "") + "</small>" : '<span class="muted">-</span>') + "</td>" +
      "<td>" + (t.depends.length ? t.depends.map(esc).join(", ") : '<span class="muted">없음</span>') + "</td>" +
      "<td>" + pill(t.status) + "</td>" +
      "<td><code>" + esc(t.artifact) + "</code></td>" +
      "<td>" + (t.commit ? '<code title="' + esc(t.branch) + '">' + esc(t.commit.slice(0, 7)) + "</code>" : '<span class="muted">-</span>') + "</td>" +
      "<td>" + (t.qa ? pill(t.qa === "failed" ? "failed" : "passed", LABEL[t.qa] || t.qa) : '<span class="muted">-</span>') + "</td>" +
      "<td>" + (t.quotaUsed ? fmtNum(t.quotaUsed) + " <small>" + esc(t.quotaUnit || "") + "</small>" : '<span class="muted">0</span>') + "</td></tr>"
    ).join("") +
    "</tbody></table></div>"
  );
}

function lineDetail(line, app) {
  const { ctx, state } = app;
  const stageId = app.ui.stageId && line.stages[app.ui.stageId] ? app.ui.stageId : ctx.studio.stages[line.stageIndex].id;
  const def = ctx.studio.stages.find((s) => s.id === stageId);
  const stage = line.stages[stageId];
  const idea = state.ideas.find((i) => i.id === line.ideaId);
  const controls =
    (line.status === "running"
      ? '<button class="btn" data-action="line-autopilot" data-id="' + esc(line.id) + '">' + (line.autopilot ? "자동진행 일시정지" : "자동진행 재개") + "</button>" +
        '<button class="btn" data-action="line-step" data-id="' + esc(line.id) + '">Leader 1스텝</button>' +
        '<button class="btn primary" data-action="line-ff" data-id="' + esc(line.id) + '">다음 게이트까지 즉시 실행</button>'
      : line.status === "paused"
        ? '<button class="btn primary" data-action="line-resume" data-id="' + esc(line.id) + '">생산라인 재개</button>'
        : line.status === "awaiting_ceo"
          ? '<button class="btn primary" data-action="tab" data-id="review">CEO Review로 이동</button>'
          : "") +
    '<button class="btn" data-action="gdd" data-id="' + esc(line.id) + '">GDD</button>' +
    (line.builds.length ? '<button class="btn" data-action="play" data-id="' + esc(line.id) + '">최신 빌드 실행</button>' : "");

  const stageTabs =
    '<ol class="stations selectable">' +
    ctx.studio.stages.map((s, i) => {
      const st = line.stages[s.id];
      const cls = [st && st.status === "completed" ? "done" : i === line.stageIndex && line.status !== "complete" ? "current" : "", s.id === stageId ? "selected" : ""].join(" ");
      return '<li class="' + cls + '"><button data-action="stage" data-id="' + esc(s.id) + '"' + (st ? "" : " disabled") + '><span>' + (i + 1) + "</span><small>" + esc(s.name) + "</small></button></li>";
    }).join("") +
    "</ol>";

  const stagePanel = stage
    ? '<section class="panel"><div class="panelHead"><div><div class="eyebrow">STAGE ' + (ctx.studio.stages.indexOf(def) + 1) + " · " + esc(def.id.toUpperCase()) + "</div><h2>" + esc(def.name) + '</h2><p class="muted">' + esc(def.summary) + "</p></div>" +
      '<div class="actions">' + pill(stage.status === "completed" ? "completed" : "in_progress") + pill(stage.qa.status, "QA " + (LABEL[stage.qa.status] || stage.qa.status)) + '<span class="chip">토큰 ' + fmtNum(stage.quotaUsed) + "</span></div></div>" +
      (stage.inherited ? '<p class="muted">포트폴리오 단계(아이디어 룸)에서 공동 수행된 공정입니다.</p>' : depGraph(stage)) +
      taskTable(stage) + "</section>"
    : "";

  const commits = line.commits.slice(0, 14);
  const byStage = {};
  for (const a of line.artifacts) (byStage[a.stageId] = byStage[a.stageId] || []).push(a.name);

  return (
    '<section class="panel lineHeader"><div class="panelHead"><div><div class="eyebrow">PRODUCTION LINE · ' + esc(line.family.toUpperCase()) + "</div><h2>" + esc(line.title) + "</h2>" +
    '<p class="muted">' + esc(idea ? idea.pitch : "") + "</p></div><div class=\"actions\">" + pill(line.status) + '<span class="pct big">' + lineProgress(line, ctx) + "%</span></div></div>" +
    '<div class="leader"><span class="leaderDot ' + esc(line.leader.state) + '"></span><div><strong>' + esc(line.leader.name) + "</strong> " + pill(line.leader.state) + "<small>" + esc(line.leader.lastDecision) + "</small></div></div>" +
    '<div class="actions wrap">' + controls + "</div>" + stageTabs + "</section>" +
    stagePanel +
    '<div class="twoCol">' +
    '<section class="panel"><div class="panelHead"><div><div class="eyebrow">GIT</div><h2>커밋 · 브랜치</h2></div><span class="chip">' + line.commits.length + " commits</span></div>" +
    (commits.length
      ? '<ul class="commitList">' + commits.map((c) => "<li><code>" + esc(c.sha.slice(0, 7)) + "</code><div><strong>" + esc(c.message) + "</strong><small>" + esc(c.branch) + "</small><small>" + esc(c.author) + (c.reviewer ? " · reviewed by " + esc(c.reviewer) : "") + " · merged → main</small></div></li>").join("") + "</ul>"
      : '<p class="muted">아직 커밋이 없습니다.</p>') +
    "</section>" +
    '<section class="panel"><div class="panelHead"><div><div class="eyebrow">AGENT INBOX</div><h2>Leader ↔ Worker 메시지</h2></div></div>' +
    '<ul class="inbox">' + line.messages.slice(0, 14).map((m) => '<li><span class="msgType">' + esc(m.type) + "</span><div><strong>" + esc(m.from) + " → " + esc(m.to) + "</strong><p>" + esc(m.text) + "</p></div><small>" + esc(fmtTime(m.time)) + "</small></li>").join("") + "</ul>" +
    "</section></div>" +
    '<div class="twoCol">' +
    '<section class="panel"><div class="panelHead"><div><div class="eyebrow">ARTIFACTS · BUILDS · DEPLOY</div><h2>산출물 · 배포</h2></div></div>' +
    publicationBlock(line, state.user.mode) +
    (line.builds.length ? '<ul class="plainList">' + line.builds.map((b) => "<li><div><strong>v" + esc(b.version) + " · " + esc(b.stageId) + "</strong><small>" + esc(fmtTime(b.createdAt)) + (b.bytes ? " · " + fmtNum(b.bytes) + " bytes" : "") + (b.commit ? " · " + esc(String(b.commit).slice(0, 7)) : "") + "</small></div>" + pill(b.smoke.passed ? "passed" : "failed", "smoke") + '<button class="btn small" data-action="play" data-id="' + esc(line.id) + '">실행</button><button class="btn small" data-action="download-build" data-id="' + esc(line.id) + '">다운로드</button></li>').join("") + "</ul>" : "") +
    '<div class="artifactGroups">' + Object.entries(byStage).map(([sid, names]) => "<div><small>" + esc(sid) + "</small>" + names.map((n) => "<code>" + esc(n) + "</code>").join("") + "</div>").join("") + "</div>" +
    "</section>" +
    '<section class="panel"><div class="panelHead"><div><div class="eyebrow">CEO FEEDBACK</div><h2>수정 지시</h2></div></div>' +
    '<form class="inlineForm" data-form="feedback" data-id="' + esc(line.id) + '"><input name="text" maxlength="200" placeholder="예: 첫 30초 튜토리얼을 더 쉽게" required><button class="btn primary">지시</button></form>' +
    '<ul class="plainList">' + line.feedback.map((f) => "<li><div><strong>" + esc(f.text) + "</strong><small>" + esc(fmtTime(f.time)) + " · " + esc(f.stageId || "") + " / " + esc(f.taskId || "") + "</small></div>" + pill(f.status === "scheduled" ? "in_progress" : "completed", f.status === "scheduled" ? "작업 편성" : "반영") + "</li>").join("") + "</ul>" +
    "</section></div>"
  );
}

export function lines(app) {
  const { state, ctx } = app;
  if (!state.lines.length) return empty("생산라인이 아직 없습니다.", '<button class="btn primary" data-action="tab" data-id="dashboard">주제 입력</button>');
  const selected = state.lines.find((l) => l.id === app.ui.lineId) || state.lines[state.lines.length - 1];
  return (
    '<div class="linesLayout"><nav class="lineList" aria-label="생산라인 목록">' +
    state.lines.slice().reverse().map((l) =>
      '<button class="lineItem' + (l.id === selected.id ? " on" : "") + '" data-action="open-line" data-id="' + esc(l.id) + '"><strong>' + esc(l.title) + "</strong><small>" +
      esc(l.stageIndex + 1 + ". " + ctx.studio.stages[l.stageIndex].name) + "</small>" + meter(lineProgress(l, ctx), { tone: "info" }) + pill(l.status) + "</button>"
    ).join("") +
    '</nav><div class="stack">' + lineDetail(selected, app) + "</div></div>"
  );
}
