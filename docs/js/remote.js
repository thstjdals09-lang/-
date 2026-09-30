// Backend mode: maps the server snapshot (GET /state) onto the state shape the views render.
// The server is authoritative; the browser keeps only per-viewer UI settings.

import { employeeFromCatalog } from "./engine.js";

export const SIM_EMPLOYEE_ID = "sim-local";

export function parseTs(value) {
  if (!value) return null;
  const ms = Date.parse(String(value).replace(" ", "T") + (/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? "" : "Z"));
  return Number.isNaN(ms) ? null : ms;
}

function employeeFromConnection(c, ctx) {
  const entry = ctx.providers.find((p) => p.id === c.catalog_id);
  if (!entry) return null;
  const e = employeeFromCatalog(entry, ctx, { authType: c.auth_type, credentialRef: c.credential_ref, connectionMode: "backend", endpoint: c.endpoint });
  e.id = c.id;
  e.model = c.model || e.model;
  e.status = c.status === "pending" ? "offline" : c.status;
  e.quota.unit = c.quota_unit || e.quota.unit;
  e.quota.limit = c.quota_limit ?? e.quota.limit;
  e.quota.used = c.quota_used || 0;
  e.quota.reserve = c.reserve ?? e.quota.reserve;
  e.quota.resetAt = parseTs(c.quota_reset_at);
  e.lastVerified = parseTs(c.last_verified);
  e.lastError = c.last_error;
  e.credentialFingerprint = c.credential_fingerprint;
  return e;
}

function simulatedEmployee(ctx) {
  const local = ctx.providers.find((p) => p.id === "local-llamacpp");
  const e = employeeFromCatalog(local, ctx);
  e.id = SIM_EMPLOYEE_ID;
  e.name = "가짜 시뮬레이션 워커";
  e.model = "AI 아님 · 서버 시뮬레이션";
  e.synthetic = true;
  return e;
}

function mapTask(t, stageId) {
  return {
    ...t,
    stageId,
    quotaUsed: 0,
    assignee: t.assignee ? { id: t.assignee.connectionId || SIM_EMPLOYEE_ID, name: t.assignee.name, model: "" } : null,
  };
}

function mapLine(l) {
  const stages = {};
  for (const [key, s] of Object.entries(l.stages)) {
    stages[key] = { status: s.status, qa: s.qa, startedAt: parseTs(s.startedAt), completedAt: parseTs(s.completedAt), quotaUsed: 0, inherited: !s.tasks.length && s.status === "completed", tasks: s.tasks.map((t) => mapTask(t, key)) };
  }
  return {
    id: l.id,
    projectId: l.projectId,
    ideaId: l.ideaId,
    title: l.title,
    topic: l.topic,
    gameType: l.gameType,
    family: l.family,
    stageIndex: l.stageIndex,
    status: l.status,
    autopilot: l.autopilot,
    leader: { name: "Leader · " + l.gameType, state: l.leader.state, lastDecision: l.leader.lastDecision || "" },
    stages,
    commits: l.commits.map((c) => ({ ...c, time: parseTs(c.time), merged: true })),
    artifacts: l.artifacts,
    builds: l.builds.map((b) => ({ ...b, createdAt: parseTs(b.createdAt), bytes: 0 })),
    publication: l.publication ? { ...l.publication, time: parseTs(l.publication.time) } : null,
    deployments: (l.deployments || []).map((d) => ({ ...d, time: parseTs(d.time) })),
    feedback: l.feedback.map((f) => ({ id: f.id, text: f.text, time: parseTs(f.created_at), stageId: f.stage_key, taskId: null, status: f.status })),
    messages: l.messages.map((m) => ({ ...m, time: parseTs(m.time) })),
    quotaUsed: 0,
  };
}

export function fromSnapshot(snap, prev, ctx) {
  const isSearch = (c) => (ctx.providers.find((p) => p.id === c.catalog_id) || {}).kind === "search";
  const employees = snap.connections.filter((c) => !isSearch(c)).map((c) => employeeFromConnection(c, ctx)).filter(Boolean);
  const searchTools = snap.connections.filter(isSearch).map((c) => {
    const entry = ctx.providers.find((p) => p.id === c.catalog_id);
    return { id: c.id, catalogId: c.catalog_id, name: entry.name, vendor: entry.vendor, status: c.status, used: c.quota_used || 0,
      limit: c.quota_limit, window: entry.quota.window, lastError: c.last_error, lastVerified: parseTs(c.last_verified) };
  });
  if (!employees.some((e) => e.status === "online")) employees.push(simulatedEmployee(ctx));
  return {
    ...prev,
    settings: {
      ...prev.settings,
      policy: snap.settings.policy,
      maxParallel: snap.settings.max_parallel,
      autoShortlist: snap.settings.auto_shortlist,
      workersPerLine: snap.settings.workers_per_line,
    },
    employees,
    searchTools,
    projects: snap.projects.map((p) => ({ id: p.id, topic: p.topic, genre: p.genre, platform: p.platform, notes: p.notes, createdAt: parseTs(p.created_at), portfolio: [],
      status: p.status || "ready", research: p.research || null })),
    ideas: snap.ideas.map((i) => ({ ...i, projectId: i.project_id })),
    lines: snap.lines.map(mapLine),
    reviews: snap.reviews.map((r) => ({
      id: r.id, lineId: r.line_id, buildId: r.build_id, title: r.title, version: r.version, stageId: r.stage_key,
      kind: r.kind, blocking: r.blocking, status: r.status, qa: r.smoke, createdAt: parseTs(r.created_at), note: r.note,
    })),
    logs: snap.logs.map((l) => ({ id: l.id, time: parseTs(l.created_at), type: l.type, text: l.text, lineId: l.line_id })),
    counters: snap.counters,
  };
}
