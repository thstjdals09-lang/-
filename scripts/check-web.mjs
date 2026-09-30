// Syntax-checks every web module and validates the shared catalogs.
import { readdirSync, readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const jsDir = join(root, "docs", "js");
for (const file of readdirSync(jsDir).filter((f) => f.endsWith(".js"))) {
  execFileSync(process.execPath, ["--check", join(jsDir, file)], { stdio: "inherit" });
}

const providers = JSON.parse(readFileSync(join(root, "docs", "catalog", "providers.json"), "utf8"));
const studio = JSON.parse(readFileSync(join(root, "docs", "catalog", "studio.json"), "utf8"));
const problems = [];
const ids = new Set();
for (const p of providers.providers) {
  if (ids.has(p.id)) problems.push("duplicate provider " + p.id);
  ids.add(p.id);
  for (const key of ["name", "adapter", "auth_types", "categories", "skills", "quota", "cost_tier"]) {
    if (p[key] == null) problems.push(p.id + " missing " + key);
  }
  if (!("last_verified" in p)) problems.push(p.id + " missing last_verified");
}
if (studio.stages.length !== 13) problems.push("expected 13 studio stages, found " + studio.stages.length);
for (const stage of studio.stages) {
  const taskIds = new Set(stage.tasks.map((t) => t.id));
  for (const t of stage.tasks) {
    for (const d of t.depends) if (!taskIds.has(d)) problems.push(stage.id + "/" + t.id + " depends on unknown " + d);
    if (!studio.roles.includes(t.role)) problems.push(stage.id + "/" + t.id + " unknown role " + t.role);
  }
}
if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
console.log("web modules and catalogs OK (" + providers.providers.length + " providers, " + studio.stages.length + " stages)");
