# What the diary does not yet watch

Measured against how a veterinary ward monitors a patient, the diary is strong on what goes
into the cat: calories, water, medication and food, each with its figures. It is weaker on
what comes out and on how she feels, and it never checks that the treatment plan was
followed. The gaps below are ordered by how much they matter, as of 25.10.2026.

These are notes on how to keep the record, not medical advice. Which of them matter most
depends on each cat's diagnosis and is a question for the vet: for the kidneys urine output
counts more, for the gut vomiting and stool do.

## 1. Doses are recorded, but not checked against a plan

The bot knows what was given and not what should have been. It cannot see a missed dose,
nor a second dose given too early; a second Cerenia dose on one day nearly got into the
diary from a message that only told about yesterday (see [the parser](parser.md)). A ward
keeps a treatment sheet with drug, dose and time.

What it would take: a plan per animal (`/meds plan`), a reminder when a dose is due, a
warning when one is missed or repeated early, and adherence in the report for the vet.

## 2. Urine is counted, not measured

The diary knows how many times the cat urinated and nothing about how much. For a cat on
subcutaneous fluids the volume says whether the fluid is passing through. At home it is
judged by the litter clumps, by size (small, normal, large) or by weighing a clump, along
with colour and any blood. Today "a huge puddle" and "a drop" count the same.

## 3. Pain and wellbeing are free text

"Вялая", "колбасилась" and "живёт свою лучшую жизнь" sit in the diary as descriptions and
never form a trend. Validated scales exist that owners can use: the Feline Grimace Scale
scores five features of the face from 0 to 2, and the HHHHHMM quality-of-life scale
(Villalobos) covers the day as a whole. One score a day, asked the way the stool score is,
would give the vet a line instead of a set of impressions.

## 4. Weight is occasional, and body condition is not scored

Weight is recorded when someone remembers. For a cat that eats poorly, weighing every two
or three days on the same scale at the same time is the usual advice, and it would let the
bot warn about, say, a 3% loss in a week. A body condition score (BCS, 1 to 9) and a muscle
condition score every week or two would catch muscle lost while the weight holds.

## 5. "Not recorded" and "did not happen" look the same

At night and when nobody watches, some feedings and visits to the litter box never reach
the diary. On the charts such a day looks like a day without food or a stool. The CareDay
export already keeps the difference ("no stool observed" rather than zero); the site and
the summaries do not. A note for unwatched stretches ("ночь не наблюдали", "по камерам")
would tell a low figure from an empty one.

## 6. Vomiting has no structure

How often, what came up (food, foam, bile, hair) and how long after a meal are the
details a vet asks for first, and each points somewhere different. Today they are only in
the description, when someone writes them.

## 7. Lab results live outside the diary

Creatinine, SDMA, haematocrit and glucose from the clinic are not recorded anywhere here.
On the same time axis as food, water and medication they would show, for example, how the
kidney values moved after Ringer's started.

## 8. Only one cat has agreed targets

Alarm thresholds exist for Skripa alone. Chipunya has none, and his 340 ml water goal was
derived from his weight when the bot was set up and was never confirmed. Targets and
thresholds for both are worth agreeing with the vet once and writing down in
[their profiles](animals.md).

## Where to start

Gaps 1 and 5 are the most valuable and take about a day each to build. Gap 3 reuses the
stool question as it stands.
