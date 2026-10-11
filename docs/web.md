# Web pages for the family

`care-web` serves read-only pages from the same database: a week table and charts, every
event of a day with the message it came from and a chart of the day by the hour,
medications, foods and refusals. It runs as the `web` container on `127.0.0.1:8280` and
mounts `data/` read-only. Nothing on these pages writes to the diary; edits go through the
[admin API](admin-api.md).

## Who sees what

Sign-in is Telegram's OpenID Connect login. A person sees an animal only while they are a
member of that animal's chat. The page asks Telegram with `getChatMember` and remembers
the answer for ten minutes, so:

- Add someone to the chat to give them access.
- Remove someone from the chat to take access away. They keep it for up to ten minutes.
- A member Telegram lists as `restricted` keeps access while they are still in the chat.

The session cookie lasts 30 days, but membership is checked again every ten minutes, so
the cookie alone does not keep access.

The bot must be an administrator of each chat, with no rights, because Telegram only
guarantees `getChatMember` for administrators. A chat without an animal appears on no page.

## Set it up

The `web` container gets only the variables listed for it in
[configuration](configuration.md#web), not the whole `.env`. It does not start without
`WEB_SESSION_SECRET` of at least 32 characters, `WEB_BASE_URL`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_OPENID_CLIENT_ID` and `TELEGRAM_OPENID_CLIENT_SECRET`.

1. In BotFather, open the bot, then Login Widget, then OpenID Connect. Copy the client id
   and secret into `.env`.
2. In BotFather, register `<WEB_BASE_URL>/auth/callback` as an allowed URL.
3. Add the site block below to `/etc/caddy/Caddyfile` on the server.
4. Validate the file with the service's environment loaded, because another site block
   reads a password from it, and reload Caddy:

```bash
sudo sh -c 'set -a; . /etc/caddy/ciwang.env; caddy validate --config /etc/caddy/Caddyfile' \
  && sudo systemctl reload caddy
```

```
cats.khvorostianova.com {
	encode zstd gzip
	reverse_proxy 127.0.0.1:8280
	header Strict-Transport-Security "max-age=31536000"

	log {
		output file /var/log/caddy/cats.log
		format console
	}
}
```

Caddy gets the certificate itself once the DNS record points at the server. It leaves
cookies out of its access log by default, so the session cookie is not written there.

## Foods

The foods page groups recorded names into one product each ("hills digestive care",
"hill's prescription diet i/d" become Hill's i/d). The rules are in `foods.py`. A refusal
that names two foods counts once for each.
