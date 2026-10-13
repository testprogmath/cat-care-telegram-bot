# Development

```bash
pip install -e '.[dev]'
OPENAI_API_KEY=dummy pytest -q
ruff check .
```

For the bot alone without Docker, run `skrypka-bot` with the variables from
[configuration](configuration.md). The admin API is `care-api`, the site `care-web`.

## What the tests cover

The tests cover the deterministic parts: water from wet food, the care-day boundary,
de-duplication, the CareDay contract, access to the site and the admin API, and Russian
wording that has produced wrong entries before. No test calls the model, so whether a
message produces the right events is not tested; see [the parser](parser.md).

Tests of a rule that does not depend on which cat it is build a made-up animal with
`animal()` from `tests/conftest.py`, with or without a tube.

## The prompt regression set

No unit test calls the model, so `evals/` holds a promptfoo set instead: real kinds of messages,
each with the events the parser must produce for it. `evals/provider.py` runs the bot's own
`parse_message`, and `evals/assert_events.py` compares only the fields a case lists, numbers
within 1% or 0.05. It calls OpenAI, so it costs a little and needs the key:

```bash
pip install -e .
cd evals
OPENAI_API_KEY=... PYTHONPATH=.. PROMPTFOO_PYTHON=$(which python) \
  npx -y promptfoo@0.124.1 eval -c promptfooconfig.yaml --no-cache
```

Add a case whenever a message was parsed wrong and the prompt was fixed for it. Write the
message for the set or cut it down to the words that matter: the cases are public, so no
names of people, places, clinics or sums of money from the chats.

The `Prompt eval` workflow runs the set on every pull request that changes `parser.py`,
`profiles.py` or `evals/`, with `OPENAI_API_KEY` from the `prompt-eval` environment.

## CI

On every pull request and every push to `main`:

- `lint`: `ruff check`. The rules and the few deliberate exceptions are in `pyproject.toml`.
- `tests`: pytest on Python 3.11 and 3.12. On 3.12 octocov reads the coverage report and
  comments on the pull request with coverage, the code to test ratio and the time of the
  test step, compared with `main`. On `main` it stores the report as a workflow artifact
  for that comparison. The settings are in `.octocov.yml`.
- `static`: shellcheck on the deploy scripts, hadolint on the Dockerfile, actionlint and
  zizmor on the workflows, and gitleaks on the whole git history.
- `build`: the Docker image.

The `Scorecard` workflow runs on every push to `main` and every Saturday. It rates the
repository on the OpenSSF Scorecard checks (pinned dependencies, token permissions, branch
protection, code review and more), publishes the score behind the README badge, and adds its
findings to code scanning under the Security tab.

Every action is pinned to a commit and every tool image to a digest. The octocov binary
is pinned by version and checksum as well, because its action otherwise downloads the
latest release. Dependabot proposes updates for pip, GitHub Actions and the base image
every week.
