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
    loginUrl: (returnTo) => base() + "/auth/google/login?return_to=" + encodeURIComponent(returnTo),
    connectProvider: (payload) => req("/providers/connections", { method: "POST", body: payload, timeout: 20000 }),
    listConnections: () => req("/providers/connections"),
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
