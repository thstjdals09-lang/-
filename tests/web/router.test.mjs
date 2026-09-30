import test from "node:test";
import assert from "node:assert/strict";
import { routeTask, classifyError, nextReset } from "../../docs/js/router.js";
import { employeeFromCatalog } from "../../docs/js/engine.js";
import { makeCtx, providers, studio } from "./helpers.mjs";

const ctx = makeCtx();
const hire = (...ids) => ids.map((id) => employeeFromCatalog(providers.find((p) => p.id === id), ctx));
const opts = { now: ctx.now, routing: studio.routing };
const pick = (task, team, extra = {}) => routeTask(task, team, { ...opts, ...extra }).ordered[0]?.employee.id;

test("simple work goes to the free local worker", () => {
  const team = hire("local-llamacpp", "cerebras", "gemini");
  assert.equal(pick({ kind: "coding", difficulty: 1 }, team), "local-llamacpp");
  assert.equal(pick({ kind: "qa", difficulty: 1 }, team), "local-llamacpp");
});

test("medium work uses abundant free quota before scarce request quota", () => {
  const team = hire("local-llamacpp", "cerebras", "gemini", "groq");
  assert.equal(pick({ kind: "coding", difficulty: 2 }, team), "cerebras");
  assert.equal(pick({ kind: "planning", difficulty: 2 }, team), "cerebras");
});

test("hard work picks the cheapest AI that meets the quality bar", () => {
  const team = hire("local-llamacpp", "cerebras", "gemini", "anthropic");
  assert.equal(pick({ kind: "planning", difficulty: 3 }, team), "gemini");
  const [local, , gemini, claude] = team;
  gemini.quota.used = gemini.quota.limit; // exhausted
  assert.equal(pick({ kind: "planning", difficulty: 3, critical: true }, [local, gemini, claude]), "anthropic");
});

test("reserve quota is kept for critical tasks only", () => {
  const [gemini] = hire("gemini");
  gemini.quota.used = gemini.quota.limit * 0.85; // 15% left, reserve 20%
  const d = routeTask({ kind: "vision", difficulty: 2 }, [gemini], opts);
  assert.equal(d.ordered.length, 0);
  assert.equal(d.rejected[0].reason, "reserve_protected");
  assert.equal(pick({ kind: "vision", difficulty: 2, critical: true }, [gemini]), "gemini");
});

test("design work skips the local worker that cannot meet quality", () => {
  const team = hire("local-llamacpp", "cloudflare", "gemini");
  assert.equal(pick({ kind: "design", difficulty: 1 }, team), "cloudflare");
});

test("failover chain continues past cooldown and degrades rather than stalling", () => {
  const team = hire("local-llamacpp", "cerebras");
  team[1].cooldownUntil = ctx.now + 1000;
  const d = routeTask({ kind: "coding", difficulty: 3 }, team, opts);
  assert.equal(d.degraded, true);
  assert.equal(d.ordered[0].employee.id, "local-llamacpp");
  assert.equal(d.rejected[0].reason, "cooldown");
});

test("error classifier maps provider failures", () => {
  assert.equal(classifyError({ status: 429 }).kind, "rate_limited");
  assert.equal(classifyError({ status: 401 }).kind, "auth_error");
  assert.equal(classifyError({ status: 503 }).kind, "transient");
  assert.equal(classifyError({ status: 413 }).kind, "context_exceeded");
});

test("quota windows reset at the next UTC boundary", () => {
  assert.equal(nextReset("day", Date.UTC(2026, 8, 30, 12)), Date.UTC(2026, 9, 1));
  assert.equal(nextReset("month", Date.UTC(2026, 11, 5)), Date.UTC(2027, 0, 1));
  assert.equal(nextReset(null, 0), null);
});
