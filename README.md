# Trading-Agent

## Quickstart

```bash
git clone <repo-url> && cd Trading-Agent
cp .env.example .env        # fill in provider keys
make up                     # docker compose up --build
python scripts/create_local_tables.py
```

Note: `make test-scheduler` and `make test-api` are expected to fail for now —
those services don't have tests yet (added in later phases).
