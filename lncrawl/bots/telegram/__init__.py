import logging
import os
import re
import shutil
import time
import asyncio
import aioredis
from urllib.parse import urlparse
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (Application, CommandHandler, ContextTypes, ConversationHandler, Job, MessageHandler, filters)
from lncrawl.core.app import App
from lncrawl.core.sources import prepare_crawler
from lncrawl.utils.uploader import upload
import tracemalloc

tracemalloc.start()
logger = logging.getLogger(__name__)

available_formats = [
    "epub",
    "text",
    "web",
    "mobi",
    "pdf",
]

# Rate limiting configuration
RATE_LIMIT = 5  # seconds between requests
USER_REQUESTS = {}

# Redis cache for storing session data
redis_cache = None


class TelegramBot:
    def __init__(self):
        self.redis = None

    async def init_redis(self):
        """Initialize Redis connection."""
        self.redis = await aioredis.from_url("redis://localhost")

    async def start(self):
        os.environ["debug_mode"] = "yes"
        TOKEN = os.getenv("TELEGRAM_TOKEN", "")
        self.application = Application.builder().token(TOKEN).build()

        # Add handlers
        self.application.add_handler(CommandHandler("help", self.show_help))
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("start", self.init_app),
                MessageHandler(
                    filters.TEXT & ~(filters.COMMAND), self.handle_novel_url
                ),
            ],
            fallbacks=[
                CommandHandler("cancel", self.destroy_app),
            ],
            states={
                "handle_novel_url": [
                    MessageHandler(
                        filters.TEXT & ~(filters.COMMAND), self.handle_novel_url
                    ),
                ],
                "handle_crawler_to_search": [
                    CommandHandler(
                        "skip", self.handle_crawler_to_search
                    ),
                    MessageHandler(
                        filters.TEXT & ~(filters.COMMAND), self.handle_crawler_to_search
                    ),
                ],
                "handle_select_novel": [
                    MessageHandler(
                        filters.TEXT & ~(filters.COMMAND), self.handle_select_novel
                    ),
                ],
                "handle_select_source": [
                    MessageHandler(
                        filters.TEXT & ~(filters.COMMAND), self.handle_select_source
                    ),
                ],
                "handle_delete_cache": [
                    MessageHandler(
                        filters.TEXT & ~(filters.COMMAND), self.handle_delete_cache
                    ),
                ],
                "handle_range_selection": [
                    CommandHandler("all", self.handle_range_all),
                    CommandHandler("last", self.handle_range_last),
                    CommandHandler(
                        "first", self.handle_range_first
                    ),
                    CommandHandler(
                        "volume", self.handle_range_volume
                    ),
                    CommandHandler(
                        "chapter", self.handle_range_chapter
                    ),
                    MessageHandler(filters.TEXT & ~(filters.COMMAND), self.display_range_selection_help),
                ],
                "handle_volume_selection": [
                    MessageHandler(
                        filters.TEXT & ~(filters.COMMAND), self.handle_volume_selection
                    ),
                ],
                "handle_chapter_selection": [
                    MessageHandler(
                        filters.TEXT & ~(filters.COMMAND), self.handle_chapter_selection
                    ),
                ],
                "handle_pack_by_volume": [
                    MessageHandler(
                        filters.TEXT & ~(filters.COMMAND), self.handle_pack_by_volume
                    ),
                ],
                "handle_output_format": [
                    MessageHandler(
                        filters.TEXT & ~(filters.COMMAND), self.handle_output_format
                    ),
                ],
            },
        )
        self.application.add_handler(conv_handler)
        self.application.add_handler(
            MessageHandler(filters.TEXT, self.handle_downloader)
        )

        # Add error handler
        self.application.add_error_handler(self.error_handler)

        print("Telegram bot is online!")
        await self.init_redis()

        await self.application.run_polling(allowed_updates=Update.ALL_TYPES)

    async def rate_limited(self, update: Update) -> bool:
        """Check if user is rate-limited"""
        user_id = str(update.effective_user.id)
        now = int(time.time())
        last_request_time = USER_REQUESTS.get(user_id)

        if last_request_time and now - last_request_time < RATE_LIMIT:
            await update.message.reply_text("Please wait before making another request.")
            return True
        USER_REQUESTS[user_id] = now
        return False

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Log Errors caused by Updates."""
        logger.warning(f"Error: {context.error}\nCaused by: {update}")

    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Send /start to create a new session.\n")
        return ConversationHandler.END

    async def destroy_app(self, update: Update, context: ContextTypes.DEFAULT_TYPE, job: Job = None):
        """Destroy the current session."""
        chat_id = str(update.effective_message.chat_id) if update else job.chat_id
        for job in self.get_current_jobs(update, context, chat_id):
            job.schedule_removal()

        app = context.user_data.pop("app", None)
        if app:
            app.destroy()
        await context.bot.send_message(chat_id, text="Session closed", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    async def init_app(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Initialize a new session."""
        if await self.rate_limited(update):
            return ConversationHandler.END

        if context.user_data.get("app"):
            await self.destroy_app(update, context)

        app = App()
        app.initialize()
        context.user_data["app"] = app
        await update.message.reply_text("A new session is created.")
        await update.message.reply_text(
            "I recognize input of these two categories:\n"
            "- Profile page url of a lightnovel.\n"
            "- A query to search your lightnovel.\n"
            "Enter whatever you want or send /cancel to stop."
        )
        return "handle_novel_url"

    async def handle_novel_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle novel URL or search query input."""
        if await self.rate_limited(update):
            return "handle_novel_url"

        app = context.user_data.get("app", App())
        app.user_input = update.message.text.strip()

        try:
            app.prepare_search()
        except Exception:
            await update.message.reply_text(
                "Sorry! I only recognize these sources:\n"
                + "https://github.com/dipu-bd/lightnovel-crawler#supported-sources"
            )
            return "handle_novel_url"

        await self.show_crawlers_to_search(update, context)

    async def show_crawlers_to_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Display options to choose search sources."""
        app = context.user_data["app"]

        buttons = [
            [f"{i + 1} - {urlparse(url).hostname}" for i, url in enumerate(app.crawler_links)]
        ]
        await update.message.reply_text(
            "Choose where to search for your novel, \n"
            "or send /skip to search everywhere.",
            reply_markup=ReplyKeyboardMarkup(buttons, one_time_keyboard=True),
        )
        return "handle_crawler_to_search"

    async def handle_crawler_to_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle search crawler selection."""
        app = context.user_data.get("app")
        link = update.message.text
        selected_crawlers = []

        if link.isdigit():
            selected_crawlers.append(app.crawler_links[int(link) - 1])
        else:
            selected_crawlers += [
                x for i, x in enumerate(app.crawler_links)
                if f"{i + 1} - {urlparse(x).hostname}" == link
            ]

        if selected_crawlers:
            app.crawler_links = selected_crawlers

        await update.message.reply_text(
            f'Searching for "{app.user_input}" in {len(app.crawler_links)} sites. Please wait.',
            reply_markup=ReplyKeyboardRemove(),
        )
        await update.message.reply_text("DO NOT type anything until I reply.")
        app.search_novel()
        return await self.show_novel_selection(update, context)

    async def show_novel_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Display search results."""
        app = context.user_data.get("app")

        if len(app.search_results) == 0:
            await update.message.reply_text(
                "No results found by your query. Try again or send /cancel to stop."
            )
            return "handle_novel_url"

        if len(app.search_results) == 1:
            context.user_data["selected"] = app.search_results[0]
            return await self.show_source_selection(update, context)

        await update.message.reply_text(
            "Choose any one of the following novels, or send /cancel to stop this session.",
            reply_markup=ReplyKeyboardMarkup(
                [
                    [f"{index + 1}. {res['title']} (in {len(res['novels'])} sources)"]
                    for index, res in enumerate(app.search_results)
                ],
                one_time_keyboard=True,
            ),
        )
        return "handle_select_novel"

    async def handle_select_novel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle novel selection."""
        app = context.user_data.get("app")
        selected_index = int(update.message.text.strip()) - 1

        if selected_index < 0 or selected_index >= len(app.search_results):
            await update.message.reply_text("Invalid selection. Please try again.")
            return "handle_select_novel"

        context.user_data["selected"] = app.search_results[selected_index]
        return await self.show_source_selection(update, context)

    async def show_source_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Display sources for the selected novel."""
        app = context.user_data["app"]
        selected = context.user_data["selected"]
        available_sources = selected["novels"]

        await update.message.reply_text(
            "Choose a source for your novel, or send /cancel to stop.",
            reply_markup=ReplyKeyboardMarkup(
                [
                    [f"{source['name']} (URL: {source['url']})"]
                    for source in available_sources
                ],
                one_time_keyboard=True,
            ),
        )
        return "handle_select_source"

    async def handle_select_source(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle source selection for the novel."""
        app = context.user_data["app"]
        selected = context.user_data["selected"]
        source_name = update.message.text.strip()

        for source in selected["novels"]:
            if source_name in source['name']:
                app.selected_source = source
                break
        else:
            await update.message.reply_text("Invalid source. Please try again.")
            return "handle_select_source"

        await update.message.reply_text(
            "Source selected. Now please select output format:",
            reply_markup=ReplyKeyboardMarkup([
                [format] for format in available_formats
            ], one_time_keyboard=True)
        )
        return "handle_output_format"

    async def handle_output_format(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle output format selection."""
        text = update.message.text.strip().lower()
        app = context.user_data["app"]
        app.output_formats = {}

        if text in available_formats:
            for x in available_formats:
                app.output_formats[x] = (x == text)
        elif text != "all":
            await update.message.reply_text("Sorry, I did not understand.")
            return

        chat_id = update.effective_message.chat_id
        job = context.job_queue.run_once(
            self.process_download_request,
            1,
            name=str(update.effective_user.id),
            chat_id=chat_id,
            data=context.user_data
        )
        context.user_data["job"] = job

        await update.message.reply_text(
            f'Your request has been received. I will generate the book in "{text}" format.',
            reply_markup=ReplyKeyboardRemove(),
        )

        return ConversationHandler.END

    async def process_download_request(self, context: ContextTypes.DEFAULT_TYPE):
        """Process the download request in the background."""
        job = context.job
        user_data = job.data
        app = user_data.get("app")

        if app:
            user_data["status"] = f'Downloading "{app.selected_source["title"]}"'
            app.start_download()
            await context.bot.send_message(job.chat_id, text="Download finished.")

        if app:
            user_data["status"] = "Generating output files"
            await context.bot.send_message(job.chat_id, text=user_data.get("status"))
            output_files = app.bind_books()
            logger.debug("Output files: %s", output_files)
            await context.bot.send_message(job.chat_id, text="Output files generated.")

        if app:
            user_data["status"] = "Compressing output folder."
            await context.bot.send_message(job.chat_id, text=user_data.get("status"))
            app.compress_books()

        for archive in app.archived_outputs:
            file_size = os.stat(archive).st_size
            if file_size < 49.99 * 1024 * 1024:
                await context.bot.send_document(
                    job.chat_id,
                    open(archive, "rb")
                )
            else:
                await context.bot.send_message(
                    job.chat_id,
                    text="File size exceeds 50 MB, so it cannot be sent via Telegram. Uploading to alternative cloud storage."
                )
                try:
                    description = "Generated by Lightnovel Crawler Telegram Bot"
                    direct_link = upload(archive, description)
                    await context.bot.send_message(job.chat_id, text=f"Get your file here: {direct_link}")
                except Exception as e:
                    logger.error(f"Failed to upload file: {archive}. Error: {e}")

        await self.destroy_app(None, context, job)

    async def handle_downloader(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle download process."""
        app = context.user_data.get("app")
        job = self.get_current_jobs(update, context)

        if app or job:
            await update.message.reply_text(
                f"{context.user_data.get('status')}\n"
                f"{app.progress} out of {len(app.chapters)} chapters have been downloaded.\n"
                "To terminate this session, send /cancel."
            )
        return ConversationHandler.END

    def get_current_jobs(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id=None):
        """Retrieve the current jobs in the queue."""
        name = str(update.effective_message.chat_id) if update else chat_id
        return context.job_queue.get_jobs_by_name(name)


if __name__ == "__main__":
    bot = TelegramBot()

    # Run the bot
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(bot.start())
    except RuntimeError as e:
        print(f"RuntimeError: {e}")
