"""
filmmaker.og Intelligence Bot — Project Watchtower
A single-operator private Telegram intelligence pipeline for film/TV industry monitoring.
"""
import os
import re
import json
import sqlite3
import hashlib
import logging
import asyncio
from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
from telegram import (
    Update,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (environment variables)
# ---------------------------------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
OWNER_ID = int(os.getenv("OWNER_ID", "7608505889"))

# Telegram Topics group — set these after creating your group + topics
LIBRARY_GROUP_CHAT_ID = int(os.getenv("LIBRARY_GROUP_CHAT_ID", "0"))

# Google Sheets — set after creating your sheet
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "watchtower.db")

# ---------------------------------------------------------------------------
# Gemini setup
# ---------------------------------------------------------------------------
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

# ---------------------------------------------------------------------------
# Topic mapping: name -> message_thread_id
# Set these after creating Topics in your Telegram group.
# To get thread IDs: send a message in each Topic, check bot logs for
# message.message_thread_id
# ---------------------------------------------------------------------------
TOPICS = {
    "development": {"id": int(os.getenv("TOPIC_DEVELOPMENT", "0")), "emoji": "🎬", "label": "Development"},
    "financing": {"id": int(os.getenv("TOPIC_FINANCING", "0")), "emoji": "💰", "label": "Financing"},
    "legal_ba": {"id": int(os.getenv("TOPIC_LEGAL_BA", "0")), "emoji": "⚖️", "label": "Legal/BA"},
    "distribution": {"id": int(os.getenv("TOPIC_DISTRIBUTION", "0")), "emoji": "🚚", "label": "Distribution"},
    "packaging": {"id": int(os.getenv("TOPIC_PACKAGING", "0")), "emoji": "📦", "label": "Packaging"},
    "talent": {"id": int(os.getenv("TOPIC_TALENT", "0")), "emoji": "🎭", "label": "Talent"},
    "intl_sales": {"id": int(os.getenv("TOPIC_INTL_SALES", "0")), "emoji": "🌍", "label": "Intl Sales"},
    "guilds": {"id": int(os.getenv("TOPIC_GUILDS", "0")), "emoji": "✊", "label": "Guilds"},
    "ai_tech": {"id": int(os.getenv("TOPIC_AI_TECH", "0")), "emoji": "🤖", "label": "AI/Tech"},
    "trending": {"id": int(os.getenv("TOPIC_TRENDING", "0")), "emoji": "🔥", "label": "Trending"},
    "spotlight": {"id": int(os.getenv("TOPIC_SPOTLIGHT", "0")), "emoji": "⭐", "label": "Spotlight"},
    "market": {"id": int(os.getenv("TOPIC_MARKET", "0")), "emoji": "📊", "label": "Market"},
    "instagram_intel": {"id": int(os.getenv("TOPIC_INSTAGRAM_INTEL", "0")), "emoji": "📸", "label": "Instagram Intel"},
    "all_intel": {"id": int(os.getenv("TOPIC_ALL_INTEL", "0")), "emoji": "📡", "label": "All Intel"},
    "daily_brief": {"id": int(os.getenv("TOPIC_DAILY_BRIEF", "0")), "emoji": "☀️", "label": "Daily Brief"},
    "weekly_report": {"id": int(os.getenv("TOPIC_WEEKLY_REPORT", "0")), "emoji": "📈", "label": "Weekly Intel Report"},
    "misc": {"id": int(os.getenv("TOPIC_MISC", "0")), "emoji": "📂", "label": "Misc"},
}

# Categories the user can file into (subset of TOPICS used in category picker)
FILING_CATEGORIES = [
    "development", "financing", "legal_ba", "distribution", "packaging",
    "talent", "intl_sales", "guilds", "ai_tech", "trending", "spotlight",
    "market", "misc",
]

# Mirror topics (items also get copied here)
MIRROR_TOPICS = {
    "all_intel": True,  # all Yes items
    "instagram_intel": False,  # only IG items
}

# Categories that do NOT write to Google Sheets
NO_SHEETS_CATEGORIES = {"misc", "instagram_intel", "all_intel", "daily_brief", "weekly_report"}

# ---------------------------------------------------------------------------
# RSS Feeds — trade + Google Alerts
# ---------------------------------------------------------------------------
TRADE_FEEDS = {
    "Deadline": "https://deadline.com/feed/",
    "Variety": "https://variety.com/feed/",
    "THR": "https://www.hollywoodreporter.com/feed/",
    "ScreenDaily": "https://www.screendaily.com/feed",
    "IndieWire": "https://www.indiewire.com/feed/",
}

# Add your Google Alerts RSS URLs here after setting them up
# Format: "Alert Name": "https://www.google.com/alerts/feeds/XXXXXX"
GOOGLE_ALERT_FEEDS = {
    # "Film Financing": "https://www.google.com/alerts/feeds/...",
    # "A24 Deals": "https://www.google.com/alerts/feeds/...",
}

ALL_FEEDS = {**TRADE_FEEDS, **GOOGLE_ALERT_FEEDS}

