# Cat Care Telegram Bot

A care diary for a seriously ill cat, kept by the people who live with her.

Nobody types structured data at 3am. They type "gave 30 ml through the tube, she pulled
free halfway" into the family group chat. This bot reads those messages, turns them into
structured events, and answers the question the vet asks at every visit: how much did she
actually eat and drink yesterday?

Written to keep one cat alive through a feeding tube, then extended to a second cat in a
second chat. Both are still using it.

## How it works

Every message in the group goes to an LLM with a per-animal prompt, and comes back as zero
or more typed events: medication with dose, water in ml, food with calories, litter box,
body temperature, general state. Events land in SQLite. Commands and the daily summary read
from there.

The interesting part is everything the prompt has to get right, because a diary that
silently miscounts is worse than no diary:

- **Offered is not eaten.** "Put down 12 g" creates no event. "Ate 6 g" does. For tube
  feeds it inverts: "gave 30 ml through the tube" is an actual feed. "Would not touch the
  Urinary Care" is a refusal, recorded with the product name and never counted as food.
- **Water comes from food too.** Each wet product carries its own moisture fraction from
  the manufacturer's label, not a flat guess. 50 g of a pouch at 78.2% moisture is 39.1 ml
  of water toward the daily goal.
- **Recipes are not feeds.** "Diluted 50 g of pâté with 50 ml of water" describes
  preparation. No event.
- **Homographs bite.** In Russian, *вырвалась* means "struggled free" and *вырвало* means
  "vomited". One letter apart, and vomiting is a reason to call the clinic tonight.
- **Daily recaps are not intake.** A message summing up the day must not be counted again.

Each named product the cats actually eat is in the prompt with its label figures, so
"32 kibbles" becomes 7.1 g becomes 28 kcal rather than a number made up on the spot.

### An example

A synthetic message and the events the parser schema expects for it. This illustrates the
output shape; it is not a recorded model response, and the chats are in Russian.

> дала 30 мл Trovet через зонд, потом 10 мл воды
> *(gave 30 ml of Trovet through the tube, then 10 ml of water)*

```json
[
  {"type": "food", "feeding": "tube", "amount_ml": 30, "kcal": 20.7,
   "liquid": true, "water_fraction": 0.87, "description": "Trovet через зонд, 30 мл"},
  {"type": "water", "water_ml": 10, "description": "вода, 10 мл"}
]
```

That message counts as 36.1 ml of water toward the daily goal: 10 ml drunk plus 26.1 ml from
the food. The message "насыпала 12 г, не ест" (*put down 12 g, she is not eating*) produces
no events at all.

### What the code checks after the model

The model's answer is not stored blindly. Before events reach the diary:

- Food and water from a message that reads like a daily recap ("за сутки", "в сумме") are
  discarded.
- A single tube feed above 100 ml is rejected as implausible (`TUBE_MAX_SINGLE_ML`).
- An exact figure in millilitres replaces a vague water estimate ("drank a little") logged
  within five minutes of it, and a repeated report of the same feed within five minutes
  keeps only the more detailed entry.
- If the OpenAI call fails, the message is stored unparsed and retried every 15 minutes, so
  an outage delays diary entries rather than losing them.

## Commands

| | |
|---|---|
| `/stats` | today's diary, or `/stats 2026-08-03` for a given day |
| `/left` | water and calories so far, and what remains; also sent as a reply to every message that adds calories |
| `/risk` | end-of-day projection from the current pace |
| `/week` | four charts: water, calories, litter box, temperature |
| `/meds` | medications for the last seven days as a grid of doses per day; `/meds all` for the whole diary, `/meds 2026-09-01 2026-09-30` for a period, both followed by a chart of doses over time |
| `/autoleft` | turn the automatic `/left` reply on or off for this chat: `/autoleft off`, `/autoleft on` |
| `/profile` | which animal this chat tracks |
| `/reminders` | pause or resume water reminders |

A summary is posted automatically at the day boundary. Water reminders fire every two hours
between 09:00 and 23:00, and only when intake is behind the pace needed to reach the goal.

**Projection, not judgement.** Verdicts are only given for finished days. Halfway through
any day every total looks like a disaster, so `/stats` shows bare numbers until midnight
and `/risk` does the extrapolating: it divides intake by the fraction of the 09:00–23:00
window that has passed.

