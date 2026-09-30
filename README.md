# AI Factory

An autonomous game studio. The CEO enters a topic ("홀덤", "좀비", "타이핑", "카지노 운영"); the factory
generates ~10 ideas, has AI reviewers score them, opens production lines for the shortlist, and runs each
line through the 13 real studio stages (Brief → Ideation → Greenlight → Pre-Production → Prototype →
Vertical Slice → Full Production → QA → Alpha → Beta → Polish → Release Build → Live Ops). The CEO reviews
builds, sends feedback, approves releases, and can start any Backlog idea later.

Live console: https://thstjdals09-lang.github.io/-/

## Two ways to run the console

| Mode | What runs | Credentials |
| --- | --- | --- |
| **Preview** (GitHub Pages, no server) | The whole factory is simulated in the browser: routing, failover, quota, task graphs, builds you can play | None. API-key inputs are disabled; nothing secret is stored |
| **Backend** (Google login) | The server Leader executes tasks on your connected AI providers, commits every task through git worktrees, and serves builds | Provider keys live only in the server's encrypted vault; the browser holds `vault://` references |

## Architecture

```
Browser console (docs/) ──Google login──▶ FastAPI backend (backend/)
                                           ├─ Encrypted vault (AES-256-GCM, AI_FACTORY_VAULT_KEY)
                                           ├─ Provider adapters ──▶ Gemini · Cerebras · Groq · OpenRouter
                                           │                         Cloudflare · Mistral · llama.cpp · …
                                           ├─ CHEAPEST_VIABLE_QUALITY router + failover
                                           ├─ Leader Agent per line (task graph, QA, repair, gates)
                                           └─ Git workspace per line (worktree per task → main)
```

- `docs/catalog/`: shared, non-secret catalogs used by both the browser and the server. `providers.json`
  holds provider metadata with `quota_source` and `last_verified`; `studio.json` holds the studio stages
  and task graphs; `games/` holds the HTML5 game templates.
- `docs/js/`: the console. `router.js` and `engine.js` are pure and tested. `remote.js` maps the backend
  snapshot onto the same views.
- `backend/app/`: `auth.py` (Google OAuth, sessions, CSRF), `vault.py`, `connections.py`, `providers/`
  (the adapter contract), `routing.py` (CVQ, mirrors `docs/js/router.js`), and `factory/` (ideation,
  Leader, executor, git workspace, API).

### Routing policy: CHEAPEST_VIABLE_QUALITY

Each task has a kind (coding, planning, debugging, design, vision, qa), a difficulty and a criticality.
The router skips AIs that are paused, unauthenticated, cooling down, out of quota, or at their reserve
line (reserve is kept for critical tasks). Among the rest it picks the cheapest cost tier whose skill
meets the task's quality bar, and easy work never spends scarce quota. Failures are classified (rate
limit, auth, quota, context, transient) and the task hands off to the next AI. If no AI can take the
task, the router tries a modality fallback, and a local or simulated worker keeps the line moving.

### Git workflow per task

`git worktree add -b ai-factory/<project>/<line>/<agent>/<stage>-<task>` → worker writes the artifact →
commit → reviewer (coding tasks) → merge `--no-ff` into `main` → worktree and branch removed. `main`
always holds a playable `game/index.html`.

## Quick start on Windows

Double-click **`start-backend.cmd`** in the repository root. On first run it creates the Python environment and
`backend/.env` (fresh vault key, local-only login), starts the server on 127.0.0.1 and opens
http://127.0.0.1:8000/console/. Then open **AI 마켓 → + AI 추가**: each provider card opens its login / key
page, you paste the key, and the server stores it in the vault and verifies it (model list, quota).
OpenRouter supports **로그인으로 연결**: approve on openrouter.ai and the key is issued straight into the vault.

## Run the backend locally

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows  (source .venv/bin/activate elsewhere)
pip install -e ".[dev]"
copy .env.example .env          # then fill in the values below
python -c "from app.vault import generate_key; print(generate_key())"   # → AI_FACTORY_VAULT_KEY
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/console/. The backend serves the console on the same origin.

- **Google login:** create an OAuth client (type "Web application") in Google Cloud Console, add the
  redirect URI `<AI_FACTORY_PUBLIC_URL>/auth/google/callback`, and set `AI_FACTORY_GOOGLE_CLIENT_ID` and
  `AI_FACTORY_GOOGLE_CLIENT_SECRET`.
- **Without Google (local only):** set `AI_FACTORY_DEV_LOGIN=1` and `AI_FACTORY_COOKIE_SECURE=false`.
  The Google button then asks for an email. Never enable dev login on a public server.
- **Using the GitHub Pages console with a hosted backend:** serve the backend over HTTPS, add
  `https://thstjdals09-lang.github.io` to `AI_FACTORY_ALLOWED_ORIGINS`, keep `COOKIE_SECURE=true` and
  `COOKIE_SAMESITE=none`, and enter the backend URL on the console's login screen.
- The server autopilot advances running lines every `AI_FACTORY_AUTOPILOT_SECONDS` (default 5, 0 = off).

## Tests

```bash
npm ci
npm run check            # module syntax + catalog validation
npm test                 # router and engine (node --test)
npm run e2e              # Chromium: preview console, desktop + mobile
npm run e2e:backend      # Chromium + uvicorn: backend mode end to end
cd backend && pytest     # vault, auth, adapters, routing parity, Leader, git workspace, P4
```

On Windows, if the default temp dir isn't writable or paths get too long, run
`pytest --basetemp .pyt -p no:cacheprovider`.

## Security rules

- API keys never go into frontend code, GitHub, `localStorage`, or logs. The browser sends a key once to
  the backend over HTTPS. The backend seals it in the vault, bound to the user and the credential id, and
  redacts it from errors.
- Sessions are random tokens stored hashed; cookies are HttpOnly. Mutating requests require the
  `X-AI-Factory` header and an allow-listed Origin.
- The server only validates generated game code statically and never executes it. It runs in the browser
  inside a sandboxed iframe (`allow-scripts` only), and backend playback adds a CSP `sandbox` header.
- `.env`, databases, workspaces and credentials are git-ignored.

## CI

- `backend-ci.yml` runs the backend tests.
- `pages.yml` deploys `docs/`. An improved workflow that gates the deploy on `npm run check`, `npm test`
  and the Chromium smoke test is at `ci/pages.yml`. Installing it needs a token with the `workflow`
  scope: run `gh auth refresh -s workflow`, then copy the file to `.github/workflows/pages.yml`.

See `IMPLEMENTATION_STATUS.md` for progress against the roadmap, and `PRODUCTION_PIPELINE.md` and
`docs/architecture/agent-swarm-reference.md` for the design.