# Gemini system instructions
SYSTEM_INSTRUCTION = """You are an elite film industry intelligence analyst. Use emojis strategically.

Expertise: Deal analysis, financing forensics, streaming strategy, BS detection, pattern recognition.

Style: Direct, analytical, sardonic. No fluff. Label speculation clearly."""

SUMMARY_INSTRUCTION = """You are a film industry intelligence analyst. Analyze this article and return a JSON object with exactly these fields:
{
  "headline": "A concise rewritten headline (1 line)",
  "tldr": "One sentence TL;DR",
  "bullets": ["bullet 1", "bullet 2", "bullet 3"],
  "tags": ["tag1", "tag2", "tag3"],
  "category_suggestion": "one of: development, financing, legal_ba, distribution, packaging, talent, intl_sales, guilds, ai_tech, trending, spotlight, market, misc",
  "why_it_matters": "One sentence on why a film producer should care"
}

Return ONLY valid JSON. No markdown, no explanation. Just the JSON object."""

# In-memory conversation store for chat mode
conversations = {}

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


def init_db():
    """Create database tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS items (
        item_id TEXT PRIMARY KEY,
        source_url TEXT,
        source_type TEXT,
        source_name TEXT,
        title TEXT,
        raw_text TEXT,
        summary_json TEXT,
        status TEXT DEFAULT 'new',
        action TEXT,
        category TEXT,
        created_at TEXT,
        filed_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS message_map (
        inbox_message_id INTEGER,
        inbox_chat_id INTEGER,
        item_id TEXT,
        PRIMARY KEY (inbox_message_id, inbox_chat_id),
        FOREIGN KEY (item_id) REFERENCES items(item_id)
    )""")
    c.execute("""CREATE INDEX IF NOT EXISTS idx_items_status ON items(status)""")
    c.execute("""CREATE INDEX IF NOT EXISTS idx_items_source_url ON items(source_url)""")
    conn.commit()
    conn.close()
    logger.info(f"Database initialized at {DB_PATH}")


def get_db():
    """Get a database connection."""
    return sqlite3.connect(DB_PATH)