**Hospital pause.** While the cat is admitted, nobody at home can offer her water, so
reminders become noise. The word *opname* in any message pauses reminders and the daily
summary; a message about coming home resumes them. Parsing keeps running throughout.

**Alarm thresholds** are per animal and live in `profiles.py`, derived from body weight and
diagnosis. Below a threshold the daily summary says so in plain language. The second cat has
none, because borrowing another animal's numbers would be worse than staying quiet.

## Multiple animals

One bot, one animal per chat. A profile holds the names, clinical parsing rules, and daily
goals; `chats.profile` maps a chat to one. The profile is guessed from the chat title on the
first message and can be changed with `/profile`.

Each profile carries two identifiers, and the difference matters. `key` is internal: it names
the profile in configuration and on the command line, and renaming it is an ordinary refactor.
`subject_id` is external: it is stored on every event and downstream systems key their own
records on it, so changing one is a migration on both sides rather than a rename. They happen
to hold the same string today.

## CareDay v1 export

`care-export --subject chipunya --since 2026-09-19 --until 2026-09-27` writes one JSONL
record per care day, for downstream clinical tooling. It reads the database and writes
nothing. Identity of a record is `(source, subject_id, care_day)`; `content_hash` covers
everything except `exported_at` and debug fields, with lists sorted, so it does not move
when database row order does.

The contract's one rule worth stating twice: **a null is not a zero.** The owner writes
down what they notice, so every quantity here is a floor over what was recorded. Nothing
was recorded means null.

| Field | Meaning when null | Meaning when set |
|---|---|---|
| `food_kcal` | no feeding carried a usable calorie value | sum over feedings that did |
| `water_drinking_ml` | no drinking recorded with a volume | sum of recorded volumes |
| `water_from_food_ml` | no feeding recorded at all | water contributed by wet food, per product moisture |
| `urinations_observed` | no urination recorded | how many were recorded |
| `stools_observed` | no stool recorded | how many were recorded |

A logged urination says nothing about whether the cat also defecated unobserved, so the
two counts are independent: a day with three urinations and no stool record reports
`stools_observed: null`, not zero.

**Every requested day is emitted, including empty ones.** An empty record means nothing is
currently recorded for that subject and day, not that nothing happened. It exists so a
snapshot can empty a day that an earlier import filled, after a correction or a deletion
in cat-care.

`vomiting_asserted_absent` is the one negative the parser can establish, because the chat
says so in as many words. No episode and no such statement stays unknown: empty
`vomiting_episodes` with the flag false.

`food_refusals` lists food the owner offered and the cat refused, with the product when the
chat names it. It is never counted in `food_events_recorded`. An empty list means no refusal
was written down, not that the cat ate everything offered.

The `*_fully_quantified` flags mean **all recorded events of that kind carried a number**,
and nothing more. They are not a claim that the owner observed everything the cat ate or
drank; cat-care cannot know that. `food_kcal_fully_quantified: true` alongside
`food_events_recorded: 1` means exactly one feeding was noticed and it had a calorie value.

Database row ids are not part of the contract. `--debug` adds `debug_event_refs` for
looking things up by hand; deduplication and reparsing recreate those rows freely, so
nothing downstream may depend on them.

### Care day: known debt

The boundary lives in two places. `db.care_day` stamps the `day` column at insert time
using `_DAY_START_HOUR`, parsed once at import, and applies it to whatever datetime it is
handed. The exporter recomputes the care day itself from the same constant, in the
timezone named by `TIMEZONE`, on wall-clock time so the boundary holds across a
daylight-saving change. Neither `db.DAY_START` as a string nor `TIMEZONE` is read by
`db.py` at all, and the container's own clock is UTC.

They agree today, checked over all 2709 stored events. They should eventually be one
timezone-aware primitive rather than two implementations that happen to match.

## Admin API

The admin API lets you inspect and fix diary rows that the parser got wrong. It runs as a
second container, `api`, from the same image.

The API listens on `127.0.0.1:8180` on the server only. Every request needs the token from
`API_TOKEN`. To reach the API, open an SSH tunnel from your local port 8080:

```bash
ssh -L 8080:127.0.0.1:8180 deploy@<host>
```

Then, from a second terminal:

