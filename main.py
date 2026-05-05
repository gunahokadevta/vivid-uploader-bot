import os
import html
import asyncio
import nest_asyncio
import subprocess
import requests
import re
import time
import shutil
import warnings
import unicodedata
import urllib.parse
from pyrogram import Client, filters, idle
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    MessageEntity
)
from pyrogram.errors import FloodWait, MessageDeleteForbidden
from pyrogram.enums import MessageEntityType, ParseMode

# Suppress warnings
warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"
os.environ["PYTHONUNBUFFERED"] = "1"

nest_asyncio.apply()

# --- CONFIG (SECURED) ---
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

app = Client(
    "VividUploader",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=300
)

users_data = {}
running_tasks = {}
active_processes = {}
last_update_time = {}

RESOLUTION_MAP = {
    "360": "640x360",
    "480": "854x480",
    "720": "1280x720",
    "1080": "1920x1080"
}

# ================= AUTH CHECK REMOVED - EVERYONE CAN USE =================

# ================= SIMPLE URL FIX FUNCTION =================

def fix_url_spaces(url):
    """Bilkul simple - spaces ko %20 mein convert karo"""
    url = url.strip()
    fixed = url.replace(' ', '%20')
    return fixed

def extract_full_url_from_line(line):
    """Extract complete URL from line"""
    line = line.strip()

    http_pos = line.find('http://')
    https_pos = line.find('https://')

    start_pos = -1
    if https_pos != -1:
        start_pos = https_pos
    elif http_pos != -1:
        start_pos = http_pos

    if start_pos == -1:
        return None

    remaining = line[start_pos:]
    fixed_url = fix_url_spaces(remaining)
    return fixed_url

async def safe_delete(chat_id, msg_ids):
    try:
        if not msg_ids:
            return
        if isinstance(msg_ids, int):
            msg_ids = [msg_ids]
        msg_ids = [x for x in msg_ids if x]
        if not msg_ids:
            return
        await app.delete_messages(chat_id, msg_ids)
    except MessageDeleteForbidden:
        pass
    except:
        pass

async def delete_prompt_and_input(chat_id, state, user_msg_id=None):
    ids = []
    if state.get("prompt_msg_id"):
        ids.append(state["prompt_msg_id"])
    if user_msg_id:
        ids.append(user_msg_id)
    await safe_delete(chat_id, ids)
    state["prompt_msg_id"] = None

def humanbytes(size):
    if not size:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0

def time_formatter(milliseconds: int) -> str:
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    tmp = ((str(hours) + "h ") if hours else "") + \
          ((str(minutes) + "m ") if minutes else "") + \
          ((str(seconds) + "s") if seconds else "")
    return tmp if tmp else "0s"

async def progress_bar(current, total, status_msg, topic, start_time, file_count_info, chat_id, part_info=""):
    if not running_tasks.get(chat_id):
        raise Exception("Task Cancelled")

    now = time.time()
    status_key = status_msg.id

    if status_key not in last_update_time:
        last_update_time[status_key] = 0

    if (now - last_update_time[status_key]) >= 12 or current == total:
        last_update_time[status_key] = now
        percentage = current * 100 / total
        speed = current / (now - start_time) if (now - start_time) > 0 else 0
        eta = round((total - current) / speed) * 1000 if speed > 0 else 0
        bar_length = 15
        filled_length = int(bar_length * current / total)
        bar = '⚡' * filled_length + '░' * (bar_length - filled_length)

        safe_topic = str(topic).replace("`", "")

        progress_str = (
            f"📡 **𝗨𝗣𝗟𝗢𝗔𝗗𝗜𝗡𝗚 𝗜𝗡 𝗣𝗥𝗢𝗚𝗥𝗘𝗦𝗦...**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📂 **𝗙𝗶𝗹𝗲:** `{safe_topic}`\n"
            f"🔢 **𝗜𝗻𝗱𝗲𝘆:** `{file_count_info}`\n"
            f"{part_info}\n"
            f"📊 **𝗕𝗮𝗿:** {bar} {percentage:.2f}%\n"
            f"🚀 **𝗦𝗽𝗲𝗲𝗱:** `{humanbytes(speed)}/s`\n"
            f"📦 **𝗦𝗶𝘇𝗲:** `{humanbytes(current)}` / `{humanbytes(total)}`\n"
            f"⏳ **𝗘𝗧𝗔:** `{time_formatter(eta)}`"
        )
        try:
            await status_msg.edit_text(progress_str)
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except:
            pass

