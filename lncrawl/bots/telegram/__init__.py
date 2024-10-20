import os
import re
import shutil
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, ReplyKeyboardMarkup, ReplyKeyboardRemove
from your_app_module import App, prepare_crawler  # Replace with actual module imports
import logging

logger = logging.getLogger(__name__)

class YourBotClass:

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Ensure that the update and context are not None
        if update is None or context is None:
            logger.error("Update or context is None.")
            return

        # Initialize the app if not already done
        context.user_data.setdefault("app", App())
        await update.message.reply_text("Welcome to the bot! How can I assist you today?")

    async def show_source_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")
        selected = context.user_data.get("selected")

        # Check if app and selected data are valid
        if app is None or selected is None:
            await update.message.reply_text("Session data is missing. Please start again.")
            return

        assert isinstance(app, App)

        if len(selected["novels"]) == 1:
            app.crawler = prepare_crawler(selected["novels"][0]["url"])
            return await self.get_novel_info(update, context)

        await update.message.reply_text(
            ('Choose a source to download "%s".' % selected["title"])
            + " or send /cancel to stop this session.",
            reply_markup=ReplyKeyboardMarkup(
                [
                    [
                        "%d. %s %s"
                        % (
                            index + 1,
                            novel["url"],
                            novel.get("info", ""),  # Use .get to avoid KeyError
                        )
                    ]
                    for index, novel in enumerate(selected["novels"])
                ],
                one_time_keyboard=True,
            ),
        )

        return "handle_select_source"

    async def handle_select_source(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")
        selected = context.user_data.get("selected")

        # Validate the app and selected data
        if app is None or selected is None:
            await update.message.reply_text("Session data is missing. Please start again.")
            return

        source = None
        text = update.message.text
        if text:
            if text.isdigit():
                source = selected["novels"][int(text) - 1]
            else:
                for i, item in enumerate(selected["novels"]):
                    sample = "%d. %s" % (i + 1, item["url"])
                    if text.startswith(sample):
                        source = item
                        break
                    elif len(text) >= 5 and text.lower() in item["url"].lower():
                        source = item
                        break

        if not selected or not (source and source.get("url")):
            return await self.show_source_selection(update, context)

        app.crawler = prepare_crawler(source.get("url"))
        return await self.get_novel_info(update, context)

    async def get_novel_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")

        if app is None:
            await update.message.reply_text("Session data is missing. Please start again.")
            return

        await update.message.reply_text(app.crawler.novel_url)
        await update.message.reply_text("Reading novel info...")
        app.get_novel_info()

        if os.path.exists(app.output_path):
            await update.message.reply_text(
                "Local cache found. Do you want to use it?",
                reply_markup=ReplyKeyboardMarkup(
                    [["Yes", "No"]], one_time_keyboard=True
                ),
            )
            return "handle_delete_cache"
        else:
            os.makedirs(app.output_path, exist_ok=True)

        # Get chapter range
        await update.message.reply_text(
            "%d volumes and %d chapters found."
            % (len(app.crawler.volumes), len(app.crawler.chapters)),
            reply_markup=ReplyKeyboardRemove(),
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
            "%d volumes and %d chapters found."
            % (len(app.crawler.volumes), len(app.crawler.chapters)),
            reply_markup=ReplyKeyboardRemove(),
        )
        return await self.display_range_selection_help(update)

    async def display_range_selection_help(self, update: Update):
        await update.message.reply_text(
            "\n".join(
                [
                    "Send /all to download everything.",
                    "Send /last to download last 50 chapters.",
                    "Send /first to download first 50 chapters.",
                    "Send /volume to choose specific volumes to download.",
                    "Send /chapter to choose a chapter range to download.",
                    "To terminate this session, send /cancel.",
                ]
            )
        )
        return "handle_range_selection"

    async def range_selection_done(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")

        if app is None:
            await update.message.reply_text("Session data is missing. Please start again.")
            return

        await update.message.reply_text(
            "You have selected %d chapters to download." % len(app.chapters)
        )
        if len(app.chapters) == 0:
            return await self.display_range_selection_help(update)

        await update.message.reply_text(
            "Do you want to generate a single file or split the books into volumes?",
            reply_markup=ReplyKeyboardMarkup(
                [["Single file", "Split by volumes"]], one_time_keyboard=True
            ),
        )
        return "handle_pack_by_volume"

    async def handle_range_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")

        if app is None:
            await update.message.reply_text("Session data is missing. Please start again.")
            return

        app.chapters = app.crawler.chapters[:]
        return await self.range_selection_done(update, context)

    async def handle_range_first(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")

        if app is None:
            await update.message.reply_text("Session data is missing. Please start again.")
            return

        app.chapters = app.crawler.chapters[:50]
        return await self.range_selection_done(update, context)

    async def handle_range_last(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")

        if app is None:
            await update.message.reply_text("Session data is missing. Please start again.")
            return

        app.chapters = app.crawler.chapters[-50:]
        return await self.range_selection_done(update, context)

    async def handle_range_volume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")

        if app is None:
            await update.message.reply_text("Session data is missing. Please start again.")
            return

        buttons = [str(vol["id"]) for vol in app.crawler.volumes]
        await update.message.reply_text(
            "I got these volumes: "
            + ", ".join(buttons)
            + "\nEnter which one of these volumes you want to download, separated by spaces or commas."
        )
        return "handle_volume_selection"

    async def handle_volume_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")

        if app is None:
            await update.message.reply_text("Session data is missing. Please start again.")
            return

        text = update.message.text
        selected = re.findall(r"\d+", text)
        await update.message.reply_text(
            "Got the volumes: " + ", ".join(selected),
        )

        selected = [int(x) for x in selected]
        app.chapters = [
            chap for chap in app.crawler.chapters if selected.count(chap["volume"]) > 0
        ]
        return await self.range_selection_done(update, context)

    async def handle_range_chapter(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")

        if app is None:
            await update.message.reply_text("Session data is missing. Please start again.")
            return

        chapters = app.crawler.chapters
        await update.message.reply_text(
            "I got %s chapters." % len(chapters)
            + "\nEnter which start and end chapter you want to generate, separated by spaces or commas."
        )
        return "handle_chapter_selection"

    async def handle_chapter_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")

        if app is None:
            await update.message.reply_text("Session data is missing. Please start again.")
            return

        text = update.message.text
        selected = re.findall(r"\d+", text)

        if len(selected) != 2:
            await update.message.reply_text("Sorry, I did not understand. Please try again.")
            return "handle_range_chapter"
        else:
            selected = [int(x) for x in selected]
            app.chapters = app.crawler.chapters[selected[0] - 1 : selected[1]]
            await update.message.reply_text(
                "Got the start chapter: %s" % selected[0]
                + "\nThe end chapter: %s" % selected[1]
                + "\nTotal chapters chosen: %s" % len(app.chapters),
            )
        return await self.range_selection_done(update, context)

    async def handle_pack_by_volume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")

        if app is None:
            await update.message.reply_text("Session data is missing. Please start again.")
            return

        text = update.message.text
        app.pack_by_volume = text.startswith("Split")

        if app.pack_by_volume:
            await update.message.reply_text("I will split output files into volumes.")
        else:
            await update.message.reply_text("I will generate single output files whenever possible.")

        i = 0
        new_list = [["all"]]
        available_formats = ["epub", "pdf"]  # Replace with actual available formats
        while i < len(available_formats):
            new_list.append(available_formats[i : i + 2])
            i += 2

        await update.message.reply_text(
            "In which format do you want me to generate your book?",
            reply_markup=ReplyKeyboardMarkup(
                new_list,
                one_time_keyboard=True,
            ),
        )

        return "handle_output_format"

    async def handle_output_format(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")
        user = update.message.from_user

        if app is None:
            await update.message.reply_text("Session data is missing. Please start again.")
            return

        text = update.message.text.strip().lower()
        app.output_formats = {}

        if text in available_formats:
            for x in available_formats:
                app.output_formats[x] = (x == text)  # Set True for the selected format, else False
        elif text != "all":
            await update.message.reply_text("Sorry, I did not understand.")
            return

        chat_id = update.effective_message.chat_id
        job = context.job_queue.run_once(
            self.process_download_request,
            1,
            name=str(user.id),
            chat_id=chat_id,
            data=context.user_data
        )
        context.user_data["job"] = job

        await update.message.reply_text(
            "Your request has been received. I will generate the book in \"%s\" format." % text,
            reply_markup=ReplyKeyboardRemove(),
        )

        return ConversationHandler.END

    async def process_download_request(self, context):
        job = context.job
        user_data = job.data
        app = user_data.get("app")

        if app is None:
            await context.bot.send_message(job.chat_id, text="Session data is missing.")
            return

        user_data["status"] = 'Downloading "%s"' % app.crawler.novel_title
        app.start_download()
        await context.bot.send_message(job.chat_id, text="Download finished.")

        user_data["status"] = "Generating output files."
        await context.bot.send_message(job.chat_id, text=user_data.get("status"))
        output_files = app.bind_books()
        logger.debug("Output files: %s", output_files)
        await context.bot.send_message(job.chat_id, text="Output files generated.")

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
                await context.bot.send_message(job.chat_id, text="File size more than 50 MB cannot be sent via telegram bot.\n"
                                                                   + "Uploading to alternative cloud storage.")
                try:
                    description = "Generated By : Lightnovel Crawler Telegram Bot"
                    direct_link = upload(archive, description)  # Implement upload function
                    await context.bot.send_message(job.chat_id, text="Get your file here: %s" % direct_link)
                except Exception as e:
                    logger.error("Failed to upload file: %s", archive, exc_info=e)

        await self.destroy_app(None, context, job)

    async def handle_downloader(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        app = context.user_data.get("app")
        job = self.get_current_jobs(update, context)

        if app or job:
            await update.message.reply_text(
                "%s\n"
                "%d out of %d chapters have been downloaded.\n"
                "To terminate this session, send /cancel."
                % (context.user_data.get("status"), app.progress, len(app.chapters))
            )
        else:
            await update.message.reply_text("No active download session.")

        return ConversationHandler.END

    # Add additional methods as needed
