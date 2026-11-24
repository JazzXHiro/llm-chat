# LLM Chatbot with Key Failover and Response Caching

A small full-stack chat app: **React (Vite)** frontend, **FastAPI** backend, **SQLite** session storage and a
**LiteLLM** gateway in front of a pool of Google Gemini API keys.

- If a key is rate-limited (429), out of quota or returns a 5xx, the request moves to the next key automatically.
- Repeated conversations are answered from LiteLLM's in-memory cache (`LLM_CACHE`) instead of calling Gemini again.
- Every reply shows its own metadata: source, model, latency, input/output tokens, key used, failed attempts.

```
Browser (React)  ──HTTP/JSON──▶  FastAPI  ──▶  LiteLLM Router ──▶ key_1 ─┐ (429 / 5xx / timeout)
      ▲                            │              │  cache                ▼
      └─────── reply + metadata ───┘              │               key_2 ──▶ Gemini
                                   ▼              ▼
                            SQLite (/data/app.db)  in-memory cache (model + full message list)
```

---

## 1. Live URLs

| Part | URL |
| --- | --- |
| Frontend (Vercel) | https://llm-chat.vercel.app |
| Backend (Render) | https://llm-chat-g7w1.onrender.com |
| Health check | https://llm-chat-g7w1.onrender.com/health |
| API docs (Swagger) | https://llm-chat-g7w1.onrender.com/docs |

> **Note:** the backend runs on Render's free plan. After ~15 minutes without traffic it goes to sleep, so the
> **first request can take up to a minute** while it wakes up. Open `/health` once before testing.
> Free Render services have no persistent disk, so the SQLite file (and history) resets when the service is
> redeployed or restarted. Locally with Docker, history is kept in a named volume.

`ENABLE_FAILURE_SIMULATION=true` is set on the deployed backend, so the `X-Simulate-Failure` header works there.

---

## 2. Run locally: with Docker and without

### Prerequisites

- 2 Gemini API keys from [Google AI Studio](https://aistudio.google.com/apikey) (ideally from 2 different projects,
  so they have separate quotas).
- Docker Desktop (for the Docker way), or Python 3.12 + Node.js 22+ (for the manual way).
- `make` (on Windows: `winget install ezwinports.make`, or run the `docker compose` command shown below directly).

### Configuration

All settings come from environment variables. Copy the example file and put your real keys in it:

```bash
cp .env.example .env        # Windows PowerShell: Copy-Item .env.example .env
```

| Variable | Example | Meaning |
| --- | --- | --- |
| `LLM_API_KEYS` | `key-a,key-b` | Comma-separated key pool (at least 2). Ids are `key_1`, `key_2`, ... in this order |
| `LLM_MODEL` | `gemini/gemini-3.5-flash-lite` | LiteLLM model name (`provider/model`) |
| `DATABASE_URL` | `sqlite:////data/app.db` | SQLite file location (4 slashes = absolute path) |
| `ALLOWED_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Comma-separated CORS origins |
| `ENABLE_FAILURE_SIMULATION` | `true` | Honour the `X-Simulate-Failure` header |
| `DEFAULT_SYSTEM_PROMPT` | `You are a helpful, concise assistant.` | Used when the client sends no system prompt |
| `LLM_TIMEOUT_SECONDS` | `30` | Max wait for one key before it counts as failed and the next key is tried |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Frontend only, **build time**: backend URL the browser calls |

Real keys never go into the repo: `.env` is in `.gitignore`, only `.env.example` (placeholders) is committed.

### Option A: Docker (recommended)

```bash
make up       # build both images and start them; waits until the backend is healthy
make down     # stop the containers (chat history is kept in the volume)
```

- Frontend: http://localhost:3000
- Backend: http://localhost:8000/health

Without `make`, the same thing is `docker compose up --build -d --wait` / `docker compose down`.

Extra targets: `make logs` (follow logs of both services), `make reset` (stop and **delete** the SQLite volume).

What Compose starts:

| Service | Image | Port | Notes |
| --- | --- | --- | --- |
| `backend` | multi-stage `python:3.12-slim` (builder venv → runtime, non-root `appuser`) | 8000 | `DATABASE_URL` forced to `sqlite:////data/app.db`, named volume `chat-data` mounted at `/data`, healthcheck on `/health` |
| `frontend` | multi-stage `node:24-alpine` build → `nginx:stable-alpine` | 3000 | Static files only; starts after the backend is healthy |

