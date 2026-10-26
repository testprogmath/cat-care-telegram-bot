"""promptfoo assertion: the parsed events match the expected ones, field by field."""

import json

from skrypka_bot import classify

TOLERANCE = 0.05


def _matches(expected: dict, actual: dict) -> bool:
    for key, want in expected.items():
        if key == "infusion":
            if classify.is_infusion(actual.get("description")) != want:
                return False
            continue
        got = actual.get(key)
        if isinstance(want, (int, float)) and not isinstance(want, bool):
            if not isinstance(got, (int, float)) or abs(got - want) > max(TOLERANCE, abs(want) * 0.01):
                return False
        elif want != got:
            return False
    return True


def get_assert(output, context):
    actual = json.loads(output)
    expected = context["vars"]["expected"]
    unmatched = list(actual)
    for want in expected:
        hit = next((a for a in unmatched if _matches(want, a)), None)
        if hit is None:
            return {"pass": False, "score": 0, "reason": f"no event matches {want}; got {actual}"}
        unmatched.remove(hit)
    if unmatched:
        return {"pass": False, "score": 0, "reason": f"unexpected events {unmatched}"}
    return {"pass": True, "score": 1, "reason": "events match"}
