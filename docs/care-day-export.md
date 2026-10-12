# CareDay v1 export

`care-export --subject chipunya --since 2026-09-19 --until 2026-09-27` writes one JSONL
record per care day, for downstream clinical tooling. It reads the database and writes
nothing. `--pretty` indents each record for reading by eye. Identity of a record is
`(source, subject_id, care_day)`; `content_hash` covers everything except `exported_at`
and debug fields, with lists sorted, so it does not move when database row order does.

## A null is not a zero

The owner writes down what they notice, so every quantity here is a floor over what was
recorded. Nothing recorded means null.

| Field | Meaning when null | Meaning when set |
|---|---|---|
| `food_kcal` | no feeding carried a usable calorie value | sum over feedings that did |
| `water_drinking_ml` | no drinking recorded with a volume | sum of recorded volumes |
| `water_from_food_ml` | no feeding recorded at all | water contributed by wet food, per product moisture |
| `urinations_observed` | no urination recorded | how many were recorded |
| `stools_observed` | no stool recorded | how many were recorded |

A logged urination says nothing about whether the cat also defecated unobserved, so the
two counts are independent: a day with three urinations and no stool record reports
`stools_observed: null`, not zero. A toilet attempt without a result counts as neither.

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

The export refuses to run over a window that holds an event with no subject, because
exporting it would attribute one animal's history to another.

Database row ids are not part of the contract. `--debug` adds `debug_event_refs` for
looking things up by hand; de-duplication and reparsing recreate those rows freely, so
nothing downstream may depend on them.

## The care day boundary

One function, `db.care_day`, decides which care day a moment falls in: it reads the moment
on the wall clock of `TIMEZONE` and shifts it by `DAY_START`, so the boundary holds across a
daylight-saving change. A moment without an offset, as in a few early rows, is read as that
wall clock. The same function stamps the `day` column when an event is stored, and the
exporter applies it again to `occurred_at` rather than trusting the column. On 12 October
2026 at 09:13 all 3893 stored events gave the same day both ways.

A change to `DAY_START` moves the boundary for new events only. Stored `day` values keep
the old boundary until they are restamped, and the bot and the site group by that column,
so restamp them in the same deploy.
