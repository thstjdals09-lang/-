// AI Factory backend client. Session is an HttpOnly cookie set by the backend; this module never
// sees or stores provider secrets. API keys are sent once in a request body and discarded.

export class ApiError extends Error {
  constructor(status, detail) {
    super("backend " + status + (detail ? ": " + detail : ""));
    this.status = status;
    this.detail = detail;
  }
}

export function createApi(getBase) {
  const base = () => String(getBase() || "").replace(/\/+$/, "");

  async function req(path, { method = "GET", body, timeout = 8000 } = {}) {
    if (!base()) throw new ApiError(0, "backend_not_configured");
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeout);
    try {
      const res = await fetch(base() + path, {
        method,
        credentials: "include",
        signal: ctrl.signal,
        // The custom header forces a CORS preflight, so only allow-listed origins can mutate state.
        headers: { "Content-Type": "application/json", "X-AI-Factory": "1" },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!res.ok) {
        let detail = "";
        try { detail = (await res.json()).detail; } catch { /* non-JSON error */ }
        throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
      }
      return res.status === 204 ? null : await res.json();
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(0, err.name === "AbortError" ? "timeout" : "unreachable");
    } finally {
      clearTimeout(timer);
    }
  }

  return {
    configured: () => !!base(),
    health: () => req("/health", { timeout: 4000 }),
    me: () => req("/auth/me"),
    logout: () => req("/auth/logout", { method: "POST" }),
    register: (email, password, name) => req("/auth/register", { method: "POST", body: { email, password, name: name || null } }),
    passwordLogin: (email, password) => req("/auth/login", { method: "POST", body: { email, password } }),
    devLogin: (email) => req("/auth/dev-login", { method: "POST", body: { email, name: email.split("@")[0] } }),
    account: () => req("/account"),
    connectGithub: (token) => req("/account/github", { method: "PUT", body: { token }, timeout: 20000 }),
    disconnectGithub: () => req("/account/github", { method: "DELETE" }),
    logoutAll: () => req("/account/logout-all", { method: "POST" }),
    deleteAccount: (email) => req("/account", { method: "DELETE", body: { confirm_email: email } }),
    exportUrl: () => base() + "/account/export",
    loginUrl: (returnTo) => base() + "/auth/google/login?return_to=" + encodeURIComponent(returnTo),
    connectProvider: (payload) => req("/providers/connections", { method: "POST", body: payload, timeout: 20000 }),
    listConnections: () => req("/providers/connections"),
    verifyConnection: (id) => req("/providers/connections/" + encodeURIComponent(id) + "/verify", { method: "POST", timeout: 20000 }),
    deleteConnection: (id) => req("/providers/connections/" + encodeURIComponent(id), { method: "DELETE" }),
    state: () => req("/state", { timeout: 15000 }),
    patchSettings: (body) => req("/settings", { method: "PATCH", body }),
    createProject: (body) => req("/projects", { method: "POST", body }),
    buildIdea: (id) => req("/ideas/" + encodeURIComponent(id) + "/build", { method: "POST" }),
    tickLine: (id) => req("/lines/" + encodeURIComponent(id) + "/tick", { method: "POST", timeout: 300000 }),
    runLine: (id) => req("/lines/" + encodeURIComponent(id) + "/run", { method: "POST", timeout: 600000 }),
    setAutopilot: (id, on) => req("/lines/" + encodeURIComponent(id) + "/autopilot", { method: "POST", body: { on } }),
    feedback: (id, text) => req("/lines/" + encodeURIComponent(id) + "/feedback", { method: "POST", body: { text } }),
    deleteLine: (id) => req("/lines/" + encodeURIComponent(id), { method: "DELETE" }),
    deleteProject: (id) => req("/projects/" + encodeURIComponent(id), { method: "DELETE", timeout: 60000 }),
    deleteIdea: (id) => req("/ideas/" + encodeURIComponent(id), { method: "DELETE" }),
    clearLogs: () => req("/logs", { method: "DELETE" }),
    approve: (id) => req("/reviews/" + encodeURIComponent(id) + "/approve", { method: "POST" }),
    revise: (id, text) => req("/reviews/" + encodeURIComponent(id) + "/revise", { method: "POST", body: { text } }),
    oauthStart: (providerId, returnTo) => req("/providers/oauth/" + encodeURIComponent(providerId) + "/start?return_to=" + encodeURIComponent(returnTo)),
  };
}

// Browser-side probe of a local OpenAI-compatible server (llama.cpp, Ollama). No credentials involved.
export async function probeLocalEndpoint(endpoint, timeout = 2500) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  try {
    const res = await fetch(String(endpoint).replace(/\/+$/, "") + "/models", { signal: ctrl.signal });
    if (!res.ok) return { ok: false, reason: "http_" + res.status };
    const body = await res.json();
    const models = Array.isArray(body.data) ? body.data.map((m) => m.id) : [];
    return { ok: true, models };
  } catch (err) {
    return { ok: false, reason: err.name === "AbortError" ? "timeout" : "unreachable" };
  } finally {
    clearTimeout(timer);
  }
}
