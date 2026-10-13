"""Any moment, in any offset: its care day is the local date or the day before, never further."""

import sys
from datetime import datetime, timedelta, timezone

import atheris

with atheris.instrument_imports():
    from skrypka_bot import db


def test_one_input(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    moment = datetime(2000, 1, 1) + timedelta(seconds=fdp.ConsumeIntInRange(0, 100 * 365 * 86400))
    if fdp.ConsumeBool():
        moment = moment.replace(tzinfo=timezone(timedelta(minutes=fdp.ConsumeIntInRange(-14 * 60, 14 * 60))))
    local = moment.astimezone(db.timezone()).date() if moment.tzinfo else moment.date()
    assert db.care_day(moment) in (local, local - timedelta(days=1)), moment


def main() -> None:
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
