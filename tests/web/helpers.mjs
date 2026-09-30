import { readFileSync } from "node:fs";
import { createRng } from "../../docs/js/engine.js";

const read = (name) => JSON.parse(readFileSync(new URL("../../docs/catalog/" + name, import.meta.url), "utf8"));

export const studio = read("studio.json");
export const providers = read("providers.json").providers;

export function makeCtx(seed = 1, settings = {}) {
  return { studio, providers, now: Date.UTC(2026, 8, 30, 12), rng: createRng(seed), settings };
}
