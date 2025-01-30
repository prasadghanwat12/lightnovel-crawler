import os
import psutil
import shutil
import signal
import subprocess
from queue import Queue
from pyrogram import Client, filters

# Load API credentials from environment variables
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Set current directory as LCRAWL_PATH
LCRAWL_PATH = os.getcwd()

# Store running tasks and queues
running_tasks = {}
download_queue = Queue()

# Initialize bot
app = Client("lncrawl_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def run_lncrawl(user_id, source_url):
    """Runs lncrawl for a specific user and manages the process."""
    output_path = os.path.join(LCRAWL_PATH, "output", str(user_id))
    os.makedirs(output_path, exist_ok=True)

    epub_file = os.path.join(output_path, "epub", "novel.epub")

    lncrawl_args = [
        "python3", os.path.join(LCRAWL_PATH, "lncrawl"),
        "-s", source_url,
        "-o", output_path,
        "--last", "50",
        "-i",
        "--format", "epub",
        "--suppress"
    ]

    try:
        process = subprocess.Popen(lncrawl_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        running_tasks[user_id] = process
        process.wait()

        if os.path.exists(epub_file):
            app.send_document(user_id, epub_file)
        else:
            app.send_message(user_id, "⚠️ Download failed. No EPUB file found.")

    except PermissionError:
        app.send_message(user_id, "❌ Permission Error: Cannot stop process.")
    
    finally:
        if user_id in running_tasks:
            del running_tasks[user_id]
        shutil.rmtree(output_path, ignore_errors=True)
