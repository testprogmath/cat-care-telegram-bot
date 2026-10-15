"""promptfoo provider: the bot's own parser on one chat message, with the fill-in the bot applies before storing."""

import asyncio
import json
from dataclasses import replace

from skrypka_bot import foods, parser, profiles


def call_api(prompt, options, context):
    test = context["vars"]
    profile = profiles.get(test["animal"])
    if test.get("tube") == "out":
        profile = replace(profile, tube=None)
    parser.client.cache_clear()
    try:
        events = asyncio.run(parser.parse_message(
            test["text"], test.get("history", []), test.get("reply_to"), bool(test.get("report_shown")), profile,
        ))
    except (parser.ParseFailed, parser.ParseRefused) as failure:
        return {"error": f"{type(failure).__name__}: {failure}"}
    for event in events:
        if event.type == "food":
            foods.fill_gravy(event)
    return {"output": json.dumps([e.model_dump(exclude_none=True) for e in events], ensure_ascii=False)}
