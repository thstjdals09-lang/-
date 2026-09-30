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
  await page.getByRole("button", { name: /Google로 계속하기/ }).click();
  await page.waitForSelector(".sidebarFoot >> text=Backend 연결");

  await page.locator("#topicForm input[name=topic]").fill("좀비");
  await page.getByRole("button", { name: "AI 공장 가동" }).click();
  await page.waitForSelector(".floorRow");
  check((await page.locator(".floorRow").count()) === 3, "expected 3 server production lines");
  await page.waitForFunction(() => document.querySelectorAll(".eventList .t-commit").length > 0, null, { timeout: 30000 });
  if (shots) await page.screenshot({ path: join(shots, "backend-dashboard.png"), fullPage: true });

  await page.locator(".nav").getByRole("button", { name: /AI 사원/ }).click();
  check(await page.getByText("Simulated Local Worker").isVisible(), "simulated worker should be shown when nothing is connected");

  await page.locator(".nav").getByRole("button", { name: /생산라인/ }).click();
  await page.getByRole("button", { name: "다음 게이트까지 즉시 실행" }).click();
  await page.waitForSelector("text=CEO 승인 대기", { timeout: 120000 });
  check((await page.locator(".commitList li").count()) > 10, "server commits should be listed");
  check((await page.locator(".commitList small", { hasText: "ai-factory/" }).count()) > 0, "branch names should follow ai-factory/<project>/<line>/<agent>/<task>");
  if (shots) await page.screenshot({ path: join(shots, "backend-line.png"), fullPage: true });

  await page.locator(".nav").getByRole("button", { name: /CEO Review/ }).click();
  await page.getByRole("button", { name: "게임 테스트 실행" }).first().click();
  const frame = page.locator("#modalRoot iframe");
  check((await frame.getAttribute("src")).includes("/builds/"), "backend build should be played from the sandboxed endpoint");
  await page.getByRole("button", { name: "닫기" }).click();
  await page.getByRole("button", { name: "승인" }).first().click();
  await page.waitForTimeout(500);

  await page.locator(".nav").getByRole("button", { name: "로그" }).click();
  check((await page.locator(".logList li").count()) > 10, "server logs should be listed");
  await page.getByRole("button", { name: "로그아웃" }).click();
  await page.waitForSelector("text=CEO 로그인");
} catch (err) {
  failures.push("step failed: " + err.message.split("\n").slice(0, 3).join(" | "));
} finally {
  if (browser) await browser.close();
  server.kill();
}

if (failures.length) {
  console.error("BACKEND SMOKE FAILED\n" + failures.join("\n"));
  process.exit(1);
}
console.log("backend smoke OK");
