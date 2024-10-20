import os
import re
import shutil
import logging
from telegram import Update, ForceReply
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, ReplyKeyboardMarkup, ReplyKeyboardRemove

# Assume these imports are defined in your app module
from your_app_module import App, prepare_crawler, upload  # Replace with actual module imports

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define conversation states
SELECT_SOURCE, HANDLE_SELECT_SOURCE, HANDLE_DELETE_CACHE, RANGE_SELECTION, HANDLE_RANGE_ALL, HANDLE_RANGE_FIRST, HANDLE_RANGE_LAST, HANDLE_RANGE_VOLUME, HANDLE_VOLUME_SELECTION, HANDLE_RANGE_CHAPTER, HANDLE_CHAPTER_SELECTION, HANDLE_PACK_BY_VOLUME, HANDLE_OUTPUT_FORMAT, HANDLE_DOWNLOADER = range(13)

class YourBotClass:
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data.clear()  # Clear user data on new start
        context.user_data['app'] = App()  # Initialize App
        await update.message.reply_text("Welcome to the LightNovel Downloader Bot! Use /download to get started.")

    async def handle_download(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Please send me the link to the novel.")
        return SELECT_SOURCE

    async def show_source_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")
        selected = context.user_data.get("selected", {})

        # Validate app and selected data
        if app is None or not selected.get("novels"):
            await update.message.reply_text("No novels found. Please start over.")
            return ConversationHandler.END

        await update.message.reply_text(
            f"Choose a source for '{selected['title']}':\n" +
            "\n".join(f"{i + 1}. {novel['url']}" for i, novel in enumerate(selected['novels'])),
            reply_markup=ReplyKeyboardMarkup(
                [[str(i + 1) for i in range(len(selected['novels']))]],
                one_time_keyboard=True
            )
        )
        return HANDLE_SELECT_SOURCE

    async def handle_select_source(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")
        selected = context.user_data.get("selected", {})
        
        # Validate input
        if app is None or selected is None:
            await update.message.reply_text("Session data is missing. Please start again.")
            return ConversationHandler.END
        
        source_index = int(update.message.text) - 1
        source = selected['novels'][source_index]

        # Prepare the crawler
        app.crawler = prepare_crawler(source["url"])
        return await self.get_novel_info(update, context)

    async def get_novel_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")
        
        if app is None:
            await update.message.reply_text("Session data is missing. Please start again.")
            return ConversationHandler.END
        
        await update.message.reply_text("Fetching novel information...")
        app.get_novel_info()

        if os.path.exists(app.output_path):
            await update.message.reply_text(
                "Local cache found. Do you want to use it?",
                reply_markup=ReplyKeyboardMarkup(
                    [["Yes", "No"]],
                    one_time_keyboard=True
                )
            )
            return HANDLE_DELETE_CACHE
        else:
            os.makedirs(app.output_path, exist_ok=True)

        await update.message.reply_text(
            f"{len(app.crawler.volumes)} volumes and {len(app.crawler.chapters)} chapters found."
        )
        return await self.display_range_selection_help(update)

    async def handle_delete_cache(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")
        text = update.message.text
        
        if text.startswith("No"):
            if os.path.exists(app.output_path):
                shutil.rmtree(app.output_path, ignore_errors=True)
            os.makedirs(app.output_path, exist_ok=True)

        await update.message.reply_text(
            f"{len(app.crawler.volumes)} volumes and {len(app.crawler.chapters)} chapters found."
        )
        return await self.display_range_selection_help(update)

    async def display_range_selection_help(self, update: Update):
        await update.message.reply_text(
            "\n".join([
                "Send /all to download everything.",
                "Send /last to download the last 50 chapters.",
                "Send /first to download the first 50 chapters.",
                "Send /volume to choose specific volumes to download.",
                "Send /chapter to choose a chapter range to download.",
                "To terminate this session, send /cancel."
            ])
        )
        return RANGE_SELECTION

    async def handle_range_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")
        app.chapters = app.crawler.chapters[:]  # Copy all chapters
        return await self.range_selection_done(update, context)

    async def handle_range_first(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")
        app.chapters = app.crawler.chapters[:50]  # First 50 chapters
        return await self.range_selection_done(update, context)

    async def handle_range_last(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")
        app.chapters = app.crawler.chapters[-50:]  # Last 50 chapters
        return await self.range_selection_done(update, context)

    async def handle_range_volume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")
        buttons = [str(vol["id"]) for vol in app.crawler.volumes]
        await update.message.reply_text(
            "Available volumes: " + ", ".join(buttons) +
            "\nEnter the volume numbers you want to download, separated by spaces."
        )
        return HANDLE_VOLUME_SELECTION

    async def handle_volume_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")
        text = update.message.text

        selected = re.findall(r"\d+", text)
        app.chapters = [chap for chap in app.crawler.chapters if chap["volume"] in map(int, selected)]
        return await self.range_selection_done(update, context)

    async def handle_range_chapter(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")
        await update.message.reply_text(
            "Enter the start and end chapter numbers separated by spaces."
        )
        return HANDLE_CHAPTER_SELECTION

    async def handle_chapter_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")
        text = update.message.text
        selected = re.findall(r"\d+", text)

        if len(selected) != 2:
            await update.message.reply_text("Please provide two chapter numbers.")
            return HANDLE_RANGE_CHAPTER
        
        start_chapter, end_chapter = map(int, selected)
        app.chapters = app.crawler.chapters[start_chapter - 1:end_chapter]
        return await self.range_selection_done(update, context)

    async def range_selection_done(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")

        await update.message.reply_text(
            f"You have selected {len(app.chapters)} chapters to download."
        )
        await update.message.reply_text(
            "Do you want to generate a single file or split the books into volumes?",
            reply_markup=ReplyKeyboardMarkup(
                [["Single file", "Split by volumes"]],
                one_time_keyboard=True
            )
        )
        return HANDLE_PACK_BY_VOLUME

    async def handle_pack_by_volume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")
        text = update.message.text
        app.pack_by_volume = text.startswith("Split")

        if app.pack_by_volume:
            await update.message.reply_text("Files will be split into volumes.")
        else:
            await update.message.reply_text("Files will be generated as a single output.")

        await update.message.reply_text(
            "In which format do you want the book? (e.g., epub, pdf)",
            reply_markup=ReplyKeyboardMarkup(
                [["epub", "pdf"], ["all"]],
                one_time_keyboard=True
            )
        )
        return HANDLE_OUTPUT_FORMAT

    async def handle_output_format(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")
        text = update.message.text.strip().lower()

        app.output_formats = {fmt: (fmt == text) for fmt in ["epub", "pdf"]}

        # Schedule download request
        chat_id = update.effective_chat.id
        context.job_queue.run_once(
            self.process_download_request,
            1,
            chat_id=chat_id,
            data=context.user_data
        )
        await update.message.reply_text("Your request is being processed.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    async def process_download_request(self, context):
        job = context.job
        user_data = job.data
        app = user_data.get("app")

        if app is None:
            await context.bot.send_message(job.chat_id, "Session data is missing.")
            return

        user_data["status"] = f'Downloading "{app.crawler.novel_title}"'
        await context.bot.send_message(job.chat_id, user_data["status"])
        
        app.start_download()  # Implement your download logic
        await context.bot.send_message(job.chat_id, "Download finished.")

        user_data["status"] = "Generating output files."
        await context.bot.send_message(job.chat_id, user_data["status"])
        output_files = app.bind_books()  # Implement your file binding logic
        logger.debug("Output files: %s", output_files)
        await context.bot.send_message(job.chat_id, "Output files generated.")

        user_data["status"] = "Compressing output folder."
        await context.bot.send_message(job.chat_id, user_data["status"])
        app.compress_books()  # Implement your compression logic

        for archive in app.archived_outputs:
            file_size = os.stat(archive).st_size
            if file_size < 50 * 1024 * 1024:  # 50MB limit
                await context.bot.send_document(job.chat_id, open(archive, "rb"))
            else:
                await context.bot.send_message(job.chat_id, "File is larger than 50 MB. Uploading to cloud storage.")
                try:
                    description = "Generated By: LightNovel Crawler Telegram Bot"
                    direct_link = upload(archive, description)  # Implement your upload logic
                    await context.bot.send_message(job.chat_id, f"Get your file here: {direct_link}")
                except Exception as e:
                    logger.error(f"Failed to upload file: {archive}", exc_info=e)

        await self.destroy_app(context)

    async def destroy_app(self, context):
        user_data = context.user_data
        if "app" in user_data:
            del user_data["app"]

    async def handle_downloader(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")
        if app:
            await update.message.reply_text(
                f"{context.user_data.get('status')}\n"
                f"{app.progress} out of {len(app.chapters)} chapters have been downloaded.\n"
                "To terminate this session, send /cancel."
            )
        else:
            await update.message.reply_text("No active download session.")

        return ConversationHandler.END

    def run(self):
        app = ApplicationBuilder().token("YOUR_TELEGRAM_BOT_TOKEN").build()

        # Define conversation handler
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start), CommandHandler("download", self.handle_download)],
            states={
                SELECT_SOURCE: [MessageHandler(filters.text & ~filters.command, self.show_source_selection)],
                HANDLE_SELECT_SOURCE: [MessageHandler(filters.text & ~filters.command, self.handle_select_source)],
                HANDLE_DELETE_CACHE: [MessageHandler(filters.text & ~filters.command, self.handle_delete_cache)],
                RANGE_SELECTION: [MessageHandler(filters.regex('^/all$'), self.handle_range_all),
                                 MessageHandler(filters.regex('^/last$'), self.handle_range_last),
                                 MessageHandler(filters.regex('^/first$'), self.handle_range_first),
                                 MessageHandler(filters.regex('^/volume$'), self.handle_range_volume),
                                 MessageHandler(filters.regex('^/chapter$'), self.handle_range_chapter)],
                HANDLE_VOLUME_SELECTION: [MessageHandler(filters.text & ~filters.command, self.handle_volume_selection)],
                HANDLE_CHAPTER_SELECTION: [MessageHandler(filters.text & ~filters.command, self.handle_chapter_selection)],
                HANDLE_PACK_BY_VOLUME: [MessageHandler(filters.text & ~filters.command, self.handle_pack_by_volume)],
                HANDLE_OUTPUT_FORMAT: [MessageHandler(filters.text & ~filters.command, self.handle_output_format)],
                HANDLE_DOWNLOADER: [CommandHandler("status", self.handle_downloader)]
            },
            fallbacks=[CommandHandler("cancel", self.destroy_app)]
        )

        app.add_handler(conv_handler)
        app.run_polling()

if __name__ == "__main__":
    YourBotClass().run()
