# Development

```bash
pip install --require-hashes -r requirements-dev.txt
pip install --no-deps -e .
OPENAI_API_KEY=dummy pytest -q
ruff check .
```

Every dependency is locked with its hashes: `requirements.txt` for the image and the bot,
`requirements-dev.txt` for tests and linting. `pyproject.toml` still says what the project
needs; the lock files say exactly which builds are installed, and pip refuses anything whose
hash differs. After changing a dependency in `pyproject.toml`, regenerate both:

```bash
uv pip compile pyproject.toml --generate-hashes --universal --python-version 3.14 -o requirements.txt
uv pip compile pyproject.toml --extra dev --generate-hashes --universal --python-version 3.14 -o requirements-dev.txt
```

Dependabot proposes version bumps for both files.

There is one Python version, the one in the image. `.python-version` names it, every CI job
and the fuzzer build read it from there, and the image smoke test fails when the `Dockerfile`
runs another. When Dependabot moves the base image to a new Python, change `.python-version`,
`requires-python` and ruff's `target-version` in the same pull request and regenerate the
lock files, the fuzzers' included.

For the bot alone without Docker, run `skrypka-bot` with the variables from
[configuration](configuration.md). The admin API is `care-api`, the site `care-web`.

## What the tests cover

The tests cover the deterministic parts: water from wet food, the care-day boundary,
de-duplication, the CareDay contract, access to the site and the admin API, and Russian
wording that has produced wrong entries before. No test calls the model, so whether a
message produces the right events is not tested; see [the parser](parser.md).

Tests of a rule that does not depend on which cat it is build a made-up animal with
`animal()` from `tests/conftest.py`, with or without a tube.

`tests/test_properties.py` states rules that must hold for every input and lets Hypothesis
look for a counterexample: each instant of a care day's window belongs to that day, a later
instant never falls on an earlier day (including the nights the clocks change), seconds of
drinking round to the nearest half millilitre, and a resent or repeated report adds nothing.

## The prompt regression set

No unit test calls the model, so `evals/` holds a promptfoo set instead: real kinds of messages,
each with the events the parser must produce for it. `evals/provider.py` runs the bot's own
`parse_message` and applies the gravy fill-in the bot applies before storing, so a case checks
what reaches the diary; `evals/assert_events.py` compares only the fields a case lists, numbers
within 1% or 0.05. It calls OpenAI, so it costs a little and needs the key:

```bash
pip install --require-hashes -r requirements.txt
pip install --no-deps -e .
cd evals
OPENAI_API_KEY=... PYTHONPATH=.. PROMPTFOO_PYTHON=$(which python) \
  npx -y promptfoo@0.124.1 eval -c promptfooconfig.yaml --no-cache
```

Add a case whenever a message was parsed wrong and the prompt was fixed for it. Write the
message for the set or cut it down to the words that matter: the cases are public, so no
names of people, places, clinics or sums of money from the chats.

The `Prompt eval` workflow runs the set on every pull request that changes `parser.py`, the prompts in `prompts/`,
`profiles.py` or `evals/`, with `OPENAI_API_KEY` from the `prompt-eval` environment. Each run
writes a table of every case to the job's summary, with the reason next to each failure, and
keeps `results.json` as an artifact for 30 days.

## Fuzzing

`fuzz/` holds Atheris fuzzers for code that reads free text from the chats or works with
arbitrary moments: the toilet classifier, product names, dose normalisation and the care-day
boundary, whose result must be the local date or the day before. ClusterFuzzLite builds them
from `.clusterfuzzlite/` and runs them for two minutes on every pull request that changes
`skrypka_bot/`, `fuzz/` or `.clusterfuzzlite/`, and for half an hour every Sunday night. The
pull request gets one comment, updated on each run, with the result, the kind of crash if
there was one, how many crashing inputs were saved and a link to the run.

The ClusterFuzzLite base image comes with its own Python 3.11, so `.clusterfuzzlite/Dockerfile`
installs the version in `.python-version` with uv and builds the fuzzers in that Python, with
atheris and pyinstaller from `.clusterfuzzlite/requirements.txt`. That file is locked with
hashes like the others:

```bash
uv pip compile .clusterfuzzlite/requirements.in --generate-hashes --python-version 3.14 \
  --python-platform x86_64-manylinux_2_17 -o .clusterfuzzlite/requirements.txt
```

To run one by hand for a minute:

```bash
pip install atheris -e .
python fuzz/text_fuzzer.py -max_total_time=60
```

## CI

On every pull request and every push to `main`:

- `lint`: `ruff check`. The rules and the few deliberate exceptions are in `pyproject.toml`.
- `tests`: pytest. octocov reads the coverage report and
  comments on the pull request with coverage, the code to test ratio and the time of the
  test step, compared with `main`. On `main` it stores the report as a workflow artifact
  for that comparison, and the `coverage-badge` job puts the coverage badge on the
  `badges` branch, where the README reads it. The settings are in `.octocov.yml`.
- `static`: shellcheck on the deploy scripts, hadolint on the Dockerfile, actionlint and
  zizmor on the workflows, and gitleaks on the whole git history.
- `build`: the Docker image, then `tests/image_smoke.py` inside it: every entry point imports,
  the image runs the Python in `.python-version`, a message writes two rows to a scratch
  database and reads them back, and the prompt files are there. It catches a file left out of the image, which the tests run from source cannot.

The `Scorecard` workflow runs on every push to `main` and every Saturday. It rates the
repository on the OpenSSF Scorecard checks (pinned dependencies, token permissions, branch
protection, code review and more), publishes the score behind the README badge, and adds its
findings to code scanning under the Security tab.

CodeRabbit reviews every pull request with the rules in `.coderabbit.yaml`. Its comments are
advice, not approval: it never approves a pull request by itself.

Every action is pinned to a commit and every tool image to a digest. The octocov binary
is pinned by version and checksum as well, because its action otherwise downloads the
latest release. Dependabot proposes updates for pip, GitHub Actions and the base image
every week.
