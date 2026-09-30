import test from "node:test";
import assert from "node:assert/strict";
import {
  createState, createProject, fastForward, approveReview, addFeedback, startBacklogIdea,
  employeeFromCatalog, tickFactory, requestRevision,
} from "../../docs/js/engine.js";
import { makeCtx, providers } from "./helpers.mjs";

function factory(seed = 7, settings = {}) {
  const ctx = makeCtx(seed);
  const state = createState(ctx);
  Object.assign(state.settings, settings);
  for (const id of ["cerebras", "gemini", "groq", "cloudflare"]) {
    state.employees.push(employeeFromCatalog(providers.find((p) => p.id === id), ctx));
  }
  return { ctx, state };
}

test("topic creates ten scored ideas, a shortlist of lines and a backlog", () => {
  const { ctx, state } = factory();
  createProject(state, { topic: "홀덤" }, ctx);
  assert.equal(state.ideas.length, 10);
  assert.equal(state.lines.length, 3);
  assert.equal(state.ideas.filter((i) => i.status === "backlog").length, 7);
  const scores = state.ideas.map((i) => i.score);
  assert.deepEqual(scores, scores.slice().sort((a, b) => b - a));
  assert.ok(state.ideas.every((i) => i.reviews.length === 4));
  assert.equal(state.lines[0].stages.brief.status, "completed");
});

test("same topic produces the same idea portfolio", () => {
  const a = factory(1), b = factory(2);
  createProject(a.state, { topic: "좀비" }, a.ctx);
  createProject(b.state, { topic: "좀비" }, b.ctx);
  assert.deepEqual(a.state.ideas.map((i) => i.type), b.state.ideas.map((i) => i.type));
});

test("a line runs every stage, stops at the CEO release gate, then finishes live ops", () => {
  const { ctx, state } = factory();
  createProject(state, { topic: "타이핑" }, ctx);
  const line = state.lines[0];
  fastForward(state, line, ctx);
  assert.equal(line.status, "awaiting_ceo");
  assert.deepEqual(line.builds.map((b) => b.version), ["1.0.0", "0.9.0", "0.8.0", "0.5.0", "0.1.0"]);
  assert.ok(line.builds.every((b) => b.smoke.passed));
  const gate = state.reviews.find((r) => r.lineId === line.id && r.blocking);
  assert.ok(gate);
  approveReview(state, gate.id, ctx);
  fastForward(state, line, ctx);
  assert.equal(line.status, "complete");
  for (const commit of line.commits) {
    assert.match(commit.branch, /^ai-factory\/[^/]+\/[^/]+\/[^/]+\/[a-z]+-[\w-]+$/);
  }
  for (const stage of Object.values(line.stages)) {
    for (const task of stage.tasks) if (task.kind === "coding" && !stage.inherited) assert.ok(task.reviewer, task.name);
  }
});

test("provider failures fail over and never stop the line", () => {
  const { ctx, state } = factory(3, { failureRate: 0.9 });
  createProject(state, { topic: "카지노 운영" }, ctx);
  const line = state.lines[0];
  fastForward(state, line, ctx);
  assert.equal(line.status, "awaiting_ceo");
  assert.ok(state.counters.failovers > 0);
  assert.ok(state.logs.some((l) => l.type === "FAILOVER"));
});

test("scarce quota hits reserve, triggers a warning and non-critical work moves elsewhere", () => {
  const { ctx, state } = factory(4, { failureRate: 0 });
  const gemini = state.employees.find((e) => e.id === "gemini");
  gemini.quota.limit = 10;
  createProject(state, { topic: "홀덤" }, ctx);
  for (const line of state.lines) fastForward(state, line, ctx);
  assert.ok(state.logs.some((l) => l.type === "QUOTA WARNING"));
  assert.ok(gemini.quota.used <= gemini.quota.limit);
});

test("QA failures create repair and retest tasks and still converge", () => {
  const { ctx, state } = factory(5, { qaFailRate: 1 });
  createProject(state, { topic: "좀비" }, ctx);
  const line = state.lines[0];
  fastForward(state, line, ctx);
  assert.equal(line.status, "awaiting_ceo");
  const repairs = Object.values(line.stages).flatMap((s) => s.tasks).filter((t) => t.repairOf);
  assert.ok(repairs.length > 0);
});

test("CEO feedback becomes a task and a revision reopens polish", () => {
  const { ctx, state } = factory();
  createProject(state, { topic: "홀덤" }, ctx);
  const line = state.lines[0];
  const fb = addFeedback(state, line.id, "난이도를 낮춰줘", ctx);
  assert.equal(fb.status, "scheduled");
  assert.ok(line.stages[fb.stageId].tasks.some((t) => t.id === fb.taskId));
  fastForward(state, line, ctx);
  const gate = state.reviews.find((r) => r.lineId === line.id && r.blocking);
  requestRevision(state, gate.id, "색을 더 밝게", ctx);
  assert.equal(line.status, "running");
  assert.equal(ctx.studio.stages[line.stageIndex].id, "polish");
  fastForward(state, line, ctx);
  assert.equal(line.status, "awaiting_ceo");
});

test("backlog idea opens a new line and respects parallel capacity", () => {
  const { ctx, state } = factory();
  createProject(state, { topic: "홀덤" }, ctx);
  const backlog = state.ideas.filter((i) => i.status === "backlog");
  assert.equal(startBacklogIdea(state, backlog[0].id, ctx).reason, "capacity");
  state.settings.maxParallel = 4;
  assert.equal(startBacklogIdea(state, backlog[0].id, ctx).ok, true);
  assert.equal(state.lines.length, 4);
});

test("all external AIs unavailable keeps the factory alive on the local worker", () => {
  const { ctx, state } = factory(9, { failureRate: 0 });
  state.employees = state.employees.filter((e) => e.id !== "local-llamacpp");
  for (const e of state.employees) e.status = "auth_required";
  createProject(state, { topic: "좀비" }, ctx);
  tickFactory(state, ctx);
  assert.ok(state.employees.some((e) => e.id === "local-llamacpp"));
  assert.ok(state.logs.some((l) => l.type === "AUTO HIRE"));
});

test("a team without vision AI substitutes text QA instead of blocking", () => {
  const ctx = makeCtx(11);
  const state = createState(ctx); // local worker only
  createProject(state, { topic: "홀덤" }, ctx);
  const line = state.lines[0];
  fastForward(state, line, ctx);
  assert.equal(line.status, "awaiting_ceo");
  assert.ok(state.logs.some((l) => l.type === "SUBSTITUTE"));
  assert.equal(line.stages.vertical.tasks.find((t) => t.id === "visualqa").substituted, "vision");
});
