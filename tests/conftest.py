import sqlite3

import pytest

COLUMNS = (
    "type",
    "description",
    "water_ml",
    "amount_ml",
    "kcal",
    "feeding",
    "liquid",
    "water_fraction",
    "occurred_at",
)


@pytest.fixture(scope="session")
def row():
    """Build a real sqlite3.Row, since the code indexes rows by column name."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    placeholders = ", ".join(f"? AS {name}" for name in COLUMNS)

    def make(**values):
        unknown = set(values) - set(COLUMNS)
        assert not unknown, f"unknown columns: {unknown}"
        return conn.execute(
            f"SELECT {placeholders}", [values.get(name) for name in COLUMNS]
        ).fetchone()

    return make
