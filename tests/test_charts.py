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


def test_water_drunk_and_water_given_are_separate_parts_of_the_bar(chat, monkeypatch):
    water = dict(type="water", name=None, dose=None, kcal=None, amount_ml=None, temp_c=None,
                 liquid=None, water_fraction=None, time=None)
    db.save_message(chat, 1, "owner", datetime(2026, 10, 6, 12, 0, tzinfo=BERLIN), "попил", [
        SimpleNamespace(**water, water_ml=30.0, feeding="self", description="попил 30 мл")])
    db.save_message(chat, 2, "owner", datetime(2026, 10, 6, 16, 0, tzinfo=BERLIN), "дала", [
        SimpleNamespace(**water, water_ml=25.0, feeding="tube", description="дала 25 мл")])
    bars = []
    original = charts.plt.Axes.bar

    def record(ax, x, height, *args, label=None, **kwargs):
        bars.append((label, list(height)))
        return original(ax, x, height, *args, label=label, **kwargs)

    monkeypatch.setattr(charts.plt.Axes, "bar", record)
    charts.render_week(chat, date(2026, 10, 6), profiles.CHIPUNYA)

    water_bars = dict(bars[:3])
    assert water_bars["drank"][-1] == 30.0
    assert water_bars["given (tube or syringe)"][-1] == 25.0
    assert water_bars["from wet food"][-1] == 0.0
