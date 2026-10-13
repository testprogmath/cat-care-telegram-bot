# Contributing

## Reporting a bug or asking for a change

Open an issue: <https://github.com/testprogmath/cat-care-telegram-bot/issues/new>. Say what
you did, what you expected and what happened instead. For a parsing mistake, give the
message as it was written and the events it produced; leave out names, places and anything
else private from the chat.

A security problem does not go in an issue. Report it privately as described in
[SECURITY.md](SECURITY.md).

Issues and pull requests are in English or Russian.

## Changing the code

1. Fork the repository or create a branch from `main`.
2. Make the change with tests (see below), then run what CI runs:

   ```bash
   pip install --require-hashes -r requirements-dev.txt
   pip install --no-deps -e .
   OPENAI_API_KEY=dummy pytest -q
   ruff check .
   ```

3. Open a pull request against `main` that says what changed and why, and give it one
   release label: `release:major`, `release:minor`, `release:patch` or `release:skip`
   ([what each means](docs/deploy.md#version-labels)).
4. A pull request is merged when CI passes. Every merge to `main` is released and deployed.

## Tests

Every change in behaviour comes with a test that fails without it, and every fixed bug
with a test that reproduces it. A rule that does not depend on a particular animal is
tested on a made-up one from `animal()` in `tests/conftest.py`.

A change to the parsing prompt (`skrypka_bot/prompts/`, `skrypka_bot/profiles.py`) also
adds a case to `evals/cases.yaml` for the message it fixes. The `Prompt eval` workflow runs
the whole set against the model on the pull request; see
[development](docs/development.md#the-prompt-regression-set).

## Style

- Code passes `ruff check` with the rules in `pyproject.toml`.
- No cat is named, defaulted to or special-cased outside `skrypka_bot/profiles.py`.
- New dependencies go into `pyproject.toml` and both lock files; regenerating them is
  described in [development](docs/development.md).
- Commit messages and pull request descriptions say why the change is needed.
