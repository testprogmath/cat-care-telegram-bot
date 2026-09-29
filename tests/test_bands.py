"""The «Оценка суток» block: a single target prints as one number."""

from datetime import date

from skrypka_bot import profiles, summary


def test_a_single_target_reads_as_one_number(row):
    lines = summary.render_assessment(
        profiles.SKRIPA,
        [row(type="food", feeding="tube", kcal=250.0, amount_ml=40.0)],
        date(2026, 9, 29),
        None,
    )
    assert "  🍗 Еда: 250 ккал из 250 — ✅ в цели" in lines
    assert "  💧 Жидкость: 34 мл из 320–370 — 🔴 серьёзная тревога" in lines
