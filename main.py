import os
import re
import csv
import asyncio
import random
import logging
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient
from dotenv import load_dotenv

# ---------------------------------------------------------
# LOAD ENVIRONMENT
# ---------------------------------------------------------
load_dotenv()

API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")

CHECK_INTERVAL_MIN = float(os.getenv("CHECK_INTERVAL_MIN", 60))
JITTER_SECONDS = int(os.getenv("JITTER_SECONDS", 300))
LOG_CHAT_ID = os.getenv("LOG_CHAT_ID")

COOLDOWN_SECONDS = 3600  # 1 hour

# ---------------------------------------------------------
# BOT PROFILES (TWO BOTS)
# ---------------------------------------------------------
BOT_PROFILES = [
    {
        "name": "USDTEMPIRES",
        "username": "USDTEMPIRESBOT",
        "trigger": "🌟 Collect Hourly",
        "button": "🎁 Hourly Bonus",
        "session": "session_USDTEMPIRES"
    },
    {
        "name": "LTCMATRIX",
        "username": "LTCMatrixMineBot",
        "trigger": "🎁 Claim Bonus",
        "button": "🎁 Hourly Bonus",
        "session": "session_LTCMATRIX"
    }
]

# ---------------------------------------------------------
# LOGGING
# ---------------------------------------------------------
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/multi_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def ensure_bot_data_dir(bot_name):
    path = f"data/{bot_name}"
    os.makedirs(path, exist_ok=True)
    return path

def get_claim_file(bot_name):
    return os.path.join(ensure_bot_data_dir(bot_name), "claims.csv")

def get_last_claim_time(bot_name):
    path = get_claim_file(bot_name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            rows = list(csv.reader(f))
        if not rows:
            return None
        last_time = datetime.fromisoformat(rows[-1][0])
        return last_time.replace(tzinfo=timezone.utc)
    except:
        return None

def record_claim(bot_name, amount):
    path = get_claim_file(bot_name)
    with open(path, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now(timezone.utc).isoformat(), amount])

def get_weekly_total(bot_name):
    path = get_claim_file(bot_name)
    if not os.path.exists(path):
        return 0.0
    total = 0
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    with open(path, "r") as f:
        for row in csv.reader(f):
            try:
                timestamp = datetime.fromisoformat(row[0])
                if timestamp >= week_ago:
                    total += float(row[1])
            except:
                continue
    return total

# ---------------------------------------------------------
# CLEANING + PARSING FIX
# ---------------------------------------------------------

def clean_text(t):
    """Remove invisible characters, emojis interference, and normalize spacing."""
    if not t:
        return ""
    return (
        t.replace("\u200b", "")   # zero-width space
         .replace("\u2060", "")   # word joiner
         .replace("\n", " ")
         .replace("\r", " ")
         .strip()
    )

def extract_reward_value(text):
    t = clean_text(text)

    # This will match strings like:
    # 0.00000023 LTC
    # 0.05 LTC
    # 1.2 DOGE
    match = re.search(r"([\d.]+)\s*(LTC|DOGE|BTC|USDT|TRX)", t, re.I)
    if match:
        try:
            return float(match.group(1))
        except:
            return 0.0
    return 0.0

def extract_time_remaining(text):
    t = clean_text(text)
    match = re.search(r"after\s+(\d+)\s*minutes?\s*(\d+)?", t, re.I)
    if not match:
        return None
    minutes = int(match.group(1))
    seconds = int(match.group(2) or 0)
    return minutes * 60 + seconds

# ---------------------------------------------------------
# LOG SENDER
# ---------------------------------------------------------

async def send_log(client, msg):
    if not LOG_CHAT_ID:
        logger.info(f"LOG: {msg}")
        return
    try:
        await client.send_message(int(LOG_CHAT_ID), msg)
    except Exception as e:
        logger.warning(f"Failed to send log message: {e}")

# ---------------------------------------------------------
# CLAIM LOGIC
# ---------------------------------------------------------

async def claim_bonus_for_bot(client, bot):
    bot_name = bot["name"]
    bot_username = bot["username"]
    trigger = bot["trigger"]
    button = bot["button"]

    last_claim = get_last_claim_time(bot_name)

    # Local cooldown
    if last_claim:
        since = (datetime.now(timezone.utc) - last_claim).total_seconds()
        if since < COOLDOWN_SECONDS:
            remain = int(COOLDOWN_SECONDS - since)
            await send_log(client, f"[{bot_name}] ⏳ Local cooldown: {remain//60}m {remain%60}s")
            return False

    logger.info(f"[{bot_name}] Triggering → '{trigger}' to @{bot_username}")

    try:
        await client.send_message(bot_username, trigger)
        await asyncio.sleep(3)

        messages = await client.get_messages(bot_username, limit=10)

        for msg in messages:
            text = clean_text(msg.text or "")
            cooldown = extract_time_remaining(text)

            # Remote cooldown
            if "🚫" in text or cooldown:
                remain = cooldown or COOLDOWN_SECONDS
                await send_log(client, f"[{bot_name}] ⏳ Remote cooldown: {remain}s")
                return False

            # Check for claim button
            if msg.buttons:
                for row in msg.buttons:
                    for btn in row:
                        if button.lower() in (btn.text or "").lower():
                            await btn.click()
                            await asyncio.sleep(4)

                            # Parse reward
                            post = await client.get_messages(bot_username, limit=5)
                            for p in post:
                                reward = extract_reward_value(p.text or "")
                                if reward > 0:
                                    record_claim(bot_name, reward)
                                    weekly = get_weekly_total(bot_name)
                                    await send_log(client,
                                        f"[{bot_name}] 🎉 Claimed +{reward} | Weekly total: {weekly}"
                                    )
                                    return True

        await send_log(client, f"[{bot_name}] ⚠️ No valid response found")
        return False

    except Exception as e:
        await send_log(client, f"[{bot_name}] ❌ Error: {e}")
        return False

# ---------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------

async def main():
    client = TelegramClient("multi_session", API_ID, API_HASH)

    async with client:
        me = await client.get_me()
        logger.info(f"Signed in as {me.first_name} (@{me.username})")

        while True:
            # Process bots sequentially
            for bot in BOT_PROFILES:
                await claim_bonus_for_bot(client, bot)
                await asyncio.sleep(5)

            # Sleep before next cycle
            base = CHECK_INTERVAL_MIN * 60
            jitter = random.randint(0, JITTER_SECONDS)
            wait = base + jitter

            logger.info(f"🌙 Sleeping {wait}s before next scan...")
            await asyncio.sleep(wait)

if __name__ == "__main__":
    asyncio.run(main())