async def update_status(status_msg, text):
    try:
        await status_msg.edit_text(text)
    except FloodWait as e:
        await asyncio.sleep(e.value)
    except:
        pass

def get_video_info(file_path):
    try:
        dur_cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{file_path}"'
        duration = float(subprocess.check_output(dur_cmd, shell=True).decode().strip())
        thumb_path = f"{file_path}.jpg"
        thumb_cmd = f'ffmpeg -y -i "{file_path}" -ss 00:00:05 -vframes 1 "{thumb_path}"'
        subprocess.run(thumb_cmd, shell=True, capture_output=True)
        return duration, thumb_path
    except:
        return 0, None

def clean_filename(name):
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name

def extract_links_and_topics(lines):
    final_links = []
    current_topic = ""
    vids = 0
    pdfs = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        url = extract_full_url_from_line(line)

        if url:
            url_start = line.find('http')
            if url_start != -1:
                topic_part = line[:url_start].strip()
            else:
                topic_part = ""

            if not topic_part or topic_part in [':', '|', '-', '→', '➡']:
                topic = current_topic if current_topic else "Video"
            else:
                topic = topic_part
                for tag in ['[Reasoning]', '[Live Class PNG]', '[Practice Set]', '[Syllabus]', '[Batch Thumbnail]']:
                    topic = topic.replace(tag, '')
                topic = topic.strip()
                topic = re.sub(r'[:|\-→➡]+$', '', topic).strip()

                if not topic:
                    topic = current_topic if current_topic else "Video"

            final_links.append({"topic": topic, "url": url})

            if ".pdf" in url.lower():
                pdfs += 1
            elif any(x in url.lower() for x in [".png", ".jpg", ".jpeg", ".gif", ".webp"]):
                pdfs += 1
            else:
                vids += 1

            current_topic = topic
        else:
            if line and line not in [':', '|', '-', '→', '➡']:
                cleaned_line = line
                for tag in ['[Reasoning]', '[Live Class PNG]', '[Practice Set]', '[Syllabus]', '[Batch Thumbnail]']:
                    cleaned_line = cleaned_line.replace(tag, '')
                cleaned_line = cleaned_line.strip()

                if cleaned_line:
                    current_topic = cleaned_line

    return final_links, vids, pdfs

# ================= EXTRACTED BY PARSER =================

FANCY_CHAR_MAP = str.maketrans({
    "ɪ": "I", "ɴ": "N", "ᴀ": "A", "ʙ": "B", "ᴄ": "C", "ᴅ": "D", "ᴇ": "E",
    "ғ": "F", "ɢ": "G", "ʜ": "H", "ᴊ": "J", "ᴋ": "K", "ʟ": "L", "ᴍ": "M",
    "ᴏ": "O", "ᴘ": "P", "ǫ": "Q", "ʀ": "R", "ꜱ": "S", "ᴛ": "T", "ᴜ": "U",
    "ᴠ": "V", "ᴡ": "W", "ʏ": "Y", "ᴢ": "Z"
})

