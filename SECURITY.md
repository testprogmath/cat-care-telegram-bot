# Security Policy

## Supported versions

Every merge to `main` is a tagged release, and the running instance runs the
latest one. Only the latest release is supported. Fixes go to `main`; nothing
older is patched.

## Reporting a vulnerability

Open a private report under **Security → Report a vulnerability** in this
repository. Do not open a public issue for a vulnerability.

Include the steps to reproduce it. This is a personal project, so expect a
first reply within a week. If the report is valid, the fix and the deploy
follow in the same week. If it is not, you get the reasoning.

## What matters here

Anyone running a copy should know where the sensitive parts are.

- **`.env` holds every secret**: the Telegram bot token, the OpenAI key, the
  admin API token, the web session secret and the OpenID client secret. It is
  gitignored and deploys leave it in place. Keep it out of the image and out of
  the repository. [Configuration](docs/configuration.md#secrets) says what each
  one lets an attacker do.
- **Every group message goes to the OpenAI API.** The bot reads all text in
  the chats it joins, because privacy mode must be off for it to work at all.
  Add it only to chats whose members know this.
- **`data/*.db` holds the message log and the care diary.** It is a plain
  SQLite file with no encryption. Treat a backup of it as personal data.
- **`deploy.sh` reads `DEPLOY_HOST` from the environment.** Do not hardcode a
  host back into the script.
- **The deploy job in CI holds an SSH key to the server.** The key is stored in
  the `production` environment, which only `main` can use. On the server the
  key is limited with `restrict` and a forced command: it can run
  `deploy/redeploy` with a tag name and nothing else. Do not give that key a
  shell.

The bot itself accepts no inbound connections. It polls Telegram and writes to a
local file. Two other containers listen, both on the host loopback only:

- **The admin API** requires a bearer token on every request and records every
  change in `event_edits`. Reach it through an SSH tunnel. Do not publish its
  port. See [the admin API](docs/admin-api.md).
- **The web pages** are public through Caddy with HTTPS. They are read-only,
  open the database read-only, and show an animal only to members of its chat,
  checked with Telegram at most ten minutes ago. See [the web pages](docs/web.md).

One chat keeps one animal's diary, and a chat without an animal stays silent, so
adding the bot to another group does not open a diary to that group.