def item_exists(source_url):
    """Check if an item with this URL already exists."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT 1 FROM items WHERE source_url = ?", (source_url,))
    exists = c.fetchone() is not None
    conn.close()
    return exists


def generate_item_id(url):
    """Generate a stable item ID from URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def save_item(item_id, source_url, source_type, source_name, title, raw_text, summary_json):
    """Save a new item to the database."""
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute(
            """INSERT OR IGNORE INTO items
            (item_id, source_url, source_type, source_name, title, raw_text, summary_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?)""",
            (item_id, source_url, source_type, source_name, title, raw_text, summary_json,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def save_message_map(message_id, chat_id, item_id):
    """Map an inbox message to an item."""
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute(
            "INSERT OR REPLACE INTO message_map (inbox_message_id, inbox_chat_id, item_id) VALUES (?, ?, ?)",
            (message_id, chat_id, item_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_item_by_id(item_id):
    """Get an item by its ID."""
    conn = get_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM items WHERE item_id = ?", (item_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def update_item_status(item_id, status, action=None, category=None):
    """Update item status, action, and/or category."""
    conn = get_db()
    c = conn.cursor()
    if category:
        c.execute(
            "UPDATE items SET status=?, action=?, category=?, filed_at=? WHERE item_id=?",
            (status, action, category, datetime.now(timezone.utc).isoformat(), item_id),
        )
    elif action:
        c.execute("UPDATE items SET status=?, action=? WHERE item_id=?", (status, action, item_id))
    else:
        c.execute("UPDATE items SET status=? WHERE item_id=?", (status, item_id))
    conn.commit()
    conn.close()


def get_daily_stats():
    """Get stats for daily digest."""
    conn = get_db()
    c = conn.cursor()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*) FROM items WHERE created_at LIKE ?", (f"{today}%",))
    total_today = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM items WHERE status='new'")
    pending = c.fetchone()[0]
    c.execute(
        "SELECT category, COUNT(*) FROM items WHERE filed_at LIKE ? AND category IS NOT NULL GROUP BY category",
        (f"{today}%",),
    )
    by_category = dict(c.fetchall())
    conn.close()
    return {"total_today": total_today, "pending": pending, "by_category": by_category}


def get_weekly_items():
    """Get all filed items from the past 7 days for weekly analysis."""
    conn = get_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        """SELECT * FROM items
        WHERE status='filed' AND filed_at >= datetime('now', '-7 days')
        ORDER BY filed_at DESC"""
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Owner-only security
# ---------------------------------------------------------------------------


def owner_only(func):
    """Decorator to restrict handlers to OWNER_ID only."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id if update.effective_user else None
        if user_id != OWNER_ID:
            logger.warning(f"Unauthorized access attempt by user {user_id}")
            if update.callback_query:
                await update.callback_query.answer("Access denied.", show_alert=True)
            elif update.message:
                await update.message.reply_text("Access denied.")
            return
        return await func(update, context)
    return wrapper


# ---------------------------------------------------------------------------
# Gemini summarization
# ---------------------------------------------------------------------------


async def gemini_summarize(title, text, source_name, url):
    """Summarize content using Gemini. Returns parsed JSON or fallback dict."""
    if not GOOGLE_API_KEY:
        return _fallback_summary(title, text)

    prompt = f"""Article to analyze:
Title: {title}
Source: {source_name}
URL: {url}
Content: {(text or '')[:12000]}"""

    try:
        chat = model.start_chat(history=[])
        response = await asyncio.to_thread(
            chat.send_message, f"{SUMMARY_INSTRUCTION}\n\n{prompt}"
        )
        raw = response.text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        parsed = json.loads(raw)
        # Validate required fields
        for key in ("headline", "tldr", "bullets", "tags"):
            if key not in parsed:
                return _fallback_summary(title, text)
        return parsed
    except Exception as e:
        logger.error(f"Gemini summarize error: {e}")
        return _fallback_summary(title, text)


def _fallback_summary(title, text):
    """Fallback summary when Gemini fails."""
    return {
        "headline": title or "Untitled",
        "tldr": (text or "")[:200] + "..." if text else "No content available.",
        "bullets": ["Full article available via link"],
        "tags": ["unprocessed"],
        "category_suggestion": "misc",
        "why_it_matters": "",
    }


async def gemini_chat(user_message, user_id):
    """Handle free-form chat with Gemini (scout/analyze mode)."""
    if user_id not in conversations:
        conversations[user_id] = []

    conversations[user_id].append({"role": "user", "parts": [user_message]})
    if len(conversations[user_id]) > 20:
        conversations[user_id] = conversations[user_id][-20:]

    try:
        chat = model.start_chat(history=[])
        if len(conversations[user_id]) > 1:
            ctx = conversations[user_id][-10:-1]
            ctx_str = "\n".join(
                [f"{'User' if m['role']=='user' else 'Assistant'}: {m['parts'][0]}" for m in ctx]
            )
            full_prompt = f"{SYSTEM_INSTRUCTION}\n\nConversation:\n{ctx_str}\n\nUser: {user_message}"
        else:
            full_prompt = f"{SYSTEM_INSTRUCTION}\n\nUser: {user_message}"

        response = await asyncio.to_thread(chat.send_message, full_prompt)
        reply = response.text
        conversations[user_id].append({"role": "assistant", "parts": [reply]})
        return reply
    except Exception as e:
        logger.error(f"Gemini chat error: {e}")
        return "Analysis error. Try again."


# ---------------------------------------------------------------------------
# Scraping helpers
# ---------------------------------------------------------------------------


def scrape_url(url):
    """Scrape article text from a URL."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; FilmmakerBot/1.0)"}
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")

        # Remove script, style, nav elements
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()

        paragraphs = soup.find_all("p")
        text = "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
        return text[:15000] if text else ""
    except Exception as e:
        logger.error(f"Scrape error for {url}: {e}")
        return ""


def scrape_instagram(url):
    """Extract info from an Instagram URL (basic metadata)."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; FilmmakerBot/1.0)"}
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        soup = BeautifulSoup(resp.content, "html.parser")
        # Try to get meta description (caption preview)
        meta = soup.find("meta", attrs={"name": "description"}) or soup.find(
            "meta", attrs={"property": "og:description"}
        )
        title_tag = soup.find("meta", attrs={"property": "og:title"})
        caption = meta["content"] if meta else ""
        title = title_tag["content"] if title_tag else "Instagram Post"
        return title, caption
    except Exception as e:
        logger.error(f"Instagram scrape error: {e}")
        return "Instagram Post", ""


def detect_source_type(url):
    """Detect if a URL is Instagram, YouTube, or a general article."""
    domain = urlparse(url).netloc.lower()
    if "instagram.com" in domain:
        return "instagram"
    elif "youtube.com" in domain or "youtu.be" in domain:
        return "youtube"
    else:
        return "article"


# ---------------------------------------------------------------------------
# Intel Card formatting
# ---------------------------------------------------------------------------


def format_intel_card(item_id, source_name, source_type, url, summary, created_at):
    """Format an Intel Card message with summary."""
    date_str = created_at[:10] if created_at else datetime.now(timezone.utc).strftime("%Y-%m-%d")

    source_emoji = {"rss": "📰", "instagram": "📸", "manual": "🔗", "google_alert": "🔔"}.get(
        source_type, "📄"
    )

    tags_str = " ".join(f"#{t}" for t in summary.get("tags", [])) if summary.get("tags") else ""
    suggestion = summary.get("category_suggestion", "")
    suggestion_str = f"\n💡 Suggested: _{suggestion}_" if suggestion else ""

    bullets = summary.get("bullets", [])
    bullets_str = "\n".join(f"  • {b}" for b in bullets[:6])

    why = summary.get("why_it_matters", "")
    why_str = f"\n\n❗ *Why it matters:* {why}" if why else ""

    card = (
        f"{source_emoji} *{source_name}* | {date_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 *{summary.get('headline', 'Untitled')}*\n\n"
        f"📝 *TL;DR:* {summary.get('tldr', '')}\n\n"
        f"📋 *Summary:*\n{bullets_str}"
        f"{why_str}\n\n"
        f"🏷 {tags_str}"
        f"{suggestion_str}"
    )
    return card


def get_triage_keyboard(item_id, url):
    """Triage buttons: Yes / Archive / No + Read Article."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes", callback_data=f"triage_yes_{item_id}"),
            InlineKeyboardButton("📁 Archive", callback_data=f"triage_archive_{item_id}"),
            InlineKeyboardButton("❌ No", callback_data=f"triage_no_{item_id}"),
        ],
        [InlineKeyboardButton("📖 Read Article", url=url)],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_category_keyboard(item_id):
    """Category picker after Yes/Archive."""
    rows = []
    row = []
    for cat_key in FILING_CATEGORIES:
        topic = TOPICS[cat_key]
        row.append(
            InlineKeyboardButton(
                f"{topic['emoji']} {topic['label']}", callback_data=f"file_{cat_key}_{item_id}"
            )
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("◀️ Cancel", callback_data=f"triage_cancel_{item_id}")])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# Persistent keyboard
# ---------------------------------------------------------------------------