def parse_extracted_input(raw_text):
    raw_text = (raw_text or "").strip()

    anchor_pattern = re.compile(
        r'<a\s+(?:[^>]*?\s+)?href\s*=\s*(["\'])(.*?)\1[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL
    )

    m = anchor_pattern.search(raw_text)
    if m:
        url = m.group(2).strip()
        inner_html = m.group(3)
        display = re.sub(r'<[^>]+>', '', inner_html).strip()
        display = html.unescape(display)
        display = re.sub(r'\s+', ' ', display)
        return {
            "raw": raw_text,
            "display": display if display else raw_text,
            "url": url
        }

    url_pattern = re.compile(r'https?://[^\s<>]+|www\.[^\s<>]+')
    url_match = url_pattern.search(raw_text)
    if url_match:
        url = url_match.group()
        display = re.sub(r'https?://[^\s<>]+|www\.[^\s<>]+', '', raw_text).strip()
        display = re.sub(r'<[^>]+>', '', display).strip()
        display = html.unescape(display)
        if not display:
            display = "Link"
        return {
            "raw": raw_text,
            "display": display,
            "url": url
        }

    plain = re.sub(r'<[^>]+>', '', raw_text).strip()
    plain = html.unescape(plain)
    plain = re.sub(r'\s+', ' ', plain)

    return {
        "raw": raw_text,
        "display": plain if plain else raw_text,
        "url": None
    }

def normalize_extension_base(display_name):
    text = str(display_name or "").strip()
    if not text:
        return "File"

    text = text.translate(FANCY_CHAR_MAP)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r'[^A-Za-z0-9 ]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    if not text:
        fallback = "".join(ch if ch.isalnum() else " " for ch in str(display_name))
        fallback = re.sub(r'\s+', ' ', fallback).strip()
        text = fallback if fallback else "File"

    return "".join(word.capitalize() for word in text.split()) or "File"

# ================= CAPTION BUILDER =================

def build_caption_and_entities(curr_idx, topic, ext_name, resolution, batch_name, extracted_display, extracted_link=None, part_num=None, total_parts=None, start_time_str=None, end_time_str=None):
    topic = str(topic)
    batch_name = str(batch_name)
    extracted_display = str(extracted_display)
    
    if part_num and total_parts:
        index_display = f"{curr_idx} part {part_num}"
        time_info = f"\n\n⏱️ **Time:** {start_time_str} - {end_time_str}" if start_time_str and end_time_str else ""
    else:
        index_display = curr_idx
        time_info = ""

    if extracted_link:
        extracted_section = f'📤 𝐄𝐗𝐓𝐑𝐀𝐂𝐓𝐄𝐃 𝐁𝐘 : <a href="{extracted_link}">{extracted_display}</a>'
    else:
        extracted_section = f'📤 𝐄𝐗𝐓𝐑𝐀𝐂𝐓𝐄𝐃 𝐁𝐘 : {extracted_display}'

    caption = f"""📕 Index : {index_display}

🎞️ Title : {topic}

📚 COURSE :- {batch_name}

{extracted_section}{time_info}"""

    return caption, None

# ================= COMMANDS =================

@app.on_message(filters.command("start"))
async def start_cmd(_, message):
    desc = (
        "⚡ **𝗩𝗜𝗩𝗜𝗗 𝗧𝗫𝗧 𝗨𝗣𝗟𝗢𝗔𝗗𝗘𝗥 𝘃𝟯.𝟱**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "◈ **Mode:** Turbo Multi-Tasking\n"
        "◈ **Downloader:** Aria2c Turbo\n\n"
        "📥 **Send me a .txt file.**\n"
        "✅ Spaces wale links auto fix honge (%20)"
    )
    await message.reply_text(desc)

@app.on_message(filters.command("id"))
async def get_id(_, message):
    await message.reply_text(f"🆔 **Chat ID:** `{message.chat.id}`")

@app.on_message(filters.command("cancel"))
async def cancel_cmd(_, message):
    chat_id = message.chat.id

    if chat_id in running_tasks:
        running_tasks[chat_id] = False

        if chat_id in active_processes:
            try:
                active_processes[chat_id].terminate()
                active_processes.pop(chat_id, None)
            except:
                pass

        await message.reply_text("🛑 **𝗣𝗥𝗢𝗖𝗘𝗦𝗦 𝗖𝗔𝗡𝗖𝗘𝗟𝗟𝗘𝗗.**")

        if chat_id in users_data:
            txt_path = users_data[chat_id].get("txt_path")
            if txt_path and os.path.exists(txt_path):
                try:
                    os.remove(txt_path)
                except:
                    pass
            users_data.pop(chat_id, None)

    elif chat_id in users_data:
        prompt_id = users_data[chat_id].get("prompt_msg_id")
        txt_path = users_data[chat_id].get("txt_path")

        await safe_delete(chat_id, prompt_id)

        if txt_path and os.path.exists(txt_path):
            try:
                os.remove(txt_path)
            except:
                pass

        users_data.pop(chat_id, None)
        await message.reply_text("🛑 **𝗦𝗘𝗧𝗨𝗣 𝗖𝗔𝗡𝗖𝗘𝗟𝗟𝗘𝗗.**")
    else:
        await message.reply_text("ℹ️ **No active process to cancel.**")

