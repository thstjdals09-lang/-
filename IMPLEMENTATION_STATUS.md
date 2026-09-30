# AI Factory implementation status

Audit date: 2026-09-30 (updated after the collaboration + deployment batch)

Legend: `[x]` implemented and tested, `[-]` partial, `[ ]` not started.

## P0: browser-testable V1 (GitHub Pages)

- [x] Google login entry (preview session without a server; real OAuth when a backend URL is set)
- [x] Dashboard as a factory floor: KPIs, 13-station line strips, active workers, quota gauges, failovers, build status, events
- [x] Topic intake → 10 ideas with nine-criterion scores and four AI reviewer critiques
- [x] Automatic shortlist → parallel production lines; Backlog with "이 아이디어 제작" and capacity guard
- [x] All 13 studio stages, each with a task graph (role, kind, difficulty, criticality, dependencies, artifact)
- [x] Per stage: assigned AI, tasks, dependency graph (SVG), artifacts, branch/commit, QA status, quota use
- [x] Leader Agent per line with lifecycle state, decisions and an agent inbox (task_started, result, review_request, handoff, blocked, quota_warning, dependency_ready)
- [x] AI Marketplace with filters (추천/설치됨/무료/코딩/기획/비전/이미지/오디오/로컬/로그인 필요) and "+ AI 추가"
- [x] Auth flow per type: OAuth, API key (backend only; disabled in preview), Local (browser health probe), Custom endpoint
- [x] Provider metadata with `quota_source` and `last_verified` (null until a real probe)
- [x] AI Employees: status, auth state, capabilities, quota gauge with reserve marker, usage, error rate, latency, next reset
- [x] CHEAPEST_VIABLE_QUALITY routing, plus quality / speed / free policies
- [x] Reserve threshold per AI, adjustable; reserve used only by critical tasks
- [x] Automatic failover (simulated 429/503/401), cooldowns, auto-hire of the local worker, modality fallback
- [x] QA failure → automatic fix + retest tasks
- [x] CEO feedback becomes a task; CEO Review with live build preview, QA checks, approve / request revision
- [x] Release Candidate gate: Live Ops starts only after CEO approval
- [x] Filterable production logs (type, line, text)
- [x] Playable HTML5 builds (0.1 prototype → 1.0 release) in a sandboxed iframe, downloadable
- [x] Tests: `node --test` engine/router suite; Chromium smoke on desktop and 390px mobile

## P1: backend data and accounts

- [x] Versioned SQLite migrations: users, sessions, oauth_states, provider_connections, encrypted_credentials, projects, ideas, production_lines, stages, tasks, task_dependencies, workers, messages, quota_snapshots, usage_logs, artifacts, builds, feedback, reviews, factory_logs
- [x] Google OAuth code flow (PKCE, single-use state, allow-listed return, ID-token claim checks); hashed sessions in HttpOnly cookies
- [x] CSRF guard (custom header + Origin allow-list); dev login behind an explicit flag
- [x] AES-256-GCM vault bound to user and credential id; `vault://` references only; secret redaction
- [x] Account-scoped settings, connections, projects, lines, quota history and feedback
- [x] AI ideation room: a planner AI invents concepts; reviewer roles cross-score them on different models (offline patterns only without AI)
- [x] Design dossier: earlier stages' artifacts and the concept reach every later task, including the programmers
- [x] Console backend mode: `/state` snapshot, all CEO actions via the API, sandboxed build playback
- [ ] Hosted backend deployment and production Google OAuth client

## P2: real provider adapters

- [x] Adapter contract: health_check, list_models, execute, quota_probe, usage_parser, error_classifier
- [x] OpenAI-compatible: Groq, Cerebras, Mistral, GitHub Models, Hugging Face router, llama.cpp, Ollama, custom endpoint
- [x] Gemini (key in header only), OpenRouter (key quota endpoint), Cloudflare Workers AI (account template)
- [x] Rate-limit header quota capture; connect → vault → health_check → quota_probe; re-verify; delete
- [ ] Provider OAuth apps (OpenRouter PKCE, GitHub, Google AI): endpoint returns 501 for now
- [ ] ComfyUI, local audio and Anthropic adapters (catalog entries are marked `planned`)
- [ ] Live verification of every free-tier quota against real accounts (needs keys)

## P3: GitHub worker execution

- [x] Dependency-aware task graph scheduler (server Leader) with per-line locks and a server autopilot
- [x] Per-task branch `ai-factory/<project>/<line>/<agent>/<stage>-<task>` in its own git worktree
- [x] Worker commit → reviewer (coding tasks) → merge `--no-ff` into main → worktree and branch cleanup
- [x] Path confinement for model-supplied file names (incl. Windows anchors/drives), Windows MAX_PATH-safe layout
- [x] Line repositories mirrored to GitHub (`aif-` repos only; existing repositories are never reused)
- [x] Parallel workers inside one wave (provider calls concurrent, git/DB finalization serialized)

## P4: end-to-end generated game

- [x] Topic → ideas → automatic selection → planning artifacts → coding → build → QA → repair → CEO review
- [x] Model-written single-file game, written from scratch from the design dossier, iterated by game tasks
- [x] Code review, stage judges and QA send work back as fix + re-check tasks carrying the notes
- [x] Web release and Windows release folder (offline game + Play.cmd launcher)
- [x] Isolated runtime QA (offline headless Chromium) with screenshots, auto-repair and safe revert
- [x] Vision QA receives the runtime screenshot
- [ ] Native Windows packaging (Tauri/Electron)
- [x] Every playable build deployed to GitHub Pages; links shown only after the URL answers 200
- [x] Verified against real GitHub (repo create → push → Pages → 200)

## CI

- [x] Backend CI (pytest)
- [-] Pages deploy: `ci/pages.yml` gates deploy on web tests and the Chromium smoke test, but the local
  `gh` token lacks the `workflow` scope, so the active workflow still runs only a syntax check.
