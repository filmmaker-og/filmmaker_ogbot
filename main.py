import os
import logging
import feedparser
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import google.generativeai as genai

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configure APIs
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel("gemini-3-flash-preview")

# === RSS FEEDS ===
NEWS_FEEDS = {
    "deadline": "https://deadline.com/feed/",
    "variety": "https://variety.com/feed/",
    "thr": "https://www.hollywoodreporter.com/feed/",
    "screendaily": "https://www.screendaily.com/feed",
    "indiewire": "https://www.indiewire.com/feed/",
}

# === SYSTEM INSTRUCTION ===
SYSTEM_INSTRUCTION = """You are an elite film industry intelligence analyst. Use emojis strategically.

Expertise: Deal analysis, financing forensics, streaming strategy, BS detection, pattern recognition.

Style: Direct, analytical, sardonic. No fluff. Label speculation clearly."""

# Storage
conversations = {}
vault_items = {}


def get_persistent_keyboard():
    """Persistent keyboard below input field."""
    keyboard = [
        [KeyboardButton("📰 Latest News"), KeyboardButton("🔥 Trending")],
        [KeyboardButton("🗄 Vault"), KeyboardButton("🔎 Scout")],
        [KeyboardButton("💵 Finance"), KeyboardButton("📚 Archive")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)


def get_main_keyboard():
    """Inline keyboard attached to messages."""
    keyboard = [
        [
            InlineKeyboardButton("🤖 AI/Tech", callback_data="cat_aitech"),
            InlineKeyboardButton("🎭 Guilds", callback_data="cat_guilds"),
            InlineKeyboardButton("📊 Market", callback_data="cat_market"),
        ],
        [
            InlineKeyboardButton("⭐ Spotlight", callback_data="cat_spotlight"),
            InlineKeyboardButton("🔥 Trending", callback_data="cat_trending"),
            InlineKeyboardButton("📰 General", callback_data="cat_general"),
        ],
        [
            InlineKeyboardButton("📡 Deadline", callback_data="src_deadline"),
            InlineKeyboardButton("📡 Variety", callback_data="src_variety"),
            InlineKeyboardButton("📡 THR", callback_data="src_thr"),
        ],
        [
            InlineKeyboardButton("🗄 Intelligence Vault", callback_data="vault"),
            InlineKeyboardButton("🔎 Scout", callback_data="scout"),
        ],
        [
            InlineKeyboardButton("💵 Finance Leads", callback_data="finance"),
            InlineKeyboardButton("📚 Master Archive", callback_data="archive"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_back_keyboard():
    keyboard = [[InlineKeyboardButton("◀️ Back to Menu", callback_data="main_menu")]]
    return InlineKeyboardMarkup(keyboard)


def fetch_news_sync(source=None, limit=5):
    """Fetch news from RSS feeds."""
    articles = []
    
    if source and source in NEWS_FEEDS:
        feeds = {source: NEWS_FEEDS[source]}
    else:
        feeds = NEWS_FEEDS
    
    for name, url in feeds.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:limit]:
                pub = entry.get("published", "")
                articles.append({
                    "source": name.upper(),
                    "title": entry.get("title", "No title"),
                    "link": entry.get("link", ""),
                    "published": pub[:16] if pub else "",
                })
        except Exception as e:
            logger.error(f"Feed error {name}: {e}")
    
    return articles[:limit] if source else articles[:10]


def format_articles(articles, category="Latest"):
    """Format articles for display."""
    if not articles:
        return f"📭 No {category} articles found. Try again later."
    
    lines = [f"📰 *{category.upper()} INTEL*", "━" * 25, ""]
    
    for i, art in enumerate(articles, 1):
        lines.append(f"*{i}. [{art['source']}]*")
        lines.append(f"   {art['title']}")
        lines.append(f"   🔗 [Read]({art['link']})")
        lines.append("")
    
    lines.append("💡 _Send any headline for analysis_")
    return "\n".join(lines)


async def post_init(application):
    """Set up bot commands for hamburger menu."""
    commands = [
        BotCommand("start", "🚀 Start bot & show menu"),
        BotCommand("news", "📰 Latest industry news"),
        BotCommand("deadline", "📡 Deadline headlines"),
        BotCommand("variety", "📡 Variety headlines"),
        BotCommand("thr", "📡 Hollywood Reporter"),
        BotCommand("trending", "🔥 Trending stories"),
        BotCommand("vault", "🗄 Your saved intel"),
        BotCommand("scout", "🔎 Investigate a topic"),
        BotCommand("finance", "💵 Financing news"),
        BotCommand("analyze", "🔍 Analyze a deal"),
        BotCommand("clear", "🧹 Clear chat history"),
        BotCommand("help", "❓ Show all commands"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands set")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversations[user_id] = []
    
    welcome = """🎬 *FILMMAKER INTELLIGENCE BOT* 🎬
━━━━━━━━━━━━━━━━━━━━━━━━━━

Ready for duty.

📰 *Live feeds:* Deadline, Variety, THR, IndieWire, Screen Daily

🔍 *Capabilities:*
• Deal & announcement analysis
• Financing structure breakdowns
• Industry BS detection
• Market trend tracking

━━━━━━━━━━━━━━━━━━━━━━━━━━
_Tap a button or send industry news to analyze._"""
    
    await update.message.reply_text(
        welcome,
        reply_markup=get_persistent_keyboard(),
        parse_mode="Markdown"
    )
    await update.message.reply_text(
        "⬇️ *SELECT A CATEGORY* ⬇️",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """❓ *ALL COMMANDS* ❓
━━━━━━━━━━━━━━━━━━━━

*📰 NEWS*
/news - All latest headlines
/deadline - Deadline feed
/variety - Variety feed  
/thr - Hollywood Reporter
/trending - Hot stories

*🔍 ANALYSIS*
/analyze - Analyze a deal
/scout - Deep dive a topic

*🗄 STORAGE*
/vault - Saved articles
/finance - Finance leads
/archive - Historical data

*⚙️ SYSTEM*
/start - Restart bot
/clear - Clear history
/help - This message

━━━━━━━━━━━━━━━━━━━━
_Or just paste any article/headline!_"""
    
    await update.message.reply_text(help_text, parse_mode="Markdown", reply_markup=get_main_keyboard())


async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 _Fetching latest intel..._", parse_mode="Markdown")
    articles = fetch_news_sync(limit=6)
    await update.message.reply_text(
        format_articles(articles, "Latest"),
        parse_mode="Markdown",
        disable_web_page_preview=True,
        reply_markup=get_back_keyboard()
    )


async def deadline_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 _Fetching Deadline..._", parse_mode="Markdown")
    articles = fetch_news_sync(source="deadline", limit=5)
    await update.message.reply_text(
        format_articles(articles, "Deadline"),
        parse_mode="Markdown",
        disable_web_page_preview=True,
        reply_markup=get_back_keyboard()
    )


async def variety_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 _Fetching Variety..._", parse_mode="Markdown")
    articles = fetch_news_sync(source="variety", limit=5)
    await update.message.reply_text(
        format_articles(articles, "Variety"),
        parse_mode="Markdown",
        disable_web_page_preview=True,
        reply_markup=get_back_keyboard()
    )


async def thr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 _Fetching THR..._", parse_mode="Markdown")
    articles = fetch_news_sync(source="thr", limit=5)
    await update.message.reply_text(
        format_articles(articles, "Hollywood Reporter"),
        parse_mode="Markdown",
        disable_web_page_preview=True,
        reply_markup=get_back_keyboard()
    )


async def trending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 _Finding trending stories..._", parse_mode="Markdown")
    articles = fetch_news_sync(limit=8)
    await update.message.reply_text(
        format_articles(articles[:5], "Trending"),
        parse_mode="Markdown",
        disable_web_page_preview=True,
        reply_markup=get_back_keyboard()
    )


async def vault_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    saved = vault_items.get(user_id, [])
    
    if not saved:
        text = """🗄 *INTELLIGENCE VAULT*
━━━━━━━━━━━━━━━━━━━━

Your vault is empty.

_Reply "save" after any analysis to store it here._"""
    else:
        text = f"🗄 *INTELLIGENCE VAULT* ({len(saved)} items)\n━━━━━━━━━━━━━━━━━━━━\n\n"
        for i, item in enumerate(saved[-10:], 1):
            text += f"{i}. {item[:50]}...\n"
    
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_back_keyboard())


async def scout_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """🔎 *SCOUT MODE*
━━━━━━━━━━━━━━━

Send me a topic to investigate:

• Company: _"Analyze A24's strategy"_
• Person: _"Jason Blum's deal structures"_  
• Trend: _"Streaming licensing changes"_
• Deal: _"Apple TV+ sports rights"_

_Just type your query after this._"""
    
    await update.message.reply_text(text, parse_mode="Markdown")


async def finance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """💵 *FINANCE LEADS*
━━━━━━━━━━━━━━━

_Tracking financing activity..._

Ask me about:
• Recent fund launches
• Gap financing deals
• Tax incentive updates
• Pre-sale market trends

_Type a finance question!_"""
    
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_back_keyboard())


async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """🔍 *ANALYZE MODE*
━━━━━━━━━━━━━━━

Paste any of the following for deep analysis:

• Deal announcement
• Trade article
• Press release
• Financing memo
• Box office report

_I'll break down what's real vs spin._"""
    
    await update.message.reply_text(text, parse_mode="Markdown")


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversations[user_id] = []
    await update.message.reply_text("🧹 *CLEARED* - Fresh start.", parse_mode="Markdown")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "main_menu":
        await query.edit_message_text(
            "⬇️ *SELECT A CATEGORY* ⬇️",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    # Source-specific feeds
    if data.startswith("src_"):
        source = data.replace("src_", "")
        source_names = {"deadline": "Deadline", "variety": "Variety", "thr": "Hollywood Reporter"}
        await query.edit_message_text(f"🔄 _Fetching {source_names.get(source, source)}..._", parse_mode="Markdown")
        articles = fetch_news_sync(source=source, limit=5)
        await query.edit_message_text(
            format_articles(articles, source_names.get(source, source)),
            parse_mode="Markdown",
            disable_web_page_preview=True,
            reply_markup=get_back_keyboard()
        )
        return
    
    # Category feeds
    if data.startswith("cat_"):
        cat_map = {
            "cat_aitech": ("AI & Tech", ["AI", "tech", "streaming", "digital", "algorithm"]),
            "cat_guilds": ("Guilds & Labor", ["guild", "union", "strike", "WGA", "SAG", "DGA", "IATSE", "labor"]),
            "cat_market": ("Box Office & Market", ["box office", "market", "stock", "earnings", "revenue"]),
            "cat_spotlight": ("Spotlight", None),
            "cat_trending": ("Trending", None),
            "cat_general": ("General", None),
        }
        cat_name, keywords = cat_map.get(data, ("News", None))
        await query.edit_message_text(f"🔄 _Fetching {cat_name}..._", parse_mode="Markdown")
        articles = fetch_news_sync(limit=10)
        
        if keywords:
            filtered = [a for a in articles if any(k.lower() in a['title'].lower() for k in keywords)]
            articles = filtered[:5] if filtered else articles[:5]
        else:
            articles = articles[:5]
        
        await query.edit_message_text(
            format_articles(articles, cat_name),
            parse_mode="Markdown",
            disable_web_page_preview=True,
            reply_markup=get_back_keyboard()
        )
        return
    
    # Other buttons
    responses = {
        "vault": "🗄 *VAULT*\n\nYour vault is empty.\n\n_Reply 'save' after analysis to store._",
        "scout": "🔎 *SCOUT*\n\nType a topic to investigate.",
        "finance": "💵 *FINANCE*\n\nAsk about financing, funds, or deals.",
        "archive": "📚 *ARCHIVE*\n\n_Coming soon: Historical deal database._",
    }
    
    if data in responses:
        await query.edit_message_text(responses[data], parse_mode="Markdown", reply_markup=get_back_keyboard())


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text
    
    # Handle persistent keyboard buttons
    button_map = {
        "📰 Latest News": "news",
        "🔥 Trending": "trending", 
        "🗄 Vault": "vault",
        "🔎 Scout": "scout",
        "💵 Finance": "finance",
        "📚 Archive": "archive",
    }
    
    if user_message in button_map:
        cmd = button_map[user_message]
        if cmd == "news":
            articles = fetch_news_sync(limit=6)
            await update.message.reply_text(
                format_articles(articles, "Latest"),
                parse_mode="Markdown",
                disable_web_page_preview=True,
                reply_markup=get_back_keyboard()
            )
        elif cmd == "trending":
            articles = fetch_news_sync(limit=5)
            await update.message.reply_text(
                format_articles(articles, "Trending"),
                parse_mode="Markdown",
                disable_web_page_preview=True,
                reply_markup=get_back_keyboard()
            )
        elif cmd == "vault":
            await vault_command(update, context)
        elif cmd == "scout":
            await scout_command(update, context)
        elif cmd == "finance":
            await finance_command(update, context)
        elif cmd == "archive":
            await update.message.reply_text("📚 *ARCHIVE*\n\n_Coming soon._", parse_mode="Markdown")
        return
    
    # Regular message handling with Gemini
    if user_id not in conversations:
        conversations[user_id] = []
    
    conversations[user_id].append({"role": "user", "parts": [user_message]})
    if len(conversations[user_id]) > 20:
        conversations[user_id] = conversations[user_id][-20:]
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    try:
        chat = model.start_chat(history=[])
        
        if len(conversations[user_id]) > 1:
            context_msgs = conversations[user_id][-10:-1]
            context_str = "\n".join([f"{'User' if m['role']=='user' else 'Assistant'}: {m['parts'][0]}" for m in context_msgs])
            full_prompt = f"{SYSTEM_INSTRUCTION}\n\nConversation:\n{context_str}\n\nUser: {user_message}"
        else:
            full_prompt = f"{SYSTEM_INSTRUCTION}\n\nUser: {user_message}"
        
        response = chat.send_message(full_prompt)
        assistant_message = response.text
        
        conversations[user_id].append({"role": "assistant", "parts": [assistant_message]})
        
        # Try markdown first, fall back to plain text
        try:
            await update.message.reply_text(assistant_message, parse_mode="Markdown")
        except:
            await update.message.reply_text(assistant_message)
        
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        await update.message.reply_text("⚠️ *ERROR* - Try again.", parse_mode="Markdown")


def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN not set")
        return
    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY not set")
        return
    
    application = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("news", news_command))
    application.add_handler(CommandHandler("deadline", deadline_command))
    application.add_handler(CommandHandler("variety", variety_command))
    application.add_handler(CommandHandler("thr", thr_command))
    application.add_handler(CommandHandler("trending", trending_command))
    application.add_handler(CommandHandler("vault", vault_command))
    application.add_handler(CommandHandler("scout", scout_command))
    application.add_handler(CommandHandler("finance", finance_command))
    application.add_handler(CommandHandler("analyze", analyze_command))
    application.add_handler(CommandHandler("clear", clear_command))
    
    # Callback & message handlers
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🚀 Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
