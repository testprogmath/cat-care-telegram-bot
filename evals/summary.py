"""Turn promptfoo's results.json into a Markdown table for the GitHub job summary."""

import json
import sys


def describe(result: dict) -> str:
    return (result.get("testCase") or {}).get("description") or result.get("description") or ""


def why(result: dict) -> str:
    reason = (result.get("gradingResult") or {}).get("reason") or result.get("error") or ""
    return reason.replace("|", "\\|").replace("\n", " ")[:300]


def main(path: str) -> None:
    with open(path) as file:
        results = json.load(file)["results"]["results"]
    passed = sum(1 for r in results if r.get("success"))
    lines = [f"### Prompt eval: {passed} of {len(results)} passed", "",
             "| | Case | Message | Why it failed |", "|---|---|---|---|"]
    for r in sorted(results, key=lambda r: bool(r.get("success"))):
        ok = r.get("success")
        lines.append(f"| {'✅' if ok else '❌'} | {describe(r)} | {r['vars'].get('text', '')} | {'' if ok else why(r)} |")
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1])
