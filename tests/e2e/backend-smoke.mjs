// End-to-end: web console in backend mode against a real FastAPI server (server Leader + git).
// Usage: node tests/e2e/backend-smoke.mjs [--shots <dir>]
// Uses $AI_FACTORY_PYTHON (default: backend/.venv python, else "python").
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright";

const backend = new URL("../../backend/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const venv = join(backend, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const python = process.env.AI_FACTORY_PYTHON || (existsSync(venv) ? venv : "python");
const shotsArg = process.argv.indexOf("--shots");
const shots = shotsArg > -1 ? process.argv[shotsArg + 1] : null;
const port = 18000 + Math.floor(Math.random() * 1000);
const origin = "http://127.0.0.1:" + port;
const data = mkdtempSync(join(tmpdir(), "aif-"));

const server = spawn(python, ["-m", "uvicorn", "app.main:app", "--port", String(port), "--log-level", "warning"], {
  cwd: backend,
  env: {
    ...process.env,
    AI_FACTORY_DEV_LOGIN: "1",
    AI_FACTORY_COOKIE_SECURE: "false",
    AI_FACTORY_DB: join(data, "db.sqlite3"),
    AI_FACTORY_WORKSPACE: join(data, "ws"),
    AI_FACTORY_AUTOPILOT_SECONDS: "1",
    AI_FACTORY_ALLOWED_ORIGINS: origin,
    AI_FACTORY_VAULT_KEY: "NDJkZWFkYmVlZmNhZmViYWJlNDJkZWFkYmVlZmNhZmU=",
  },
  stdio: ["ignore", "inherit", "inherit"],
});

async function waitForServer() {
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(origin + "/health")).ok) return; } catch { /* starting */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("backend did not start");
}

const failures = [];
const check = (cond, msg) => { if (!cond) failures.push(msg); };
let browser;
try {
  await waitForServer();
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.on("pageerror", (e) => failures.push("pageerror: " + e.message));
  page.on("dialog", (d) => (d.type() === "prompt" ? d.accept("ceo@localhost") : d.accept()));
  await page.goto(origin + "/console/");
  // real account flow: sign up with email + password
  await page.getByRole("button", { name: "회원가입" }).click();
  await page.locator('input[name="email"]').fill("ceo@localhost.dev");
  await page.locator('input[name="password"]').fill("factory-pass-123");
  await page.getByRole("button", { name: "계정 만들기" }).click();
  await page.waitForSelector(".sidebarFoot >> text=Backend 연결");

  await page.locator("#topicForm input[name=topic]").fill("좀비");
  await page.getByRole("button", { name: "AI 공장 가동" }).click();
  await page.waitForSelector(".floorRow");
  check((await page.locator(".floorRow").count()) === 3, "expected 3 server production lines");
  await page.waitForFunction(() => document.querySelectorAll(".eventList .t-commit").length > 0, null, { timeout: 30000 });
  if (shots) await page.screenshot({ path: join(shots, "backend-dashboard.png"), fullPage: true });

  await page.locator(".nav").getByRole("button", { name: /AI 사원/ }).click();
  check(await page.getByText("실제 연결 AI 0명").isVisible(), "team view must say no real AI is connected");
  check((await page.locator(".pill.fake").count()) >= 1, "the placeholder worker must carry the fake badge");

  await page.locator(".nav").getByRole("button", { name: /생산라인/ }).click();
  await page.getByRole("button", { name: "다음 게이트까지 즉시 실행" }).click();
  await page.waitForSelector("text=CEO 승인 대기", { timeout: 420000 });
  check((await page.locator(".commitList li").count()) > 10, "server commits should be listed");
  check((await page.locator(".commitList small", { hasText: "ai-factory/" }).count()) > 0, "branch names should follow ai-factory/<project>/<line>/<agent>/<task>");
  if (shots) await page.screenshot({ path: join(shots, "backend-line.png"), fullPage: true });

  await page.locator(".nav").getByRole("button", { name: /CEO Review/ }).click();
  await page.getByRole("button", { name: "게임 테스트 실행" }).first().click();
  const frame = page.locator("#modalRoot iframe");
  check((await frame.getAttribute("src")).includes("/builds/"), "backend build should be played from the sandboxed endpoint");
  await page.getByRole("button", { name: "닫기" }).click();
  await page.locator(".reviewCard", { hasText: "승인 필요" }).first().getByRole("button", { name: "승인" }).click();
  await page.waitForTimeout(800);
  const after = await page.evaluate(async (o) => (await fetch(o + "/state", { credentials: "include" })).json(), origin);
  check(after.lines.some((l) => l.stage === "live" && l.status !== "awaiting_ceo"), "approved release must leave the CEO gate (no awaiting_ceo at live)");

  await page.locator(".accountChip").click();
  await page.waitForSelector("text=내 사용 현황");
  check(await page.getByText("ceo@localhost.dev").first().isVisible(), "account page shows the signed-in email");
  check(await page.getByText("이메일·비밀번호").isVisible(), "sign-in method is email + password");
  check(await page.getByText("미연결").first().isVisible(), "personal GitHub starts disconnected");
  if (shots) await page.screenshot({ path: join(shots, "backend-account.png"), fullPage: true });
  await page.locator(".nav").getByRole("button", { name: "로그" }).click();
  check((await page.locator(".logList li").count()) > 10, "server logs should be listed");
  // delete an unneeded line on the server
  await page.locator(".nav").getByRole("button", { name: /생산라인/ }).click();
  const linesBefore = await page.locator(".lineItem").count();
  await page.getByRole("button", { name: "라인 삭제" }).click();
  await page.waitForFunction((n) => document.querySelectorAll(".lineItem").length === n - 1, linesBefore, { timeout: 30000 });
  await page.locator(".accountChip").click();
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await page.waitForSelector('form[data-form="password-login"]');
  // sign back in with the password
  await page.locator('input[name="email"]').fill("ceo@localhost.dev");
  await page.locator('input[name="password"]').fill("factory-pass-123");
  await page.locator('form[data-form="password-login"] button').click();
  await page.waitForSelector(".sidebarFoot >> text=Backend 연결");
} catch (err) {
  failures.push("step failed: " + err.message.split("\n").slice(0, 3).join(" | "));
  try {
    const page = browser && browser.contexts()[0] && browser.contexts()[0].pages()[0];
    if (page) {
      const snap = await page.evaluate(async (o) => (await fetch(o + "/state", { credentials: "include" })).json(), origin);
      failures.push("lines: " + snap.lines.map((l) => l.title + "=" + l.status + "@" + l.stage).join(", "));
      failures.push("logs: " + snap.logs.slice(0, 8).map((l) => l.type + " " + l.text.slice(0, 90)).join(" || "));
    }
  } catch { /* diagnostics only */ }
} finally {
  if (browser) await browser.close();
  server.kill();
}

if (failures.length) {
  console.error("BACKEND SMOKE FAILED\n" + failures.join("\n"));
  process.exit(1);
}
console.log("backend smoke OK");
