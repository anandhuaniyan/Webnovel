# Webnovel Platform

Webnovel is an isolated, copyright-first literature platform behind the existing frontend. It includes FastAPI, PostgreSQL, Redis/Celery workers, resumable multi-source ingestion, independent rights evidence, chapter extraction and integrity checks, search, accounts and reader state, admin workflows, SEO pages/sitemaps, consent-aware analytics, and disabled-by-default AdSense/provider integrations.

Every project file and persistent local path is rooted at `C:\Users\anadh\Development\Webnovel`. It does not share ports, networks, volumes, credentials, or configuration with another project.

## Reserved local endpoints

- Frontend: `http://localhost:5273`
- Backend API: `http://localhost:8270`
- PostgreSQL: `127.0.0.1:55432`
- Redis: `127.0.0.1:56379`
- Optional MinIO API: `127.0.0.1:59000`
- Optional MinIO console: `127.0.0.1:59001`

These are recorded in `.env`. `scripts\select-ports.ps1` replaces any occupied port with an unused one and updates dependent URLs before startup. It never terminates the process that owns an occupied port.

## Safe startup

Run all commands from the project root:

```powershell
cd C:\Users\anadh\Development\Webnovel
.\scripts\start.ps1
```

To include the optional local object store:

```powershell
.\scripts\start.ps1 -WithStorage
```

Stop only this project's containers:

```powershell
.\scripts\stop.ps1
```

The stop script does not remove volumes. Never use global Docker cleanup commands for this project.

After startup:

- Website: `http://localhost:5273`
- API health: `http://localhost:8270/health`
- API docs (development): `http://localhost:8270/api/docs`
- Account: `http://localhost:5273/account`
- Admin: `http://localhost:5273/admin`

The catalogue starts empty by design. Queue the 20-candidate Gutenberg checkpoint through the admin page or API. Workers will archive source claims and stop every candidate at independent rights review. Nothing is published merely because it was discovered or downloaded.

## Database safety

The expected database is exactly `webnovel`, owned by `webnovel_app`. Before any migration, run:

```powershell
.\scripts\verify-database.ps1 -RequireConnection
```

The verifier prints the configured host, port, and database; confirms that the running container belongs to Compose project `webnovel_platform`; queries the actual database name; and aborts on any mismatch.

## Configuration

`.env` contains local-only credentials and is ignored by Git. `.env.example` documents the required keys but contains no usable secrets. Do not copy configuration from another project.

See `docs\ISOLATION.md` for the enforced boundaries and resource names.

## Development and tests

The local Python environment lives in `.venv` inside this project:

```powershell
$env:PYTHONPATH = "$PWD\backend"
.\.venv\Scripts\python.exe -m pytest -c backend\pyproject.toml tests
.\.venv\Scripts\ruff.exe check backend tests
```

The 10,000+ target is a staged operating goal, not a fabricated seed count: 20 → 100 → 1,000 → 5,000 → 10,000+. Only independently rights-verified, complete, reviewed editions count as published.

Architecture and operating documentation is in `docs`, beginning with `ARCHITECTURE.md`, `INGESTION.md`, and `RIGHTS_VERIFICATION.md`.
