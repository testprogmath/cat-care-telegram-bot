"""promptfoo provider: the bot's own parser on one chat message, with the fill-in the bot applies before storing."""

import asyncio
import json
from dataclasses import replace

from skrypka_bot import foods, parser, profiles


async def _parse(test, profile):
    """Parse in this call's event loop and close the client in it, before the loop ends."""
    parser.client.cache_clear()
    try:
        return await parser.parse_message(
            test["text"], test.get("history", []), test.get("reply_to"), bool(test.get("report_shown")), profile,
        )
    finally:
        await parser.client().close()


def call_api(prompt, options, context):
    test = context["vars"]
    profile = profiles.get(test["animal"])
    if test.get("tube") == "out":
        profile = replace(profile, tube=None)
    try:
        events = asyncio.run(_parse(test, profile))
    except (parser.ParseFailed, parser.ParseRefused) as failure:
        return {"error": f"{type(failure).__name__}: {failure}"}
    for event in events:
        if event.type == "food":
            foods.fill_gravy(event)
    return {"output": json.dumps([e.model_dump(exclude_none=True) for e in events], ensure_ascii=False)}
