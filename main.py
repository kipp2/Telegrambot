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
COOLDOWN_SECONDS = 3600

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

def extract_time_remaining(text):
    t = text.lower()
    # Handle formats like "after 38 minutes 25 sec"
    m = re.search(r"after\s*(\d+)\s*minutes?\s*(\d+)?\s*(?:sec|seconds)?", t)
    if m:
        minutes = int(m.group(1))
        seconds = int(m.group(2)) if m.group(2) else 0
        return minutes * 60 + seconds
    # Handle "xx minutes"
    m = re.search(r"(\d+)\s*(?:minutes|min|m)", t)
    if m:
        return int(m.group(1)) * 60
    # Handle "hh:mm:ss"
    m = re.search(r"(\d+):(\d+):(\d+)", t)
    if m:
        h, m1, s = map(int, m.groups())
        return h * 3600 + m1 * 60 + s
    return None

def record_claim(value):
    if not os.path.exists("data"):
        os.makedirs("data")
    with open("data/claims.csv", "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now(timezone.utc).isoformat(), value])

def get_last_claim_time():
    if not os.path.exists("data/claims.csv"):
        return None
    with open("data/claims.csv") as f:
        lines = f.readlines()
        if not lines:
            return None
        last_time = lines[-1].split(",")[0]
        return datetime.fromisoformat(last_time)

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
    last_claim_time = get_last_claim_time()
    if last_claim_time:
        since = (datetime.now(timezone.utc) - last_claim_time).total_seconds()
        if since < COOLDOWN_SECONDS:
            msg = f"⚠️ Claim skipped: last claim was {int(since // 60)} min ago."
            logger.warning(msg)
            await send_log(client, msg)
            return False

    logger.info(f"Sending trigger '{trigger_text}' to @{bot_username}...")
    try:
        await client.send_message(bot_username, trigger_text)
        await asyncio.sleep(5)
        messages = await client.get_messages(bot_username, limit=5)
        for msg in messages:
            # Detect cooldown messages first
            time_remain = extract_time_remaining(msg.text)
            if "🚫" in msg.text or time_remain:
                remain_min = int((time_remain or 0) / 60)
                msg_text = f"⏳ Claim failed: cooldown {remain_min} minutes remaining."
                logger.warning(msg_text)
                await send_log(client, msg_text)
                return False

            # Then detect successful reward messages
            if "received" in msg.text.lower() or "bonus" in msg.text.lower():
                value = extract_reward_value(msg.text)
                if value > 0:
                    record_claim(value)
                    claim_num = sum(1 for _ in open("data/claims.csv"))
                    weekly_total = get_weekly_total()
                    msg_text = f"✅ Claim #{claim_num}: +{value} LTC\n📅 Weekly total: {weekly_total:.8f} LTC"
                    logger.info(msg_text)
                    await send_log(client, msg_text)
                    return True

            if msg.buttons:
                for row in msg.buttons:
                    for button in row:
                        if target_button_text.lower() in button.text.lower():
                            logger.info(f"Found button '{button.text}', clicking...")
                            await button.click()
                            await asyncio.sleep(4)
                            return await claim_bonus_cycle(client, bot_username, trigger_text, target_button_text)

        logger.warning("No claim button or reward found — possible cooldown.")
        await send_log(client, "⚠️ No claim button or reward found.")
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
