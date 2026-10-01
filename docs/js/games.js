// Standalone HTML5 builds (games and other programs) rendered from the shared templates in docs/catalog/games/.
// The backend (backend/app/factory/games.py) renders the same templates with the same tokens.

export const FAMILIES = ["strategy", "action", "management", "app"]; // "app": programs that are not games
let templates = null;

export function setGameTemplates(map) {
  templates = map;
}

export async function loadGameTemplates(base = "./catalog/games/") {
  const entries = await Promise.all(FAMILIES.map(async (f) => [f, await fetch(base + f + ".html").then((r) => r.text())]));
  setGameTemplates(Object.fromEntries(entries));
}

// JSON literal safe to embed inside a <script> element.
function jsonForScript(value) {
  return JSON.stringify(String(value == null ? "" : value)).replace(/</g, "\\u003c");
}

export function gameFamily(type) {
  if (/Tycoon|Management/.test(type)) return "management";
  if (/Roguelike|Survivor|Extraction|Arcade/.test(type)) return "action";
  return "strategy";
}

// line: {title, topicName | topic, gameType, family}
export function buildGame(line) {
  const family = line.family || gameFamily(line.gameType || "");
  const tpl = templates && (templates[family] || templates.strategy);
  if (!tpl) throw new Error("game templates not loaded");
  return tpl
    .replace("{{TITLE_JSON}}", () => jsonForScript(line.title))
    .replace("{{TOPIC_JSON}}", () => jsonForScript(line.topicName || line.topic))
    .replace("{{TYPE_JSON}}", () => jsonForScript(line.gameType || family));
}

export function smokeTest(html) {
  const checks = [
    ["doctype", /<!doctype html>/i.test(html)],
    ["entry_point", html.indexOf("startGame") !== -1],
    ["factory_marker", html.indexOf('data-ai-factory-game="v2"') !== -1],
    ["no_external_scripts", !/<script[^>]+src=/i.test(html)],
    ["tokens_resolved", html.indexOf("{{") === -1],
  ];
  return { passed: checks.every((c) => c[1]), checks: checks.map(([id, ok]) => ({ id, ok })) };
}
