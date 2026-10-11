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

Every action is pinned to a commit and every tool image to a digest. The octocov binary
is pinned by version and checksum as well, because its action otherwise downloads the
latest release. Dependabot proposes updates for pip, GitHub Actions and the base image
every week.
