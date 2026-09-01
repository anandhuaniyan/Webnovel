# Webnovel Platform

Webnovel is an isolated, copyright-first literature platform behind the existing frontend. It includes FastAPI, PostgreSQL, Redis/Celery workers, resumable multi-source ingestion, independent rights evidence, chapter extraction and integrity checks, search, accounts and synchronized reader state, an immersive responsive reader, approved chapter artwork with subtle reduced-motion-safe animation, PWA caching, admin workflows, SEO pages/sitemaps, consent-aware analytics, and disabled-by-default AdSense/provider integrations.

Every project file and persistent local path is rooted at `C:\Users\anadh\Development\Webnovel`. It does not share ports, networks, volumes, credentials, or configuration with another project.

## Reserved endpoints

- Frontend: `0.0.0.0:5273` (host PC and private LAN)
- Backend API: `127.0.0.1:8270` (host PC only; browsers use frontend `/api`)
- PostgreSQL: `127.0.0.1:55432`
- Redis: `127.0.0.1:56379`
- Optional MinIO API: `127.0.0.1:59000`
- Optional MinIO console: `127.0.0.1:59001`

These are recorded in `.env`. `scripts\select-ports.ps1` replaces any occupied port with an unused one, detects the active physical LAN IPv4 address, and updates dependent URLs before startup. It never terminates the process that owns an occupied port. PostgreSQL, Redis, the backend, and optional MinIO ports remain bound to loopback.

## Safe startup

Run all commands from the project root:

```powershell
cd C:\Users\anadh\Development\Webnovel
.\scripts\configure-lan-firewall.ps1
.\scripts\start.ps1
```

Run the firewall command once from an Administrator PowerShell. It creates only a Private-profile inbound TCP rule for port 5273; it does not disable Windows Firewall or open backend, database, Redis, or storage ports.

To include the optional local object store:

```powershell
.\scripts\start.ps1 -WithStorage
```

Stop only this project's containers:

```powershell
.\scripts\stop.ps1
```

The stop script does not remove volumes. Never use global Docker cleanup commands for this project.

After startup the script prints the detected URLs. With a host LAN address such as `192.168.4.21`:

- Website: `http://localhost:5273`
- Phone/tablet: `http://192.168.4.21:5273`
- Same-origin API health: `http://192.168.4.21:5273/api/health`
- API docs (development): `http://localhost:8270/api/docs`
- Account: `http://localhost:5273/account`
- Admin: `http://localhost:5273/admin`

The LAN address is detected at startup and is never hard-coded. Devices must be on the same private LAN/Wi-Fi. Guest-network or router client-isolation settings can prevent device-to-device access and must be changed in the router rather than in this project. See `docs\LAN_ACCESS.md`.

The current local deployment contains 3 independently reviewed public-domain works with 209 complete chapters. The initial 20-candidate discovery checkpoint is retained for staged rights review; the remaining candidates stay unpublished until a human verifies their rights evidence. Nothing is published merely because it was discovered or downloaded.

The reader supports synchronized progress, local offline fallback, bookmarks, chapter jumping, keyboard and touch navigation, type/size/spacing/width controls, light/sepia/dark themes, fullscreen focus, estimated time remaining, lazy chapter artwork, and `prefers-reduced-motion`. Installable PWA metadata and a bounded same-origin service worker cache keep the shell and recently read public chapters available after first load.

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
.\.venv\Scripts\python.exe -m ruff check backend scripts tests
```

The 10,000+ target is a staged operating goal, not a fabricated seed count: 20 → 100 → 1,000 → 5,000 → 10,000+. Only independently rights-verified, complete, reviewed editions count as published.

Architecture and operating documentation is in `docs`, beginning with `ARCHITECTURE.md`, `INGESTION.md`, and `RIGHTS_VERIFICATION.md`.
