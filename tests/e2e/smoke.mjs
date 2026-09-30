// Browser smoke test for the GitHub Pages console: drives the whole CEO flow in Chromium.
// Usage: node tests/e2e/smoke.mjs [--shots <dir>]
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { chromium } from "playwright";

const docs = normalize(new URL("../../docs/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const shotsArg = process.argv.indexOf("--shots");
const shots = shotsArg > -1 ? process.argv[shotsArg + 1] : null;
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };

const server = createServer(async (req, res) => {
  const path = decodeURIComponent(new URL(req.url, "http://x").pathname);
  const file = normalize(join(docs, path.endsWith("/") ? path + "index.html" : path));
  if (!file.startsWith(docs)) { res.writeHead(403).end(); return; }
  try {
    res.writeHead(200, { "Content-Type": TYPES[extname(file)] || "application/octet-stream" }).end(await readFile(file));
  } catch {
    res.writeHead(404).end();
  }
}).listen(0);
const url = "http://127.0.0.1:" + server.address().port + "/";

const errors = [];
const browser = await chromium.launch();
const failures = [];
const check = (cond, msg) => { if (!cond) failures.push(msg); };

let page = null;
let lastLabel = "";

async function run(viewport, label) {
  lastLabel = label;
  page = await browser.newPage({ viewport });
  page.on("pageerror", (e) => errors.push(label + " pageerror: " + e.message));
  page.on("console", (m) => { if (m.type() === "error") errors.push(label + " console: " + m.text()); });
  await page.goto(url);
  // Google login needs a server: without one it must not silently fall back to guest mode
  await page.getByRole("button", { name: /Google 계정으로 로그인/ }).click();
  check(await page.getByText("계정 로그인에는 AI Factory 서버가 필요합니다").isVisible(), label + ": Google login without a server must explain, not fake a login");
  await page.getByRole("button", { name: /게스트로 둘러보기/ }).click();
  check(await page.getByText("게스트 · 계정 없음").isVisible(), label + ": guest mode must be labelled");
  await page.locator("#topicForm input[name=topic]").fill("홀덤");
  await page.getByRole("button", { name: "AI 공장 가동" }).click();
  await page.waitForSelector(".floorRow");
  check((await page.locator(".floorRow").count()) === 3, label + ": expected 3 production lines");
  await page.waitForTimeout(3500);
  if (shots) await page.screenshot({ path: join(shots, label + "-dashboard.png"), fullPage: true });

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  check(overflow <= 1, label + ": horizontal overflow " + overflow + "px on dashboard");

  await page.locator(".nav").getByRole("button", { name: "아이디어" }).click();
  check((await page.locator(".idea").count()) === 10, label + ": expected 10 idea cards");

  await page.locator(".nav").getByRole("button", { name: /생산라인/ }).click();
  await page.waitForSelector(".depGraph");
  await page.getByRole("button", { name: "다음 게이트까지 즉시 실행" }).click();
  await page.waitForSelector("text=CEO 승인 대기");
  if (shots) await page.screenshot({ path: join(shots, label + "-line.png"), fullPage: true });

  await page.locator(".nav").getByRole("button", { name: /CEO Review/ }).click();
  await page.waitForSelector(".reviewCard iframe");
  if (shots) await page.screenshot({ path: join(shots, label + "-review.png"), fullPage: true });
  await page.getByRole("button", { name: "승인" }).first().click();

  await page.getByRole("button", { name: "게임 테스트 실행" }).first().click();
  await page.waitForSelector("#modalRoot iframe");
  await page.getByRole("button", { name: "닫기" }).click();

  await page.locator(".nav").getByRole("button", { name: "AI 마켓" }).click();
  await page.getByRole("tab", { name: /^무료/ }).click();
  await page.locator('[data-action="connect"][data-id="mistral"]').click();
  check(await page.locator('input[name="api_key"]').isDisabled(), label + ": API key input must be disabled in preview mode");
  await page.getByRole("button", { name: "가짜(시뮬레이션)로 추가" }).click();

  await page.locator(".nav").getByRole("button", { name: /AI 사원/ }).click();
  check((await page.locator(".employee").count()) >= 2, label + ": hired employee should appear");
  check(await page.getByText("실제 연결 AI 0명").isVisible(), label + ": preview must report zero real AIs");
  check((await page.locator(".employee .pill.fake").count()) === (await page.locator(".employee").count()), label + ": every preview employee is marked fake");
  await page.locator('[data-action="emp-drain"][data-id="mistral"]').click();
  if (shots) await page.screenshot({ path: join(shots, label + "-team.png"), fullPage: true });

  await page.locator(".nav").getByRole("button", { name: "로그" }).click();
  check((await page.locator(".logList li").count()) > 10, label + ": logs should be populated");
  await page.locator(".nav").getByRole("button", { name: "설정" }).click();
  await page.locator(".nav").getByRole("button", { name: "결과물" }).click();
  check((await page.locator(".result").count()) >= 1, label + ": completed build should appear in results");

  const stored = await page.evaluate(() => JSON.stringify(localStorage));
  check(!/api[_-]?key"\s*:\s*"[^"]/i.test(stored), label + ": localStorage must not hold API keys");
  await page.close();
}

try {
  await run({ width: 1440, height: 900 }, "desktop");
  await run({ width: 390, height: 844 }, "mobile");
} catch (err) {
  failures.push(lastLabel + " step failed: " + err.message.split("\n").slice(0, 3).join(" | "));
  if (shots && page) await page.screenshot({ path: join(shots, lastLabel + "-failure.png"), fullPage: true });
} finally {
  await browser.close();
  server.close();
}

const all = failures.concat(errors);
if (all.length) {
  console.error("SMOKE FAILED\n" + all.join("\n"));
  process.exit(1);
}
console.log("smoke OK (desktop + mobile)");
