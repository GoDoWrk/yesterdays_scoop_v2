# Yesterday's Scoop (Autonomous Integration-First v1)

Yesterday's Scoop is a self-hosted, cluster-first news intelligence app.

## Quick install (Linux)

```bash
git clone <repo-url> yesterdays-scoop
cd yesterdays-scoop
./scripts/install.sh
```

The installer handles Docker checks, directory/data path setup, `.env` generation, and stack startup.
After that, open the printed URL and complete setup in the browser wizard.

For manual Compose/Portainer/CasaOS instructions, see `docs/INSTALL.md`.

Installer defaults are user-writable (`$HOME/yesterdays-scoop` and `$HOME/yesterdays-scoop-data`) and are validated for writability before startup.

## Configuration ownership (installer vs GUI)

**Installer / env-managed**
- host ports
- auth and DB secrets
- database credentials/URLs
- host data path / volume root
- service base wiring values

**GUI / DB-managed**
- source presets and source controls
- topics and region
- setup-wizard-selected provider/profile values
- AI/social feature toggles exposed in the UI
- social context toggles and max items
- poll interval and other safe runtime tuning exposed in settings

## Architecture
- **Miniflux**: feed subscriptions, source management, OPML-ready ingestion backend
- **Meilisearch**: primary end-user search engine for article + cluster retrieval
- **Ollama**: default local LLM (summaries + embeddings)
- **FastAPI app**: orchestration, clustering/ranking, and product UI
- **PostgreSQL**: relational/state storage
- **Redis + Celery worker/beat**: autonomous scheduling + background execution

## Autonomous operational model
Once started, the system updates itself continuously:
1. Celery Beat schedules pipeline runs (`ingest → cluster → summarize → rank → index`).
2. Miniflux bootstrap runs immediately at startup.
3. If bootstrap fails (service startup lag, temporary outage), periodic retry task keeps trying until complete.
4. Ingestion is idempotent by canonical URL/entry ID checks, with source-aware polling cadence.
5. Cluster summaries/what-changed/rank/search are updated for touched clusters incrementally.
6. External service calls (Miniflux, Meilisearch, Ollama) use bounded retries and emit explicit warnings on failure.

Normal operation is autonomous after setup, but service outages will surface as degraded health and may require operator attention.

## First-run setup wizard
- Open `/setup/1` in the browser on first launch.
- Flow:
  1. Welcome
  2. System checks
  3. Admin confirmation
  4. Region and relevance
  5. Source preset selection
  6. AI setup + connection test
  7. Optional social context
  8. Review and finish
- Wizard state (`setup_completed`, `setup_last_step`) and selected settings are stored in DB.
- Incomplete setup blocks normal browsing routes and redirects users to the wizard until completion.

### First-run success criteria
- Setup wizard loads at `/setup/1` without server 500s.
- Admin account can be created/confirmed at step 3.
- Completing step 8 queues bootstrap + pipeline tasks automatically.
- `/health` shows pipeline/service progression and explicit degraded reasons if something is unavailable.

## Default deployment safety
- The default Compose stack uses **separate PostgreSQL databases**:
  - `app_db` for Yesterday's Scoop app state (Alembic migrations run here).
  - `miniflux_db` for Miniflux internal state.
- This avoids accidental schema overlap and keeps backups/restores unsurprising.

### Data layout
- **Yesterday's Scoop data**: `articles`, `clusters`, `cluster_events`, `app_settings`, `users`, and `service_state` in `app_db`.
- **Miniflux data**: Miniflux-managed feed/category/entry tables in `miniflux_db`.
- The app only talks to Miniflux via HTTP API; it does not query `miniflux_db` directly.

## Key env vars
- `LLM_PROVIDER=ollama|openai`
- `OLLAMA_BASE_URL`, `OLLAMA_CHAT_MODEL`, `OLLAMA_EMBED_MODEL`
- `MINIFLUX_BASE_URL`, `MINIFLUX_ADMIN_USERNAME`, `MINIFLUX_ADMIN_PASSWORD`
- optional `MINIFLUX_API_KEY`, `MINIFLUX_APP_API_KEY_NAME`
- `MINIFLUX_MARK_READ_AFTER_INGEST=true|false`
- `MEILI_URL`, `MEILI_MASTER_KEY`

## Source quality and ingestion controls

The system now maintains a source registry with:
- `source_tier` (1-3)
- `priority_weight`
- `poll_frequency_minutes`
- `health_status`
- `failure_count`
- `average_latency_ms`
- `last_successful_fetch` and `last_article_time`

Tier-based polling defaults:
- Tier 1: every 10 minutes
- Tier 2: every 20 minutes
- Tier 3: every 45 minutes

When a high-impact cluster has low corroboration, the system marks it as `seeking_confirmation` and prioritizes polling Tier 1/2 sources first.

## Ranking model and tuning knobs

Cluster ranking is computed from persistent signals:
- `impact_score`
- `source_confidence_score`
- `corroboration_count`
- `velocity_score`
- `freshness_score`
- `local_relevance_score`
- `staleness_decay`

Formula:
- `importance = weighted_sum(impact, confidence, corroboration, velocity, freshness)`
- `final_score = importance * (1 + local_relevance_boost) * staleness_decay`

Default weights live in `app/services/ranking.py` as `RANKING_WEIGHTS` and can be tuned there.
`LOCAL_RELEVANCE_BOOST_CAP` controls local uplift, and staleness/freshness half-life behavior is controlled by the helper functions in the same module.

## Social context layer (separate from reporting)

