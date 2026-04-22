# Integration-First Refactor Notes

## What was replaced

1. **Custom RSS polling loop**
   - Replaced by Miniflux API ingestion.
   - `app/services/ingestion.py` now pulls entries from Miniflux.

2. **PostgreSQL primary search experience**
   - Replaced by Meilisearch indexes (`articles`, `clusters`).
   - `/search` route now queries Meilisearch.

3. **Cloud-only summarization path**
   - Replaced with Ollama-first provider abstraction.
   - OpenAI remains optional fallback.

4. **Token-only clustering strategy**
   - Upgraded to semantic-aware scaffolding with embeddings + cosine similarity.

## What remains custom (intentional)

- Cluster assignment policy and thresholds.
- Story timeline model and cluster event history.
- Story ranking heuristics.
- Product UX, story pages, and source comparison presentation.

## Deprecated modules

- `Source` / `FeedFetchState` data model are kept for compatibility and marked deprecated.
- `poll_sources()` name retained, but internally calls Miniflux ingestion.
- `scripts/seed_sources.py` now seeds Miniflux feeds.

## Operational migration checklist

1. Start new stack with Miniflux, Meilisearch, and Ollama.
   - Use separate Postgres databases for app data and Miniflux data (default compose now does this).
   - App DB container/service: `app_db`.
   - Miniflux DB container/service: `miniflux_db`.
   - App migrations apply only to `DATABASE_URL` (app DB), not Miniflux DB.
2. Miniflux bootstrap is automatic using admin Basic auth from env (`MINIFLUX_ADMIN_USERNAME`/`MINIFLUX_ADMIN_PASSWORD`).
3. Optional: provide `MINIFLUX_API_KEY` manually for advanced setups.
4. Pull Ollama models manually if needed:
   - `ollama pull llama3.1:8b`
   - `ollama pull nomic-embed-text`
5. Trigger pipeline manually once (`POST /pipeline/run`) to ingest, cluster, summarize, and index.
6. Database migrations now run through Alembic on startup (`alembic upgrade head`).
7. Miniflux entries are ingested using local processed-state (`after_entry_id`) and can be marked read after persistence.
8. If Miniflux is slow to start, automated bootstrap retries run in the background until complete.
9. Scheduler health and last pipeline execution state are now exposed in `/health`.
10. Backup/restore is available in GUI at `/backups` (admin-only):
    - Export JSON backups with optional article inclusion.
    - Restore validates backup schema version and requires explicit overwrite confirmation.
11. First-run setup wizard is available at `/setup/1` until `app_settings.setup_completed=true`.
12. Source management is available at `/sources` (admin-only), synced with Miniflux feeds.
13. AI configuration is available at `/ai` (admin-only), persisted in DB and used by runtime provider overrides.