Because the database lives in the named volume, history survives `make down` / `make up` and image rebuilds.
(The response cache is in memory, so it starts empty after a restart.)

### Option B: without Docker

In `.env`, change `DATABASE_URL` to a local path, e.g. `sqlite:///./data/app.db`
(Docker ignores this value and always uses `/data/app.db`, so this is safe).

**Backend** (Python 3.12):

```bash
cd backend
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --port 8000 --env-file ../.env
```

**Frontend** (Node.js 22+), in a second terminal:

```bash
cd frontend
cp .env.example .env                 # VITE_API_BASE_URL=http://localhost:8000
npm install
npm run dev                          # http://localhost:5173
```

### Backend tests

```bash
cd backend
python -m pytest            # 61 tests, ~4 s
```

The tests never call Gemini: the internet is blocked in `conftest.py` and every key gets a LiteLLM
`mock_response`. They cover health, validation (422), multi-turn history, failover (429/500/502/503, `*`),
the 503 path (nothing stored), the failure-simulation header and the cache (hit/miss, identical reply, tokens,
`key_id = null`, faster than live).

### Project structure

```
backend/
  app/
    main.py        FastAPI app: routes, CORS, JSON-only error handling
    config.py      settings from environment variables
    schemas.py     request/response models (field names = API contract)
    db.py          SQLite storage (sessions + messages), schema created on startup
    llm.py         LiteLLM Router (key pool + fallbacks) and in-memory cache
    simulate.py    X-Simulate-Failure parser + LiteLLM hook that fakes provider errors
  tests/           pytest suite (no network)
  Dockerfile       multi-stage
frontend/
  src/App.jsx              chat state, session id, sending, errors
  src/api.js               fetch wrapper, readable error messages
  src/components/          ChatMessage (reply + metadata), Composer, SettingsPanel
  Dockerfile, nginx.conf   multi-stage build -> nginx on :3000
docker-compose.yml, Makefile, .env.example
```

---

## 3. Design decisions: key fallback, caching, SQLite session storage

### Key fallback (LiteLLM Router)

- Each API key is its **own Router deployment / model group**, named after its public id
  (`model_name = "key_1"`, `model_info.id = "key_1"`). The real key only lives in `litellm_params.api_key`
  and is never logged or returned.
- Every request asks for `key_1`, with `fallbacks=[{"key_1": ["key_2", ...]}]`. If `key_1` raises a
  rate-limit (429), quota, 5xx or timeout error, the Router repeats the **same messages** on `key_2`, and so on.
- `num_retries=0`: don't retry the same broken key, go straight to the next one.
- `disable_cooldowns=True`: a failure (real or simulated) must not "bench" a key for the following requests;
  each request starts with `key_1` again.
- The Router reports what happened, so I didn't write my own retry loop:
  - `key_id` = `response._hidden_params["model_id"]` (the deployment that answered),
  - `fallback_attempts` = the `x-litellm-attempted-fallbacks` header LiteLLM adds.
- If the last key also fails, the endpoint returns **503 `{"detail": "all providers unavailable"}`** and
  nothing is saved. An empty reply from the provider is treated as a failure too (never a blank 200).
