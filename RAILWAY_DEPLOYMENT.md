# Railway Deployment

## Services

Create one Railway project with these services:

1. Backend: FastAPI service from `backend`
2. Frontend: React/Vite static site from `frontend`
3. Database: Postgres with pgvector template
4. Upload storage: Volume mounted to the backend service

## Backend

Set the service root directory to `backend`.

Python is pinned in `backend/.python-version`:

```txt
3.12.7
```

`backend/mise.toml` disables Python artifact attestation verification for
Railway's mise-based builder.

Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Environment variables:

```env
DATABASE_URL=<Railway Postgres DATABASE_URL>
OPENAI_API_KEY=<OpenAI API key>
UPLOAD_DIR=/app/uploads
CORS_ORIGINS=https://<frontend-domain>
DEBUG_MODE=false
```

The app accepts Railway database URLs that start with either `postgres://` or
`postgresql://`.

Mount the Railway Volume at `/app/uploads` so uploaded PDFs survive redeploys.

## Frontend

Set the service root directory to `frontend`.

Use Railway's static site or React static hosting flow. If Railway asks for a
publish/output directory, set it to `dist`.

Public networking:

```txt
Target Port: 8080
```

Build command:

```bash
npm run build
```

Leave the install command empty/default. Railway runs `npm ci` automatically
before the build step.

Environment variables:

```env
VITE_API_BASE_URL=https://<backend-domain>/api/v1
```

## After Deploy

1. Generate a public domain for the backend service.
2. Set the frontend `VITE_API_BASE_URL` to the backend domain plus `/api/v1`.
3. Generate a public domain for the frontend service.
4. Set backend `CORS_ORIGINS` to the frontend domain.
5. Redeploy both services.
6. Open `https://<backend-domain>/health` and confirm it returns `{"status":"ok"}`.
7. Test login, PDF upload, session start, one turn, and session report.
