"""Run inside the built image, not by pytest: the code and its data files are in place and a message writes rows."""

import os
import pathlib
import tempfile
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

os.environ.setdefault("OPENAI_API_KEY", "smoke")

from skrypka_bot import (  # noqa: E402, F401
              api,
              care_export,
              db,
              ingest,
              main,
              parser,
              profiles,
              web,
)

db.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "smoke.db"
db.init()
db.set_profile(-1, "chipunya")
now = datetime.now(ZoneInfo("Europe/Berlin"))
fields = dict(name=None, dose=None, water_ml=None, kcal=None, feeding="self", amount_ml=None, temp_c=None,
              liquid=None, water_fraction=None, time=None)
ingest.save_message(-1, 1, "smoke", now, "съел 5 г, попил 10 мл", [
    SimpleNamespace(**{**fields, "type": "food", "kcal": 18.5, "description": "съел 5 г"}),
    SimpleNamespace(**{**fields, "type": "water", "water_ml": 10.0, "description": "попил 10 мл"}),
])
stored = [(r["type"], r["kcal"], r["water_ml"], r["subject"]) for r in db.events_for_day("chipunya", db.care_day(now))]
assert stored == [("food", 18.5, None, "chipunya"), ("water", None, 10.0, "chipunya")], stored

prompt = parser.system_prompt(profiles.SKRIPA)
assert len(prompt) > 10_000 and "{subject}" not in prompt, len(prompt)
print(f"image smoke ok: {len(stored)} rows written and read, prompt {len(prompt)} characters")
