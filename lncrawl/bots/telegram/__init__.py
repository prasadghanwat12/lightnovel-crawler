import logging
import os
import shutil
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          ConversationHandler, MessageHandler, filters, Job)
from lncrawl.core.app import App
from lncrawl.utils.uploader import upload
from lncrawl.core.sources import prepare_crawler  # Added missing import

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
                "handle_pack_by_volume": [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_pack_by_volume),
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
        """Initialize a new session and set the output path."""
        if context.user_data.get("app"):
            await self.destroy_app(update, context)

        app = App()
        app.initialize()

        # Define the output path for the app
        app.output_path = os.path.join(os.getcwd(), "downloads", str(update.message.chat_id))

        # Ensure the output directory exists
        if not os.path.exists(app.output_path):
            os.makedirs(app.output_path)

        context.user_data["app"] = app
        context.user_data["chat_id"] = update.message.chat_id  # Store the chat_id here

        await update.message.reply_text("A new session is created. Please provide the novel URL or query.")
        return "handle_novel_url"

    async def handle_novel_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle user input for the novel URL or search query."""
        if "app" not in context.user_data:
            await update.message.reply_text("Error: Application is not initialized.")
            return "handle_novel_url"

        app = context.user_data["app"]
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

        # Ask user if they want single file or split by volume
        await update.message.reply_text(
            "Do you want a single file or split the book by volumes?",
            reply_markup=ReplyKeyboardMarkup([["Single file", "Split by volumes"]], one_time_keyboard=True),
        )

        return "handle_pack_by_volume"

    async def handle_pack_by_volume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle user choice for single file or split by volume."""
        app = context.user_data.get("app")
        user_input = update.message.text.strip().lower()

        if user_input == "single file":
            app.pack_by_volume = False
            await update.message.reply_text("You chose to generate a single file.")
        elif user_input == "split by volumes":
            app.pack_by_volume = True
            await update.message.reply_text("You chose to split the book by volumes.")
        else:
            await update.message.reply_text("Invalid choice. Please try again.")
            return "handle_pack_by_volume"

        # Start the download process
        job = context.job_queue.run_once(self.start_download, 1, data=context.user_data)
        context.user_data["job"] = job

        await update.message.reply_text("Download started. I will notify you when it completes.")
        return ConversationHandler.END

    async def start_download(self, context):
        """Start the download process."""
        app = context.job.data["app"]
        chat_id = context.job.data["chat_id"]  # Retrieve chat_id

        app.start_download()
        await context.bot.send_message(chat_id=chat_id, text="Download finished!")

        await self.generate_output(context)

    async def generate_output(self, context):
        """Generate the output files and send them to the user."""
        app = context.job.data["app"]
        chat_id = context.job.data["chat_id"]  # Retrieve chat_id
        output_files = app.bind_books()

        for file in output_files:
            file_size = os.stat(file).st_size
            if file_size < 50 * 1024 * 1024:
                await context.bot.send_document(chat_id=chat_id, document=open(file, "rb"))
            else:
                await context.bot.send_message(chat_id=chat_id, text="File is too large for Telegram.")
                await self.upload_to_cloud(file, context)

    async def upload_to_cloud(self, file, context):
        """Upload large files to an alternative cloud storage."""
        chat_id = context.job.data["chat_id"]  # Retrieve chat_id
        try:
            description = "Generated By: Lightnovel Crawler Telegram Bot"
            direct_link = upload(file, description)
            await context.bot.send_message(chat_id=chat_id, text=f"Get your file here: {direct_link}")
        except Exception as e:
            logger.error("Failed to upload file: %s", e)
            await context.bot.send_message(chat_id=chat_id, text="Failed to upload the file.")

    async def destroy_app(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Clean up the current session."""
        chat_id = str(update.effective_message.chat_id) if update else context.job.data["chat_id"]

        job = context.user_data.get("job")
        if job:
            job.schedule_removal()

        app = context.user_data.get("app")
        if app:
            app.destroy()
            context.user_data.pop("app", None)

        await context.bot.send_message(chat_id, text="Session closed", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    async def show_crawlers_to_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle showing the list of crawlers."""
        app = context.user_data.get("app")

        if not app.crawler_links:
            await update.message.reply_text("No crawler links found. Please try again or use a different query.")
            return "handle_novel_url"  # Return to previous state

        buttons = []

        def make_button(i, url):
            return "%d - %s" % (i + 1, urlparse(url).hostname)

        for i in range(1, len(app.crawler_links) + 1, 2):
            buttons += [
                [
                    make_button(i - 1, app.crawler_links[i - 1]),
                    make_button(i, app.crawler_links[i]) if i < len(app.crawler_links) else "",
                ]
            ]

        await update.message.reply_text(
            "Choose where to search for your novel, \n"
            "or send /skip to search everywhere.",
            reply_markup=ReplyKeyboardMarkup(buttons, one_time_keyboard=True),
        )
        return "handle_crawler_to_search"

    async def show_novel_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle showing the list of novel selection."""
        app = context.user_data.get("app")

        if not app.search_results:
            await update.message.reply_text(
                "No results found by your query.\nTry again or send /cancel to stop."
            )
            return "handle_novel_url"

        if len(app.search_results) == 1:
            context.user_data["selected"] = app.search_results[0]
            return self.show_source_selection(update, context)

        await update.message.reply_text(
            "Choose any one of the following novels,"
            + " or send /cancel to stop this session.",
            reply_markup=ReplyKeyboardMarkup(
                [
                    [
                        "%d. %s (in %d sources)"
                        % (index + 1, res["title"], len(res["novels"]))
                    ]
                    for index, res in enumerate(app.search_results)
                ],
                one_time_keyboard=True,
            ),
        )

        return "handle_select_novel"
