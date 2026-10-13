"""The prompt files reach the model complete: joined lines, every placeholder filled."""

import re

from conftest import animal

from skrypka_bot import parser
from skrypka_bot.profiles import Tube


def test_a_backslash_at_a_line_end_joins_the_lines():
    assert "\\\n" not in parser.SYSTEM_PROMPT_TEMPLATE
    assert "\\\n" not in parser.CONDENSE_PROMPT


def test_every_placeholder_is_filled_from_the_profile():
    tube = Tube(water_portion_ml=25.0, max_feed_ml=100.0, feeding_field="TUBE RULES")
    for profile in (animal(feeding_field="NO TUBE RULES"), animal(tube=tube)):
        prompt = parser.system_prompt(profile)
        assert not re.search(r"\{[a-z_]+(:[^}]*)?\}", prompt)
    assert "TUBE RULES" in parser.system_prompt(animal(tube=tube))
