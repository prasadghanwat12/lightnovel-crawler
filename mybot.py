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

# lncrawl installation path (current working directory)
LCRAWL_PATH = os.getcwd()

# Track active processes & user queues
user_processes = {}
task_queue = Queue()
user_positions = {}

app = Client("lncrawl_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def check_system_usage():
    """Check CPU & RAM usage"""
    cpu_usage = psutil.cpu_percent(interval=1)
    ram_usage = psutil.virtual_memory().percent
    return cpu_usage >= 75 or ram_usage >= 75

@app.on_message(filters.command("download") & filters.private)
def run_lncrawl(client, message):
    global user_processes, task_queue, user_positions
    user_id = message.from_user.id

    if user_id in user_processes and user_processes[user_id].poll() is None:
        message.reply_text("\u26a0\ufe0f You already have an active download. Use /cancel to stop it.", parse_mode=None)
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        message.reply_text("\u26a0\ufe0f Please provide a novel URL.\nUsage: /download <URL>", parse_mode=None)
        return

    source_url = args[1].strip()
    output_path = os.path.join(LCRAWL_PATH, "downloads", str(user_id))
    os.makedirs(output_path, exist_ok=True)

    # Check system load
    if check_system_usage():
        queue_position = task_queue.qsize() + 1
        task_queue.put((user_id, source_url))
        user_positions[user_id] = queue_position
        message.reply_text(f"\u26a0\ufe0f System is busy (CPU/RAM > 75%).\nYour task is in queue (#{queue_position}).", parse_mode=None)
    else:
        start_download(client, user_id, source_url, output_path, message)

def start_download(client, user_id, source_url, output_path, message):
    """Start downloading"""
    global user_processes

    lncrawl_args = [
        "python", os.path.join(LCRAWL_PATH, "lncrawl"),
        "-s", source_url,
        "-o", output_path,
        "--last", "50",
        "-i",
        "--format", "epub",
        "--suppress"
    ]

    message.reply_text(f"\ud83d\ude80 Downloading your novel now...\nSource: {source_url}", parse_mode=None)
    process = subprocess.Popen(lncrawl_args)
    user_processes[user_id] = process
    process.wait()

    if process.returncode == 0:
        send_epub_file(client, user_id, output_path, message)
    else:
        message.reply_text("\u274c Download failed.", parse_mode=None)

    del user_processes[user_id]
    check_queue(client)

def send_epub_file(client, user_id, output_path, message):
    """Send EPUB file to user"""
    epub_folder = os.path.join(output_path, "epub")
    epub_files = [f for f in os.listdir(epub_folder) if f.endswith(".epub")]

    if epub_files:
        epub_file_path = os.path.join(epub_folder, epub_files[0])
        message.reply_document(epub_file_path, caption="\ud83d\udcda Here is your EPUB file!")
        shutil.rmtree(output_path)
    else:
        message.reply_text("\u26a0\ufe0f No EPUB file found.", parse_mode=None)

def check_queue(client):
    """Start next task if system is free"""
    global task_queue, user_positions
    if not task_queue.empty() and not check_system_usage():
        user_id, source_url = task_queue.get()
        output_path = os.path.join(LCRAWL_PATH, "downloads", str(user_id))
        user_positions.pop(user_id, None)
        
        # Notify user that the task is starting
        client.send_message(user_id, "\ud83d\ude80 Your queued download is now starting!")
        start_download(client, user_id, source_url, output_path, client.send_message)

@app.on_message(filters.command("cancel") & filters.private)
def cancel_download(client, message):
    global user_processes, task_queue, user_positions
    user_id = message.from_user.id

    # Cancel if user is in queue
    if user_id in user_positions:
        queue_position = user_positions.pop(user_id)
        new_queue = Queue()
        while not task_queue.empty():
            uid, url = task_queue.get()
            if uid != user_id:
                new_queue.put((uid, url))
        task_queue = new_queue
        message.reply_text(f"\u274c Your queued task (#{queue_position}) has been canceled.", parse_mode=None)
        return

    # Cancel if process is running
    if user_id in user_processes:
        process = user_processes[user_id]
        if process.poll() is None:
            try:
                if platform.system() == "Windows":
                    subprocess.run(["taskkill", "/F", "/PID", str(process.pid)], check=True)
                else:
                    os.kill(process.pid, signal.SIGTERM)

                message.reply_text("\u274c Your download has been canceled.", parse_mode=None)
                output_path = os.path.join(LCRAWL_PATH, "downloads", str(user_id))
                if os.path.exists(output_path):
                    shutil.rmtree(output_path)
            except subprocess.CalledProcessError:
                message.reply_text("\u26a0\ufe0f Unable to terminate the process. Try again.", parse_mode=None)
            except PermissionError:
                message.reply_text("\u26a0\ufe0f Permission denied! Run as admin if needed.", parse_mode=None)
            except Exception as e:
                message.reply_text(f"\u274c Error: {e}", parse_mode=None)

        del user_processes[user_id]
    else:
        message.reply_text("\u26a0\ufe0f No active download found.", parse_mode=None)

if __name__ == "__main__":
    print("\ud83e\udd16 Bot is running...")
    app.run()
