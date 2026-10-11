# Animals, goals and reminders

## One animal per chat

A profile in `profiles.py` holds an animal's names, its parsing rules, its daily goals and
whether it has a feeding tube. `chats.profile` ties a chat to one profile, and one profile
to at most one chat: the database refuses a second chat for the same animal.

- On a chat's first message the bot guesses the profile from the chat title, skipping
  animals another chat already keeps.
- A chat with no profile stays silent. The bot neither parses nor stores its messages,
  answers no command there except `/profile <имя>`, and leaves it out of summaries,
  reminders, the site and the admin API.
- `/profile <имя>` assigns a free animal to the chat. It refuses an animal another chat
  keeps. To move a diary, see [the admin API](admin-api.md#move-a-diary-to-another-chat).

Each profile carries two identifiers, and the difference matters. `key` is internal: it
names the profile in configuration and on the command line, and renaming it is an ordinary
refactor. `subject_id` is external: it is stored on every event and downstream systems key
their own records on it, so changing one is a migration on both sides rather than a
rename. They happen to hold the same string today.

## The tube

What depends on a feeding tube depends on whether the profile has a `tube`, not on which
animal it is. A tube carries two numbers: the most water that is safe to give at once (25
ml for the first cat) and the largest plausible single feed (100 ml, `TUBE_MAX_SINGLE_ML`).
The water reminder splits portions only for an animal with a tube, and the
implausible-feed check applies only to one.

## Goals and thresholds

Daily water and calorie goals are per profile and can be changed with
[environment variables](configuration.md). Water from wet food counts toward the water
goal at each product's moisture fraction.

Alarm thresholds are per animal too, derived from body weight and diagnosis. Below a
threshold the daily summary says so in plain language. The second cat has none, because
borrowing another animal's numbers would be worse than staying quiet.

## Projection, not judgement

Verdicts are only given for finished days. Halfway through any day every total looks like
a disaster, so `/stats` shows bare numbers until the care day ends, and `/risk` does the
extrapolating: it divides intake by the fraction of the 09:00 to 23:00 window that has
passed.

## Water reminders

At 09:00, 11:00 and every two hours to 23:00 the bot compares each animal's water with an
even schedule: the daily goal spread over 09:00 to 23:00. It writes only when the animal is
more than 25 ml behind. The reminder says how much there is, how much the schedule expects
by now and how much is missing. For an animal with a tube it also splits what is left of
the goal into portions no larger than the tube takes, for example "примерно 9 раз по ~24 мл
(не больше 25 мл за раз)".

## Hospital pause

While the cat is admitted, nobody at home can offer her water, so reminders become noise.
The word *opname* (or *опнаме*) in any message pauses water reminders and the daily
summary. A message about coming home ("забрали", "домой", "выписали", "ontslag", "naar
huis") or `/reminders on` resumes them. Parsing and commands keep working throughout.
