"""/stats and /left end with a link to that day on the family site."""

from datetime import date

from skrypka_bot import main, profiles


def test_the_link_opens_the_day_page(monkeypatch):
    monkeypatch.setenv("WEB_BASE_URL", "https://cats.example/")
    text = main.with_site_link("сводка", profiles.CHIPUNYA, date(2026, 10, 8))
    assert text == "сводка\n\n🔗 https://cats.example/chipunya/day/2026-10-08"


def test_without_a_site_the_text_is_unchanged(monkeypatch):
    monkeypatch.delenv("WEB_BASE_URL", raising=False)
    assert main.with_site_link("сводка", profiles.SKRIPA, date(2026, 10, 8)) == "сводка"
