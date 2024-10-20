import logging
import os
from telegram import ReplyKeyboardRemove, Update
from telegram.ext import (Application, CommandHandler, ConversationHandler, MessageHandler, filters, ContextTypes)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global dictionary to store user-specific data, including chat_id
user_data_store = {}

class TelegramBot:
    def __init__(self):
        os.environ["debug_mode"] = "yes"
        TOKEN = os.getenv("TELEGRAM_TOKEN")
        if not TOKEN:
            raise ValueError("TELEGRAM_TOKEN environment variable is missing!")
        self.application = Application.builder().token(TOKEN).build()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Initiates the bot for a user when /start command is sent."""
        chat_id = update.effective_chat.id
        user_data_store[chat_id] = {}  # Initialize data store for the user
        await update.message.reply_text("Welcome! Send me a novel URL or /cancel to exit.")
        return "handle_novel_url"  # Transition to handle_novel_url state

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancels the current conversation and clears user data."""
        chat_id = update.effective_chat.id
        if chat_id in user_data_store:
            del user_data_store[chat_id]  # Remove user data from store
        await update.message.reply_text("Operation cancelled.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    async def handle_novel_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handles the novel URL provided by the user."""
        chat_id = update.effective_chat.id
        url = update.message.text

        if chat_id not in user_data_store:
            user_data_store[chat_id] = {}

        user_data_store[chat_id]['novel_url'] = url
        await update.message.reply_text(f"URL received: {url}. Processing...")

        # Optionally, ask for more URLs or offer an exit
        await update.message.reply_text("Send another URL or /cancel to exit.")
        return "handle_novel_url"  # Stay in the same state for more URLs

    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Displays help information."""
        await update.message.reply_text("Send a novel URL to start downloading or /cancel to stop.")

    def setup_conversation_handler(self):
        """Sets up the conversation handler with states."""
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start)],  # Start via /start command
            states={
                "handle_novel_url": [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_novel_url),
                ],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
        )
        self.application.add_handler(conv_handler)
        self.application.add_handler(CommandHandler("help", self.show_help))

    def run(self):
        """Runs the bot."""
        self.setup_conversation_handler()
        self.application.run_polling()  # This starts the bot and listens for commands like /start

# Function to start the bot without invoking 'start()' manually
def run_bot():
    bot = TelegramBot()  # Instantiate the bot
    bot.run()  # This will run the bot and wait for user commands

if __name__ == "__main__":
    run_bot()
