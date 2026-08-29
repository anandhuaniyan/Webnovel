# Project isolation contract

## Fixed root

The only permitted project root is:

`C:\Users\anadh\Development\Webnovel`

Source, configuration, local databases, runtime storage, logs, backups, generated assets, caches, and temporary files must remain below that root.

## Dedicated resources

- Compose project: `webnovel_platform`
- Docker network: `webnovel_network`
- Frontend container and image: `webnovel_frontend`, `webnovel_frontend:local`
- PostgreSQL container and volume: `webnovel_postgres`, `webnovel_postgres_data`
- Redis container and volume: `webnovel_redis`, `webnovel_redis_data`
- Optional storage container and volume: `webnovel_storage`, `webnovel_storage_data`
- Database and user: `webnovel`, `webnovel_app`

The named volumes use bind-backed directories under `database` and `storage`, so persistent data remains inside the fixed root. Nothing connects to an external Docker network.

## Operational rules

1. Run project scripts from the fixed root only.
2. Run `scripts\select-ports.ps1` before startup; it selects unused ports without stopping unrelated processes.
3. Run `scripts\preflight.ps1` before Compose operations.
4. Run `scripts\verify-database.ps1 -RequireConnection` before migrations.
5. Never remove volumes automatically.
6. Never run a global Docker prune or cleanup command.
7. Never read another project's `.env`, virtual environment, database, storage, or network.
8. Install Node dependencies only from `frontend` (or another explicit package directory beneath this root).
9. If Python is introduced, create `.venv` directly beneath this root.
10. Before any Git commit, verify that `git rev-parse --show-toplevel` resolves to the fixed root.
