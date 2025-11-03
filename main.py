import os
import re
import csv
import asyncio
import random
import logging
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION = os.getenv("TELEGRAM_SESSION", "auto_session")
TARGET_BOT = os.getenv("TARGET_BOT")
TRIGGER_TEXT = os.getenv("TRIGGER_TEXT", "🎁 Claim Bonus")
BUTTON_TEXT = os.getenv("BUTTON_TEXT", "🎁 Hourly Bonus")
CHECK_INTERVAL_MIN = int(os.getenv("CHECK_INTERVAL_MIN", 60))
JITTER_SECONDS = int(os.getenv("JITTER_SECONDS", 300))
LOG_RECEIVER_ID = int(os.getenv("LOG_RECEIVER_ID", 0))

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

def extract_reward_value(text):
    match = re.search(r"([\d.]+)", text)
    if match:
        return float(match.group(1))
    return 0.0

def record_claim(value):
    if not os.path.exists("data"):
        os.makedirs("data")
    with open("data/claims.csv", "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now(timezone.utc).isoformat(), value])

def get_weekly_total():
    if not os.path.exists("data/claims.csv"):
        return 0.0
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    total = 0.0
    with open("data/claims.csv") as f:
        reader = csv.reader(f)
        for row in reader:
            timestamp, value = row
            if datetime.fromisoformat(timestamp) > cutoff:
                total += float(value)
    return total

async def send_log(client, message):
    if LOG_RECEIVER_ID:
        try:
            await client.send_message(LOG_RECEIVER_ID, message)
        except Exception as e:
            logger.warning(f"Failed to send Telegram log: {e}")

async def claim_bonus_cycle(client, bot_username, trigger_text, target_button_text):
    logger.info(f"Sending trigger '{trigger_text}' to @{bot_username}...")
    try:
        await client.send_message(bot_username, trigger_text)
        await asyncio.sleep(5)
        messages = await client.get_messages(bot_username, limit=5)
        for msg in messages:
            if not msg.buttons:
                continue
            for row in msg.buttons:
                for button in row:
                    if target_button_text.lower() in button.text.lower():
                        logger.info(f"Found button '{button.text}', clicking...")
                        await button.click()
                        await asyncio.sleep(4)
                        new_msgs = await client.get_messages(bot_username, limit=3)
                        for reply in new_msgs:
                            if "received" in reply.text.lower() or "bonus" in reply.text.lower():
                                value = extract_reward_value(reply.text)
                                record_claim(value)
                                claim_num = sum(1 for _ in open("data/claims.csv"))
                                weekly_total = get_weekly_total()
                                msg_text = f"✅ Claim #{claim_num}: +{value} LTC\n📅 Weekly total: {weekly_total:.8f} LTC"
                                logger.info(msg_text)
                                await send_log(client, msg_text)
                                return True
        logger.warning("No claim button found after sending trigger.")
        return False
    except Exception as e:
        logger.error(f"Error while trying to claim bonus: {e}")
        await send_log(client, f"❌ Error during claim: {e}")
        return False

async def main():
    async with TelegramClient(SESSION, API_ID, API_HASH) as client:
        me = await client.get_me()
        logger.info(f"Signed in as {me.first_name} (@{me.username})")
        while True:
            success = await claim_bonus_cycle(
                client,
                bot_username=TARGET_BOT,
                trigger_text=TRIGGER_TEXT,
                target_button_text=BUTTON_TEXT
            )
            if success:
                logger.info("Bonus claimed successfully this round.")
            else:
                logger.warning("Bonus claim failed this round.")
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