def get_persistent_keyboard():
    """Persistent keyboard below input field."""
    keyboard = [
        [KeyboardButton("📰 Latest News"), KeyboardButton("🔥 Trending")],
        [KeyboardButton("🔎 Scout"), KeyboardButton("📊 Stats")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)


# ---------------------------------------------------------------------------
# Google Sheets integration
# ---------------------------------------------------------------------------


async def append_to_sheets(item):
    """Append a row to Google Sheets. Returns True on success."""
    if not GOOGLE_SHEET_ID:
        logger.info("GOOGLE_SHEET_ID not set, skipping Sheets write")
        return True  # Don't block filing if Sheets not configured yet

    try:
        from google.oauth2 import service_account as sa
        from googleapiclient.discovery import build as gbuild

        sa_file = os.path.join(BASE_DIR, "service_account.json")
        if not os.path.exists(sa_file):
            logger.warning("service_account.json not found, skipping Sheets")
            return True

        creds = sa.Credentials.from_service_account_file(
            sa_file, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        service = gbuild("sheets", "v4", credentials=creds, cache_discovery=False)

        summary = json.loads(item.get("summary_json", "{}")) if item.get("summary_json") else {}
        bullets_str = " | ".join(summary.get("bullets", []))
        tags_str = ", ".join(summary.get("tags", []))

        row = [
            item.get("item_id", ""),
            item.get("created_at", ""),
            item.get("source_type", ""),
            item.get("source_name", ""),
            item.get("action", ""),
            item.get("category", ""),
            summary.get("headline", ""),
            summary.get("tldr", ""),
            bullets_str,
            tags_str,
            item.get("source_url", ""),
            item.get("filed_at", ""),
        ]

        await asyncio.to_thread(
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=GOOGLE_SHEET_ID,
                range="Library!A:L",
                valueInputOption="USER_ENTERED",
                body={"values": [row]},
            )
            .execute
        )
        logger.info(f"Sheets: appended row for {item.get('item_id')}")
        return True
    except Exception as e:
        logger.error(f"Sheets error: {e}")
        return False


# ---------------------------------------------------------------------------
# Telegram Topics routing
# ---------------------------------------------------------------------------


async def post_to_topic(bot, category, text, url=None):
    """Post a message to a Topic in the library group."""
    if LIBRARY_GROUP_CHAT_ID == 0:
        logger.info("LIBRARY_GROUP_CHAT_ID not set, skipping Topics post")
        return True

    topic = TOPICS.get(category)
    if not topic or topic["id"] == 0:
        logger.warning(f"Topic '{category}' not configured, skipping")
        return True

    try:
        keyboard = None
        if url:
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("📖 Read Article", url=url)]]
            )
        await bot.send_message(
            chat_id=LIBRARY_GROUP_CHAT_ID,
            message_thread_id=topic["id"],
            text=text,
            parse_mode="Markdown",
            reply_markup=keyboard,
            disable_web_page_preview=False,
        )
        return True
    except Exception as e:
        logger.error(f"Topics post error ({category}): {e}")
        return False


# ---------------------------------------------------------------------------
# RSS Polling
# ---------------------------------------------------------------------------


