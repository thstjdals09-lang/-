// AI Router — CHEAPEST_VIABLE_QUALITY and alternative policies.
// Pure functions only: the backend router (backend/app/router.py) mirrors these rules.

export const POLICIES = {
  cheapest_viable_quality: "최저비용 + 충분한 품질",
  quality: "품질 우선",
  speed: "속도 우선",
  free: "무료쿼터 최대 활용",
};

const DEFAULT_ROUTING = {
  required_quality: { 1: 55, 2: 72, 3: 85 },
  estimated_tokens: { 1: 2500, 2: 6000, 3: 12000 },
  scarce_request_limit: 500,
};

export function isUnlimited(employee) {
  return employee.quota.unit === "unlimited";
}

function hasKnownLimit(employee) {
  return !isUnlimited(employee) && typeof employee.quota.limit === "number" && employee.quota.limit > 0;
}

export function remaining(employee) {
  if (!hasKnownLimit(employee)) return Infinity;
  return Math.max(0, employee.quota.limit - employee.quota.used);
}

export function remainingRatio(employee) {
  if (!hasKnownLimit(employee)) return 1;
  return remaining(employee) / employee.quota.limit;
}

export function atReserve(employee) {
  if (!hasKnownLimit(employee)) return false;
  return remaining(employee) <= employee.quota.limit * (employee.quota.reserve || 0);
}

export function exhausted(employee) {
  return hasKnownLimit(employee) && remaining(employee) <= 0;
}

export function requiredQuality(task, routing = DEFAULT_ROUTING) {
  return routing.required_quality[task.difficulty] ?? 70;
}

// Usage a task will consume, expressed in the provider's quota unit.
export function usageFor(employee, task, routing = DEFAULT_ROUTING) {
  const tokens = routing.estimated_tokens[task.difficulty] ?? 5000;
  switch (employee.quota.unit) {
    case "tokens": return tokens;
    case "requests": return 1;
    case "neurons": return Math.ceil(tokens / 25);
    case "credits": return Math.round((tokens / 10000) * 100) / 100;
    default: return 0;
  }
}

export function capabilityFor(employee, kind) {
  if (kind === "image" || kind === "audio") {
    return (employee.modalities || []).includes(kind) ? employee.skills.design || 0 : 0;
  }
  return employee.skills[kind] || 0;
}

// Scarcity penalises spending rare quota (small request budgets, low remaining ratio) on easy work.
export function scarcity(employee, routing = DEFAULT_ROUTING) {
  if (!hasKnownLimit(employee)) return 0;
  const smallRequestBudget = employee.quota.unit === "requests" && employee.quota.limit <= routing.scarce_request_limit;
  return (smallRequestBudget ? 0.5 : 0) + (1 - remainingRatio(employee)) * 0.5;
}

// Returns null when the employee may take the task, otherwise the reason it is excluded.
export function exclusionReason(employee, task, now) {
  if (employee.status === "paused") return "paused";
  if (employee.status === "auth_required") return "auth_required";
  if (employee.status === "offline") return "offline";
  if (employee.cooldownUntil && employee.cooldownUntil > now) return "cooldown";
  if (exhausted(employee)) return "quota_exhausted";
  if (atReserve(employee) && !task.critical) return "reserve_protected";
  if (task.contextNeeded && employee.contextLength && task.contextNeeded > employee.contextLength) return "context_too_small";
  if (capabilityFor(employee, task.kind) <= 0) return "missing_capability";
  return null;
}

// How strongly scarce quota is protected: easy work almost never spends it, hard work ignores it.
const SCARCITY_WEIGHT = { 1: 100, 2: 40, 3: 0 };

function orderFor(policy, task) {
  const weight = SCARCITY_WEIGHT[task.difficulty] ?? 40;
  switch (policy) {
    case "quality":
      return (a, b) => b.capability - a.capability || b.reliability - a.reliability;
    case "speed":
      return (a, b) => b.speed - a.speed || b.capability - a.capability;
    case "free":
      return (a, b) => a.costTier - b.costTier || b.ratio - a.ratio || b.capability - a.capability;
    default:
      // cheapest viable: cheapest tier first; inside a tier keep scarce quota for hard work.
      return (a, b) => {
        if (a.costTier !== b.costTier) return a.costTier - b.costTier;
        const sa = a.capability - a.scarcity * weight;
        const sb = b.capability - b.scarcity * weight;
        return sb - sa || b.reliability - a.reliability;
      };
  }
}

/**
 * Rank every employee for a task.
 * @returns {{ordered: Array, rejected: Array, degraded: boolean, required: number}}
 * `ordered` is the failover chain: index 0 is the primary choice.
 */
export function routeTask(task, employees, { policy = "cheapest_viable_quality", now = Date.now(), routing = DEFAULT_ROUTING } = {}) {
  const required = requiredQuality(task, routing);
  const rejected = [];
  const eligible = [];

  for (const employee of employees) {
    const reason = exclusionReason(employee, task, now);
    if (reason) {
      rejected.push({ employee, reason });
      continue;
    }
    const capability = capabilityFor(employee, task.kind);
    eligible.push({
      employee,
      capability,
      viable: capability >= required,
      costTier: employee.costTier ?? 1,
      scarcity: scarcity(employee, routing),
      ratio: remainingRatio(employee),
      speed: employee.speed ?? 50,
      reliability: employee.reliability ?? 50,
    });
  }

  const viable = eligible.filter((c) => c.viable);
  let ordered;
  let degraded = false;
  if (viable.length) {
    const below = eligible.filter((c) => !c.viable).sort((a, b) => b.capability - a.capability);
    ordered = viable.sort(orderFor(policy, task)).concat(below);
    // Below-quality candidates are only a last-resort tail so the line never stops.
  } else {
    degraded = eligible.length > 0;
    ordered = eligible.sort((a, b) => b.capability - a.capability);
  }

  return { ordered, rejected, degraded, required };
}

// Maps a provider failure onto a routing action. Mirrors backend error_classifier.
export function classifyError({ status, code } = {}) {
  if (status === 429 || code === "rate_limited") return { kind: "rate_limited", retryable: true, cooldownMs: 45000 };
  if (status === 401 || status === 403 || code === "auth") return { kind: "auth_error", retryable: false, cooldownMs: 0 };
  if (status === 413 || code === "context_length_exceeded") return { kind: "context_exceeded", retryable: true, cooldownMs: 0 };
  if (status === 408 || (status >= 500 && status < 600) || code === "timeout") return { kind: "transient", retryable: true, cooldownMs: 10000 };
  return { kind: "unknown", retryable: true, cooldownMs: 5000 };
}

export function nextReset(window, now) {
  const d = new Date(now);
  if (window === "day") return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 1);
  if (window === "month") return Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1);
  return null;
}