# ================= TXT HANDLING =================

@app.on_message(filters.document)
async def handle_txt(_, message):
    if not message.document.file_name.endswith(".txt"):
        return

    chat_id = message.chat.id

    if chat_id in running_tasks and running_tasks.get(chat_id):
        await message.reply_text("⚠️ **A process is already running! Use /cancel first.**")
        return

    path = await message.download()

    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except:
        with open(path, "r", encoding="latin-1") as f:
            lines = f.readlines()

    final_links, vids, pdfs = extract_links_and_topics(lines)

    if not final_links:
        await message.reply_text("❌ **No valid URLs found in the text file.**")
        try:
            os.remove(path)
        except:
            pass
        return

    users_data[chat_id] = {
        "links": final_links,
        "step": "index",
        "total_v": vids,
        "total_p": pdfs,
        "destination_chat": chat_id,
        "txt_path": path,
        "prompt_msg_id": None
    }

    msg = await message.reply_text(
        f"📊 **𝗗𝗔𝗧𝗔 𝗔𝗡𝗔𝗟𝗬𝗦𝗜𝗦**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ **𝗧𝗼𝘁𝗮𝗹:** `{len(final_links)}`\n"
        f"📹 **𝗩𝗶𝗱𝗲𝗼𝘀:** `{vids}`\n"
        f"📄 **𝗣𝗗𝗙𝘀/𝗜𝗺𝗮𝗴𝗲𝘀:** `{pdfs}`\n\n"
        f"🔢 **𝗘𝗻𝘁𝗲𝗿 𝘀𝘁𝗮𝗿𝘁𝗶𝗻𝗴 𝗶𝗻𝗱𝗲𝘅:**"
    )

    users_data[chat_id]["prompt_msg_id"] = msg.id
    await safe_delete(chat_id, message.id)

# ================= INPUT STEPS =================

