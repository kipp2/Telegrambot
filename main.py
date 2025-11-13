import os
import re
import csv
import asyncio
import random
import logging
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient
from dotenv import load_dotenv

# --- Load environment variables ---
load_dotenv()

API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION = os.getenv("TELEGRAM_SESSION", "auto_session")
TARGET_BOT = os.getenv("TARGET_BOT")
TRIGGER_TEXT = os.getenv("TRIGGER_TEXT", "🎁 Claim Bonus")
BUTTON_TEXT = os.getenv("BUTTON_TEXT", "🎁 Hourly Bonus")
CHECK_INTERVAL_MIN = float(os.getenv("CHECK_INTERVAL_MIN", 60))
JITTER_SECONDS = int(os.getenv("JITTER_SECONDS", 300))
LOG_RECEIVER_ID = int(os.getenv("LOG_RECEIVER_ID", 0))

# --- Logging setup ---
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/claim_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Data helpers ---
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
COOLDOWN_SECONDS = 3600  # 1 hour


def get_last_claim_time():
    path = os.path.join(DATA_DIR, "claims.csv")
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return None
    try:
        with open(path, "r") as f:
            rows = list(csv.reader(f))
        if not rows:
            return None
        last_time = datetime.fromisoformat(rows[-1][0])
        return last_time.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def record_claim(amount):
    path = os.path.join(DATA_DIR, "claims.csv")
    with open(path, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now(timezone.utc).isoformat(), amount])


def get_weekly_total():
    path = os.path.join(DATA_DIR, "claims.csv")
    if not os.path.exists(path):
        return 0.0
    total = 0.0
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    with open(path, "r") as f:
        reader = csv.reader(f)
        for row in reader:
            try:
                timestamp = datetime.fromisoformat(row[0])
                if timestamp >= week_ago:
                    total += float(row[1])
            except Exception:
                continue
    return total


def extract_reward_value(text):
    match = re.search(r"([\d.]+)\s*(LTC|DOGE|BTC|USDT|TRX)", text, re.I)
    if match:
        return float(match.group(1))
    return 0.0


def extract_time_remaining(text):
    match = re.search(r"after\s+(\d+)\s*minutes?\s*(\d+)?", text, re.I)
    if match:
        minutes = int(match.group(1))
        seconds = int(match.group(2) or 0)
        return minutes * 60 + seconds
    return None


async def send_log(client, message):
    log_chat_id = os.getenv("LOG_CHAT_ID")
    if not log_chat_id:
        logger.info(f"LOG: {message}")
        return
    try:
        await client.send_message(int(log_chat_id), message)
    except Exception as e:
        logger.warning(f"Failed to send log message: {e}")


async def claim_bonus_cycle(client, bot_username, trigger_text, target_button_text):
    last_claim_time = get_last_claim_time()
    if last_claim_time:
        since = (datetime.now(timezone.utc) - last_claim_time).total_seconds()
        if since < COOLDOWN_SECONDS:
            remain_local = int(COOLDOWN_SECONDS - since)
            msg = f"⚠️ Local cooldown active: next claim in {remain_local//60}m {remain_local%60}s."
            logger.warning(msg)
            await send_log(client, msg)
            return False, remain_local

    logger.info(f"Sending trigger '{trigger_text}' to @{bot_username}...")
    try:
        sent = await client.send_message(bot_username, trigger_text)
        send_time = sent.date.replace(tzinfo=timezone.utc)

        WAIT_TIMEOUT = 20
        POLL_INTERVAL = 1
        elapsed = 0
        claim_clicked = False

        while elapsed < WAIT_TIMEOUT:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            messages = await client.get_messages(bot_username, limit=8)
            new_msgs = [
                m for m in messages
                if getattr(m, "date", send_time).replace(tzinfo=timezone.utc) >= send_time
            ]
            if not new_msgs:
                continue

            for msg in new_msgs:
                text = msg.text or ""
                cooldown_time = extract_time_remaining(text)

                if msg.buttons and not claim_clicked:
                    for row in msg.buttons:
                        for button in row:
                            if target_button_text.lower() in (button.text or "").lower():
                                logger.info(f"Found '{button.text}', clicking...")
                                await button.click()
                                claim_clicked = True
                                await asyncio.sleep(5)

                                post_msgs = await client.get_messages(bot_username, limit=6)
                                for pm in post_msgs:
                                    ptext = pm.text or ""
                                    if "🚫" in ptext or "after" in ptext.lower():
                                        remain_remote = int(extract_time_remaining(ptext) or 0)
                                        msg_text = f"⏳ Remote cooldown active: {remain_remote//60}m {remain_remote%60}s."
                                        logger.warning(msg_text)
                                        await send_log(client, msg_text)
                                        return False, remain_remote
                                    if "received" in ptext.lower() or "bonus" in ptext.lower():
                                        value = extract_reward_value(ptext)
                                        if value > 0:
                                            record_claim(value)
                                            claim_num = sum(1 for _ in open("data/claims.csv"))
                                            total = get_weekly_total()
                                            text_done = (
                                                f"✅ Claim #{claim_num}: +{value} LTC\n"
                                                f"📅 Weekly total: {total:.8f} LTC"
                                            )
                                            logger.info(text_done)
                                            await send_log(client, text_done)
                                            return True, COOLDOWN_SECONDS

                if "🚫" in text or cooldown_time:
                    remain_remote = int((cooldown_time or 0))
                    msg_text = f"⏳ Remote cooldown detected: {remain_remote//60}m {remain_remote%60}s."
                    logger.warning(msg_text)
                    await send_log(client, msg_text)
                    return False, remain_remote or COOLDOWN_SECONDS

                if "received" in text.lower() or "bonus" in text.lower():
                    value = extract_reward_value(text)
                    if value > 0:
                        record_claim(value)
                        claim_num = sum(1 for _ in open("data/claims.csv"))
                        total = get_weekly_total()
                        text_done = (
                            f"✅ Claim #{claim_num}: +{value} LTC\n"
                            f"📅 Weekly total: {total:.8f} LTC"
                        )
                        logger.info(text_done)
                        await send_log(client, text_done)
                        return True, COOLDOWN_SECONDS

        msg = "⚠️ No response or button found after waiting."
        logger.warning(msg)
        await send_log(client, msg)
        return False, COOLDOWN_SECONDS

    except Exception as e:
        logger.error(f"❌ Error while claiming: {e}")
        await send_log(client, f"❌ Error: {e}")
        return False, COOLDOWN_SECONDS


# --- Main bot loop with reconnection & segmented sleep ---
async def main():
    client = TelegramClient(SESSION, API_ID, API_HASH, connection_retries=None)
    async with client:
        me = await client.get_me()
        logger.info(f"Signed in as {me.first_name} (@{me.username})")

        while True:
            try:
                if not client.is_connected():
                    logger.warning("Client disconnected. Reconnecting...")
                    await client.connect()
                    if not await client.is_user_authorized():
                        logger.error("Client not authorized after reconnect. Exiting loop.")
                        break

                success, _ = await claim_bonus_cycle(
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

                # --- segmented sleep with heartbeat every 5 min ---
                sleep_remaining = total_sleep
                while sleep_remaining > 0:
                    await asyncio.sleep(min(300, sleep_remaining))
                    sleep_remaining -= 300
                    logger.debug("Heartbeat: still alive, %ds remaining", sleep_remaining)

            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}")
                await send_log(client, f"⚠️ Main loop error: {e}")
                await asyncio.sleep(60)  # wait 1 min then retry


if __name__ == "__main__":
    asyncio.run(main())

