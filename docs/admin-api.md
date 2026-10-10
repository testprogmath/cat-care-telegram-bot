# Admin API

The admin API lets you inspect and fix diary rows that the parser got wrong, add rows the
chat never had, and move an animal's diary to another chat. It runs as the `api` container,
from the same image as the bot.

## Reach it

The API listens on `127.0.0.1:8180` on the server only. Every request needs the token from
`API_TOKEN`. Open an SSH tunnel from your local port 8080:

```bash
ssh -L 8080:127.0.0.1:8180 deploy@<host>
```

Then, from a second terminal:

```bash
export API_TOKEN=...   # the same value as in the server's .env
AUTH="Authorization: Bearer $API_TOKEN"

curl -H "$AUTH" 'http://127.0.0.1:8080/events?subject=chipunya'
curl -H "$AUTH" 'http://127.0.0.1:8080/events?subject=skripa&day=2026-09-29&type=food'
curl -H "$AUTH" http://127.0.0.1:8080/events/3029
curl -H "$AUTH" -X PATCH -H 'content-type: application/json' \
  -d '{"kcal": 8.6, "water_fraction": 0.795}' http://127.0.0.1:8080/events/3029
curl -H "$AUTH" -X DELETE 'http://127.0.0.1:8080/events/2949?confirm=true'
curl -H "$AUTH" http://127.0.0.1:8080/events/3029/edits
curl -H "$AUTH" -X POST -H 'content-type: application/json' \
  -d '{"subject": "skripa", "type": "weight", "occurred_at": "2026-09-28T12:00:00", "weight_kg": 7.61, "description": "вес 7,61 кг"}' \
  http://127.0.0.1:8080/events
curl -H "$AUTH" http://127.0.0.1:8080/chats
```

## Requests

| Request | Result |
|---|---|
| `GET /events` | Rows of one care day: id, time, type, description, kcal, water, amount. The day is today unless you give `day`. `subject` and `type` filter. |
| `POST /events` | Creates one row the chat never had, e.g. a weighing told by voice: `subject`, `type`, `occurred_at`, `description`, and the fields `PATCH` takes. The care day comes from the time. |
| `GET /events/{id}` | Every column of one row, and the chat message it came from. |
| `PATCH /events/{id}` | Sets `type`, `description`, `kcal`, `water_ml`, `amount_ml`, `water_fraction`, `name`, `dose`, `liquid`, `feeding`, `weight_kg`, `breaths`, `asleep` or `occurred_at`. Send `null` to clear a field. |
| `DELETE /events/{id}?confirm=true` | Deletes one row and returns it. Without `confirm=true` the API refuses. |
| `GET /events/{id}/edits` | The history of changes to one row, newest first, also after a delete. |
| `GET /chats` | Every chat the bot has seen: `chat_id`, `title`, `profile`. |
| `PATCH /chats/{chat_id}` | Sets the chat's `profile`, or clears it with `null`. Answers 409 if another chat already keeps that animal's diary. |

## Rules

- Look up the id with `GET /events` right before a `PATCH` or `DELETE`. De-duplication
  can replace a row with a more detailed one, and the new row has a new id.
- `occurred_at` takes an ISO 8601 time. A time without an offset is read in `TIMEZONE`.
  The API recomputes the care day from the new time.
- The API stores values as you give them. It does not check that a value fits the type
  of the row.
- Every create, change and delete writes the old and new values to `event_edits`. To undo
  a change, send a `PATCH` with the `before` values from `/edits`.
- A row you create has no chat message. De-duplication never replaces such a row: a later
  chat message about the same moment is skipped instead.
- The next `/stats` in the chat, the site and the next `care-export` show the change at once.

## Move a diary to another chat

One chat keeps one animal's diary. To move it:

1. Send `GET /chats` and find both chat ids. The new chat appears after its first message.
2. Clear the old chat: `PATCH /chats/<old id>` with `{"profile": null}`.
3. Set the new chat: `PATCH /chats/<new id>` with `{"profile": "<key>"}`.

The old chat goes silent after step 2. Rows already stored keep their chat and their
subject; the bot does not move them. The CareDay export reads by subject, so it keeps the
whole history. The bot's summaries and most figures on the site read by chat, so they show
only what the new chat recorded.

## Token

Generate the token once and put it in the server's `.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

The API does not start without a token of at least 32 characters. Anyone who has the
token and a tunnel can rewrite or delete the diary, so keep it only in `.env` and in your
password manager.
