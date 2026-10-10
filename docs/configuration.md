# Configuration

All settings are environment variables. On the server they live in `.env`, which git
ignores and deploys leave in place. `.env.example` lists the ones a new install fills in.

## Bot and admin API

`bot` and `api` read the whole `.env`.

| Variable | Default | |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | none | from BotFather; the bot does not start without it |
| `OPENAI_API_KEY` | none | |
| `OPENAI_MODEL` | `gpt-5-mini` | model used for parsing |
| `TIMEZONE` | `Europe/Berlin` | the zone the care day and all times are read in |
| `DAY_START` | `00:00` | where one care day ends and the next begins, and when the daily summary is posted |
| `DB_PATH` | `data/skrypka.db` | |
| `SKRIPA_WATER_GOAL_ML` `SKRIPA_KCAL_GOAL` | `340` `250` | daily goals, first cat |
| `CHIPUNYA_WATER_GOAL_ML` `CHIPUNYA_KCAL_GOAL` | `340` `295` | daily goals, second cat |
| `TUBE_MAX_SINGLE_ML` | `100` | a single tube feed above this is rejected as implausible |
| `LIQUID_FOOD_WATER_FRACTION` | `0.85` | water fraction for a liquid food stored without its own |
| `WEB_BASE_URL` | none | when set, `/stats` and `/left` end with a link to that day on the site |
| `API_TOKEN` | none | required by the admin API, at least 32 characters |
| `API_HOST` `API_PORT` | `127.0.0.1` `8080` | admin API listener inside the container; compose sets `API_HOST=0.0.0.0` and publishes it as `127.0.0.1:8180` on the host |
| `CARE_EXPORT_INSTANCE` | the host name | `source_instance` in CareDay records |
| `DEPLOY_HOST` `DEPLOY_KEY` `DEPLOY_DIR` | none | read by `deploy.sh` on your machine only |

The goal variables are named after the profile `key`, as `<KEY>_WATER_GOAL_ML` and
`<KEY>_KCAL_GOAL`.

## Web

`web` gets only these, from `docker-compose.yml`:

| Variable | |
|---|---|
| `WEB_BASE_URL` | the public address, e.g. `https://cats.khvorostianova.com` |
| `WEB_SESSION_SECRET` | at least 32 characters; signs the session cookie |
| `TELEGRAM_OPENID_CLIENT_ID` `TELEGRAM_OPENID_CLIENT_SECRET` | from BotFather, Login Widget, OpenID Connect |
| `TELEGRAM_BOT_TOKEN` | for `getChatMember` |
| `TIMEZONE` `DAY_START` `DB_PATH` | as above, with the same defaults |
| the four goal variables | as above |
| `DB_READ_ONLY` | compose sets `1`; the pages open the database read-only |
| `WEB_HOST` `WEB_PORT` | `127.0.0.1` `8080` inside the container; compose sets `WEB_HOST=0.0.0.0` and publishes it as `127.0.0.1:8280` |

## Secrets

Three values in `.env` give real power to whoever holds them:

- `TELEGRAM_BOT_TOKEN`: reads and writes in every chat the bot is in.
- `API_TOKEN`: with an SSH tunnel, rewrites or deletes any diary row.
- `WEB_SESSION_SECRET`: signs a cookie for any Telegram user id, so it lets someone sign
  in to the site as anyone.

`OPENAI_API_KEY` and `TELEGRAM_OPENID_CLIENT_SECRET` cost money or identity if they leak.
Generate the two random secrets with
`python -c "import secrets; print(secrets.token_urlsafe(32))"`.
