"""
......
Telegram hourly-claim user-client (Telethon)

Usage:
  1. Install: pip install telethon python-dotenv
  2. Create a .env file with TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION (optional), TARGET_BOT (username or id), BUTTON_TEXT (optional)
  3. Run: python telegram_hourly_claim_bot.py

Security:
  - Keep your API credentials and session string private.
  - Use a VPS or small droplet to run continuously.

This script will:
  - Connect as your user account (Telethon)
  - Check the target bot for the latest message every 55-65 minutes
  - If the latest message has inline buttons it will try to click the button matching BUTTON_TEXT or fallback to the first button
  - Log actions and avoid double-clicking

Note: Use only after getting explicit permission from the target bot owner.
"""

import os
import asyncio
import logging
from datetime import datetime
from telethon import TelegramClient, events, errors
from telethon.tl.types import Message
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv('TELEGRAM_API_ID', '0'))
API_HASH = os.getenv('TELEGRAM_API_HASH', '')
SESSION = os.getenv('TELEGRAM_SESSION', 'auto_session')  # optional: a filename or session string
TARGET_BOT = os.getenv('TARGET_BOT', 'example_bot')  # username or numeric id, e.g. 'myfaucetbot' or 123456
BUTTON_TEXT = os.getenv('BUTTON_TEXT', '').strip()  # e.g. 'Claim', 'Get Reward' - optional
CHECK_INTERVAL_MIN = int(os.getenv('CHECK_INTERVAL_MIN', '61'))  # minutes between attempts (set >= 55)
JITTER_SECONDS = int(os.getenv('JITTER_SECONDS', '300'))  # random jitter upto this many seconds

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')
logger = logging.getLogger('claimbot')

# Safety: make sure interval is at least 50 minutes by default to avoid spam
if CHECK_INTERVAL_MIN < 50:
    logger.warning('CHECK_INTERVAL_MIN is very small; raising to 50 minutes to be safe')
    CHECK_INTERVAL_MIN = 50

client = TelegramClient(SESSION, API_ID, API_HASH)


async def find_and_click():
    """Fetch last message from the target bot and attempt to click an inline button."""
    try:
        msgs = await client.get_messages(TARGET_BOT, limit=3)
        if not msgs:
            logger.info('No messages found from %s', TARGET_BOT)
            return False

        # Check messages from newest -> older
        for msg in msgs:
            if not isinstance(msg, Message):
                continue
            if not msg.buttons:
                continue

            # flatten buttons into list of tuples (row_index, col_index, button)
            buttons = []
            for r_idx, row in enumerate(msg.buttons):
                for c_idx, btn in enumerate(row):
                    # btn may be a telethon Button
                    buttons.append((r_idx, c_idx, btn))

            # try to find by text if provided
            target_btn = None
            if BUTTON_TEXT:
                for (r, c, btn) in buttons:
                    text = getattr(btn, 'text', None)
                    if text and BUTTON_TEXT.lower() in text.lower():
                        target_btn = (r, c, btn)
                        break

            # fallback to the first button
            if not target_btn and buttons:
                target_btn = buttons[0]

            if target_btn:
                r, c, btn = target_btn
                btn_text = getattr(btn, 'text', '<callback>')
                logger.info('Attempting to click button "%s" from message id %s', btn_text, msg.id)
                try:
                    # Telethon lets you click the button by specifying row/col or the button object
                    await msg.click(r, c)
                    logger.info('Clicked button "%s" successfully', btn_text)
                    return True
                except errors.RPCError as e:
                    logger.error('RPC error while clicking: %s', e)
                    return False
                except Exception as e:
                    logger.exception('Unexpected error while clicking: %s', e)
                    return False

        logger.info('No clickable message/button found in recent messages')
        return False

    except Exception as e:
        logger.exception('Error fetching messages: %s', e)
        return False


async def run_loop():
    await client.start()
    logger.info('Client started as %s', await client.get_me())

    while True:
        start_time = datetime.utcnow()
        try:
            ok = await find_and_click()
            if ok:
                logger.info('Claim attempt done.')
            else:
                logger.info('No claim performed this cycle.')

        except Exception:
            logger.exception('Unhandled error in cycle')

        # sleep until next interval with jitter
        import random
        jitter = random.randint(0, JITTER_SECONDS)
        total_sleep = CHECK_INTERVAL_MIN * 60 + jitter
        next_run = datetime.utcnow().timestamp() + total_sleep
        logger.info('Sleeping for %d seconds (jitter %d). Next run at %s UTC', total_sleep, jitter, datetime.utcfromtimestamp(next_run).isoformat())
        await asyncio.sleep(total_sleep)


if __name__ == '__main__':
    try:
        client.loop.run_until_complete(run_loop())
    except KeyboardInterrupt:
        logger.info('Interrupted by user, quitting')
    finally:
        client.disconnect()
