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
or more typed events: medication with dose, water in ml and whether the cat drank it or was given it, food with
calories, refusals, litter box, body temperature, weight, breathing rate, general state.
Events land in SQLite. Commands and the daily summary read
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
"32 kibbles" becomes 7.1 g becomes 28 kcal rather than a number made up on the spot. The
code then checks the answer before it is stored: it drops daily recaps, rejects
implausible tube feeds and merges repeated reports. [The parser](docs/parser.md) has an
example and the full list.

## Commands

| | |
|---|---|
| `/stats` | today's diary; `/stats 2026-08-03` for a given day, `/stats 09:00` for the 24 hours from that time |
| `/left` | water and calories so far, and what remains; also sent as a reply to every message that adds calories |
| `/autoleft` | turn that automatic reply off or on: `/autoleft off`, `/autoleft on` |
| `/risk` | end-of-day projection from the current pace |
| `/week` | four charts: water, calories, litter box, temperature |
| `/meds` | medications for the last seven days as a grid of doses per day; `/meds all` for the whole diary, `/meds 2026-09-01 2026-09-30` for a period, both followed by a chart of doses over time |
| `/profile` | which animal this chat keeps; `/profile <имя>` assigns a free one |
| `/reminders` | whether water reminders and the daily summary run; `/reminders off`, `/reminders on` |
| `/help` | what the bot does and how it counts |

A summary is posted at the start of each care day, midnight by default. Water reminders
come every two hours between 09:00 and 23:00, only when the animal is behind the day's
schedule, and say how far behind. [Animals, goals and reminders](docs/animals.md) has the
rules, including the pause while a cat is in hospital.

The family also gets [web pages](docs/web.md) with the same diary: the week, every day by
the hour, medications, foods and refusals.

## Running it

```bash
cp .env.example .env
docker compose up -d --build bot
```

The bot needs only `TELEGRAM_BOT_TOKEN` and `OPENAI_API_KEY`. The `api` and `web`
containers each need their own secrets and do not start without them; see
[configuration](docs/configuration.md). The database lives in `./data/`, mounted as a
volume, and survives rebuilds.

In BotFather, disable privacy mode for the bot, otherwise it never sees ordinary group
messages. Then add the bot to a chat and assign the animal with `/profile <имя>`.

## Documentation

- [The parser](docs/parser.md): an example answer, the checks after the model, what
  happens when parsing fails.
- [Animals, goals and reminders](docs/animals.md): one chat per animal, the tube,
  thresholds, reminders, the hospital pause.
- [CareDay v1 export](docs/care-day-export.md): the contract for downstream tools.
- [Admin API](docs/admin-api.md): fixing and adding diary rows, moving a diary.
- [Web pages](docs/web.md): sign-in, who sees what, Caddy.
- [Configuration](docs/configuration.md): every environment variable, and which secrets
  matter.
- [Releases and deploys](docs/deploy.md): labels, the deploy key, rollback, setup.
- [Development](docs/development.md): tests and CI.
- [Security](SECURITY.md): reporting a vulnerability, and where the sensitive parts are.

Python 3.11+, python-telegram-bot, APScheduler, matplotlib, FastAPI, SQLite. No ORM, no
migrations framework.

## Limits

- The classification rules live in the prompt, so they are model judgements. No automated
  test checks that a given message produces the right events.
- Parsing is written for Russian-language chats. Messages in other languages are handled
  only as far as the model follows the prompt.
- One animal per chat, one running instance, one SQLite file.
- The diary records what people report. It does not give medical advice, and the alarm
  thresholds belong to one specific animal; they are not general clinical guidance.
