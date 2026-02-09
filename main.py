import os
import logging
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
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

# Gemini model
model = genai.GenerativeModel("gemini-2.0-flash")

# System instruction
SYSTEM_INSTRUCTION = """You are an elite film industry intelligence analyst and strategic advisor. Your expertise spans:

DEAL ARCHAEOLOGY: Expose the real economics behind announced deals. When someone shares trade news, dig beneath the headline - identify what is actually being said vs implied, spot missing context, and highlight red flags.

FINANCING FORENSICS: Analyze film financing structures, gap financing, tax incentives, pre-sales, MGs, corridors, and waterfalls. Identify where money actually flows vs where press releases claim.

SVOD/STREAMING STRATEGY: Deep knowledge of platform economics, licensing windows, originals vs acquisitions, and how streamers actually value content. Understand the difference between headline deals and actual P&L impact.

BULLSHIT DETECTOR: The industry runs on spin. Your job is to cut through it. When something sounds too good, explain why. When a deal seems structured oddly, explain what is really happening.

PATTERN RECOGNITION: Connect dots across the industry. Relate current news to historical precedents, identify emerging trends, and spot when history is repeating.

REPLICATION FILTER: Before suggesting any strategy, ask - can this person actually execute this? Avoid survivorship bias. Do not recommend paths that require existing relationships, track records, or capital the user may not have.

Communication style: Direct, analytical, occasionally sardonic. You respect the user's intelligence. No fluff, no cheerleading, no generic advice. When you do not know something, say so. When something is speculation, label it clearly."""

# Store conversation history
conversations = {}


async def post_init(application: Application) -> None:
    """Set up bot commands for the menu."""
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("clear", "Clear conversation history"),
        BotCommand("help", "Show available commands"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands menu initialized")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    user_id = update.effective_user.id
    conversations[user_id] = []
    
    welcome = """[FILMMAKER INTELLIGENCE BOT]

Ready for duty.

I analyze deals, decode financing structures, and cut through industry spin.

Commands:
/clear - Reset conversation
/help - Show commands

What do you want to dig into?"""
    
    await update.message.reply_text(welcome)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    help_text = """[COMMANDS]

/start - Restart the bot
/clear - Clear conversation history
/help - Show this message

[CAPABILITIES]

- Deal analysis and archaeology
- Financing structure breakdowns
- Streaming/SVOD strategy
- Industry news analysis
- BS detection on trade announcements

Just send me any industry news, deal memo, or question."""
    
    await update.message.reply_text(help_text)


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clear command."""
    user_id = update.effective_user.id
    conversations[user_id] = []
    await update.message.reply_text("[CLEARED] Conversation history reset. Fresh start.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming messages."""
    user_id = update.effective_user.id
    user_message = update.message.text
    
    if user_id not in conversations:
        conversations[user_id] = []
    
    conversations[user_id].append({"role": "user", "parts": [user_message]})
    
    # Keep last 20 messages for context
    if len(conversations[user_id]) > 20:
        conversations[user_id] = conversations[user_id][-20:]
    
    try:
        # Build chat with system instruction
        chat = model.start_chat(history=[])
        
        # Send system instruction first
        full_prompt = f"{SYSTEM_INSTRUCTION}\n\nUser message: {user_message}"
        
        # Include conversation context if exists
        if len(conversations[user_id]) > 1:
            context_msgs = conversations[user_id][-10:-1]
            context_str = "\n".join([f"{'User' if m['role']=='user' else 'Assistant'}: {m['parts'][0]}" for m in context_msgs])
            full_prompt = f"{SYSTEM_INSTRUCTION}\n\nRecent conversation:\n{context_str}\n\nUser message: {user_message}"
        
        response = chat.send_message(full_prompt)
        assistant_message = response.text
        
        conversations[user_id].append({"role": "assistant", "parts": [assistant_message]})
        
        await update.message.reply_text(assistant_message)
        
    except Exception as e:
        logger.error(f"Error generating response: {e}")
        await update.message.reply_text("[ERROR] Failed to generate response. Try again.")


def main() -> None:
    """Start the bot."""
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN not set")
        return
    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY not set")
        return
    
    # Build application with post_init
    application = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("clear", clear))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Starting Filmmaker Intelligence Bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
