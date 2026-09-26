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
  feeds it inverts: "gave 30 ml through the tube" is an actual feed.
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
| `/left` | water and calories so far, and what remains |
| `/risk` | end-of-day projection from the current pace |
| `/week` | four charts: water, calories, litter box, temperature |
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

`./deploy.sh` rsyncs to a VPS and restarts the container there. It needs `DEPLOY_HOST` set.

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
