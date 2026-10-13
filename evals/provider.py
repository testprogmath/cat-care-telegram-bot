"""promptfoo provider: the bot's own parser, run on one chat message for one animal."""

import asyncio
import json
from dataclasses import replace

from skrypka_bot import parser, profiles


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
    return {"output": json.dumps([e.model_dump(exclude_none=True) for e in events], ensure_ascii=False)}
