# Connecting @Hive to Microsoft Teams

Everything in the repo is ready. What remains is an Azure Bot registration (only you can
do that) plus a public HTTPS URL pointing at your local bot.

**Already verified on this machine:** ngrok 3.39 installed · manifest valid (v1.16, scopes
`personal`/`team`/`groupChat`) · icons correct (192×192 and 32×32) · `botbuilder-core` 4.17.1
imports on Python 3.14 · `.env` created from the template.

---

## 0. Check you are allowed to sideload

Teams admin center → **Teams apps → Setup policies → Global** → *Upload custom apps* must be
**On**. Without it, step 6 fails no matter what else is correct, and only a Teams administrator
can change it. Check this first — it is the most common hard stop.

## 1. Register the Azure Bot

[Azure Portal](https://portal.azure.com) → **Create a resource** → search **Azure Bot** → Create.

| Field | Value |
| --- | --- |
| Bot handle | `hive-levelshift` (any unique name) |
| Subscription / Resource group | your own |
| Pricing tier | **F0** (free) is enough |
| Type of App | **Multi Tenant** |
| Creation type | **Create new Microsoft App ID** |

After it deploys:

1. Open the bot → **Configuration** → copy the **Microsoft App ID**.
2. Click **Manage** (next to the App ID) → **Certificates & secrets** → **New client secret** →
   copy the **Value** immediately (it is shown once).

> `APP_TYPE` in [bot/app.py](../backend/bot/app.py) is `MultiTenant`. If you register a
> single-tenant bot instead, set `AZURE_AD_TENANT_ID` in `.env` and change `APP_TYPE` to
> `SingleTenant`, or authentication will fail with a 401 that looks like a wrong secret.

## 2. Put the credentials in `.env`

```bash
BOT_APP_ID=<the Microsoft App ID>
BOT_APP_PASSWORD=<the client secret Value>
```

Leave the rest as it is — the bot runs against the same SQLite database as the CLI.

## 3. Install the bot dependencies and start it

The Bot Framework SDK is a separate install from the API:

```bash
cd backend
pip install -r requirements-bot.txt
export PYTHONPATH=$PWD        # PowerShell: $env:PYTHONPATH = $PWD
python -m bot.app             # listens on :3978
```

Confirm it is up:

```bash
curl http://localhost:3978/health
# {"status": "ok", "surface": "teams"}
```

The bot talks to the database directly, so **the API server does not need to be running**. Seed
some data first if you have not: `python -m hive.cli seed`.

> **Windows long paths:** if `pip install` fails with
> `OSError: [Errno 2] No such file or directory: ...botframework\connector\token_api\...`, that
> is the 260-character path limit, not a broken package. Either enable long paths
> (`New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name
> LongPathsEnabled -Value 1 -PropertyType DWORD -Force`, then reboot) or use a venv in a short
> path such as `C:\hbv`.

## 4. Expose it over HTTPS

In a second terminal:

```bash
ngrok http 3978
```

Copy the `https://` forwarding URL (e.g. `https://a1b2-c3d4.ngrok-free.app`).

Back in the Azure Bot → **Configuration** → **Messaging endpoint**:

```
https://<your-ngrok-subdomain>.ngrok-free.app/api/messages
```

Click **Apply**.

> The free ngrok URL changes every restart, and you must update the messaging endpoint each
> time. For anything beyond a demo, deploy the bot (`docker compose up bot`, or Azure Container
> Apps) and point the endpoint at its stable URL instead.

## 5. Enable the Teams channel

Azure Bot → **Channels** → **Microsoft Teams** → accept the terms → **Apply**.

Optional smoke test before touching Teams: **Test in Web Chat** on the bot's overview page.
If Web Chat works, the credentials and endpoint are right, and any later failure is Teams-side.

## 6. Build and sideload the app package

```bash
python scripts/build_teams_package.py        # reads BOT_APP_ID from .env
# wrote dist/hive-teams-app.zip (botId <guid>)
```

Teams → **Apps** → **Manage your apps** → **Upload an app** → **Upload a custom app** →
choose `dist/hive-teams-app.zip`.

## 7. Talk to it

```
@Hive who fixed the jwt refresh loop in billing auth?
@Hive who knows billing-service
@Hive kr how do we rotate the ADO service account PAT?
@Hive help
```

Answers arrive as Adaptive Cards carrying their sources. When Hive has no evidence, the card
offers **Raise a Knowledge Request**, which records the gap and routes it to the best-placed
expert.

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| "Upload a custom app" missing in Teams | Sideloading disabled by policy | Teams admin center → Setup policies → Upload custom apps → On |
| Bot never replies; ngrok shows no requests | Messaging endpoint wrong or stale | Re-copy the ngrok URL, keep the `/api/messages` suffix, Apply |
| ngrok shows `401` | `BOT_APP_ID`/`BOT_APP_PASSWORD` wrong, or single- vs multi-tenant mismatch | Re-copy the secret **Value**; check `APP_TYPE` in `bot/app.py` |
| ngrok shows `500` | Dispatch raised | Read the bot terminal; the card reply says "Something broke on my side" |
| Teams says "app package is invalid" | `${{BOT_APP_ID}}` still a placeholder | Rebuild with `scripts/build_teams_package.py`; never zip `appPackage/` by hand |
| Cards render but every answer is an evidence list | No LLM configured | Set `LLM_PROVIDER=azure_openai` + endpoint/deployment (see the README) |
| `ModuleNotFoundError: botbuilder` | SDK not installed in the active interpreter | `pip install -r backend/requirements-bot.txt` |
| Answers say "could not find anything" | Nothing ingested | `python -m hive.cli seed` or `ingest-git --repo <path>` |

## What proactive messages need

Routing a Knowledge Request queues a row in the `notifications` table. Delivery requires two
things: the person must have messaged @Hive at least once (that is what stores their conversation
reference), and the drain task must be running:

```bash
celery -A workers.celery_app worker --loglevel=info   # needs Redis
```

Until then, routings stay `pending` in the outbox — recorded, never lost.
