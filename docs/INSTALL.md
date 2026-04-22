# Installation Guide

## Recommended flow (Linux)

1. Download the app:
   ```bash
   git clone <repo-url> yesterdays-scoop
   cd yesterdays-scoop
   ```
2. Run installer:
   ```bash
   ./scripts/install.sh
   ```
3. Open the printed browser URL and finish setup in the web wizard.

The installer prompts for only host-level essentials:
- install directory
- app/miniflux/meili ports
- persistent data path
- admin username/password
- auth/database/service secrets

### Installer defaults and writable-path behavior

- Default install path: `$HOME/yesterdays-scoop`
- Default data path: `$HOME/yesterdays-scoop-data`
- Before continuing, the installer verifies both selected paths are writable by the current user.
- If either path is not writable, installation stops with a clear error so a non-root Raspberry Pi user can choose a valid path.

## First-run expectations

After `docker compose up -d --build`, first boot should:
- apply DB migrations (or safe schema fallback),
- create initial app settings,
- start the web app without crash loops,
- open setup wizard at `/setup/1`.

Setup wizard covers:
1. Welcome
2. Service checks
3. Admin creation/confirmation
4. Region/topics
5. Source preset
6. AI/provider settings
7. Optional social context
8. Finish + onboarding

## Verify ingestion is working

After setup completes:
1. Open `/admin` and confirm health is not `degraded` due to DB/auth failures.
2. Trigger **Run pipeline now** once from admin page.
3. Confirm `last_pipeline_success=true` and `last_pipeline_stage=complete|complete_warn` in `/health`.
4. Confirm article count increases in DB/admin metrics and the homepage shows clusters.
5. Use `/search` with a known headline term to confirm indexed results appear.

## If Docker is missing

`install.sh` checks Docker + Compose first.
If missing, it exits with install links:
- Docker Engine: https://docs.docker.com/engine/install/
- Docker Compose plugin: https://docs.docker.com/compose/install/linux/

After installing prerequisites, run `./scripts/install.sh` again.

## Installer-managed vs GUI-managed config

### Installer-managed (env/.env)
- ports
- secrets and DB passwords
- DB/service URLs
- host data path (`YS_DATA_ROOT`)
- host integration values

### GUI-managed (DB settings)
- setup wizard selections (region/topics/source preset/provider profile)
- settings page toggles (AI/social) and safe runtime knobs (poll interval, social item limits)
- source registry controls from `/sources` (tier/priority/frequency/enable state)


## Operator checks and debug workflow
When troubleshooting, use `/admin` first. It now shows:
- ingest + cluster throughput counters
- per-stage run timestamps (ingest/cluster/summarize/rank)
- queue depth snapshots (active/reserved/scheduled)
- pipeline run trend graph + run history table
- stage-event stream with duration/error details
- recent enrichment failures
- source-health cues and service reachability

This should make it clear whether backend jobs are progressing and whether UI gaps are due to processing or hard failure.

## Seed deterministic demo stories (optional)
For local UI validation without relying on live feeds/LLM availability:

```bash
python scripts/seed_demo_data.py
```

This adds `demo-*` stories across ready/partial/failed/concluded states and timeline events.

## Manual Compose fallback

If you prefer manual setup:
```bash
cp .env.example .env
docker compose up -d --build
```
Then open `http://<host>:8000`.

## Portainer / CasaOS

- Portainer compose: `deploy/portainer-stack.yml`
- CasaOS compose: `deploy/casaos-compose.yml`

Use `.env.example` as baseline env values and preserve the same secret-handling approach.
