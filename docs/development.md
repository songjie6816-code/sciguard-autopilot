# Development environment

## Local baseline checked on 2026-07-17

- macOS 15.5 on Apple Silicon
- 10 CPU cores, 16 GB physical memory, 233 GB free disk
- Python 3.11.15 in the repository-local `.venv`
- DataHub CLI 1.6.0.15
- Docker client 29.6.2 and server 29.5.2
- Docker Compose 5.3.1
- Colima 0.10.3 using Apple Virtualization.framework and virtiofs
- Colima allocation: 4 CPU, about 8 GB RAM, and a 60 GB Docker data disk

Docker Desktop is also supported by the official DataHub instructions. This machine uses
the Docker-compatible Colima runtime because Homebrew was already installed and Docker
Desktop was not present.

Activate the checked environment with:

```bash
conda activate "$PWD/.venv"
```

If Homebrew is not already on the shell path on Apple Silicon, prefix Docker commands
with `PATH=/opt/homebrew/bin:$PATH`.

## Quickstart verification

The installed CLI currently resolves the default Quickstart plan to DataHub image tag
`v1.5.0.6`. The local stack was started successfully and verified with the frontend at
<http://localhost:9002>, GMS at <http://localhost:8080>, and healthy MySQL, OpenSearch,
Kafka, GMS, and frontend containers.

The official `showcase-ecommerce` datapack was loaded successfully. Because this
Quickstart plan sets `METADATA_SERVICE_AUTH_ENABLED=false`, load local samples by setting
the GMS endpoint directly:

```bash
DATAHUB_GMS_URL=http://localhost:8080 datahub datapack load showcase-ecommerce
```

Do not run `datahub init` for this local plan. With the current CLI/server version pair,
the login succeeds but token creation is rejected because metadata-service authentication
is disabled. This does not affect local ingestion or the browser login.
