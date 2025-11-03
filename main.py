import os
import asyncio
import random
import logging
from datetime import datetime, timezone
from telethon import TelegramClient
from dotenv import load_dotenv

# ------------------------- Setup -------------------------
load_dotenv()

API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION = os.getenv("TELEGRAM_SESSION", "auto_session")
TARGET_BOT = os.getenv("TARGET_BOT")
TRIGGER_TEXT = os.getenv("TRIGGER_TEXT", "🎁 Claim Bonus")  # the message that reveals buttons
BUTTON_TEXT = os.getenv("BUTTON_TEXT", "🎁 Hourly Bonus")   # the actual button to click
CHECK_INTERVAL_MIN = int(os.getenv("CHECK_INTERVAL_MIN", 60))
JITTER_SECONDS = int(os.getenv("JITTER_SECONDS", 300))

# ------------------------- Logging -------------------------
if not os.path.exists("logs"):
    os.makedirs("logs")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/claim_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ------------------------- Core Logic -------------------------
async def claim_bonus_cycle(client, bot_username, trigger_text, target_button_text):
    """
    Sends the trigger text to the bot to reveal buttons,
    waits for a response, then clicks the claim button.
    """
    logger.info(f"Sending trigger '{trigger_text}' to @{bot_username}...")
    try:
        # 1️⃣ Send the trigger message
        await client.send_message(bot_username, trigger_text)
        await asyncio.sleep(5)  # wait for bot reply

        # 2️⃣ Get recent messages from the bot
        messages = await client.get_messages(bot_username, limit=5)
        for msg in messages:
            if not msg.buttons:
                continue

            # 3️⃣ Look for the claim button
            for row in msg.buttons:
                for button in row:
                    if target_button_text.lower() in button.text.lower():
                        logger.info(f"Found button '{button.text}', clicking...")
                        await button.click()
                        logger.info("✅ Claim button clicked successfully!")
                        return True

        logger.warning("⚠️ No claim button found after sending trigger.")
        return False

    except Exception as e:
        logger.error(f"❌ Error while trying to claim bonus: {e}")
        return False


async def main():
    async with TelegramClient(SESSION, API_ID, API_HASH) as client:
        me = await client.get_me()
        logger.info(f"Signed in successfully as {me.first_name} (@{me.username})")

        while True:
            # Perform the claim attempt
            success = await claim_bonus_cycle(
                client,
                bot_username=TARGET_BOT,
                trigger_text=TRIGGER_TEXT,
                target_button_text=BUTTON_TEXT
            )

            if success:
                logger.info("✅ Bonus claimed successfully this round.")
            else:
                logger.warning("⚠️ Bonus claim failed this round.")

            # Compute randomized cooldown before next claim
            base_sleep = CHECK_INTERVAL_MIN * 60
            jitter = random.randint(0, JITTER_SECONDS)
            total_sleep = base_sleep + jitter
            next_run = datetime.now(timezone.utc).timestamp() + total_sleep

            logger.info(
                "Sleeping for %d seconds (jitter %d). Next run at %s UTC",
                total_sleep, jitter,
                datetime.fromtimestamp(next_run, tz=timezone.utc).isoformat()
            )
            await asyncio.sleep(total_sleep)


if __name__ == "__main__":
    asyncio.run(main())