```bash
export API_TOKEN=...   # the same value as in .env
AUTH="Authorization: Bearer $API_TOKEN"

curl -H "$AUTH" 'http://127.0.0.1:8080/events?subject=chipunya'
curl -H "$AUTH" 'http://127.0.0.1:8080/events?subject=skripa&day=2026-09-29&type=food'
curl -H "$AUTH" http://127.0.0.1:8080/events/3029
curl -H "$AUTH" -X PATCH -H 'content-type: application/json' \
  -d '{"kcal": 8.6, "water_fraction": 0.795}' http://127.0.0.1:8080/events/3029
curl -H "$AUTH" -X DELETE 'http://127.0.0.1:8080/events/2949?confirm=true'
curl -H "$AUTH" http://127.0.0.1:8080/events/3029/edits
```

| Request | Result |
|---|---|
| `GET /events` | Rows of one care day: id, time, type, description, kcal, water, amount. The day is today unless you give `day`. `subject` and `type` filter. |
| `GET /events/{id}` | Every column of one row, and the chat message it came from. |
| `PATCH /events/{id}` | Sets `type`, `description`, `kcal`, `water_ml`, `amount_ml`, `water_fraction`, `name`, `dose`, `liquid`, `feeding` or `occurred_at`. Send `null` to clear a field. |
| `DELETE /events/{id}?confirm=true` | Deletes one row and returns it. Without `confirm=true` the API refuses. |
| `GET /events/{id}/edits` | The history of changes to one row, newest first, also after a delete. |

Rules:

- Look up the id with `GET /events` right before a `PATCH` or `DELETE`. Row ids change
  when the bot deduplicates or reparses a message.
- `occurred_at` takes an ISO 8601 time. A time without an offset is read in `TIMEZONE`.
  The API recomputes the care day from the new time.
- The API stores values as you give them. It does not check that a value fits the type
  of the row.
- Every change writes the old and new values to `event_edits`. To undo a change, send a
  `PATCH` with the `before` values from `/edits`.
- The next `/stats` in the chat and the next `care-export` show the change at once.

Generate the token once and put it in `.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

The API does not start without a token of at least 32 characters.

## Web pages for the family

`care-web` serves read-only pages from the same database: a week table and charts, every
event of a day with the message it came from, medications, foods and refusals. It runs as a
third container, `web`, on `127.0.0.1:8280`, and mounts `data/` read-only. Nothing on these
pages writes to the diary; edits stay with the admin API.

Sign-in is Telegram's OpenID Connect login. A person sees an animal only while they are a
member of that animal's chat: the page asks Telegram with `getChatMember` and remembers the
answer for ten minutes. Add someone to the chat to give them access, remove them to take it
away. The bot must be an administrator of each chat, with no rights, because Telegram only
guarantees `getChatMember` for administrators.

The `web` container gets only the variables it needs, not the whole `.env`:

| Variable | |
|---|---|
| `WEB_BASE_URL` | the public address, e.g. `https://cats.khvorostianova.com` |
| `WEB_SESSION_SECRET` | at least 32 characters; signs the session cookie |
| `TELEGRAM_OPENID_CLIENT_ID`, `TELEGRAM_OPENID_CLIENT_SECRET` | from BotFather → the bot → Login Widget → OpenID Connect |
| `TELEGRAM_BOT_TOKEN` | for `getChatMember` |

In BotFather, register `<WEB_BASE_URL>/auth/callback` as an allowed URL.

