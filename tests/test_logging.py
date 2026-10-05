"""The bot's logs must not carry the Telegram token."""

import logging

from skrypka_bot import main

TOKEN = "123456:secret-token"


def test_a_telegram_request_is_not_logged_with_its_url(caplog):
    main.configure_logging()
    with caplog.at_level(logging.INFO):
        logging.getLogger("httpx").info(
            'HTTP Request: POST https://api.telegram.org/bot%s/getUpdates "HTTP/1.1 200 OK"', TOKEN
        )
    assert TOKEN not in caplog.text
