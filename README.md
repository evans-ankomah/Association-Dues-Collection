# DeptHub — Association Dues Collection

A dues and membership platform for university departments: member rosters, academic sessions, dues assessments, online and offline payments, receipts, and finance reporting.

Built as a Django modular monolith with server-rendered pages (HTMX, Alpine.js, Tailwind CSS), PostgreSQL, and Celery/Redis for background jobs.

## Requirements

- Python 3.12
- Node.js 20+ (builds the CSS and copies the browser libraries)
- Docker Desktop (runs PostgreSQL and Redis)

## First-time setup

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows; use `source .venv/bin/activate` elsewhere
pip install -r requirements-dev.txt
npm install
npm run build                     # writes static/css/app.css and static/vendor/
cp .env.example .env              # then edit values as needed
docker compose up -d              # PostgreSQL on localhost:5433, Redis on localhost:6379
python manage.py migrate
python manage.py runserver
```

Open http://localhost:8000. The health check is at `/healthz/`.

PostgreSQL is exposed on port **5433** so it doesn't clash with a locally installed PostgreSQL on 5432.

## Everyday commands

| Task | Command |
|---|---|
| Run tests | `pytest` |
| Lint and format | `ruff check . && ruff format .` |
| Rebuild CSS while editing templates | `npm run dev` |
| Stop the database | `docker compose down` (data is kept in the `pgdata` volume) |

## Project layout

```
config/       settings (base, dev, test, prod), URLs, Celery
apps/         one Django app per module (common, accounts, finance, ...)
templates/    shared templates and partials
static/src/   Tailwind entry point
seed/         anonymised UMaT sample-data generator (see seed/README.md)
```

## Branches

- `main`: released code.
- `develop`: integration branch. Feature branches (`feature/*`, `chore/*`) merge here through pull requests once CI passes.