The foods page groups recorded names into one product each ("hills digestive care",
"hill's prescription diet i/d" → Hill's i/d). The rules are in `foods.py`. A refusal that
names two foods counts once for each.

## Running it

```bash
cp .env.example .env   # fill in TELEGRAM_BOT_TOKEN and OPENAI_API_KEY
docker compose up -d --build
```

The database lives in `./data/`, mounted as a volume, and survives rebuilds. For local
development without Docker, `pip install -e .` and run `skrypka-bot` with the same
environment.

In BotFather, disable privacy mode for the bot, otherwise it never sees ordinary group
messages.

`./deploy.sh` rsyncs to a VPS and restarts the containers there, the bot and the admin
API. It needs `DEPLOY_HOST` set. Use it only when the release workflow cannot run.

## Releases and deploys

Every merge to `main` is a release. When CI passes on `main`, the `Release` workflow tags
the merge commit, publishes a GitHub Release with notes generated from the merged pull
requests, and deploys that tag to the server.

The label on the pull request sets the version, as in semantic versioning:

| Label | Version change | Use it for |
|---|---|---|
| `release:major` | `v1.4.2` → `v2.0.0` | a change a consumer must adapt to, e.g. the CareDay contract |
| `release:minor` | `v1.4.2` → `v1.5.0` | a new command or feature |
| `release:patch` | `v1.4.2` → `v1.4.3` | a fix |
| `release:skip` | no release, no deploy | docs and CI changes |

The `Release label` check fails on a pull request until it has exactly one of these
labels. The first release is `v1.0.0`. The version in `pyproject.toml` is not updated; the tag is
the version.

The workflow cannot open a shell on the server. Its SSH key runs one command,
`deploy/redeploy`, which accepts only a tag name. The script checks out that tag in the
server's git checkout, then builds and restarts the containers. `data/` and `.env` are
ignored by git and stay in place.

### One-time setup

On your machine, create a key for the workflow and read the server's host key:

```bash
ssh-keygen -t ed25519 -N "" -C github-actions-deploy -f ~/.ssh/skrypka_deploy
ssh-keyscan -t ed25519 <host>
```

On the server, turn the deploy directory into a git checkout. Tracked files are replaced
by the same files from git. `data/` and `.env` do not change.

```bash
cd ~/apps/skrypka-telegram-bot
git init -q
git remote add origin https://github.com/testprogmath/cat-care-telegram-bot.git
git fetch -q origin main
git checkout -f -B main origin/main
```

On the server, add one line to `~/.ssh/authorized_keys`. Put the content of
`~/.ssh/skrypka_deploy.pub` after the options:

```
restrict,command="/home/deploy/apps/skrypka-telegram-bot/deploy/redeploy" ssh-ed25519 AAAA... github-actions-deploy
```

In the repository settings, create the environment `production`, allow only `main` to
deploy to it, and add three secrets to it:

| Secret | Value |
|---|---|
| `DEPLOY_SSH_KEY` | the content of `~/.ssh/skrypka_deploy` |
| `DEPLOY_KNOWN_HOSTS` | the output of `ssh-keyscan` |
| `DEPLOY_HOST` | `deploy@<host>` |

Create the labels `release:major`, `release:minor`, `release:patch` and `release:skip`.
In the branch protection for `main`, make `release-label` a required status check.

To deploy a tag by hand, use the same key: `ssh -i ~/.ssh/skrypka_deploy deploy@<host> v1.2.3`.
To roll back, deploy an earlier tag the same way.

## Configuration

| Variable | Default | |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | from BotFather |
| `OPENAI_API_KEY` | — | |
| `OPENAI_MODEL` | `gpt-5-mini` | model used for parsing |
| `TIMEZONE` | `Europe/Berlin` | |
| `DAY_START` | `11:00` | day boundary, and the time the daily summary is posted |
| `DB_PATH` | `data/skrypka.db` | |
| `SKRIPA_WATER_GOAL_ML` `SKRIPA_KCAL_GOAL` | `340` `310` | daily goals, first cat |
| `CHIPUNYA_WATER_GOAL_ML` `CHIPUNYA_KCAL_GOAL` | `340` `295` | daily goals, second cat |
| `API_TOKEN` | — | required by the admin API, at least 32 characters |
| `API_HOST` `API_PORT` | `127.0.0.1` `8080` | admin API listener inside the container; compose sets `API_HOST=0.0.0.0` and publishes it as `127.0.0.1:8180` on the host |
| `DEPLOY_HOST` `DEPLOY_KEY` `DEPLOY_DIR` | — | used by `deploy.sh` only |

Python 3.11+, python-telegram-bot, APScheduler, matplotlib, SQLite. No ORM, no migrations
framework: schema changes are `ALTER TABLE` guarded by a column check at startup.

## Tests

```bash
pip install -e '.[dev]'
OPENAI_API_KEY=dummy pytest -q
```

The tests cover the deterministic parts: water from wet food, the care-day boundary, and
Russian wording that has produced wrong entries before. CI runs them on Python 3.11 and
3.12 and builds the Docker image. No test calls the model.

## Limits

- The classification rules above live in the prompt, so they are model judgements. No
  automated test checks that a given message produces the right events.
- Parsing is written for Russian-language chats. Messages in other languages are handled
  only as far as the model follows the prompt.
- One animal per chat, one running instance, one SQLite file.
- The diary records what people report. It does not give medical advice, and the alarm
  thresholds belong to one specific animal; they are not general clinical guidance.
