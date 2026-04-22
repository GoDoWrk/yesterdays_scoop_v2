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