async def poll_rss(context: ContextTypes.DEFAULT_TYPE):
    """Poll all RSS feeds for new items."""
    logger.info("RSS poll starting...")
    new_count = 0

    for source_name, feed_url in ALL_FEEDS.items():
        try:
            feed = await asyncio.to_thread(feedparser.parse, feed_url)
            source_type = "google_alert" if source_name in GOOGLE_ALERT_FEEDS else "rss"

            for entry in feed.entries[:5]:
                url = entry.get("link", "")
                if not url or item_exists(url):
                    continue

                title = entry.get("title", "Untitled")
                item_id = generate_item_id(url)

                # Scrape article text
                raw_text = await asyncio.to_thread(scrape_url, url)

                # Gemini summarize
                summary = await gemini_summarize(title, raw_text, source_name, url)
                summary_json = json.dumps(summary)

                # Save to DB
                save_item(item_id, url, source_type, source_name, title, raw_text, summary_json)
                new_count += 1

                # Send Intel Card to owner
                card_text = format_intel_card(
                    item_id, source_name, source_type, url, summary,
                    datetime.now(timezone.utc).isoformat(),
                )
                try:
                    msg = await context.bot.send_message(
                        chat_id=OWNER_ID,
                        text=card_text,
                        parse_mode="Markdown",
                        reply_markup=get_triage_keyboard(item_id, url),
                        disable_web_page_preview=False,
                    )
                    save_message_map(msg.message_id, msg.chat_id, item_id)
                except Exception as e:
                    logger.error(f"Failed to send intel card: {e}")
                    # Try without markdown
                    try:
                        msg = await context.bot.send_message(
                            chat_id=OWNER_ID,
                            text=card_text,
                            reply_markup=get_triage_keyboard(item_id, url),
                        )
                        save_message_map(msg.message_id, msg.chat_id, item_id)
                    except Exception as e2:
                        logger.error(f"Failed to send intel card (plain): {e2}")

        except Exception as e:
            logger.error(f"Feed error {source_name}: {e}")

    logger.info(f"RSS poll complete. {new_count} new items.")


# ---------------------------------------------------------------------------
# Daily digest
# ---------------------------------------------------------------------------


async def send_daily_digest(context: ContextTypes.DEFAULT_TYPE):
    """Send daily morning digest to owner."""
    stats = get_daily_stats()

    cat_lines = []
    for cat, count in stats["by_category"].items():
        topic = TOPICS.get(cat, {})
        emoji = topic.get("emoji", "📄")
        label = topic.get("label", cat)
        cat_lines.append(f"  {emoji} {label}: {count}")

    cat_str = "\n".join(cat_lines) if cat_lines else "  No items filed yet today."

    digest = (
        f"☀️ *DAILY INTELLIGENCE BRIEF*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{datetime.now(timezone.utc).strftime('%A, %B %d, %Y')}\n\n"
        f"📬 *New items:* {stats['total_today']}\n"
        f"⏳ *Pending triage:* {stats['pending']}\n\n"
        f"📂 *Filed today:*\n{cat_str}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"_Open the bot to triage pending items._"
    )

    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=digest, parse_mode="Markdown")
        # Also post to Daily Brief topic
        await post_to_topic(context.bot, "daily_brief", digest)
    except Exception as e:
        logger.error(f"Daily digest error: {e}")


# ---------------------------------------------------------------------------
# Weekly report
# ---------------------------------------------------------------------------


async def send_weekly_report(context: ContextTypes.DEFAULT_TYPE):
    """Generate and send weekly intelligence report via Gemini."""
    items = get_weekly_items()
    if not items:
        return

    # Build context for Gemini
    summaries = []
    for item in items[:50]:
        s = json.loads(item.get("summary_json", "{}")) if item.get("summary_json") else {}
        summaries.append(
            f"- [{item.get('source_name')}] {s.get('headline', item.get('title', ''))}: "
            f"{s.get('tldr', '')} (Category: {item.get('category', 'unknown')})"
        )

    prompt = (
        "You are a film industry intelligence analyst. Based on this week's filed intel items, "
        "write a Weekly Intelligence Report. Include:\n"
        "1. Top 3 trends of the week\n"
        "2. Deals to watch\n"
        "3. Pattern analysis (connections between items)\n"
        "4. Instagram patterns (if any IG items present)\n"
        "5. One contrarian take\n\n"
        "Items filed this week:\n" + "\n".join(summaries)
    )

    try:
        chat = model.start_chat(history=[])
        response = await asyncio.to_thread(chat.send_message, prompt)
        report = response.text

        header = (
            f"📈 *WEEKLY INTELLIGENCE REPORT*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Week of {datetime.now(timezone.utc).strftime('%B %d, %Y')}\n"
            f"Items analyzed: {len(items)}\n\n"
        )

        full_report = header + report

        await context.bot.send_message(chat_id=OWNER_ID, text=full_report, parse_mode="Markdown")
        await post_to_topic(context.bot, "weekly_report", full_report)
    except Exception as e:
        logger.error(f"Weekly report error: {e}")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


@owner_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command — show welcome and set up polling."""
    welcome = """🎬 *PROJECT WATCHTOWER ACTIVE* 🎬
━━━━━━━━━━━━━━━━━━━━━━━━━━

📰 *Live feeds:* Deadline, Variety, THR, IndieWire, Screen Daily
📸 *Instagram:* Paste any IG link for analysis
🔗 *URLs:* Paste any article link for analysis

🔍 *Capabilities:*
• Gemini-powered article summaries
• Two-step triage filing
• Auto-categorization with tags
• Telegram Topics library
• Google Sheets export

