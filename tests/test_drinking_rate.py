"""Water from seconds of drinking uses the animal's own rate."""

from conftest import animal

from skrypka_bot import parser


def test_the_prompt_states_the_animals_rate_and_examples_worked_out_with_it():
    prompt = parser.system_prompt(animal(drinking_ml_per_second=0.275))
    assert ("считай объём как секунды × 0.275 мл, округляя до 0.5 мл: «попила секунд 10» → "
            "3 мл, «пила 40 секунд» → 11 мл.") in " ".join(prompt.split())


def test_seconds_turn_into_millilitres_rounded_to_half_a_millilitre():
    cat = animal(drinking_ml_per_second=0.275)
    assert [parser.drunk_ml(cat, s) for s in (51, 30, 5)] == [14.0, 8.5, 1.5]
