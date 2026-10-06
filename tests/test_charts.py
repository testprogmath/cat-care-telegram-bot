"""The /week chart prints each bar's value."""

from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from skrypka_bot import charts, db, profiles

BERLIN = ZoneInfo("Europe/Berlin")


def test_week_bars_carry_their_values(chat, monkeypatch):
    event = dict(type="food", name=None, dose=None, water_ml=None, kcal=40.0, feeding="tube",
                 amount_ml=None, temp_c=None, liquid=None, water_fraction=None, time=None,
                 description="через зонд")
    db.save_message(chat, 1, "owner", datetime(2026, 10, 6, 12, 0, tzinfo=BERLIN), "запись",
                    [SimpleNamespace(**event), SimpleNamespace(**{**event, "feeding": "self", "kcal": 12.0})])
    labels = []
    original = charts.plt.Axes.bar_label

    def record(ax, container, labels_=None, **kwargs):
        labels.append(list(kwargs.get("labels") or labels_ or []))
        return original(ax, container, **kwargs)

    monkeypatch.setattr(charts.plt.Axes, "bar_label", record)
    png = charts.render_week(chat, date(2026, 10, 6), profiles.CHIPUNYA)

    assert png.startswith(b"\x89PNG")
    assert ["", "", "", "", "", "", "40"] in labels
    assert ["", "", "", "", "", "", "12"] in labels
    assert ["", "", "", "", "", "", "52"] in labels