━━━━━━━━━━━━━━━━━━━━━━━━━━
_Items arrive automatically. Triage with the buttons._
_Paste any URL or IG link for instant analysis._"""

    await update.message.reply_text(
        welcome, reply_markup=get_persistent_keyboard(), parse_mode="Markdown"
    )

    # Start RSS polling (every 30 min)
    jobs = context.job_queue.get_jobs_by_name("rss_poll")
    if not jobs:
        context.job_queue.run_repeating(poll_rss, interval=1800, first=10, name="rss_poll")
        logger.info("RSS polling scheduled (every 30 min)")

    # Schedule daily digest (7 AM UTC — adjust as needed)
    daily_jobs = context.job_queue.get_jobs_by_name("daily_digest")
    if not daily_jobs:
        from datetime import time as dtime
        context.job_queue.run_daily(
            send_daily_digest, time=dtime(hour=13, minute=0), name="daily_digest"
        )
        logger.info("Daily digest scheduled (13:00 UTC / 7 AM CT)")

    # Schedule weekly report (Sunday 8 AM UTC)
    weekly_jobs = context.job_queue.get_jobs_by_name("weekly_report")
    if not weekly_jobs:
        from datetime import time as dtime
        context.job_queue.run_daily(
            send_weekly_report, time=dtime(hour=14, minute=0),
            days=(6,), name="weekly_report",
        )
        logger.info("Weekly report scheduled (Sunday 14:00 UTC / 8 AM CT)")


@owner_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """❓ *ALL COMMANDS*
━━━━━━━━━━━━━━━━━━━━

*📰 NEWS*
/news — Latest RSS headlines
/deadline — Deadline feed
/variety — Variety feed
/thr — Hollywood Reporter

*🔍 ANALYSIS*
/scout — Investigate a topic
/analyze — Analyze a deal

*📊 INFO*
/stats — Filing statistics
/pending — Show pending items

*⚙️ SYSTEM*
/start — Restart bot + polling
/clear — Clear chat history
/help — This message

━━━━━━━━━━━━━━━━━━━━
_Or paste any URL / IG link for instant analysis!_"""

    await update.message.reply_text(help_text, parse_mode="Markdown")


@owner_only
async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 _Fetching latest intel..._", parse_mode="Markdown")
    articles = await asyncio.to_thread(fetch_news_simple, limit=8)
    text = format_news_list(articles, "Latest Intel")
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)


@owner_only
async def cmd_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 _Fetching Deadline..._", parse_mode="Markdown")
    articles = await asyncio.to_thread(fetch_news_simple, source="Deadline", limit=5)
    text = format_news_list(articles, "Deadline")
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)


@owner_only
async def cmd_variety(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 _Fetching Variety..._", parse_mode="Markdown")
    articles = await asyncio.to_thread(fetch_news_simple, source="Variety", limit=5)
    text = format_news_list(articles, "Variety")
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)


@owner_only
async def cmd_thr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 _Fetching THR..._", parse_mode="Markdown")
    articles = await asyncio.to_thread(fetch_news_simple, source="THR", limit=5)
    text = format_news_list(articles, "Hollywood Reporter")
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)


@owner_only
async def cmd_scout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """🔎 *SCOUT MODE*
━━━━━━━━━━━━━━━

Send me a topic to investigate:

• Company: _"Analyze A24's strategy"_
• Person: _"Jason Blum's deal structures"_
• Trend: _"Streaming licensing changes"_
• Deal: _"Apple TV+ sports rights"_

_Just type your query._"""
    await update.message.reply_text(text, parse_mode="Markdown")


@owner_only
async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """🔍 *ANALYZE MODE*
━━━━━━━━━━━━━━━

Paste any of the following for deep analysis:

• Deal announcement
• Trade article URL
• Press release
• Financing memo
• Instagram post link

