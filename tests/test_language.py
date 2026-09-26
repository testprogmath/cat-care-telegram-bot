"""Russian wording that has produced wrong diary entries before."""

import pytest

from skrypka_bot import db, summary


def test_struggled_free_is_not_vomiting(row):
    """вырвалась = pulled free from your hands. вырвало = vomited."""
    assert not summary.vomited([row(type="state", description="дала 50 мл, вырвалась")])


def test_vomiting_is_vomiting(row):
    assert summary.vomited([row(type="state", description="её вырвало после еды")])


def test_explicit_denial_does_not_count(row):
    assert not summary.vomited([row(type="state", description="поела, рвоты не было")])


def test_food_events_are_not_scanned_for_vomiting(row):
    assert not summary.vomited([row(type="food", description="тошнит")])


@pytest.mark.parametrize(
    "description",
    ["покакала в лоток", "жидкий стул", "понос с утра", "дефекация в 6 утра"],
)
def test_stool_is_recognised(description):
    assert db.is_stool(description)


@pytest.mark.parametrize("description", ["пописала", "сходила на жёлтый коврик", ""])
def test_other_toilet_wording_is_not_stool(description):
    assert not db.is_stool(description)


@pytest.mark.parametrize(
    "text",
    [
        "Кошка выпила 96 мл воды. Если считать ещё 116 мл через зонд, всего минимум 212 мл",
        "суммарно за сутки 300 мл",
    ],
)
def test_daily_recaps_are_recognised(text):
    """A message that sums the day up must not be counted as intake again."""
    assert db._RECAP_RE.search(text)
