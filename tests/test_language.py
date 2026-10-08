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
    assert not summary.vomited([row(type="food", description="вырвало")])


@pytest.mark.parametrize("description", ["тошнит", "сохраняется тошнота", "подташнивает"])
def test_nausea_is_not_vomiting(row, description):
    assert not summary.vomited([row(type="state", description=description)])


@pytest.mark.parametrize(
    "description",
    ["покакала в лоток", "жидкий стул", "понос с утра", "дефекация в 6 утра", "немного какала",
     "какает в лоток"],
)
def test_stool_is_recognised(description):
    assert db.is_stool(description)


@pytest.mark.parametrize("description", ["пописала", "сходила на жёлтый коврик", "какао", ""])
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


@pytest.mark.parametrize(
    "description",
    [
        "пыталась какать, ничего не получилось",
        "тужится, пробует покакать (третий раз)",
        "покопала горшок",
        "22 августа не какала",
        "не писает",
        "подходила к лотку, не получилось (1 из 2)",
        "не сделала никакой туалет (не помочила/не покакала)",
    ],
)
def test_attempts_without_a_result_are_failed(description):
    assert db.toilet_kind(description) == "failed"


@pytest.mark.parametrize(
    ("description", "kind"),
    [
        ("покакала тремя маленькими какашечками — не успели упасть, вытерла", "stool"),
        ("покакала, часть прилипла к попе, достать не получается", "stool"),
        ("покопала, посидела и покакала", "stool"),
        ("тужилась и пописала", "urine"),
        ("пописала, не очень много", "urine"),
    ],
)
def test_a_visit_with_a_result_counts(description, kind):
    assert db.toilet_kind(description) == kind