_I'll break down what's real vs spin._"""
    await update.message.reply_text(text, parse_mode="Markdown")


@owner_only
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM items")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM items WHERE status='new'")
    pending = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM items WHERE status='filed'")
    filed = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM items WHERE status='dismissed'")
    dismissed = c.fetchone()[0]
    c.execute(
        "SELECT category, COUNT(*) FROM items WHERE category IS NOT NULL GROUP BY category ORDER BY COUNT(*) DESC"
    )
    cats = c.fetchall()
    conn.close()

    cat_lines = []
    for cat, count in cats:
        topic = TOPICS.get(cat, {})
        emoji = topic.get("emoji", "📄")
        label = topic.get("label", cat)
        cat_lines.append(f"  {emoji} {label}: {count}")

    cat_str = "\n".join(cat_lines) if cat_lines else "  No items filed yet."

    stats = (
        f"📊 *INTELLIGENCE STATS*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📬 Total items: {total}\n"
        f"⏳ Pending: {pending}\n"
        f"✅ Filed: {filed}\n"
        f"❌ Dismissed: {dismissed}\n\n"
        f"📂 *By category:*\n{cat_str}"
    )
    await update.message.reply_text(stats, parse_mode="Markdown")


@owner_only
async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM items WHERE status='new' ORDER BY created_at DESC LIMIT 10")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    if not rows:
        await update.message.reply_text("✅ No pending items. Inbox zero!")
        return

    await update.message.reply_text(
        f"⏳ *{len(rows)} pending items:*\n", parse_mode="Markdown"
    )

    for item in rows:
        summary = json.loads(item.get("summary_json", "{}")) if item.get("summary_json") else {}
        card_text = format_intel_card(
            item["item_id"], item["source_name"], item["source_type"],
            item["source_url"], summary, item["created_at"],
        )
        try:
            msg = await update.message.reply_text(
                card_text,
                parse_mode="Markdown",
                reply_markup=get_triage_keyboard(item["item_id"], item["source_url"]),
                disable_web_page_preview=False,
            )
            save_message_map(msg.message_id, msg.chat_id, item["item_id"])
        except Exception:
            msg = await update.message.reply_text(
                card_text,
                reply_markup=get_triage_keyboard(item["item_id"], item["source_url"]),
            )
            save_message_map(msg.message_id, msg.chat_id, item["item_id"])


@owner_only
async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversations[user_id] = []
    await update.message.reply_text("🧹 *CLEARED* — Fresh start.", parse_mode="Markdown")


# ---------------------------------------------------------------------------
# Simple news fetch (for /news, /deadline etc — quick list, no triage)
# ---------------------------------------------------------------------------


def fetch_news_simple(source=None, limit=5):
    """Fetch news from RSS feeds (simple list, no Gemini processing)."""
    articles = []
    feeds = {source: TRADE_FEEDS[source]} if source and source in TRADE_FEEDS else TRADE_FEEDS

    for name, url in feeds.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:limit]:
                pub = entry.get("published", "")
                articles.append({
                    "source": name,
                    "title": entry.get("title", "No title"),
                    "link": entry.get("link", ""),
                    "published": pub[:16] if pub else "",
                })
        except Exception as e:
            logger.error(f"Feed error {name}: {e}")

    return articles[:limit] if source else articles[:10]


def format_news_list(articles, category="Latest"):
    """Format articles as a simple list."""
    if not articles:
        return f"📭 No {category} articles found."

    lines = [f"📰 *{category.upper()} INTEL*", "━" * 25, ""]
    for i, art in enumerate(articles, 1):
        lines.append(f"*{i}. [{art['source']}]*")
        lines.append(f"   {art['title']}")
        lines.append(f"   🔗 [Read]({art['link']})")
        lines.append("")

    lines.append("💡 _Paste any URL for full Gemini analysis_")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Callback (button) handler — triage + category filing
# ---------------------------------------------------------------------------


@owner_only
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all inline button presses."""
    query = update.callback_query
    await query.answer()
    data = query.data

    # --- TRIAGE: Yes ---
    if data.startswith("triage_yes_"):
        item_id = data.replace("triage_yes_", "")
        item = get_item_by_id(item_id)
        if not item or item["status"] == "filed":
            await query.edit_message_text("Already processed.")
            return
        update_item_status(item_id, "picking_category", action="yes")
        await query.edit_message_text(
            "🎯 *Select a category:*",
            reply_markup=get_category_keyboard(item_id),
            parse_mode="Markdown",
        )

    # --- TRIAGE: Archive ---
    elif data.startswith("triage_archive_"):
        item_id = data.replace("triage_archive_", "")
        item = get_item_by_id(item_id)
        if not item or item["status"] == "filed":
            await query.edit_message_text("Already processed.")
            return
        update_item_status(item_id, "picking_category", action="archive")
        await query.edit_message_text(
            "📁 *Select archive category:*",
            reply_markup=get_category_keyboard(item_id),
            parse_mode="Markdown",
        )

    # --- TRIAGE: No ---
    elif data.startswith("triage_no_"):
        item_id = data.replace("triage_no_", "")
        update_item_status(item_id, "dismissed", action="no")
        try:
            await query.message.delete()
        except Exception:
            await query.edit_message_text("❌ Dismissed.")

    # --- TRIAGE: Cancel (go back to triage buttons) ---
    elif data.startswith("triage_cancel_"):
        item_id = data.replace("triage_cancel_", "")
        item = get_item_by_id(item_id)
        if item:
            update_item_status(item_id, "new")
            summary = json.loads(item.get("summary_json", "{}")) if item.get("summary_json") else {}
            card_text = format_intel_card(
                item_id, item["source_name"], item["source_type"],
                item["source_url"], summary, item["created_at"],
            )
            try:
                await query.edit_message_text(
                    card_text,
                    parse_mode="Markdown",
                    reply_markup=get_triage_keyboard(item_id, item["source_url"]),
                )
            except Exception:
                await query.edit_message_text(
                    card_text,
                    reply_markup=get_triage_keyboard(item_id, item["source_url"]),
                )

    # --- FILE to category ---
    elif data.startswith("file_"):
        parts = data.split("_", 2)
        if len(parts) < 3:
            return
        category = parts[1]
        item_id = parts[2]

        item = get_item_by_id(item_id)
        if not item:
            await query.edit_message_text("Item not found.")
            return
        if item["status"] == "filed":
            await query.edit_message_text("Already filed.")
            return

        # Commit: update DB
        update_item_status(item_id, "filed", action=item.get("action", "yes"), category=category)

        # Refresh item after update
        item = get_item_by_id(item_id)
        summary = json.loads(item.get("summary_json", "{}")) if item.get("summary_json") else {}
        topic = TOPICS.get(category, {})

        # Build the card text for the Topic post
        card_for_topic = format_intel_card(
            item_id, item["source_name"], item["source_type"],
            item["source_url"], summary, item["created_at"],
        )

        # Post to the chosen Topic
        await post_to_topic(context.bot, category, card_for_topic, item["source_url"])

        # Mirror to All Intel topic
        await post_to_topic(context.bot, "all_intel", card_for_topic, item["source_url"])

        # Mirror to Instagram Intel if source is Instagram
        if item.get("source_type") == "instagram":
            await post_to_topic(context.bot, "instagram_intel", card_for_topic, item["source_url"])

        # Write to Google Sheets (unless excluded category)
        sheets_ok = True
        if category not in NO_SHEETS_CATEGORIES:
            sheets_ok = await append_to_sheets(item)

        # Update inbox card
        status_emoji = "✅" if sheets_ok else "⚠️"
        topic_label = topic.get("label", category)
        await query.edit_message_text(
            f"{status_emoji} *Filed to {topic_label}*"
            + ("" if sheets_ok else "\n⚠️ Sheets write failed — item is saved locally."),
            parse_mode="Markdown",
        )


