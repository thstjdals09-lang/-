// Factory engine: ideation, shortlist, Leader Agent scheduling, worker execution and failover.
// Pure state transitions. The caller supplies ctx = {studio, providers, now, rng, settings}.

import { routeTask, usageFor, atReserve, classifyError, nextReset, remaining } from "./router.js";

// When no installed AI has a modality, the Leader downgrades the task instead of stalling the line.
const FALLBACK_KIND = { vision: "qa", image: "design", audio: "design" };
import { buildGame, gameFamily, smokeTest } from "./games.js";

export const STATE_VERSION = 4;
const MAX_LOGS = 400;
const MAX_MESSAGES = 120;

// ---------- utilities ----------

export function createRng(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function hashString(value) {
  let h = 2166136261;
  for (const ch of String(value)) {
    h ^= ch.codePointAt(0);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function slugify(value) {
  const slug = String(value || "")
    .toLowerCase()
    .normalize("NFC")
    .replace(/[^a-z0-9가-힣]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
  return slug || "item";
}

function uid(ctx, prefix) {
  return prefix + "-" + ctx.now.toString(36) + "-" + Math.floor(ctx.rng() * 1e9).toString(36);
}

function sha(ctx) {
  let out = "";
  for (let i = 0; i < 40; i++) out += Math.floor(ctx.rng() * 16).toString(16);
  return out;
}

export function addLog(state, ctx, type, text, lineId = null) {
  state.logs.unshift({ id: uid(ctx, "log"), time: ctx.now, type, text, lineId });
  if (state.logs.length > MAX_LOGS) state.logs.length = MAX_LOGS;
}

function message(line, ctx, type, from, to, text, taskId = null) {
  line.messages.unshift({ id: uid(ctx, "msg"), time: ctx.now, type, from, to, taskId, text });
  if (line.messages.length > MAX_MESSAGES) line.messages.length = MAX_MESSAGES;
}

// ---------- state ----------

export function defaultSettings() {
  return {
    policy: "cheapest_viable_quality",
    maxParallel: 3,
    autoShortlist: 3,
    workersPerLine: 3,
    autopilot: true,
    failureRate: 0.08,
    qaFailRate: 0.15,
    backendUrl: "",
  };
}

export function employeeFromCatalog(entry, ctx, overrides = {}) {
  const limit = entry.quota.limit;
  return {
    id: entry.id,
    catalogId: entry.id,
    name: entry.name,
    vendor: entry.vendor,
    model: entry.default_model,
    adapter: entry.adapter,
    authType: overrides.authType || entry.auth_types[0],
    status: "online",
    credentialRef: overrides.credentialRef || null,
    endpoint: overrides.endpoint || entry.base_url,
    categories: entry.categories.slice(),
    modalities: entry.modalities.slice(),
    skills: { ...entry.skills },
    contextLength: entry.context_length,
    speed: entry.speed,
    reliability: entry.reliability,
    costTier: entry.cost_tier,
    free: entry.free,
    quota: {
      unit: entry.quota.unit,
      limit,
      used: 0,
      reserve: entry.quota.default_reserve,
      window: entry.quota.window,
      resetAt: nextReset(entry.quota.window, ctx.now),
    },
    cooldownUntil: 0,
    // simulated: preview only · backend: credential held by the server vault · verified: endpoint answered a probe
    connectionMode: overrides.connectionMode || "simulated",
    installedAt: ctx.now,
    lastVerified: null,
    stats: { requests: 0, tokens: 0, errors: 0, failovers: 0, latencyTotal: 0, tasksDone: 0, quality: [] },
  };
}

export function createState(ctx) {
  const local = ctx.providers.find((p) => p.id === "local-llamacpp");
  return {
    version: STATE_VERSION,
    user: { signedIn: false, mode: null, email: null, name: null },
    settings: defaultSettings(),
    employees: local ? [employeeFromCatalog(local, ctx)] : [],
    projects: [],
    ideas: [],
    lines: [],
    reviews: [],
    logs: [],
    counters: { failovers: 0, handoffs: 0, quotaWarnings: 0, tasksDone: 0 },
  };
}

// ---------- ideation ----------

export function generateIdeas(project, ctx) {
  const rng = createRng(hashString(project.topic + "|" + project.genre + "|" + project.platform));
  const criteria = ctx.studio.idea_criteria;
  const ideas = ctx.studio.idea_patterns.map((pattern, i) => {
    const metrics = {};
    for (const c of criteria) {
      const base = 62 + Math.floor(rng() * 30);
      metrics[c.id] = Math.max(35, Math.min(99, base + (pattern.bias[c.id] || 0)));
    }
    if (project.genre && project.genre !== "자동선택" && pattern.type.toLowerCase().includes(project.genre.toLowerCase())) {
      metrics.fun = Math.min(99, metrics.fun + 6);
      metrics.market = Math.min(99, metrics.market + 4);
    }
    const score = Math.round(criteria.reduce((sum, c) => sum + metrics[c.id] * c.weight, 0) * 10) / 10;
    const reviews = ctx.studio.idea_reviewers.map((r) => {
      const avg = Math.round(r.focus.reduce((s, k) => s + metrics[k], 0) / r.focus.length);
      const weakest = r.focus.slice().sort((a, b) => metrics[a] - metrics[b])[0];
      const label = criteria.find((c) => c.id === weakest).label;
      return {
        role: r.role,
        score: avg,
        verdict: avg >= 80 ? "강력 추천" : avg >= 70 ? "조건부 추천" : "보류",
        note: avg >= 80 ? label + "까지 안정적입니다." : label + " 보완이 필요합니다.",
      };
    });
    return {
      id: uid(ctx, "idea") + i,
      projectId: project.id,
      title: project.topic + " · " + pattern.type,
      type: pattern.type,
      family: pattern.family,
      pitch: project.topic + "를 " + pattern.pitch,
      loop: pattern.loop.slice(),
      metrics,
      score,
      reviews,
      status: "candidate",
      rank: 0,
    };
  });
  ideas.sort((a, b) => b.score - a.score);
  ideas.forEach((idea, i) => { idea.rank = i + 1; });
  return ideas;
}

// Executes a portfolio-level stage (brief/ideation) so it shows who did the work.
function runPortfolioStage(state, stageDef, project, ctx) {
  const record = { stageId: stageDef.id, tasks: [] };
  for (const def of stageDef.tasks) {
    const task = { ...def, critical: !!def.critical };
    const assignee = dispatch(state, task, ctx, null);
    record.tasks.push({ id: def.id, name: def.name, role: def.role, artifact: def.artifact, assignee: assignee ? assignee.name : "대기" });
  }
  project.portfolio.push(record);
}

export function createProject(state, input, ctx) {
  const project = {
    id: uid(ctx, "proj"),
    topic: String(input.topic).trim(),
    genre: input.genre || "자동선택",
    platform: input.platform || "Windows PC",
    notes: input.notes || "",
    createdAt: ctx.now,
    portfolio: [],
  };
  state.projects.unshift(project);
  const portfolioStages = ctx.studio.stages.filter((s) => s.scope === "portfolio");
  runPortfolioStage(state, portfolioStages[0], project, ctx);
  const ideas = generateIdeas(project, ctx);
  runPortfolioStage(state, portfolioStages[1], project, ctx);
  state.ideas.push(...ideas);

  const running = state.lines.filter((l) => l.status === "running").length;
  const slots = Math.max(0, state.settings.maxParallel - running);
  const n = Math.min(state.settings.autoShortlist, slots, ideas.length);
  ideas.forEach((idea, i) => {
    if (i < n) {
      idea.status = "shortlisted";
      createLine(state, idea, ctx, true);
    } else {
      idea.status = "backlog";
    }
  });
  addLog(state, ctx, "IDEATION", project.topic + " · 아이디어 " + ideas.length + "개 생성 · 상위 " + n + "개 자동 shortlist · " + (ideas.length - n) + "개 Backlog 보관");
  if (n < Math.min(state.settings.autoShortlist, ideas.length)) {
    addLog(state, ctx, "CAPACITY", "병렬 생산라인 한도 " + state.settings.maxParallel + " · 나머지 shortlist는 Backlog에서 대기");
  }
  return project;
}

// ---------- production lines ----------

function productionStages(ctx) {
  return ctx.studio.stages.filter((s) => s.scope !== "portfolio");
}

export function stageList(ctx) {
  return ctx.studio.stages;
}

export function createLine(state, idea, ctx, automatic) {
  if (state.lines.some((l) => l.ideaId === idea.id)) return null;
  const project = state.projects.find((p) => p.id === idea.projectId);
  const firstIndex = ctx.studio.stages.findIndex((s) => s.scope !== "portfolio");
  const line = {
    id: uid(ctx, "line"),
    projectId: idea.projectId,
    ideaId: idea.id,
    title: idea.title,
    topic: project ? project.topic : "game",
    gameType: idea.type,
    family: idea.family || gameFamily(idea.type),
    slug: slugify(idea.type),
    projectSlug: slugify(project ? project.topic : "game"),
    stageIndex: firstIndex,
    status: "running",
    autopilot: state.settings.autopilot,
    createdAt: ctx.now,
    leader: { name: "Leader · " + idea.type, state: "planning", lastDecision: "생산라인 개설" },
    stages: {},
    commits: [],
    artifacts: [],
    builds: [],
    feedback: [],
    messages: [],
    quotaUsed: 0,
  };
  for (let i = 0; i < firstIndex; i++) {
    const def = ctx.studio.stages[i];
    line.stages[def.id] = {
      status: "completed",
      inherited: true,
      startedAt: ctx.now,
      completedAt: ctx.now,
      tasks: def.tasks.map((t) => ({ ...t, stageId: def.id, status: "completed", assignee: null, attempts: 0 })),
      qa: { status: "passed", checks: [] },
      quotaUsed: 0,
    };
    for (const t of def.tasks) line.artifacts.push({ name: t.artifact, stageId: def.id, taskId: t.id });
  }
  state.lines.push(line);
  idea.status = "in_production";
  addLog(state, ctx, "LINE START", idea.title + " · " + (automatic ? "자동 shortlist" : "CEO 지시") + "로 생산라인 개설", line.id);
  message(line, ctx, "lifecycle", "CEO", line.leader.name, automatic ? "자동 shortlist 생산 시작" : "CEO가 Backlog 아이디어 제작 지시");
  return line;
}

export function currentStageDef(line, ctx) {
  return ctx.studio.stages[line.stageIndex];
}

function instantiateStage(line, def, ctx) {
  const stage = {
    status: "in_progress",
    startedAt: ctx.now,
    completedAt: null,
    tasks: def.tasks.map((t) => ({
      id: t.id,
      stageId: def.id,
      name: t.name,
      role: t.role,
      kind: t.kind,
      difficulty: t.difficulty,
      critical: !!t.critical,
      depends: t.depends.slice(),
      artifact: t.artifact,
      status: t.depends.length ? "pending" : "ready",
      attempts: 0,
      assignee: null,
      reviewer: null,
      branch: null,
      commit: null,
      qa: null,
      quotaUsed: 0,
      remaining: 0,
      startedAt: null,
      finishedAt: null,
      repairOf: null,
    })),
    qa: { status: "pending", checks: [] },
    quotaUsed: 0,
  };
  line.stages[def.id] = stage;
  line.leader.state = "planning";
  line.leader.lastDecision = def.name + " 작업 " + stage.tasks.length + "개로 분해";
  message(line, ctx, "plan", line.leader.name, "workers", def.name + " task graph 생성 (" + stage.tasks.length + " tasks)");
  return stage;
}

export function branchName(line, agentName, task) {
  return "ai-factory/" + line.projectSlug + "/" + line.slug + "/" + slugify(agentName) + "/" + task.stageId + "-" + task.id;
}

// Routes a task and simulates provider calls with automatic failover. Returns the employee that
// accepted the work, or null when nobody could (the task is then blocked).
export function dispatch(state, task, ctx, line) {
  ensureContinuity(state, ctx);
  const decision = routeTask(task, state.employees, { policy: state.settings.policy, now: ctx.now, routing: ctx.studio.routing });
  let previous = null;
  for (const candidate of decision.ordered) {
    const e = candidate.employee;
    const failP = (state.settings.failureRate || 0) * (1.5 - (e.reliability || 80) / 100);
    const latency = Math.round(400 + (100 - (e.speed || 50)) * 40 + ctx.rng() * 600);
    e.stats.requests += 1;
    e.stats.latencyTotal += latency;
    if (e.authType !== "local" && ctx.rng() < failP) {
      const roll = ctx.rng();
      const status = roll < 0.55 ? 429 : roll < 0.95 ? 503 : 401;
      const err = classifyError({ status });
      e.stats.errors += 1;
      if (err.kind === "auth_error") e.status = "auth_required";
      if (err.cooldownMs) e.cooldownUntil = ctx.now + err.cooldownMs;
      previous = { employee: e, status, err };
      continue;
    }
    if (previous) {
      state.counters.failovers += 1;
      previous.employee.stats.failovers += 1;
      addLog(state, ctx, "FAILOVER", previous.employee.name + " " + previous.status + " " + previous.err.kind + " → " + e.name + "에게 " + task.role + " '" + task.name + "' handoff", line && line.id);
      if (line) message(line, ctx, "handoff", previous.employee.name, e.name, previous.err.kind + " 발생으로 작업 인계", task.id);
    }
    if (decision.degraded || !candidate.viable) {
      addLog(state, ctx, "DEGRADED", task.name + " · 품질 기준 " + decision.required + " 이상 AI 없음 → " + e.name + " (" + candidate.capability + ")로 진행", line && line.id);
    }
    consume(state, e, task, ctx, line);
    return { employee: e, capability: candidate.capability, viable: candidate.viable };
  }
  return null;
}

// Retries a blocked task with a text-only fallback when no capable AI will become free soon.
function substituteIfUnroutable(state, task, ctx, line) {
  const fallback = FALLBACK_KIND[task.kind];
  if (!fallback) return null;
  // A capable AI that is only cooling down will be back within seconds: wait for it.
  const capableCoolingDown = state.employees.some((e) => e.cooldownUntil > ctx.now && e.status === "online" && (e.skills[task.kind] || 0) > 0);
  if (capableCoolingDown) return null;
  const from = task.kind;
  task.kind = fallback;
  task.substituted = from;
  addLog(state, ctx, "SUBSTITUTE", task.name + " · " + from + " 가능한 AI 없음 → " + fallback + " 방식으로 대체 수행 (AI 마켓에서 " + from + " AI 추가 권장)", line && line.id);
  if (line) message(line, ctx, "blocked", line.leader.name, "Router", from + " → " + fallback + " 대체", task.id);
  return dispatch(state, task, ctx, line);
}

function consume(state, employee, task, ctx, line) {
  const use = usageFor(employee, task, ctx.studio.routing);
  const wasReserve = atReserve(employee);
  if (employee.quota.limit != null && employee.quota.unit !== "unlimited") {
    employee.quota.used = Math.min(employee.quota.limit, Math.round((employee.quota.used + use) * 100) / 100);
  }
  const tokens = ctx.studio.routing.estimated_tokens[task.difficulty] || 5000;
  employee.stats.tokens += tokens;
  task.quotaUsed = (task.quotaUsed || 0) + use;
  task.quotaUnit = employee.quota.unit;
  if (line) {
    line.quotaUsed += tokens;
    const stage = line.stages[task.stageId];
    if (stage) stage.quotaUsed += tokens;
  }
  if (!wasReserve && atReserve(employee)) {
    state.counters.quotaWarnings += 1;
    addLog(state, ctx, "QUOTA WARNING", employee.name + " 예약선(" + Math.round(employee.quota.reserve * 100) + "%) 도달 · 비핵심 작업 배정 중단, 핵심 작업 전용으로 보존", line && line.id);
    if (line) message(line, ctx, "quota_warning", "Router", line.leader.name, employee.name + " reserve 도달");
  }
}

export function ensureContinuity(state, ctx) {
  const probe = { kind: "qa", difficulty: 1, critical: false };
  const anyUsable = state.employees.some((e) => routeTask(probe, [e], { now: ctx.now, routing: ctx.studio.routing }).ordered.length > 0);
  if (anyUsable) return;
  const local = ctx.providers.find((p) => p.id === "local-llamacpp");
  const installed = state.employees.find((e) => e.catalogId === "local-llamacpp");
  if (installed) {
    if (installed.status !== "online") {
      installed.status = "online";
      addLog(state, ctx, "AUTO RECOVER", "모든 AI가 사용 불가 → Local Worker 강제 복귀");
    }
    return;
  }
  if (local) {
    state.employees.push(employeeFromCatalog(local, ctx));
    addLog(state, ctx, "AUTO HIRE", "모든 외부 AI가 사용 불가 → Local Unlimited Worker 자동 투입");
  }
}

function spawnRepair(stage, qaTask, line, ctx) {
  const n = stage.tasks.filter((t) => t.repairOf === qaTask.id).length / 2 + 1;
  const fixId = qaTask.id + "-fix" + n;
  const retestId = qaTask.id + "-retest" + n;
  stage.tasks.push({
    ...qaTask, id: fixId, name: "자동 수정: " + qaTask.name + " 실패 항목", role: "Gameplay Programmer", kind: "debugging",
    difficulty: 2, critical: false, depends: [], artifact: "fix-" + qaTask.id + ".patch", status: "ready", attempts: 0,
    assignee: null, reviewer: null, branch: null, commit: null, qa: null, quotaUsed: 0, remaining: 0, repairOf: qaTask.id,
  });
  stage.tasks.push({
    ...qaTask, id: retestId, name: "재검증: " + qaTask.name, depends: [fixId], status: "pending", attempts: 0,
    assignee: null, reviewer: null, branch: null, commit: null, qa: null, quotaUsed: 0, remaining: 0, repairOf: qaTask.id,
  });
  // Downstream work now waits for the retest instead of the failed QA task.
  for (const t of stage.tasks) {
    if (t.id !== retestId && t.depends.includes(qaTask.id) && t.status === "pending") t.depends.push(retestId);
  }
  message(line, ctx, "blocked", qaTask.assignee ? qaTask.assignee.name : "QA", line.leader.name, qaTask.name + " 실패 → 수정/재검증 task 생성", qaTask.id);
}

function completeTask(state, line, stage, task, ctx) {
  task.status = "completed";
  task.finishedAt = ctx.now;
  const agent = task.assignee ? task.assignee.name : "worker";
  task.branch = branchName(line, agent, task);
  task.commit = sha(ctx).slice(0, 12);
  line.commits.unshift({
    sha: task.commit,
    branch: task.branch,
    message: task.stageId + ": " + task.name,
    stageId: task.stageId,
    taskId: task.id,
    author: agent,
    reviewer: task.reviewer ? task.reviewer.name : null,
    time: ctx.now,
    merged: true,
  });
  line.artifacts.push({ name: task.artifact, stageId: task.stageId, taskId: task.id });
  const worker = task.assignee && state.employees.find((e) => e.id === task.assignee.id);
  if (worker) worker.stats.tasksDone += 1;
  state.counters.tasksDone += 1;
  addLog(state, ctx, "COMMIT", line.title + " · " + task.commit.slice(0, 7) + " " + task.branch + " → main", line.id);
  message(line, ctx, "result", agent, line.leader.name, task.name + " 완료 · " + task.artifact, task.id);
}

function finishWork(state, line, stage, task, ctx) {
  if (task.kind === "coding" && task.status === "in_progress") {
    // Coding work always passes through a reviewer diff check and tests before merge.
    const review = { kind: "debugging", difficulty: 2, critical: false, role: "Technical Director", name: "diff 리뷰: " + task.name, stageId: task.stageId };
    const reviewer = dispatch(state, review, ctx, line);
    task.status = "review";
    task.reviewer = reviewer ? { id: reviewer.employee.id, name: reviewer.employee.name } : null;
    task.qa = "tests_passed";
    addLog(state, ctx, "REVIEW", line.title + " · " + task.name + " diff 리뷰 → " + (reviewer ? reviewer.employee.name : "대기"), line.id);
    message(line, ctx, "review_request", task.assignee ? task.assignee.name : "worker", task.reviewer ? task.reviewer.name : "reviewer", "diff 검토 요청", task.id);
    return;
  }
  if ((task.kind === "qa" || task.kind === "vision") && !task.repairOf && ctx.rng() < (state.settings.qaFailRate || 0)) {
    task.qa = "failed";
    completeTask(state, line, stage, task, ctx);
    addLog(state, ctx, "QA FAIL", line.title + " · " + task.name + " 실패 → 자동 수정 루프", line.id);
    spawnRepair(stage, task, line, ctx);
    return;
  }
  if (task.kind === "qa" || task.kind === "vision") task.qa = "passed";
  completeTask(state, line, stage, task, ctx);
}

function refreshReadiness(stage, line, ctx) {
  const done = new Set(stage.tasks.filter((t) => t.status === "completed").map((t) => t.id));
  for (const t of stage.tasks) {
    if (t.status === "pending" && t.depends.every((d) => done.has(d))) {
      t.status = "ready";
      if (t.depends.length) message(line, ctx, "dependency_ready", line.leader.name, t.role, t.name + " 선행작업 완료", t.id);
    }
  }
}

function completeStage(state, line, def, stage, ctx) {
  stage.status = "completed";
  stage.completedAt = ctx.now;
  const failedThenFixed = stage.tasks.filter((t) => t.qa === "failed").length;
  stage.qa = {
    status: "passed",
    checks: [
      { id: "tasks_complete", ok: true },
      { id: "all_commits_reviewed", ok: stage.tasks.filter((t) => t.kind === "coding").every((t) => t.reviewer) },
      { id: "repairs_resolved", ok: true, detail: failedThenFixed + " repaired" },
    ],
  };
  addLog(state, ctx, "STAGE COMPLETE", line.title + " · " + def.name + " 통과", line.id);

  if (def.build) {
    const build = makeBuild(line, def, ctx);
    line.builds.unshift(build);
    addLog(state, ctx, "BUILD", line.title + " v" + build.version + " · smoke " + (build.smoke.passed ? "통과" : "실패"), line.id);
    if (def.id === "vertical" || def.ceo_gate) queueReview(state, line, build, def, ctx);
  }

  if (def.ceo_gate) {
    line.status = "awaiting_ceo";
    line.leader.state = "gate";
    line.leader.lastDecision = "릴리즈 빌드 CEO 승인 대기";
    return;
  }
  advanceStage(state, line, ctx);
}

function advanceStage(state, line, ctx) {
  if (line.stageIndex >= ctx.studio.stages.length - 1) {
    line.status = "complete";
    line.leader.state = "idle";
    line.leader.lastDecision = "Live Ops 계획 수립 완료";
    addLog(state, ctx, "LINE COMPLETE", line.title + " · 전 공정 완료", line.id);
    return;
  }
  line.stageIndex += 1;
}

export function makeBuild(line, def, ctx) {
  const html = buildGame({ title: line.title, topicName: line.topic, gameType: line.gameType, family: line.family });
  return {
    id: uid(ctx, "build"),
    version: def.build,
    stageId: def.id,
    createdAt: ctx.now,
    status: "playable",
    platform: "web",
    smoke: smokeTest(html),
    bytes: html.length,
  };
}

function queueReview(state, line, build, def, ctx) {
  const blocking = !!def.ceo_gate;
  state.reviews.unshift({
    id: uid(ctx, "review"),
    lineId: line.id,
    buildId: build.id,
    title: line.title,
    version: build.version,
    stageId: def.id,
    kind: blocking ? "release_candidate" : "milestone",
    blocking,
    status: "pending",
    qa: build.smoke,
    createdAt: ctx.now,
  });
  addLog(state, ctx, "CEO REVIEW", line.title + " v" + build.version + " " + (blocking ? "출시 승인 요청" : "마일스톤 빌드 검토 가능"), line.id);
}

export function lineProgress(line, ctx) {
  const total = ctx.studio.stages.length;
  if (line.status === "complete") return 100;
  const def = ctx.studio.stages[line.stageIndex];
  const stage = line.stages[def.id];
  const frac = stage ? stage.tasks.filter((t) => t.status === "completed").length / Math.max(1, stage.tasks.length) : 0;
  return Math.round(((line.stageIndex + frac) / total) * 100);
}

// One Leader Agent step for a line.
export function tickLine(state, line, ctx) {
  if (line.status !== "running") return;
  const def = currentStageDef(line, ctx);
  let stage = line.stages[def.id];
  if (!stage || stage.status === "completed") stage = instantiateStage(line, def, ctx);

  // 1. Workers progress; finished work goes to review/merge.
  for (const task of stage.tasks) {
    if (task.status === "review") {
      completeTask(state, line, stage, task, ctx);
    } else if (task.status === "in_progress") {
      task.remaining -= 1;
      if (task.remaining <= 0) finishWork(state, line, stage, task, ctx);
    }
  }

  refreshReadiness(stage, line, ctx);

  // 2. Assign ready/blocked tasks while worker slots are free.
  const busy = stage.tasks.filter((t) => t.status === "in_progress" || t.status === "review").length;
  let slots = Math.max(0, (state.settings.workersPerLine || 3) - busy);
  for (const task of stage.tasks) {
    if (slots <= 0) break;
    if (task.status !== "ready" && task.status !== "blocked") continue;
    const assigned = dispatch(state, task, ctx, line) || substituteIfUnroutable(state, task, ctx, line);
    if (!assigned) {
      if (task.status !== "blocked") {
        task.status = "blocked";
        addLog(state, ctx, "BLOCKED", line.title + " · " + task.name + " 배정 가능한 AI 없음", line.id);
        message(line, ctx, "blocked", line.leader.name, "Router", task.name + " 배정 불가 · 재시도 대기", task.id);
      }
      continue;
    }
    task.status = "in_progress";
    task.attempts += 1;
    task.startedAt = ctx.now;
    task.remaining = task.difficulty >= 3 ? 2 : task.difficulty;
    task.assignee = { id: assigned.employee.id, name: assigned.employee.name, model: assigned.employee.model };
    message(line, ctx, "task_started", line.leader.name, assigned.employee.name, task.role + " · " + task.name, task.id);
    slots -= 1;
  }

  const blocked = stage.tasks.filter((t) => t.status === "blocked").length;
  const active = stage.tasks.filter((t) => t.status === "in_progress" || t.status === "review").length;
  line.leader.state = blocked ? "waiting" : active ? "dispatching" : "planning";
  line.leader.lastDecision = def.name + " · 진행 " + active + " · 대기 " + blocked + " · 완료 " + stage.tasks.filter((t) => t.status === "completed").length + "/" + stage.tasks.length;

  // 3. Stage gate.
  if (stage.tasks.every((t) => t.status === "completed")) completeStage(state, line, def, stage, ctx);
}

export function resetQuotaWindows(state, ctx) {
  for (const e of state.employees) {
    if (e.quota.resetAt && ctx.now >= e.quota.resetAt) {
      const wasReserve = atReserve(e);
      e.quota.used = 0;
      e.quota.resetAt = nextReset(e.quota.window, ctx.now);
      if (wasReserve) addLog(state, ctx, "QUOTA RESET", e.name + " 사용량 복구 → 다시 배정 가능");
    }
    if (e.cooldownUntil && ctx.now >= e.cooldownUntil) e.cooldownUntil = 0;
  }
}

export function tickFactory(state, ctx) {
  resetQuotaWindows(state, ctx);
  for (const line of state.lines) {
    if (line.status === "running" && line.autopilot) tickLine(state, line, ctx);
  }
}

// Runs a line until it stops (gate, completion) or the guard trips.
export function fastForward(state, line, ctx, guard = 400) {
  while (line.status === "running" && guard-- > 0) {
    ctx.now += 2000;
    resetQuotaWindows(state, ctx);
    tickLine(state, line, ctx);
  }
}

// ---------- CEO actions ----------

export function startBacklogIdea(state, ideaId, ctx) {
  const idea = state.ideas.find((i) => i.id === ideaId);
  if (!idea || idea.status === "in_production") return { ok: false, reason: "not_found" };
  const running = state.lines.filter((l) => l.status === "running").length;
  if (running >= state.settings.maxParallel) return { ok: false, reason: "capacity" };
  const line = createLine(state, idea, ctx, false);
  return { ok: !!line, line };
}

export function addFeedback(state, lineId, text, ctx) {
  const line = state.lines.find((l) => l.id === lineId);
  text = String(text || "").trim();
  if (!line || !text) return null;
  const item = { id: uid(ctx, "fb"), text, time: ctx.now, stageId: null, taskId: null, status: "queued" };
  line.feedback.unshift(item);

  if (line.status === "complete" || line.status === "awaiting_ceo") {
    reopenAt(line, "polish", ctx);
  }
  const def = currentStageDef(line, ctx);
  let stage = line.stages[def.id];
  if (!stage || stage.status === "completed") stage = instantiateStage(line, def, ctx);
  const task = {
    id: "ceo-" + (line.feedback.length), stageId: def.id, name: "CEO 수정 반영: " + text.slice(0, 40), role: "Gameplay Programmer",
    kind: "coding", difficulty: 2, critical: true, depends: [], artifact: "ceo-revision-" + line.feedback.length + ".patch",
    status: "ready", attempts: 0, assignee: null, reviewer: null, branch: null, commit: null, qa: null, quotaUsed: 0, remaining: 0, repairOf: null,
  };
  stage.tasks.push(task);
  item.stageId = def.id;
  item.taskId = task.id;
  item.status = "scheduled";
  if (line.status === "paused") line.status = "running";
  addLog(state, ctx, "CEO FEEDBACK", line.title + " · " + text + " → " + def.name + " task로 편성", line.id);
  message(line, ctx, "question", "CEO", line.leader.name, text, task.id);
  return item;
}

function reopenAt(line, stageId, ctx) {
  const idx = ctx.studio.stages.findIndex((s) => s.id === stageId);
  line.stageIndex = idx;
  for (let i = idx; i < ctx.studio.stages.length; i++) delete line.stages[ctx.studio.stages[i].id];
  line.status = "running";
  line.autopilot = true;
}

export function approveReview(state, reviewId, ctx) {
  const review = state.reviews.find((r) => r.id === reviewId);
  if (!review || review.status !== "pending") return;
  review.status = "approved";
  review.reviewedAt = ctx.now;
  const line = state.lines.find((l) => l.id === review.lineId);
  addLog(state, ctx, "CEO APPROVED", review.title + " v" + review.version + " 승인", review.lineId);
  if (line && review.blocking && line.status === "awaiting_ceo") {
    line.status = "running";
    advanceStage(state, line, ctx);
  }
}

export function requestRevision(state, reviewId, note, ctx) {
  const review = state.reviews.find((r) => r.id === reviewId);
  note = String(note || "").trim();
  if (!review || !note) return;
  review.status = "revision_requested";
  review.reviewedAt = ctx.now;
  review.note = note;
  addFeedback(state, review.lineId, note, ctx);
}

export function setLineStatus(state, lineId, action, ctx) {
  const line = state.lines.find((l) => l.id === lineId);
  if (!line) return { ok: false };
  if (action === "pause" && line.status === "running") line.autopilot = false;
  if (action === "resume") {
    if (line.status === "paused") {
      const running = state.lines.filter((l) => l.status === "running").length;
      if (running >= state.settings.maxParallel) return { ok: false, reason: "capacity" };
      line.status = "running";
    }
    line.autopilot = true;
  }
  if (action === "stop" && (line.status === "running" || line.status === "paused")) {
    line.status = "paused";
    line.autopilot = false;
  }
  addLog(state, ctx, "LINE " + action.toUpperCase(), line.title, line.id);
  return { ok: true };
}

export function activeWorkers(state) {
  const out = [];
  for (const line of state.lines) {
    for (const stage of Object.values(line.stages)) {
      for (const t of stage.tasks) {
        if ((t.status === "in_progress" || t.status === "review") && t.assignee) out.push({ line, task: t });
      }
    }
  }
  return out;
}

export function quotaSummary(employee) {
  const r = remaining(employee);
  return { remaining: r, unlimited: r === Infinity };
}
