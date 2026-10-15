import logging
import os
from datetime import time, timedelta

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from . import commands, common, db, jobs, messages

RETRY_INTERVAL = timedelta(minutes=15)

logger = logging.getLogger(__name__)


async def post_init(app: Application) -> None:
    await app.bot.set_my_commands(commands.BOT_COMMANDS)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    configure_logging()
    db.init()

    app = (
        Application.builder()
        .token(os.environ["TELEGRAM_BOT_TOKEN"])
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("stats", commands.for_known_chat(commands.stats_command)))
    app.add_handler(CommandHandler("left", commands.for_known_chat(commands.left_command)))
    app.add_handler(CommandHandler("autoleft", commands.for_known_chat(commands.autoleft_command)))
    app.add_handler(CommandHandler("risk", commands.for_known_chat(commands.risk_command)))
    app.add_handler(CommandHandler("week", commands.for_known_chat(commands.week_command)))
    app.add_handler(CommandHandler("meds", commands.for_known_chat(commands.meds_command)))
    app.add_handler(CommandHandler("profile", commands.profile_command))
    app.add_handler(CommandHandler("reminders", commands.for_known_chat(commands.reminders_command)))
    app.add_handler(CommandHandler("tube", commands.for_known_chat(commands.tube_command)))
    app.add_handler(CommandHandler(["help", "start"], commands.for_known_chat(commands.help_command)))
    app.add_handler(
        MessageHandler((filters.TEXT | filters.CAPTION) & ~filters.COMMAND, messages.handle_message)
    )

    hour, minute = (int(part) for part in db.DAY_START.split(":"))
    app.job_queue.run_daily(jobs.daily_summary, time(hour, minute, tzinfo=common.TIMEZONE))
    app.job_queue.run_repeating(
        messages.retry_unparsed, interval=RETRY_INTERVAL, first=timedelta(minutes=1)
    )

    for reminder_hour in range(
        jobs.WATER_REMINDER_START_HOUR, jobs.WATER_REMINDER_END_HOUR + 1, jobs.WATER_REMINDER_STEP_HOURS
    ):
        app.job_queue.run_daily(jobs.water_reminder, time(reminder_hour, 0, tzinfo=common.TIMEZONE))

    logger.info("Starting bot (day boundary and summary at %s %s)", db.DAY_START, common.TIMEZONE)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