# ---------------------------------------------------------------------------
# Message handler — URL detection + chat
# ---------------------------------------------------------------------------


@owner_only
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages: URL ingestion or Gemini chat."""
    text = update.message.text.strip()

    # Handle persistent keyboard buttons
    if text == "📰 Latest News":
        return await cmd_news(update, context)
    elif text == "🔥 Trending":
        return await cmd_news(update, context)
    elif text == "🔎 Scout":
        return await cmd_scout(update, context)
    elif text == "📊 Stats":
        return await cmd_stats(update, context)

    # Check if it's a URL
    url_match = re.match(r"https?://\S+", text)
    if url_match:
        url = url_match.group(0)
        await process_url(update, context, url)
        return

    # Otherwise, Gemini chat mode
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    reply = await gemini_chat(text, update.effective_user.id)
    try:
        await update.message.reply_text(reply, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(reply)


async def process_url(update: Update, context: ContextTypes.DEFAULT_TYPE, url):
    """Process a pasted URL — scrape, summarize, present Intel Card."""
    # Dedupe check
    if item_exists(url):
        await update.message.reply_text("ℹ️ This URL has already been processed.")
        return

    await update.message.reply_text("🔄 _Analyzing..._", parse_mode="Markdown")

    source_type = detect_source_type(url)
    item_id = generate_item_id(url)

    if source_type == "instagram":
        title, raw_text = await asyncio.to_thread(scrape_instagram, url)
        source_name = "Instagram"
    else:
        raw_text = await asyncio.to_thread(scrape_url, url)
        title = ""
        # Try to get title from the page
        try:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; FilmmakerBot/1.0)"}
            resp = await asyncio.to_thread(
                lambda: requests.get(url, headers=headers, timeout=15)
            )
            soup = BeautifulSoup(resp.content, "html.parser")
            title = soup.title.get_text(strip=True) if soup.title else ""
        except Exception:
            pass
        source_name = urlparse(url).netloc.replace("www.", "")

    # Gemini summarize
    summary = await gemini_summarize(title, raw_text, source_name, url)
    summary_json = json.dumps(summary)

    # Save to DB
    save_item(item_id, url, source_type, source_name, title, raw_text, summary_json)

    # Send Intel Card
    card_text = format_intel_card(
        item_id, source_name, source_type, url, summary,
        datetime.now(timezone.utc).isoformat(),
    )

    try:
        msg = await update.message.reply_text(
            card_text,
            parse_mode="Markdown",
            reply_markup=get_triage_keyboard(item_id, url),
            disable_web_page_preview=False,
        )
    except Exception:
        msg = await update.message.reply_text(
            card_text,
            reply_markup=get_triage_keyboard(item_id, url),
        )

    save_message_map(msg.message_id, msg.chat_id, item_id)


# ---------------------------------------------------------------------------
# Bot setup and commands registration
# ---------------------------------------------------------------------------


async def post_init(application):
    """Set up bot commands for hamburger menu."""
    commands = [
        BotCommand("start", "Launch bot + start monitoring"),
        BotCommand("news", "Latest industry headlines"),
        BotCommand("deadline", "Deadline feed"),
        BotCommand("variety", "Variety feed"),
        BotCommand("thr", "Hollywood Reporter"),
        BotCommand("scout", "Investigate a topic"),
        BotCommand("analyze", "Analyze a deal/article"),
        BotCommand("stats", "Filing statistics"),
        BotCommand("pending", "Show pending items"),
        BotCommand("clear", "Clear chat history"),
        BotCommand("help", "Show all commands"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands registered")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN not set")
        return
    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY not set")
        return

    init_db()

    application = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    # Command handlers
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("news", cmd_news))
    application.add_handler(CommandHandler("deadline", cmd_deadline))
    application.add_handler(CommandHandler("variety", cmd_variety))
    application.add_handler(CommandHandler("thr", cmd_thr))
    application.add_handler(CommandHandler("scout", cmd_scout))
    application.add_handler(CommandHandler("analyze", cmd_analyze))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("pending", cmd_pending))
    application.add_handler(CommandHandler("clear", cmd_clear))

    # Callback & message handlers
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info(f"🎬 Project Watchtower starting... Owner: {OWNER_ID}")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
