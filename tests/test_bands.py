"""The «Оценка суток» block: a single target prints as one number."""

from datetime import date

from skrypka_bot import profiles, summary


def test_a_single_target_reads_as_one_number(row):
    lines = summary.render_assessment(
        profiles.SKRIPA,
        [row(type="food", feeding="tube", kcal=225.0, amount_ml=40.0)],
        date(2026, 9, 29),
        None,
    )
    assert "  🍗 Еда: 225 ккал из 225 (100%) — ✅ в цели" in lines
    assert "  💧 Жидкость: 34 мл из 320–370 — 🔴 серьёзная тревога" in lines


def test_three_days_under_80_percent_of_the_goal_raise_the_alarm(chat, monkeypatch, row):
    low = [row(type="food", feeding="self", kcal=150.0)]
    monkeypatch.setattr(summary.db, "events_for_day", lambda subject, day: low)
    lines = summary.render_assessment(profiles.CHIPUNYA, low, date(2026, 11, 18), chat)
    assert lines == ["\n⚖️ Оценка суток:", "  🔴 меньше 80% нормы (216 ккал) 30 суток подряд"]


def test_two_days_under_80_percent_are_not_yet_an_alarm(chat, monkeypatch, row):
    days = {date(2026, 11, 18): [row(type="food", feeding="self", kcal=150.0)],
            date(2026, 11, 17): [row(type="food", feeding="self", kcal=150.0)],
            date(2026, 11, 16): [row(type="food", feeding="self", kcal=260.0)]}
    monkeypatch.setattr(summary.db, "events_for_day", lambda subject, day: days.get(day, []))
    assert summary.render_assessment(profiles.CHIPUNYA, days[date(2026, 11, 18)], date(2026, 11, 18), chat) == []
