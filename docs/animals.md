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

Daily water and calorie goals are per profile, with defaults from
[environment variables](configuration.md). A chat changes its own with `/limit food 225` or
`/limit water 340`, and `/limit food default` goes back to the configured one; the value is
kept on the chat, so it survives restarts and deploys. `/left`, the water reminders, the
daily assessment and the site all count from it, the site's past days included, since the
goal is applied when a page is drawn and not stored with the records. A threshold band
whose target is the goal itself, such as the first cat's calorie target, moves with it;
the alarm levels do not. Water from wet food counts toward the water goal at each
product's moisture fraction.

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

## Feeding reminders

Between 07:00 and 23:00 the bot writes "🍗 Пора предложить еду" when an animal has had no meal
for an hour and a half. The wait starts at the first entry of the day at or after 07:00, of
any kind, so a quiet morning brings no reminder before someone is up and writing. A meal
starts the wait again, and so does a reminder, so an ignored reminder repeats every hour
and a half rather than every check. The job checks every five minutes.

A soup drunk without its pieces and a sauce are not meals: they bring water and few
calories. `foods.is_meal` decides. A pieces answer settles it when there is one ("нет" is not
a meal, "половину" is). Otherwise a row whose name is a Felix Sauce product is not a meal.
Nor is a description that says the pieces were left ("без кусочков", "только бульон",
"кусочки оставила", "кусочки не стал"), or one that says broth, sauce or gravy was drunk or
licked ("выпил бульон", "слизала подливку") without a word on the pieces. The name decides the
product before the description does, because "выпила весь соус из Felix Soup" is a soup.
Against every food row in production on 28.10, 1,350 rows from 04.08, the rule set aside
209; the rows that mention broth, sauce, gravy or pieces were read one by one. A refusal is
not a meal either. An entry dated in the future does not count until its time comes.

The reminder says when the last meal was and how many calories the care day has so far,
counting only entries up to now.

## Stool score and check-ins

A stool whose consistency the message describes gets a score on the 1 to 5 Feline Fecal
Consistency Scale (Koochaki et al., Waltham International Nutritional Sciences Symposium,
2013), which was developed and validated on cats and describes each point as an owner sees
it, litter included: 1 liquid, 2 slimy like pudding, 3 mushy, 4 formed and moist (ideal),
5 hard and dry. A stool with no consistency named gets a reply asking for the score. An
answer to that question with one digit, or a word that names one point ("кашица",
"норма"), scores every stool of the asked message without going through the model; any
other answer is parsed as an ordinary message. A lone digit sent without replying counts as
the answer too when a stool question in that chat is under 30 minutes old and still
unanswered. The score shows next to the stool in the
summary and on the day page, and every score of a day is printed under that day on the
week page's toilet chart and in the stool bar of `/week`, coloured by how far it is from a
formed 4.

Between 09:00 and 22:00, when nothing has been written in a chat for three hours, the bot
asks how the animal is doing. Its question counts as a message, so the next one waits
another three hours. The answer is parsed like any message.

A Felix Soup or Felix Sensations feeding whose message says nothing about the pieces is
counted by the default, broth or gravy only for soup and the usual mix for Sensations, and
gets a reply asking whether the pieces were eaten. An answer to that question ("нет",
"половину", "все") sets how many and recounts the feeding's calories and water from its
grams in code, without the model. A message that is nothing but such an answer counts
without replying too, when exactly one pieces question in that chat is under 30 minutes old
and still unanswered. With two open, as after a soup and a pouch in one message, the bot
cannot tell which one is meant and waits for a reply.

## Hospital pause

While the cat is admitted, nobody at home can offer her water, so reminders become noise.
The word *opname* (or *опнаме*) in any message pauses water and feeding reminders, check-ins and the
daily summary. A message about coming home ("забрали", "домой", "выписали", "ontslag", "naar
huis") or `/reminders on` resumes them. Parsing and commands keep working throughout.
