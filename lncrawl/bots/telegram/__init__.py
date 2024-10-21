import logging
import os
from telegram import ReplyKeyboardRemove, Update
from telegram.ext import (Application, CommandHandler, ConversationHandler, MessageHandler, filters, ContextTypes)

logger = logging.getLogger(__name__)

available_formats = [
    "epub",
    "text",
    "web",
    "mobi",
    "pdf",
]

# Global dictionary to store user-specific data, including chat_id
user_data_store = {}


class TelegramBot:
    def __init__(self):
        os.environ["debug_mode"] = "yes"
        TOKEN = os.getenv("TELEGRAM_TOKEN", "")
        self.application = Application.builder().token(TOKEN).build()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Initiates the bot for a user."""
        chat_id = update.effective_chat.id
        user_data_store[chat_id] = {}  # Initialize data store for the user
        await update.message.reply_text("Welcome! Send me a novel URL or /cancel to exit.")

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

        # Ensure user has been initialized
        if chat_id not in user_data_store:
            user_data_store[chat_id] = {}

        # Store URL in user-specific storage
        user_data_store[chat_id]['novel_url'] = url

        # Proceed with handling URL and initiate further steps
        await update.message.reply_text(f"URL received: {url}. Processing...")

    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Displays help information."""
        await update.message.reply_text("Send a novel URL to start downloading or /cancel to stop.")

    def setup_conversation_handler(self):
        """Sets up the conversation handler with states."""
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start)],
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
        self.application.run_polling()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    bot = TelegramBot()
    bot.run()