@app.on_message((filters.text | filters.photo) & ~filters.command(["start", "cancel", "id"]))
async def steps_handler(_, message):
    chat_id = message.chat.id
    if chat_id not in users_data:
        return

    state = users_data[chat_id]
    user_text = message.text.strip() if message.text else ""

    if state["step"] == "index":
        try:
            entered_index = int(user_text)

            if entered_index < 1 or entered_index > len(state["links"]):
                await delete_prompt_and_input(chat_id, state, message.id)
                error_msg = await app.send_message(
                    chat_id,
                    f"❌ **Index must be between 1 and {len(state['links'])}.**\n\n"
                    f"🔢 **𝗘𝗻𝘁𝗲𝗿 𝘀𝘁𝗮𝗿𝘁𝗶𝗻𝗴 𝗶𝗻𝗱𝗲𝘅:**"
                )
                state["prompt_msg_id"] = error_msg.id
                return

            state["index"] = entered_index
            state["step"] = "batch"

            await delete_prompt_and_input(chat_id, state, message.id)

            msg = await app.send_message(chat_id, "📚 **𝗘𝗻𝘁𝗲𝗿 𝗖𝗼𝘂𝗿𝘀𝗲 𝗡𝗮𝗺𝗲:**")
            state["prompt_msg_id"] = msg.id

        except:
            await delete_prompt_and_input(chat_id, state, message.id)
            error_msg = await app.send_message(
                chat_id,
                "❌ **Send an integer.**\n\n🔢 **𝗘𝗻𝘁𝗲𝗿 𝘀𝘁𝗮𝗿𝘁𝗶𝗻𝗴 𝗶𝗻𝗱𝗲𝘅:**"
            )
            state["prompt_msg_id"] = error_msg.id

    elif state["step"] == "batch":
        state["batch"] = user_text
        state["step"] = "extracted"

        await delete_prompt_and_input(chat_id, state, message.id)

        msg = await app.send_message(chat_id, "📤 **𝗘𝗻𝘁𝗲𝗿 '𝗘𝘅𝘁𝗿𝗮𝗰𝘁𝗲𝗱 𝗕𝘆' 𝗡𝗮𝗺𝗲:**\n(You can use HTML link: `<a href=URL>Name</a>`)")
        state["prompt_msg_id"] = msg.id

    elif state["step"] == "extracted":
        parsed = parse_extracted_input(user_text)

        state["extracted"] = parsed["display"]
        state["extracted_link"] = parsed["url"]
        state["extracted_ext_base"] = normalize_extension_base(parsed["display"])
        state["step"] = "quality"

        await delete_prompt_and_input(chat_id, state, message.id)

        kb = ReplyKeyboardMarkup([["360p", "480p"], ["720p", "1080p"]], resize_keyboard=True)
        msg = await app.send_message(chat_id, "⚙️ **𝗦𝗲𝗹𝗲𝗰𝘁 𝗥𝗲𝘀𝗼𝗹𝘂𝘁𝗶𝗼𝗻:**", reply_markup=kb)
        state["prompt_msg_id"] = msg.id

    elif state["step"] == "quality":
        state["quality"] = user_text.replace("p", "").strip()
        state["step"] = "thumb"

        await delete_prompt_and_input(chat_id, state, message.id)

        msg = await app.send_message(
            chat_id,
            "🖼 **𝗨𝗽𝗹𝗼𝗮𝗱 𝗖𝘂𝘀𝘁𝗼𝗺 𝗧𝗵𝘂𝗺𝗯𝗻𝗮𝗶𝗹** or send 'no':",
            reply_markup=ReplyKeyboardRemove()
        )
        state["prompt_msg_id"] = msg.id

    elif state["step"] == "thumb":
        if message.photo:
            state["thumb"] = await message.download(file_name=f"thumb_{chat_id}.jpg")
        else:
            state["thumb"] = None

        await delete_prompt_and_input(chat_id, state, message.id)

        if "txt_path" in state and os.path.exists(state["txt_path"]):
            try:
                os.remove(state["txt_path"])
            except:
                pass

        running_tasks[chat_id] = True
        asyncio.create_task(process_files(chat_id, state))

# ================= VIDEO SPLITTER =================

