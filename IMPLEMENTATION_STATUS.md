# AI Factory implementation status

Audit date: 2026-09-29

Legend: `[x]` implemented, `[-]` partially implemented, `[ ]` not implemented.

## Existing foundation

- [x] FastAPI application skeleton and health endpoint
- [x] SQLite employee and routing-log persistence
- [x] AI employee capability and quota model
- [x] Balanced, quality, free, and speed routing policies
- [x] Employee, routing, and routing-log APIs
- [x] Router unit tests and backend CI workflow
- [x] Static GitHub Pages deployment workflow
- [x] Real game-studio production pipeline document
- [x] ClawTeam-inspired leader/worker/task-graph architecture document

## P0 — browser-testable V1

- [x] Google login entry screen (preview session; real OAuth belongs to P1/P2)
- [x] CEO dashboard
- [x] Topic intake
- [x] Topic change with completed-result preservation and paused-line resume
- [x] Deterministic simulation of ten game ideas
- [x] Automatic scoring and shortlist
- [x] Idea Backlog and “build this idea” action
- [x] Multiple independent production-line cards
- [x] All 13 real game-studio stages
- [x] AI Marketplace
- [x] Add/install AI action
- [x] Installed AI employee list
- [x] Quota gauges
- [x] `CHEAPEST_VIABLE_QUALITY` browser routing simulation
- [x] Per-provider reserve threshold
- [x] Automatic failover simulation with reserve protection and handoff logs
- [x] CEO feedback entry and production log
- [x] Autonomous stage-by-stage Autopilot with pause/resume and instant-complete controls
- [x] Dedicated CEO Review queue with build/QA/approval/revision state
- [x] Left-side completed-game results view with repository and GitHub Pages addresses
- [x] Real standalone HTML5 microgame generation, in-browser play, smoke validation, and download
- [x] Server-side game-named repository creation/update, release commit, main-ref push, and GitHub Pages activation code
- [ ] Publisher backend hosting and `AI_FACTORY_GITHUB_TOKEN` configuration
- [ ] Authenticated browser-to-backend completion/publish wiring
- [x] Unpublished preview records do not expose clickable GitHub/Pages links

## P1 — backend data and account structure

- [ ] Users and real Google OAuth session
- [ ] Provider connections and credential references
- [ ] Encrypted credential vault
- [ ] Projects and ideas
- [ ] Production lines and stages
- [ ] Tasks and task dependencies
- [ ] Workers and structured inbox messages
- [ ] Quota snapshots and usage logs
- [ ] Artifacts and builds
- [ ] CEO feedback persistence

## P2 — real provider adapters

- [ ] Common adapter contract (`health_check`, `list_models`, `execute`, `quota_probe`, `usage_parser`, `error_classifier`)
- [ ] Gemini
- [ ] Cerebras
- [ ] Groq
- [ ] OpenRouter
- [ ] Cloudflare Workers AI
- [ ] Mistral
- [ ] llama.cpp local endpoint

## P3 — GitHub worker execution

- [ ] Dependency-aware task graph scheduler
- [ ] Per-worker branch and Git worktree
- [ ] Worker commit
- [ ] Reviewer diff and automated tests
- [ ] Merge and worktree cleanup
- [x] Server-side GitHub repository publisher

## P4 — end-to-end generated game

- [ ] Theme to idea selection
- [ ] Planning to generated code
- [ ] Sandboxed run and test
- [ ] Automated repair loop
- [ ] Windows build
- [ ] CEO build review
- [ ] Release and live-ops loop

## Security checks

- [x] `.env`, databases, logs, build outputs, and common credential files are ignored
- [x] Static preview stores no provider API key
- [x] Architecture keeps provider secrets behind a backend/vault boundary
- [ ] Encrypted server-side vault implementation
- [ ] Sandboxed generated-code runner

## Immediate implementation order

1. Persist production lines and publish-job results in the backend.
2. Connect the browser completion queue to the authenticated backend publisher.
3. Replace the preview's predicted URLs with the publisher's returned repository and `github.io` URLs.
4. Continue P1 persistence and account boundaries.
