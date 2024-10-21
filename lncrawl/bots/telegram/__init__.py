import logging
import os
import re
import shutil
from urllib.parse import urlparse

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          ConversationHandler, Job, MessageHandler, filters)

from lncrawl.core.app import App
from lncrawl.core.sources import prepare_crawler
from lncrawl.utils.uploader import upload

logger = logging.getLogger(__name__)

# Available formats for the download
available_formats = ["epub", "pdf", "mobi"]

# Define states for conversation handler
HANDLE_NOVEL_URL, HANDLE_FORMAT, DOWNLOAD_CHAPTERS = range(3)

class NovelCrawlerBot:
    def __init__(self):
        self.jobs = {}

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_data = context.user_data
        chat_id = update.message.chat_id
        user_data['chat_id'] = chat_id  # Save chat ID in user-specific data

        if self.get_current_jobs(update, context):
            await update.message.reply_text("You already have an active session. Please wait for it to finish or send /cancel to stop.")
            return ConversationHandler.END

        await update.message.reply_text(
            "Welcome! I recognize two types of input:\n"
            "- A lightnovel profile page URL.\n"
            "- A query to search your lightnovel.\n"
            "Send /cancel to stop this session anytime."
        )
        return HANDLE_NOVEL_URL

    def get_current_jobs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        return context.user_data.get("job")

    async def handle_novel_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_data = context.user_data

        if self.get_current_jobs(update, context):
            app = user_data.get("app")
            await update.message.reply_text(
                f"{user_data.get('status')}\n"
                f"{app.progress} out of {len(app.chapters)} chapters downloaded.\n"
                "To terminate this session, send /cancel."
            )
            return ConversationHandler.END
        else:
            app = App()
            app.initialize()
            user_data["app"] = app

            app.user_input = update.message.text.strip()

            try:
                app.prepare_search()
            except Exception:
                await update.message.reply_text(
                    "Sorry! I only recognize supported sources:\n"
                    "https://github.com/dipu-bd/lightnovel-crawler#supported-sources\n"
                    "Send a novel link or /cancel."
                )
                return HANDLE_NOVEL_URL

            if app.crawler:
                await update.message.reply_text("Got your novel link. Let's continue!")
                return self.handle_format(update, context)

    async def handle_format(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_data = context.user_data
        markup = ReplyKeyboardMarkup(
            [[f"/format {fmt}" for fmt in available_formats]],
            one_time_keyboard=True,
        )
        await update.message.reply_text("Choose a format", reply_markup=markup)
        return HANDLE_FORMAT

    async def handle_download(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_data = context.user_data
        app = user_data.get("app")

        user_data["status"] = "Downloading chapters..."
        await update.message.reply_text(user_data["status"])
        app.download_chapters()

        await update.message.reply_text(f"Chapters downloaded: {len(app.chapters)}")
        return ConversationHandler.END

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_data = context.user_data

        if self.get_current_jobs(update, context):
            await update.message.reply_text("Download cancelled.", reply_markup=ReplyKeyboardRemove())
            context.user_data.clear()  # Clear all user-specific data

        return ConversationHandler.END

    async def error(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.warning(f"Update {update} caused error {context.error}")

def main():
    application = Application.builder().token("YOUR_BOT_TOKEN").build()

    novel_bot = NovelCrawlerBot()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', novel_bot.start)],
        states={
            HANDLE_NOVEL_URL: [MessageHandler(filters.TEXT, novel_bot.handle_novel_url)],
            HANDLE_FORMAT: [MessageHandler(filters.TEXT, novel_bot.handle_format)],
            DOWNLOAD_CHAPTERS: [MessageHandler(filters.TEXT, novel_bot.handle_download)],
        },
        fallbacks=[CommandHandler('cancel', novel_bot.cancel)],
    )

    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == '__main__':
    main()
