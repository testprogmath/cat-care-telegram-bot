# The parser

Every message in a chat with an animal goes to the model with that animal's prompt
(`parser.py` plus the profile's own rules in `profiles.py`) and comes back as zero or
more typed events. The README lists the traps the prompt has to avoid. This page shows
what an answer looks like and what the code checks before an answer reaches the diary.

## An example

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

## What the code checks after the model

The model's answer is not stored blindly. Before events reach the diary:

- Food and water from a message that reads like a daily recap are discarded. The test is
  a word list (`_RECAP_RE` in `db.py`: "за сутки", "за день", "в сумме" and a few more),
  so a real feed written as "за день первый раз съела 5 г" is discarded too.
- For an animal with a tube, a single tube feed above the tube's limit (100 ml by default)
  is rejected as implausible.
- A repeated report replaces or yields to what is stored. Within five minutes, a more
  detailed feeding replaces a less detailed one, an exact water volume replaces an
  estimate such as "попила немного", and a longer description of the same toilet visit
  replaces a shorter one. For the same medication the window is ten minutes. Visits
  counted in one message ("два раза пописала") are all kept.
- Every replacement is written to `event_edits` with action `dedup` and the full row it
  removed. A row added through the admin API is never replaced.

## When parsing fails

| What happened | What the bot does |
|---|---|
| OpenAI did not answer, or answered with an error | Keeps the message unparsed and retries every 15 minutes. Warns the chat at most every two hours and names the cause: no credit left, or OpenAI not answering. |
| The model answered without a usable result (a refusal, a cut-off or filtered answer) | Keeps the message, records nothing from it, and replies that it could not read the message and asks for different wording. It does not retry. |
| The bot itself failed | Logs the traceback, keeps the message for retry, and warns the chat that this is a bug in the bot. |

An outage therefore delays diary entries rather than losing them.

## Changing the prompt

Every new message in every chat goes through the prompt, and a lost rule raises no error:
the bot starts writing wrong calories or dropping events, and the wrong numbers reach the
summaries, charts, before-and-after comparisons and the CareDay export. No test checks the
model's answers today. Run a change against a set of real messages before and after, and
read every difference, before it reaches `main`.
