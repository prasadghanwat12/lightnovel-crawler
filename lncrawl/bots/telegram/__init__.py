import logging
import os
import shutil
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          ConversationHandler, MessageHandler, filters, Job)
from lncrawl.core.app import App
from lncrawl.core.sources import prepare_crawler
from lncrawl.utils.uploader import upload

logger = logging.getLogger(__name__)

available_formats = ["epub", "text", "web", "mobi", "pdf"]

class TelegramBot:
    def start(self):
        os.environ["debug_mode"] = "yes"

        # Get the Telegram token from environment variables
        TOKEN = os.getenv("TELEGRAM_TOKEN", "")
        self.application = Application.builder().token(TOKEN).build()

        # Add a command handler for help
        self.application.add_handler(CommandHandler("help", self.show_help))

        # Add conversation handler with states
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("start", self.init_app),
                MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_novel_url),
            ],
            fallbacks=[CommandHandler("cancel", self.destroy_app)],
            states={
                "handle_novel_url": [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_novel_url),
                ],
                "handle_output_format": [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_output_format),
                ],
            },
        )
        self.application.add_handler(conv_handler)

        # Log all errors
        self.application.add_error_handler(self.error_handler)

        print("Telegram bot is online!")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Log Errors caused by Updates."""
        logger.warning("Error: %s\nCaused by: %s", context.error, update)

    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help message."""
        await update.message.reply_text("Send /start to create a new session.\n")
        return ConversationHandler.END

    async def init_app(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Initialize a new session."""
        if context.user_data.get("app"):
            await self.destroy_app(update, context)

        app = App()
        app.initialize()
        context.user_data["app"] = app
        await update.message.reply_text("A new session is created. Please provide the novel URL or query.")
        return "handle_novel_url"

    async def handle_novel_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle user input for the novel URL or search query."""
        app = context.user_data.get("app")
        app.user_input = update.message.text.strip()

        try:
            app.prepare_search()
        except Exception as e:
            await update.message.reply_text("Error: Invalid source or search query.")
            return "handle_novel_url"

        if app.crawler:
            await update.message.reply_text("Novel found! Preparing download...")
            return await self.process_download_request(update, context)

        await update.message.reply_text("No results. Please try again.")
        return "handle_novel_url"

    async def process_download_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process the download request."""
        app = context.user_data.get("app")

        # Select the output format (e.g., epub, pdf, etc.)
        i = 0
        buttons = []
        while i < len(available_formats):
            buttons.append(available_formats[i : i + 2])
            i += 2

        await update.message.reply_text(
            "In which format would you like to download the novel?",
            reply_markup=ReplyKeyboardMarkup(buttons, one_time_keyboard=True),
        )

        return "handle_output_format"

    async def handle_output_format(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle user selection of output format."""
        app = context.user_data.get("app")
        user_input = update.message.text.strip().lower()

        if user_input in available_formats:
            app.output_formats = {fmt: fmt == user_input for fmt in available_formats}
            await update.message.reply_text(f"Selected format: {user_input}")
        else:
            await update.message.reply_text("Invalid format. Please try again.")
            return "handle_output_format"

        # Start the download process
        job = context.job_queue.run_once(self.start_download, 1, context=context)
        context.user_data["job"] = job

        await update.message.reply_text("Download started. I will notify you when it completes.")
        return ConversationHandler.END

    async def start_download(self, context):
        """Start the download process."""
        app = context.job.context["app"]

        app.start_download()
        await context.bot.send_message(chat_id=context.job.chat_id, text="Download finished!")

        await self.generate_output(context)

    async def generate_output(self, context):
        """Generate the output files and send them to the user."""
        app = context.job.context["app"]
        output_files = app.bind_books()

        for file in output_files:
            file_size = os.stat(file).st_size
            if file_size < 50 * 1024 * 1024:
                await context.bot.send_document(context.job.chat_id, open(file, "rb"))
            else:
                await context.bot.send_message(context.job.chat_id, text="File is too large for Telegram.")
                await self.upload_to_cloud(file, context)

    async def upload_to_cloud(self, file, context):
        """Upload large files to an alternative cloud storage."""
        try:
            description = "Generated By: Lightnovel Crawler Telegram Bot"
            direct_link = upload(file, description)
            await context.bot.send_message(context.job.chat_id, text=f"Get your file here: {direct_link}")
        except Exception as e:
            logger.error("Failed to upload file: %s", e)
            await context.bot.send_message(context.job.chat_id, text="Failed to upload the file.")

    async def destroy_app(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Clean up the current session."""
        chat_id = str(update.effective_message.chat_id) if update else context.job.chat_id

        job = context.user_data.get("job")
        if job:
            job.schedule_removal()

        app = context.user_data.get("app")
        if app:
            app.destroy()
            context.user_data.pop("app", None)

        await context.bot.send_message(chat_id, text="Session closed", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
