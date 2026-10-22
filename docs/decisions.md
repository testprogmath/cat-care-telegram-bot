# Decisions

Four times the diary was wrong in a way nobody would have caught from the code. Each entry
says what the numbers were, how the mistake surfaced and what changed. Dates are care days in
October 2026; figures come from the diary rows of those days.

## Drinking time was worth 1.7 times too much water

People do not measure what a cat drinks from a bowl. They watch her and write "пила водичку 40
секунд", so the bot turns seconds into millilitres at a rate per animal. Skripa's rate of
0.275 ml a second came from a single weighing, 14 ml in 51 seconds, and went into her profile
on 12.10 (#63).

On 17.10 the family weighed the bowl around three drinks. It lost 22 g, from 2051 g to 2029 g.
The three drinks were 25, 40 and 70 seconds, which the rate had stored as 7, 11 and 19.5 ml:
37.5 ml against 22. One weighing had looked like a calibration and was a sample of one.

Both weighings together give 36 ml in 186 seconds, about 0.19 ml a second, and that is the
rate now (#96). The two weighings disagree by more than a scale's error, so the rate rests
on both rather than on whichever came last. Earlier records keep the volumes they were stored with; only the three weighed drinks were
corrected to sum to 22 ml.

## A pouch that is mostly gravy

Felix Sensations was counted at the whole food's 0.74 kcal/g. Both cats mostly lick its
gravy and leave the pieces, and an 85 g pouch is 60 g of gravy and 25 g of pieces with very
different values: about 0.40 kcal and 0.88 ml of water per gram of gravy, 1.72 kcal and
0.75 ml per gram of pieces. These are estimates, not lab figures. "30 g, mostly
gravy" had been 22.2 kcal and is 16.0 at a tenth of pieces. On 15.10, recounting three such
feedings took 19.6 kcal off Skripa's day, a twelfth of her 250 kcal goal, and added 6.3 ml of
water.

The prompt now derives calories and water from the share of pieces (#90): none for gravy
alone, the pouch's own 29.4% for the usual mix, the midpoint of a range such as "10-15%".
That was not enough on its own. For gravy alone, which needs no arithmetic, the model left
the calories empty in three of four test runs. The code now fills them from the product's
gravy figure whenever the model leaves them out, and the eval provider applies the same step,
so the regression set checks what reaches the diary rather than what the model said.

## The second handful disappeared

The bot drops a report it has already stored: a resent message or a reply restating it
should not count twice. Two feedings count as one when they are close in time and their names
nest, so "Purina One" and "Purina One with beef" are the same product named more or less
fully.

On 17.10 at 23:55 the chat said "29 kibbles of Purina One", and at 23:57 "and 18 kibbles of
Purina One Zalm". The names nest and dry food has no volume to tell portions apart, so the
second feeding was logged as a duplicate and skipped: 11.6 kcal missing from the day, in
the last minutes before the daily summary went out.

Wet food already treats different volumes as separate portions. For two feedings with no
volume, different calories now do the same (#97); a resent report with the same calories is
still one feeding. The cost is known and accepted: someone who corrects "29 kibbles" with a
new message saying "30" instead of editing the first gets two feedings. An edited message
still replaces its old rows.

## A typo turned 42 kcal into 222

On 16.10 the chat said "Скушала 60 грам важного корма Royal canin light weight care". *Важного*
was a typo for *влажного*, wet. The bot did not know the product, saw no word for wet and
counted it at the prompt's 3.7 kcal/g for dry food: 222 kcal for 60 g of a pouch that is
0.694 kcal/g and 82% water. The day's total went 180 kcal over what she ate, and the 49 ml of water in the
food did not count at all.

This is the expensive direction to be wrong in. A day that reads as close to the calorie goal
is a day nobody offers more food. The product is now in the rules with its label figures and
counts as wet unless the message says dry (#92), and the misspelt message is a case in the
regression set.
