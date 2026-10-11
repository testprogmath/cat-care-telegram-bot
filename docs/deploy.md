# Releases and deploys

Every merge to `main` is a release. When lint, static checks, tests and the image build
pass on `main`, the `release` job in CI tags the merge commit, publishes a GitHub Release
with notes generated from the merged pull requests, and deploys that tag to the server.

## Version labels

The label on the pull request sets the version, as in semantic versioning:

| Label | Version change | Use it for |
|---|---|---|
| `release:major` | `v1.4.2` to `v2.0.0` | a change a consumer must adapt to, e.g. the CareDay contract |
| `release:minor` | `v1.4.2` to `v1.5.0` | a new command or feature |
| `release:patch` | `v1.4.2` to `v1.4.3` | a fix |
| `release:skip` | no release, no deploy | docs and CI changes |

The `Release label` check fails on a pull request until it has exactly one of these
labels. A push to `main` that did not come from a labelled pull request releases a patch.
The first release was `v1.0.0`. The version in `pyproject.toml` is not updated; the tag
is the version.

## How a deploy reaches the server

The workflow cannot open a shell on the server. Its SSH key runs one command,
`deploy/redeploy`, which accepts only a tag name. The script checks out that tag in the
server's git checkout, then builds and restarts the `bot`, `api` and `web` containers.
`data/` and `.env` are ignored by git and stay in place.

The bot changes the database schema in place at startup (`ALTER TABLE` guarded by a
column check). Copy `data/` before you deploy a release that changes the schema.

To deploy a tag by hand, use the same key:
`ssh -i ~/.ssh/skrypka_deploy deploy@<host> v1.2.3`. To roll back, deploy an earlier tag
the same way.

## When CI cannot deploy

`./deploy.sh` copies your working tree to the server with rsync and rebuilds all three
containers there. It keeps the server's `.env` and `data/`. It needs `DEPLOY_HOST`. Use it
only when the release job cannot run: afterwards the server's checkout no longer matches
any tag, so the next tag deploy overwrites it.

## One-time setup

On your machine, create a key for the workflow and read the server's host key:

```bash
ssh-keygen -t ed25519 -N "" -C github-actions-deploy -f ~/.ssh/skrypka_deploy
ssh-keyscan -t ed25519 <host>
```

On the server, turn the deploy directory into a git checkout. Tracked files are replaced
by the same files from git. `data/` and `.env` do not change.

```bash
cd ~/apps/skrypka-telegram-bot
git init -q
git remote add origin https://github.com/testprogmath/cat-care-telegram-bot.git
git fetch -q origin main
git checkout -f -B main origin/main
```

On the server, add one line to `~/.ssh/authorized_keys`. Put the content of
`~/.ssh/skrypka_deploy.pub` after the options:

```
restrict,command="/home/deploy/apps/skrypka-telegram-bot/deploy/redeploy" ssh-ed25519 AAAA... github-actions-deploy
```

In the repository settings, create the environment `production`, allow only `main` to
deploy to it, and add three secrets to it:

| Secret | Value |
|---|---|
| `DEPLOY_SSH_KEY` | the content of `~/.ssh/skrypka_deploy` |
| `DEPLOY_KNOWN_HOSTS` | the output of `ssh-keyscan` |
| `DEPLOY_HOST` | `deploy@<host>` |

Create the labels `release:major`, `release:minor`, `release:patch` and `release:skip`.
In the branch protection for `main`, make `release-label` a required status check.
