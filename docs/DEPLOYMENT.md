# Deployment

Local startup from the exact project root is:

```powershell
.\scripts\start.ps1
```

The script selects unused ports without terminating owners, validates isolation and Compose, builds images, starts only project PostgreSQL/Redis, verifies database identity, runs Alembic, then starts backend, worker, scheduler, and frontend. Optional MinIO uses `-WithStorage`. Stop with `scripts/stop.ps1`; volumes are retained.

For production, use unique secrets from a secret manager, HTTPS/reverse proxy, managed PostgreSQL with backups/PITR, managed Redis, S3-compatible versioned object storage, restricted network access, centralized logs/metrics, health checks, worker autoscaling, and a single migration job. Disable API docs, set the real public origin, configure email/privacy contacts, and keep AdSense/Analytics off until consent and account configuration are complete.

Release gates: migration on a staging clone; unit/integration/API/reader/SEO/security tests; current rights recheck; no unpublished sitemap leakage; cover/media integrity; backup restore exercise; takedown drill; storage headroom; and rollback instructions. Never run global Docker prune or volume removal for this project.
