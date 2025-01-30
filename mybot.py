import subprocess
import os
import shutil
import signal
import platform
import psutil  # Monitor system usage
from pyrogram import Client, filters

# Telegram Bot API details
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# lncrawl installation path
LCRAWL_PATH = os.getcwd()

# Track active processes
user_processes = {}

app = Client("lncrawl_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.command("download") & filters.private)
def run_lncrawl(client, message):
    global user_processes
    user_id = message.from_user.id

    if user_id in user_processes and user_processes[user_id].poll() is None:
        message.reply_text("⚠️ You already have an active download. Use /cancel to stop it.", parse_mode=None)
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        message.reply_text("⚠️ Please provide a novel URL.\nUsage: /download <URL>", parse_mode=None)
        return

    source_url = args[1].strip()
    output_path = os.path.join(LCRAWL_PATH, "downloads", str(user_id))
    os.makedirs(output_path, exist_ok=True)

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

    message.reply_text(f"🚀 Downloading your novel now...\nSource: {source_url}", parse_mode=None)
    process = subprocess.Popen(lncrawl_args)
    user_processes[user_id] = process
    process.wait()

    if process.returncode == 0:
        send_epub_file(client, user_id, output_path, message)
    else:
        message.reply_text("❌ Download failed.", parse_mode=None)

    del user_processes[user_id]

def send_epub_file(client, user_id, output_path, message):
    """Send EPUB file to user"""
    epub_folder = os.path.join(output_path, "epub")
    epub_files = [f for f in os.listdir(epub_folder) if f.endswith(".epub")]

    if epub_files:
        epub_file_path = os.path.join(epub_folder, epub_files[0])
        message.reply_document(epub_file_path, caption="📖 Here is your EPUB file!")
        shutil.rmtree(output_path)
    else:
        message.reply_text("⚠️ No EPUB file found.", parse_mode=None)

@app.on_message(filters.command("cancel") & filters.private)
def cancel_download(client, message):
    global user_processes
    user_id = message.from_user.id

    if user_id in user_processes:
        process = user_processes[user_id]
        if process.poll() is None:
            try:
                if platform.system() == "Windows":
                    subprocess.run(["taskkill", "/F", "/PID", str(process.pid)], check=True)
                else:
                    os.kill(process.pid, signal.SIGTERM)

                message.reply_text("❌ Your download has been canceled.", parse_mode=None)
                output_path = os.path.join(LCRAWL_PATH, "downloads", str(user_id))
                if os.path.exists(output_path):
                    shutil.rmtree(output_path)
            except subprocess.CalledProcessError:
                message.reply_text("⚠️ Unable to terminate the process. Try again.", parse_mode=None)
            except PermissionError:
                message.reply_text("⚠️ Permission denied! Run as admin if needed.", parse_mode=None)
            except Exception as e:
                message.reply_text(f"❌ Error: {e}", parse_mode=None)

        del user_processes[user_id]
    else:
        message.reply_text("⚠️ No active download found.", parse_mode=None)

if __name__ == "__main__":
    print("Bot is running...")
    app.run()