- **Failover test hook:** `X-Simulate-Failure` is parsed into e.g. `{"key_1": 429}` and stored in a
  `ContextVar` (so concurrent requests never see each other's header). A LiteLLM callback
  (`async_pre_call_check`) runs **after the Router picks a key and before Gemini is called**; if that key is listed,
  it raises the same LiteLLM exception a real provider error would (`RateLimitError`, `InternalServerError`,
  `BadGatewayError`, `ServiceUnavailableError`). So the simulated path goes through exactly the same fallback
  code as a real failure. A badly formatted header returns 422; with `ENABLE_FAILURE_SIMULATION=false` the
  header is ignored.

### Caching (LiteLLM built-in, in-memory)

- `litellm.cache = Cache(type="local", ttl=3600, max_messages=None)` + Router `cache_responses=True`.
- **Cache key = model + the full message list** (system prompt + history + new message). So:
  - the same first message in a new session → `LLM_CACHE` with the identical reply,
  - a different message, a different system prompt or a different history → miss → `LIVE_INFERENCE`.
- `caching_groups=[("key_1", "key_2", ...)]`: by default LiteLLM puts the model *group* name in the cache key,
  so a reply that came from `key_2` after a fallback would never be found when asking `key_1`. One caching
  group means all keys share one cache. The API key itself is not part of the cache key.
- `max_messages=None`: LiteLLM skips caching for requests with more than 4 messages by default; I wanted every
  conversation length to be cacheable.
- On a hit (`_hidden_params["cache_hit"]`): `resolution_source = LLM_CACHE`, `key_id = null`,
  `fallback_attempts = 0`, and the tokens are the usage stored with the cached response.
- LiteLLM writes to the cache in a background task *after* returning. The backend waits for that write before
  responding, so an identical request sent straight after is already a hit.
- **Warm-up at startup:** the first cache hit made LiteLLM import heavy modules (~600 ms). On startup the app
  does one mock call + one mock hit (`mock_response`, no Gemini call, no quota), then flushes the cache.
  Result: cache hits take a few milliseconds (e.g. live 1175 ms → cache 8 ms on the deployed app).
- `X-Simulate-Failure` is checked before any key is called, so `*=429` still returns 503 even if the message
  is cached; `key_1=429` on a cached message is answered from cache.
- Why in-memory and not disk: simplest option, no extra dependency, fast. Trade-off: the cache is per process
  and empties on restart (fine for this app; history itself is in SQLite).

### SQLite session storage

- Python's built-in `sqlite3`, no ORM. The schema is created on startup (`CREATE TABLE IF NOT EXISTS`):
  - `messages` (exactly the required columns: `id`, `session_id`, `role`, `content`, `metadata` JSON,
    `created_at` ISO-8601) + index on `(session_id, id)`,
  - `sessions` (`session_id`, `system_prompt`, `created_at`) to remember a custom system prompt per session.
- The client sends only the new message; the backend loads the history from SQLite and builds the full list
  `system + history + new message` for the LLM.
- System prompt priority: prompt sent in this request → prompt saved for this session → `DEFAULT_SYSTEM_PROMPT`.
  It is never returned by the history endpoint.
- The user message and the reply are saved **together in one transaction, only after the LLM succeeded**.
  So a 422 or 503 request leaves no half-saved turn.
- WAL journal mode, so reads don't block the writer. A fresh connection per operation keeps it simple and safe
  with async FastAPI.
- `DATABASE_URL` points to `/data/app.db`, which is a named Docker volume, so history survives restarts.
- `/health` returns 200 only when keys are configured and the database answers `SELECT 1`.

### Errors

- Validation (missing/empty/too long `message` or `session_id`, malformed JSON) → FastAPI's 422 `{"detail": [...]}`.
  Whitespace is trimmed before the 1–4000 length check.
- A small middleware catches any unexpected exception and returns `500 {"detail": "internal server error"}`,
  so no stack trace or HTML page ever reaches the client (the full error is in the server log).
- In the UI, 422 / 503 / network errors appear as a readable red message in the chat; nothing crashes.

---

## 4. Verification: how to see failover, cache hits and per-message token usage

Set the base URL (live or local):

```bash
B=https://llm-chat-g7w1.onrender.com     # or http://localhost:8000
```

> On Windows PowerShell use `curl.exe` (not `curl`), or simply use the Swagger UI at `$B/docs`.

### Health

```bash
curl $B/health
# {"status":"ok","keys_configured":2,"cache_enabled":true}
```

### Live reply, multi-turn and per-request tokens

```bash
curl -X POST $B/chat -H "Content-Type: application/json" \
  -d '{"session_id":"demo-1","message":"Name three primary colours."}'
# resolution_source LIVE_INFERENCE, key_id key_1, fallback_attempts 0, input_tokens ~17

curl -X POST $B/chat -H "Content-Type: application/json" \
  -d '{"session_id":"demo-1","message":"Which one did you list second?"}'
# the bot remembers turn 1; input_tokens is bigger (history is sent) but it is THIS request only

curl $B/sessions/demo-1/messages
# 4 messages, oldest first, metadata only on assistant messages, no system prompt
```

### Cache hit

Send the **same first message in a new session**:

```bash
curl -X POST $B/chat -H "Content-Type: application/json" \
  -d '{"session_id":"demo-2","message":"Name three primary colours."}'
# resolution_source LLM_CACHE, identical reply, key_id null, fallback_attempts 0,
# same tokens as the original, latency a few ms instead of ~1000 ms
```

### Failover with `X-Simulate-Failure`

```bash
curl -X POST $B/chat -H "Content-Type: application/json" -H "X-Simulate-Failure: key_1=429" \
  -d '{"session_id":"demo-3","message":"Say hi in French."}'
# 200, key_id key_2, fallback_attempts 1, a real answer

curl -X POST $B/chat -H "Content-Type: application/json" -H "X-Simulate-Failure: key_1=500" \
  -d '{"session_id":"demo-3","message":"Say hi in Spanish."}'
# 200, key_id key_2, fallback_attempts 1

curl -i -X POST $B/chat -H "Content-Type: application/json" -H "X-Simulate-Failure: *=429" \
  -d '{"session_id":"demo-3","message":"This one fails."}'
# 503 {"detail":"all providers unavailable"}; GET /sessions/demo-3/messages does not contain it
```

### Errors

```bash
curl -i -X POST $B/chat -H "Content-Type: application/json" -d '{"session_id":"x","message":"   "}'   # 422
curl -i -X POST $B/chat -H "Content-Type: application/json" -d '{bad json'                          # 422
curl -i $B/sessions/does-not-exist/messages                     # 404 {"detail":"session not found"}
```

### In the UI

1. Open the frontend. A new session id is created on every page load.
2. Send a message → the reply shows `LIVE_INFERENCE`, model, latency (`… ms`), In/Out tokens, Key `key_1`, Fallbacks `0`.
3. Click **New chat** (or reload) and send the same first message → `LLM_CACHE`, identical text, Key `none`, much lower latency.
4. In the side panel, set **Failover test** to `key_1 = 429` and send → Key `key_2`, Fallbacks `1`.
5. Set it to `All keys = 429` and send → a readable "Error 503" message in the chat; the turn is not saved.
6. Optional: type a **system prompt** before the first message (e.g. "Answer like a pirate"). It is locked for
   the rest of the session.

The `data-testid`s from the contract are on these elements: `chat-input`, `send-button`, `assistant-message`,
`meta-source`, `meta-model`, `meta-latency`, `meta-input-tokens`, `meta-output-tokens`, `system-prompt-input`.

---

## 5. Setup Used

| Area | What I used |
| --- | --- |
| Editor | **VS Code** |
| AI tools | **Claude Code** (Anthropic's coding assistant), used for checking LiteLLM's Router/cache behaviour with small experiments, writing code and tests, and reviewing them against the API contract. I reviewed, ran and tested every change myself. |
| OS / shell | Windows 11, PowerShell and Git Bash |
| Backend | Python 3.12 in a virtual env created with `uv`, FastAPI, LiteLLM, pytest; Swagger UI (`/docs`) and `curl` for manual API checks |
| Frontend | Node.js, Vite + React, oxlint |
| Containers | Docker Desktop (Compose), `make` (on Windows via `winget install ezwinports.make`) |
| Version control | Git + GitHub |
| Hosting | Render (backend, Docker web service), Vercel (frontend) |
| LLM provider | Google Gemini, 2 API keys from 2 separate Google AI Studio projects |

---

## 6. Bonus features (if any)

| Feature | Why |
| --- | --- |
| **Failover test dropdown** in the UI (sends `X-Simulate-Failure`) | Failover can be shown from the browser, without curl |
| Extra metadata in each reply: **key id** and **fallback attempts** (`meta-key-id`, `meta-fallback-attempts`) | You can see *which* key answered and that a fallback happened |
| **Health badge** in the header (calls `/health`) | Shows at a glance if the backend is awake (useful with Render cold starts) |
| **New chat** button | Starts a new session without reloading; makes the cache demo quick |
| System prompt **locked after the first reply** | The prompt is part of the cache key and of the conversation, so changing it mid-session would be confusing |
| Cache **warm-up** at startup + waiting for the cache write | Even the first cache hit is fast, and an immediate repeat is already a hit |
| `LLM_TIMEOUT_SECONDS` | A hanging key counts as failed and the next key is tried, instead of waiting forever |
| 61 **offline backend tests** | Contract, failover, cache and storage rules are checked without using real quota |
| Docker: **non-root user**, healthcheck, frontend waits for a healthy backend, `make logs` / `make reset` | Safer images and a reliable `make up` |
| Small image for the frontend (nginx serving static files, gzip, long cache for hashed assets) | Fast page loads, ~100 MB image |
| Light/dark theme and a mobile layout | Clean UI on any screen |
| `ALLOWED_ORIGINS` ignores a trailing `/` | A common deployment mistake (`https://site.app/`) would otherwise break CORS |

### Known limitations

- Free Render: cold start (~1 min) and the SQLite file resets on redeploy/restart (no persistent disk on the free plan).
- The response cache is in memory and per process: it is empty after a restart and not shared between replicas.
- A slow provider can make one request take up to `LLM_TIMEOUT_SECONDS × number of keys` before the 503.
