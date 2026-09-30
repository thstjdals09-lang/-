// Isolated runtime QA for a generated single-file HTML5 game.
// Usage: node runtime-qa.mjs <game.html> <screenshot.png>
// Runs in a fresh offline Chromium context: every network request is aborted, dialogs dismissed,
// no cookies or storage carried over. Prints one JSON object to stdout.
import { readFileSync } from "node:fs";
import { chromium } from "playwright";

const [htmlPath, shotPath] = process.argv.slice(2);
const html = readFileSync(htmlPath, "utf8");
const errors = [];
const network = [];
const checks = [];
const check = (id, ok, detail) => checks.push(detail === undefined ? { id, ok } : { id, ok, detail });

const browser = await chromium.launch({ args: ["--disable-extensions", "--disable-background-networking"] });
try {
  const context = await browser.newContext({ viewport: { width: 960, height: 640 }, offline: true, serviceWorkers: "block", acceptDownloads: false });
  context.on("request", (r) => { if (!/^(data|about|blob):/.test(r.url())) network.push(r.url().slice(0, 120)); });
  await context.route("**/*", (route) => route.abort());
  const page = await context.newPage();
  page.on("pageerror", (e) => errors.push(String(e.message).slice(0, 300)));
  page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text().slice(0, 300)); });
  page.on("dialog", (d) => d.dismiss().catch(() => {}));

  await page.setContent(html, { waitUntil: "load", timeout: 10000 });
  await page.waitForTimeout(600);
  const hasStart = await page.evaluate(() => typeof window.startGame === "function");
  check("start_function", hasStart);
  const before = await page.screenshot();
  if (hasStart) await page.evaluate(() => { window.startGame(); }).catch((e) => errors.push("startGame: " + String(e.message).slice(0, 200)));
  const button = page.locator("button:visible").first();
  if (await button.count()) await button.click({ timeout: 1000 }).catch(() => {});
  for (const key of ["ArrowRight", "ArrowUp", "Space", "Enter", "KeyD", "KeyW"]) {
    await page.keyboard.down(key);
    await page.waitForTimeout(90);
    await page.keyboard.up(key);
  }
  await page.mouse.click(480, 320);
  await page.waitForTimeout(1200);
  const after = await page.screenshot({ path: shotPath });

  const content = await page.evaluate(() => ({
    text: (document.body && document.body.innerText.trim().length) || 0,
    canvas: document.querySelectorAll("canvas").length,
  }));
  check("renders_content", content.text > 0 || content.canvas > 0, content);
  check("responds_to_input", !before.equals(after));
  check("no_runtime_errors", errors.length === 0, errors.length);
  check("no_network", network.length === 0, network.length);
} catch (err) {
  errors.push("runner: " + String(err.message).split("\n")[0].slice(0, 300));
  check("loads", false);
} finally {
  await browser.close();
}

// responds_to_input is informational: timer-driven games change without input and some
// turn-based games legitimately wait for a specific control.
const required = new Set(["start_function", "renders_content", "no_runtime_errors", "no_network", "loads"]);
const ok = checks.filter((c) => required.has(c.id)).every((c) => c.ok);
process.stdout.write(JSON.stringify({ ok, checks, errors: errors.slice(0, 10), network: network.slice(0, 5) }));
