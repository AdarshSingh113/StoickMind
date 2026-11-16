# Running and deploying Kotler AI (free)

Kotler AI has two programs:

| Program | Command | What it is for |
|---|---|---|
| **API server + app** | `uvicorn kotler.server:app` | Landing page, the React dashboard (all screens), Telegram/WhatsApp webhooks, website chat |
| Classic dashboard | `streamlit run app.py` | Optional: the original Streamlit version, handy for ML exploration |

The API server serves the React app itself (after `cd frontend && npm run build`), so **deploying the server
deploys the dashboard too, on the same database as the chats.** Streamlit reads the same SQLite file
(`data/kotler.db`, or `KOTLER_DB_PATH`) only when it runs on the same machine.

## Secrets

Never commit them. Locally: `.streamlit/secrets.toml` (git-ignored) or environment variables.

| Name | Needed for |
|---|---|
| `GEMINI_API_KEY` | all AI replies |
| `TELEGRAM_BOT_TOKEN` | Telegram (from @BotFather) |
| `TELEGRAM_WEBHOOK_SECRET` | Telegram webhook mode (any random string) |
| `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN` | WhatsApp sending |
| `WHATSAPP_APP_SECRET` | checking Meta's signature |
| `WHATSAPP_VERIFY_TOKEN` | Meta's webhook handshake (any random string) |
| `WHATSAPP_ALLOWED_NUMBERS` | comma-separated test numbers, e.g. `919812345678` |
| `KOTLER_ALLOWED_ORIGINS` | sites allowed to use the chat widget (default `*`) |
| `KOTLER_ADMIN_PASSWORD` | dashboard login. **Required in production** (login is disabled without it) |
| `KOTLER_SECRET_KEY` | optional: signs login cookies (default: derived from the password) |

Generate a random secret: `python -c "import secrets; print(secrets.token_urlsafe(24))"`

## Option A: Telegram with polling (easiest, nothing to host)

Polling means *our* program asks Telegram "any new messages?" in a loop, so no public URL is needed.

1. Telegram → @BotFather → `/newbot` → copy the token.
2. On your laptop or in a GitHub Codespace:

```bash
export TELEGRAM_BOT_TOKEN=...  GEMINI_API_KEY=...
python -m kotler.channels.telegram poll
```

3. Message your bot. In another terminal run `streamlit run app.py` and open **Channels** to watch the chat.

It runs while the terminal runs. Great for learning and demos.

## Option B: GitHub Codespaces (both programs, public URL)

1. On GitHub: **Code → Codespaces → Create codespace**.
2. In its terminal:

```bash
pip install -r requirements.txt
(cd frontend && npm ci && npm run build)
uvicorn kotler.server:app --host 0.0.0.0 --port 8000 &
streamlit run app.py
```

3. In the **Ports** tab, set port 8000 to *Public* and copy its URL.
4. Dashboard: open that URL and log in. Demo store with the website chat: `/store`. Telegram webhook:

```bash
python -m kotler.channels.telegram set-webhook https://YOUR-URL/webhooks/telegram
```

Same machine, same database: the dashboard sees every conversation. Codespaces stop when idle (free hours apply).

## Option C: Render free web service (always-on URL)

1. render.com → **New → Web Service** → connect the repo → Render detects the **Dockerfile**: choose it.
   (The image builds the React app with Node, then serves everything from Python.)
2. Add the secrets above under **Environment**, at least `KOTLER_ADMIN_PASSWORD` and `GEMINI_API_KEY`.
3. Open `https://YOUR-APP.onrender.com`, log in.

The Dockerfile hasn't been built in this project's CI yet (no Docker there); if Render reports a build error,
the message names the failing line.
4. Point Telegram (`set-webhook`) and Meta (webhook URL `https://YOUR-APP.onrender.com/webhooks/whatsapp`,
   verify token = `WHATSAPP_VERIFY_TOKEN`, subscribe to **messages**) at it.

Limits of the free plan: it sleeps after ~15 min idle (the first message wakes it, ~30 s; Telegram retries, and
our de-duplication makes retries harmless), and its disk is **temporary**, so the SQLite file resets on redeploy.
The Streamlit Cloud dashboard is a different machine and won't see these chats. For a learning project that's
fine; a real business would move to a hosted database (e.g. free Postgres) shared by both programs.

## WhatsApp (Meta Cloud API, free test number)

1. developers.facebook.com → **Create app** → Business → add **WhatsApp**.
2. **API Setup**: copy the phone number ID and temporary access token; add your own number(s) as recipients.
3. **App settings → Basic**: copy the app secret.
4. Configure the webhook (Option B or C URL) and subscribe to `messages`.
5. Message the test number from your phone first: the 24-hour window opens and the bot can reply.

The code only ever sends to `WHATSAPP_ALLOWED_NUMBERS`.

## Website widget on any site

```html
<script src="https://YOUR-APP/widget.js" defer></script>
```

Set `KOTLER_ALLOWED_ORIGINS=https://your-shop.com` so other sites can't use your AI quota.