async def split_and_upload_video(file_path, destination, caption_base, thumb, duration, status_msg, topic, file_count_info, chat_id, curr_idx, state):
    """Split video into maximum 2GB parts with 10 second overlap"""
    file_size = os.path.getsize(file_path)
    MAX_SIZE_BYTES = 1.9 * 1024 * 1024 * 1024  # 1.9GB safe limit for Telegram 2GB limit
    
    if file_size <= MAX_SIZE_BYTES:
        start_time = time.time()
        final_caption, _ = build_caption_and_entities(
            curr_idx=curr_idx, topic=topic, ext_name=None,
            resolution=RESOLUTION_MAP.get(state.get("quality", "480"), "854x480"),
            batch_name=state["batch"],
            extracted_display=state.get("extracted", "Unknown"),
            extracted_link=state.get("extracted_link")
        )
        await app.send_video(
            destination, video=file_path, caption=final_caption,
            duration=int(duration), thumb=thumb, supports_streaming=True,
            parse_mode=ParseMode.HTML, progress=progress_bar,
            progress_args=(status_msg, topic, start_time, file_count_info, chat_id, "")
        )
        return
    
    num_parts = int((file_size + MAX_SIZE_BYTES - 1) // MAX_SIZE_BYTES)
    part_duration_no_overlap = duration / num_parts
    
    await update_status(status_msg, f"✂️ **𝗦𝗣𝗟𝗜𝗧𝗧𝗜𝗡𝗚 𝗙𝗜𝗟𝗘... ({file_count_info})**\n📂 `{topic}`\n📦 Splitting into {num_parts} parts (2GB each with 10s overlap)")
    
    part_dir = f"parts_{chat_id}_{curr_idx}"
    os.makedirs(part_dir, exist_ok=True)
    
    part_base_name = f"{clean_filename(topic)}_{state.get('extracted_ext_base', 'File')}"
    
    for part_num in range(1, num_parts + 1):
        start_time_sec = (part_num - 1) * part_duration_no_overlap
        
        if part_num > 1:
            start_time_sec = max(0, start_time_sec - 10)
        
        if part_num < num_parts:
            end_time_sec = part_num * part_duration_no_overlap + 10
        else:
            end_time_sec = duration
        
        part_dur = end_time_sec - start_time_sec
        
        start_min = int(start_time_sec // 60)
        start_sec = int(start_time_sec % 60)
        end_min = int(end_time_sec // 60)
        end_sec = int(end_time_sec % 60)
        time_range = f"{start_min:02d}:{start_sec:02d} - {end_min:02d}:{end_sec:02d}"
        
        part_output = os.path.join(part_dir, f"{part_base_name}_part{part_num}.mp4")
        
        cmd = f'ffmpeg -i "{file_path}" -ss {start_time_sec} -t {part_dur} -c copy -avoid_negative_ts make_zero "{part_output}"'
        
        process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await process.communicate()
        
        if not os.path.exists(part_output) or os.path.getsize(part_output) == 0:
            cmd = f'ffmpeg -i "{file_path}" -ss {start_time_sec} -t {part_dur} -c:v libx264 -c:a aac "{part_output}"'
            await asyncio.create_subprocess_shell(cmd)
        
        part_caption, _ = build_caption_and_entities(
            curr_idx=curr_idx, topic=topic, ext_name=None,
            resolution=RESOLUTION_MAP.get(state.get("quality", "480"), "854x480"),
            batch_name=state["batch"],
            extracted_display=state.get("extracted", "Unknown"),
            extracted_link=state.get("extracted_link"),
            part_num=part_num,
            total_parts=num_parts,
            start_time_str=time_range.split(" - ")[0],
            end_time_str=time_range.split(" - ")[1]
        )
        
        if part_num < num_parts:
            part_caption += f"\n\n🔄 **Next part starts from:** {time_range.split(' - ')[1]}"
        elif part_num > 1:
            part_caption += f"\n\n🔄 **Previous part ended at:** {time_range.split(' - ')[0]}"
        
        await update_status(status_msg, f"📤 **𝗨𝗣𝗟𝗢𝗔𝗗𝗜𝗡𝗚 𝗣𝗔𝗥𝗧 {part_num}/{num_parts}... ({file_count_info})**\n📂 `{topic}`\n⏱️ `{time_range}`")
        
        part_duration, _ = get_video_info(part_output)
        
        upload_start = time.time()
        await app.send_video(
            destination, video=part_output, caption=part_caption,
            duration=int(part_duration) if part_duration else int(part_dur),
            thumb=thumb, supports_streaming=True,
            parse_mode=ParseMode.HTML, progress=progress_bar,
            progress_args=(status_msg, f"{topic} (Part {part_num}/{num_parts})", upload_start, file_count_info, chat_id, f"🔸 **𝗣𝗮𝗿𝘁:** `{part_num}/{num_parts}`\n⏱️ **𝗧𝗶𝗺𝗲:** `{time_range}`")
        )
        
        try:
            os.remove(part_output)
        except:
            pass
    
    shutil.rmtree(part_dir, ignore_errors=True)

# ================= CORE ENGINE =================

async def process_files(chat_id, state):
    all_links = state["links"]
    start_idx = state["index"]
    links_to_process = all_links[start_idx - 1:] if start_idx <= len(all_links) else []
    total_to_process = len(links_to_process)
    curr_idx = start_idx
    custom_thumb = state["thumb"]
    chosen_quality = state["quality"]
    destination = state["destination_chat"]

    extracted_display = state.get("extracted", "Unknown")
    extracted_link = state.get("extracted_link")
    extracted_ext_base = state.get("extracted_ext_base", "File")
    resolution = RESOLUTION_MAP.get(chosen_quality, "854x480")

    if total_to_process == 0:
        await app.send_message(chat_id, "❌ **No links to process. Invalid start index.**")
        running_tasks.pop(chat_id, None)
        return

    for i, link_data in enumerate(links_to_process, start=1):
        if not running_tasks.get(chat_id):
            break

        work_dir = f"vivid_{chat_id}_{curr_idx}"
        if not os.path.exists(work_dir):
            os.makedirs(work_dir)

        topic = link_data.get("topic", f"File_{curr_idx}")
        url = link_data.get("url", "")

        if not url:
            curr_idx += 1
            shutil.rmtree(work_dir, ignore_errors=True)
            continue

        file_count_info = f"{i}/{total_to_process}"
        safe_topic_display = str(topic).replace("`", "")

        status = await app.send_message(
            chat_id,
            f"🛰 **𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ({file_count_info})**\n📂 `{safe_topic_display}`"
        )

        safe_topic = clean_filename(topic)
        if len(safe_topic) > 100:
            safe_topic = safe_topic[:100]

        is_pdf = '.pdf' in url.lower()
        is_image = any(ext in url.lower() for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp'])

        pdf_filename = os.path.join(work_dir, f"{safe_topic}.pdf")
        img_filename = os.path.join(work_dir, f"{safe_topic}_{extracted_ext_base}.jpg")
        video_filename = os.path.join(work_dir, f"{safe_topic}_{extracted_ext_base}.mp4")

        try:
            if is_image:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                r = requests.get(url, timeout=60, headers=headers)
                r.raise_for_status()
                file_size = len(r.content)
                with open(img_filename, "wb") as f:
                    f.write(r.content)

                caption_html, _ = build_caption_and_entities(
                    curr_idx=curr_idx, topic=topic, ext_name=None,
                    resolution=resolution, batch_name=state["batch"],
                    extracted_display=extracted_display, extracted_link=extracted_link
                )

                if file_size > 5 * 1024 * 1024:
                    await update_status(status, f"📡 **𝗨𝗣𝗟𝗢𝗔𝗗𝗜𝗡𝗚... ({file_count_info})**\n📂 `{safe_topic_display}`")

                await app.send_photo(destination, img_filename, caption=caption_html, parse_mode=ParseMode.HTML)

            elif is_pdf:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                r = requests.get(url, timeout=60, headers=headers)
                r.raise_for_status()
                file_size = len(r.content)
                with open(pdf_filename, "wb") as f:
                    f.write(r.content)

                caption_html, _ = build_caption_and_entities(
                    curr_idx=curr_idx, topic=topic, ext_name=None,
                    resolution=resolution, batch_name=state["batch"],
                    extracted_display=extracted_display, extracted_link=extracted_link
                )

                if file_size > 5 * 1024 * 1024:
                    await update_status(status, f"📡 **𝗨𝗣𝗟𝗢𝗔𝗗𝗜𝗡𝗚... ({file_count_info})**\n📂 `{safe_topic_display}`")

                await app.send_document(destination, pdf_filename, caption=caption_html, thumb=custom_thumb, parse_mode=ParseMode.HTML)

            else:
                # SIMPLE AND CORRECT - Direct format selection
                if chosen_quality == "480":
                    cmd = f'yt-dlp -f "best[height<=480]" --merge-output-format mp4 --external-downloader aria2c --external-downloader-args "aria2c:-x 16 -s 16 -j 32 -k 1M --min-split-size=1M" --no-check-certificate "{url}" -o "{video_filename}"'
                elif chosen_quality == "360":
                    cmd = f'yt-dlp -f "best[height<=360]" --merge-output-format mp4 --external-downloader aria2c --external-downloader-args "aria2c:-x 16 -s 16 -j 32 -k 1M --min-split-size=1M" --no-check-certificate "{url}" -o "{video_filename}"'
                elif chosen_quality == "720":
                    cmd = f'yt-dlp -f "best[height<=720]" --merge-output-format mp4 --external-downloader aria2c --external-downloader-args "aria2c:-x 16 -s 16 -j 32 -k 1M --min-split-size=1M" --no-check-certificate "{url}" -o "{video_filename}"'
                elif chosen_quality == "1080":
                    cmd = f'yt-dlp -f "best[height<=1080]" --merge-output-format mp4 --external-downloader aria2c --external-downloader-args "aria2c:-x 16 -s 16 -j 32 -k 1M --min-split-size=1M" --no-check-certificate "{url}" -o "{video_filename}"'
                else:
                    cmd = f'yt-dlp -f "best" --merge-output-format mp4 --external-downloader aria2c --external-downloader-args "aria2c:-x 16 -s 16 -j 32 -k 1M --min-split-size=1M" --no-check-certificate "{url}" -o "{video_filename}"'

                process = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                active_processes[chat_id] = process
                await process.communicate()
                active_processes.pop(chat_id, None)

                if not running_tasks.get(chat_id):
                    break

                if os.path.exists(video_filename) and os.path.getsize(video_filename) > 0:
                    dur, auto_thumb = get_video_info(video_filename)
                    final_thumb = custom_thumb if custom_thumb else auto_thumb
                    
                    file_size = os.path.getsize(video_filename)
                    
                    if file_size > 2 * 1024 * 1024 * 1024:
                        await update_status(status, f"📦 **𝗣𝗥𝗘𝗣𝗔𝗥𝗜𝗡𝗚 𝗟𝗔𝗥𝗚𝗘 𝗙𝗜𝗟𝗘... ({file_count_info})**\n📂 `{safe_topic_display}`\n📊 Size: {humanbytes(file_size)}\n✂️ Splitting into 2GB parts with overlap...")
                        
                        await split_and_upload_video(
                            video_filename, destination, None, final_thumb, dur,
                            status, topic, file_count_info, chat_id, curr_idx, state
                        )
                    else:
                        caption_html, _ = build_caption_and_entities(
                            curr_idx=curr_idx, topic=topic, ext_name=None,
                            resolution=resolution, batch_name=state["batch"],
                            extracted_display=extracted_display, extracted_link=extracted_link
                        )
                        
                        await update_status(status, f"📡 **𝗨𝗣𝗟𝗢𝗔𝗗𝗜𝗡𝗚... ({file_count_info})**\n📂 `{safe_topic_display}`")
                        start_time = time.time()
                        
                        await app.send_video(
                            destination, video=video_filename, caption=caption_html,
                            duration=int(dur), thumb=final_thumb, supports_streaming=True,
                            parse_mode=ParseMode.HTML, progress=progress_bar,
                            progress_args=(status, topic, start_time, file_count_info, chat_id, "")
                        )
                else:
                    raise Exception("Download failed - file not found")

        except Exception as e:
            failed_text = f"""❌ **FAILED LINKS REPORT**

📙 **Index :** `{curr_idx}`

📝 **Topic :** `{topic}`

🔗 **URL :** `{url}`

📛 **Error :** `{str(e)[:200]}`"""
            await app.send_message(chat_id, failed_text)

        try:
            await status.delete()
        except:
            pass

        if status.id in last_update_time:
            last_update_time.pop(status.id, None)

        curr_idx += 1
        shutil.rmtree(work_dir, ignore_errors=True)

    if custom_thumb and os.path.exists(custom_thumb):
        try:
            os.remove(custom_thumb)
        except:
            pass

    if running_tasks.get(chat_id):
        await app.send_message(chat_id, "𝗧𝗵𝗮𝘁'𝘀 𝗶𝘁 ❤️")

    running_tasks.pop(chat_id, None)
    if chat_id in active_processes:
        active_processes.pop(chat_id, None)
    if chat_id in users_data:
        users_data.pop(chat_id, None)

async def main():
    # Suppress all subprocess output
    if os.path.exists("VividUploader.session"):
        try:
            os.remove("VividUploader.session")
        except:
            pass
    if os.path.exists("VividUploader.session-journal"):
        try:
            os.remove("VividUploader.session-journal")
        except:
            pass

    await app.start()
    print("Bot Started - Now anyone can use it!")

    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
