# Webnovel Platform

This is the isolated local Webnovel platform. Every project file and persistent local data path is rooted at `C:\Users\anadh\Development\Webnovel`.

The current Compose stack serves a dependency-free Webnovel frontend alongside isolated PostgreSQL, Redis, and optional MinIO infrastructure. It does not share ports, networks, volumes, credentials, or configuration with another project.

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

## Database safety

The expected database is exactly `webnovel`, owned by `webnovel_app`. Before any migration, run:

```powershell
.\scripts\verify-database.ps1 -RequireConnection
```

The verifier prints the configured host, port, and database; confirms that the running container belongs to Compose project `webnovel_platform`; queries the actual database name; and aborts on any mismatch.

## Configuration

`.env` contains local-only credentials and is ignored by Git. `.env.example` documents the required keys but contains no usable secrets. Do not copy configuration from another project.

See `docs\ISOLATION.md` for the enforced boundaries and resource names.