Clusters can optionally include a social context panel (Reddit + optional X) that surfaces:
- **Official responses** (verified / known-figure accounts)
- **Public reaction**

Important: social items are stored and displayed separately and are **not mixed** into core article/cluster ranking.

Enable via Settings:
- `enable_social_context`
- `enable_reddit_context`
- `enable_x_context`
- `social_max_items`

X integration requires `x_api_bearer_token`.

## Operator/debug surface (`/admin`)
The internal admin dashboard is now the primary observability surface for day-2 operations.

It exposes:
- total articles and total clusters
- article ingest volume (1h / 24h)
- clusters touched (1h / 24h)
- per-stage run timestamps (`ingest`, `cluster`, `summarize`, `rank`)
- queue visibility (`active`, `reserved`, `scheduled` Celery tasks)
- pipeline run history table (per-run counts/status/errors)
- stage event stream (`ingest`/`cluster`/`summarize`/`rank`/`index`) with durations and failures
- trend graph for ingest volume vs stage errors across recent runs
- recent enrichment failures (from `cluster_events`)
- source health cues (`health_status`, failure count, freshness)
- practical service health checks for DB, Redis/Celery, Miniflux, Meilisearch, and Ollama

Use `/admin` first when a page looks stale or incomplete; it now makes backend uncertainty explicit instead of silent.

## Story model in the UI
### Cards = quick story snapshots
Cards are intentionally compact and now only surface:
- headline
- one-line current state
- one-line latest change
- one-line why-it-matters
- last updated time
- status badge (`Developing`, `Active`, `Stabilizing`, `Concluded`)
- source/update counts

### Detail view = context payoff
Opening a story now focuses on context:
- Current state
- Latest change
- Why it matters
- What to know
- Timeline (chronological article updates)
- Cluster events
- Sources and corroboration

### Story status definitions
- **Developing**: very recent movement (typically within ~8h).
- **Active**: still moving but no longer initial break (~8-36h).
- **Stabilizing**: slower update cadence (~36-96h).
- **Concluded**: long-tail updates only (>=96h) or archived state.

### Explicit readiness/uncertainty states
Cards and detail pages now label data maturity directly:
- Processing
- Awaiting summary
- Awaiting clustering
- Partial data available
- AI generation failed
- No recent updates
- Ready

No section should appear "finished" when the required data is unavailable.

## AI fallback behavior
If LLM generation is unavailable or fails:
- **Current state** falls back to deterministic extractive text from attached articles.
- **Latest change** falls back to a delta from the newest two attached updates.
- **Why it matters** falls back to a concise deterministic sentence.
- Fallback-oriented readiness labels are shown to the user.

This keeps story pages usable without hiding model failures.

## Demo/dev seed mode
Load deterministic sample stories for UI evaluation independent of live ingestion/LLM health:

```bash
python scripts/seed_demo_data.py
```

The seed includes:
- healthy/ready stories
- partial/in-progress stories
- AI-failed fallback stories
- stale/concluded stories

All demo records are prefixed with `demo-` slugs and are safe to reseed.

## Health/status
`/health` reports:
- database
- miniflux reachability
- miniflux bootstrap completion
- miniflux last bootstrap attempt time
- miniflux retry count
- scheduler health (beat-driven heartbeat task timestamp)
- worker health (Celery worker heartbeat + control ping)
- `degraded_reasons` list for quick diagnosis when `status=degraded`
- last pipeline start/finish/success/stage
- meilisearch
- ollama

## UI live signals
- bootstrap pending banner when sources are still being set up
- relative “updated X minutes ago” indicators on story cards
- cluster detail freshness indicator
- `/admin` dashboard with service health cards, throughput counters, retry/error details, and manual action buttons
- `/ai` page for provider selection, model selection, model pulls, fallback behavior, and AI toggle
- `/sources` page for feed CRUD, enable/disable, OPML import/export, and source priority controls

## Manual override
`POST /pipeline/run` remains available as admin override, but normal operation is scheduled.

## Backups & restore (GUI)
- Open `/backups` as an admin user.
- **Backup**: export app settings/sources/clusters/events, with optional article inclusion toggle.
- **Restore**: upload a backup JSON, pass schema compatibility validation, and confirm overwrite before restore.
- Restore preserves user/auth rows and replaces restorable app-domain tables.

## Optional advanced/manual mode
- You can still provide `MINIFLUX_API_KEY` explicitly.
- If provided, the app will use it directly.

## Migration notes
See `docs/MIGRATION_NOTES.md` for migration and bootstrap details.

## Ready-to-test checklist
Use this checklist before calling the stack "usable":
1. `docker compose up --build` completes and all core services stay up for at least 10 minutes.
2. `/health` reports:
   - `status=ok`
   - `miniflux_bootstrapped=true`
   - `scheduler_healthy=true`
   - `worker_healthy=true`
3. Add or modify at least one feed in Miniflux and confirm:
   - new articles are ingested without duplicates,
   - clusters are attached/created sensibly,
   - search shows the newly indexed items.
4. Stop and restart worker/beat containers and confirm `/health` recovers to `ok` automatically.
5. Temporarily stop Ollama and verify summarizer fallback still produces non-empty cluster summaries.
6. Temporarily stop Meilisearch and confirm pipeline keeps ingesting/clustering and reports `complete_warn` until search recovers.

### Quick ingest verification
1. Add at least one active feed in `/sources` (or keep seeded defaults).
2. Run pipeline from `/admin`.
3. Confirm:
   - `articles` count grows,
   - homepage shows populated clusters,
   - `/search` returns matching articles/clusters.
