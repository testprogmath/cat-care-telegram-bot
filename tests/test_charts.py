"""The /week chart prints each bar's value."""

from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from skrypka_bot import charts, daily, ingest, profiles, week_view

BERLIN = ZoneInfo("Europe/Berlin")


def test_week_bars_carry_their_values(chat, monkeypatch):
    event = dict(type="food", name=None, dose=None, water_ml=None, kcal=40.0, feeding="tube",
                 amount_ml=None, temp_c=None, liquid=None, water_fraction=None, time=None,
                 description="через зонд")
    ingest.save_message(chat, 1, "owner", datetime(2026, 10, 6, 12, 0, tzinfo=BERLIN), "запись",
                    [SimpleNamespace(**event), SimpleNamespace(**{**event, "feeding": "self", "kcal": 12.0})])
    labels = []
    original = charts.plt.Axes.bar_label

    def record(ax, container, labels_=None, **kwargs):
        labels.append(list(kwargs.get("labels") or labels_ or []))
        return original(ax, container, **kwargs)

    monkeypatch.setattr(charts.plt.Axes, "bar_label", record)
    png = charts.render_week(date(2026, 10, 6), profiles.CHIPUNYA)

    assert png.startswith(b"\x89PNG")
    assert ["", "", "", "", "", "", "40"] in labels
    assert ["", "", "", "", "", "", "12"] in labels
    assert ["", "", "", "", "", "", "52"] in labels


def test_water_drunk_and_water_given_are_separate_parts_of_the_bar(chat, monkeypatch):
    water = dict(type="water", name=None, dose=None, kcal=None, amount_ml=None, temp_c=None,
                 liquid=None, water_fraction=None, time=None)
    ingest.save_message(chat, 1, "owner", datetime(2026, 10, 6, 12, 0, tzinfo=BERLIN), "попил", [
        SimpleNamespace(**water, water_ml=30.0, feeding="self", description="попил 30 мл")])
    ingest.save_message(chat, 2, "owner", datetime(2026, 10, 6, 16, 0, tzinfo=BERLIN), "дала", [
        SimpleNamespace(**water, water_ml=25.0, feeding="tube", description="дала 25 мл")])
    bars = []
    original = charts.plt.Axes.bar

    def record(ax, x, height, *args, label=None, **kwargs):
        bars.append((label, list(height)))
        return original(ax, x, height, *args, label=label, **kwargs)

    monkeypatch.setattr(charts.plt.Axes, "bar", record)
    charts.render_week(date(2026, 10, 6), profiles.CHIPUNYA)

    water_bars = dict(bars[:3])
    assert water_bars["drank"][-1] == 30.0
    assert water_bars["given (tube or syringe)"][-1] == 25.0
    assert water_bars["from wet food"][-1] == 0.0


def _stools(chat_id, *scores):
    stool = dict(type="toilet", name=None, dose=None, water_ml=None, kcal=None, feeding=None, amount_ml=None,
                 temp_c=None, liquid=None, water_fraction=None, time=None, description="покакал")
    for n, score in enumerate(scores, start=1):
        ingest.save_message(chat_id, n, "owner", datetime(2026, 10, 6, 6 + n * 3, 0, tzinfo=BERLIN), "покакал",
                            [SimpleNamespace(**stool, stool_score=score)])


def test_each_stool_score_of_the_day_sits_in_the_stool_bar(chat, monkeypatch):
    _stools(chat, 4, 1)
    texts = []
    original = charts.plt.Axes.text

    def record(ax, x, y, s, *args, **kwargs):
        texts.append((s, kwargs.get("bbox", {}).get("fc")))
        return original(ax, x, y, s, *args, **kwargs)

    monkeypatch.setattr(charts.plt.Axes, "text", record)
    charts.render_week(date(2026, 10, 6), profiles.CHIPUNYA)
    assert ("4", charts.STOOL_TONES["ok"]) in texts
    assert ("1", charts.STOOL_TONES["bad"]) in texts


def test_the_site_lists_each_stool_score_under_its_day(chat):
    _stools(chat, 5, 3)
    rows = daily.day_rows("chipunya", date(2026, 10, 1), date(2026, 10, 6))
    assert rows[-1].stool_scores == [5, 3]
    chart = week_view.mini_chart(rows, 270)
    assert chart.toilet[-1].scores == [(5, "warn"), (3, "warn")]
    assert chart.score_rows == 2
