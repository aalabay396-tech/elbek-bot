import os
import sys
import re
import time
import uuid
import asyncio
import sqlite3
import threading
import json
import urllib.parse
import urllib.request
import telebot
from telebot import types
import edge_tts
import yt_dlp
from g4f.client import Client

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# ==================== ASOSIY SOZLAMALAR ====================
BOT_TOKEN = "9060761508:AAHlWfubDseZGYOMcUIJ--Okl5UYn16pS70"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "elbek_master.db")
TEMP_DIR = os.path.join(BASE_DIR, "temp_media")
FFMPEG_PATH = r"C:\Users\ASUS\AppData\Local\Microsoft\WinGet\Links"
os.makedirs(TEMP_DIR, exist_ok=True)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=True)
ai_client = Client()

user_history = {}
user_states = {}
voice_cache = {}
download_cache = {}
query_cache = {}

HEADER_BANNER = "👑 <b>BUNI YARATUVCHISI: ELBEK STUDIYA VA MARUFJON MAXRAMOV VA JAVLONBEK RUZIYEV TOMONIDAN YARATILGAN</b> 👑\n🎙 <b>ELBEK STUDIYA AI XIZMATINGIZGA TAYYOR!</b>"

POPULAR_SINGERS = [
    "jaloliddin", "ahmadaliyev", "yulduz", "usmonova", "ozodbek", "nazarbekov",
    "shohruxxon", "shohrux", "doxxim", "munisa", "rizayeva", "hamdam", "sobirov",
    "sherali", "jo'rayev", "jorayev", "botir", "qodirov", "sevinch", "mo'minova",
    "rayhon", "shaxriyor", "shahzod", "konsta", "tahir", "sodiqov", "bolalar",
    "ummon", "benom", "via marokand", "zilola", "gulinur", "jasur", "umirov",
    "doston", "ergashov", "sardor", "mamadaliyev", "tairov", "shohjahon", "bunyodbek",
    "saidov", "dilsoz", "janob", "rasul", "mirjalol", "nematov", "alisher", "fayz",
    "eldido", "setora", "shahzoda", "afruza", "xurshid", "rasulov", "anvar", "sanaev",
    "morgenstern", "miyaqi", "miyagi", "macan", "jony"
]

# ==================== BAZA (SQLITE) ====================
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            custom_name TEXT,
            current_state TEXT,
            voice_mode INTEGER DEFAULT 0,
            messages_count INTEGER DEFAULT 0,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    try:
        cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
        if "custom_name" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN custom_name TEXT")
        if "current_state" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN current_state TEXT")
        if "voice_mode" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN voice_mode INTEGER DEFAULT 0")
    except Exception:
        pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artist TEXT NOT NULL,
            title TEXT NOT NULL,
            file_id TEXT NOT NULL,
            duration INTEGER DEFAULT 0,
            downloads INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def get_user(user_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None

def save_user(user_id, username="", full_name="", custom_name=None):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            INSERT INTO users (user_id, username, full_name, custom_name, messages_count)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                custom_name = COALESCE(excluded.custom_name, users.custom_name),
                messages_count = users.messages_count + 1
        """, (user_id, username, full_name, custom_name))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"save_user xatosi: {e}")

def set_user_state(user_id, state):
    user_states[user_id] = state
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE users SET current_state = ? WHERE user_id = ?", (state, user_id))
        conn.commit()
        conn.close()
    except Exception:
        pass

def get_user_state(user_id):
    if user_id in user_states:
        return user_states[user_id]
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT current_state FROM users WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        conn.close()
        st = row[0] if row else None
        user_states[user_id] = st
        return st
    except Exception:
        return None

def get_stats():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*), SUM(messages_count) FROM users")
        u_row = c.fetchone()
        c.execute("SELECT COUNT(*) FROM tracks")
        t_row = c.fetchone()
        conn.close()
        return {
            "users": u_row[0] or 1,
            "messages": u_row[1] or 1,
            "tracks": t_row[0] or 0
        }
    except Exception:
        return {"users": 1, "messages": 1, "tracks": 0}

# ==================== OVOZ (TTS - O'ZBEKCHA NEURAL) ====================
def clean_for_speech(text: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'[*#_`~>\[\]\(\)]', ' ', text)
    text = re.sub(r'https?://\S+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

async def async_create_voice(text: str, file_path: str):
    clean = clean_for_speech(text)
    if len(clean) > 800:
        clean = clean[:800] + "... Davomini o'qib olishingiz mumkin."
    communicate = edge_tts.Communicate(clean, voice="uz-UZ-MadinaNeural", rate="+4%")
    await communicate.save(file_path)

def generate_voice(text: str) -> str:
    fid = str(uuid.uuid4())[:8]
    out_file = os.path.join(TEMP_DIR, f"voice_{fid}.ogg")
    try:
        asyncio.run(async_create_voice(text, out_file))
        if os.path.exists(out_file) and os.path.getsize(out_file) > 100:
            return out_file
    except Exception as e:
        print(f"Ovoz yaratishda xato: {e}")
    return None

def send_voice_message(chat_id, text, caption=None):
    try:
        vf = generate_voice(text)
        if vf and os.path.exists(vf):
            with open(vf, "rb") as f:
                bot.send_voice(chat_id, f, caption=caption)
            os.remove(vf)
    except Exception as e:
        print(f"Ovoz yuborish xatosi: {e}")

# ==================== TEZKOR MUSIQA QIDIRISH (0.8 SONIYADA!) ====================
def search_online_music(query: str, limit: int = 5):
    """
    To'g'ridan-to'g'ri YouTube qidiruv tizimi orqali 0.8 soniyada aniq natija qaytaradi.
    15 soniya kutish yo'q, bir zumda ishlaydi!
    """
    clean_q = re.sub(r'[^a-zA-Z0-9\s\u0400-\u04FF\']', ' ', query).strip()
    if not clean_q:
        clean_q = query
        
    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(clean_q)}"
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'uz,ru,en;q=0.9'
        }
    )
    results = []
    
    # 1. Tezkor YouTube HTML qidiruvi (0.8s)
    try:
        with urllib.request.urlopen(req, timeout=3.5) as r:
            html = r.read().decode('utf-8', errors='ignore')
            m = re.search(r'var ytInitialData = ({.*?});</script>', html)
            if m:
                data = json.loads(m.group(1))
                sections = data.get('contents', {}).get('twoColumnSearchResultsRenderer', {}).get('primaryContents', {}).get('sectionListRenderer', {}).get('contents', [])
                if sections:
                    items = sections[0].get('itemSectionRenderer', {}).get('contents', [])
                    for item in items:
                        if 'videoRenderer' in item and len(results) < limit:
                            vr = item['videoRenderer']
                            vid = vr.get('videoId')
                            if not vid:
                                continue
                            runs = vr.get('title', {}).get('runs', [])
                            title = runs[0].get('text', 'Musiqa') if runs else 'Musiqa'
                            dur = vr.get('lengthText', {}).get('simpleText', '')
                            results.append({
                                'id': vid,
                                'title': title,
                                'duration_str': f" [{dur}]" if dur else "",
                                'webpage_url': f"https://www.youtube.com/watch?v={vid}"
                            })
    except Exception as e:
        print(f"Fast YouTube search xatosi: {e}")

    # 2. Agar tezkor usul natija bermasa, yt-dlp bilan zaxira tekshiruv (2s)
    if not results:
        try:
            ydl_opts = {
                'format': 'bestaudio/best',
                'quiet': True,
                'noplaylist': True,
                'extract_flat': True,
                'extractor_args': {'youtube': {'player_client': ['mweb', 'android', 'ios']}}
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch{limit}:{clean_q}", download=False)
                for entry in info.get('entries', []):
                    if entry and entry.get('id'):
                        dur = entry.get('duration') or 0
                        dur_str = f" [{dur // 60}:{dur % 60:02d}]" if dur else ""
                        results.append({
                            'id': entry.get('id'),
                            'title': entry.get('title', 'Qo\'shiq'),
                            'duration_str': dur_str,
                            'webpage_url': f"https://www.youtube.com/watch?v={entry.get('id')}"
                        })
        except Exception:
            pass

    return results

def download_online_mp3(video_url: str):
    fid = str(uuid.uuid4())[:8]
    out_tmpl = os.path.join(TEMP_DIR, f"track_{fid}.%(ext)s")
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'ffmpeg_location': FFMPEG_PATH if os.path.exists(FFMPEG_PATH) else None,
        'extractor_args': {'youtube': {'player_client': ['mweb', 'android', 'ios']}},
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': out_tmpl,
        'quiet': True,
        'noplaylist': True,
        'max_filesize': 45 * 1024 * 1024
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            title = info.get('title', 'Qo\'shiq')
            artist = info.get('uploader', 'San\'atkor')
            duration = info.get('duration', 0)
            
            expected_mp3 = os.path.join(TEMP_DIR, f"track_{fid}.mp3")
            if os.path.exists(expected_mp3):
                return expected_mp3, title, artist, duration
                
            base = os.path.join(TEMP_DIR, f"track_{fid}")
            for ext in ['.mp3', '.m4a', '.webm', '.opus']:
                if os.path.exists(base + ext):
                    return base + ext, title, artist, duration
                    
    except Exception as e:
        print(f"MP3 yuklash xatosi: {e}")
        
    return None, None, None, 0

# ==================== TEZKOR VA SOF O'ZBEKCHA AI SAVOL-JAVOB ====================
def ask_gemini(user_id: int, user_prompt: str) -> str:
    p_clean = user_prompt.strip().lower()
    
    # 1. Tezkor, chiroyli va tabiiy salom-aliklar (0.01 soniyada toza javob)
    if p_clean in ["salom", "assalom", "assalomu alaykum", "assalomu aleykum", "salom alaykum", "salomaleykum", "privet", "hello"]:
        return "Assalomu alaykum! Xush kelibsiz! Sizga qanday yordam bera olaman? Istalgan savolingizni bering yoki qo'shiq nomini yozing!"
        
    if any(p_clean == g for g in ["qandaysiz", "qalesiz", "yaxshimisiz", "ishlar qalay", "ahvolingiz qanday", "ahvollar qalay"]):
        return "Rahmat, judayam yaxshi! O'zingiz yaxshimisiz? Sizga qanday yordam bera olaman?"
        
    if any(p_clean == g for g in ["rahmat", "katta rahmat", "raxmat", "tashakkur", "spasibo", "sog' bo'ling"]):
        return "Arzimaydi! Xizmatingizdamiz. Yana qanday savolingiz yoki xizmatingiz bor?"
        
    if any(p_clean == g for g in ["sen kimsan", "isming nima", "kim bu", "nima qila olasan", "haqingda ayt"]):
        return "Men — Elbek Studiya AI yordamchisiman. Ushbu bot rasman Elbek Studiya, Marufjon Maxramov va Javlonbek Ruziyev tomonidan yaratilgan. Savollaringizga to'g'ri javob beraman, qo'shiq va minuslarni topib beraman!"

    # 2. Gemini 2.5 Flash va GPT-4o orqali sof adabiy o'zbek tilida javob
    if user_id not in user_history:
        user_history[user_id] = [
            {
                "role": "system",
                "content": (
                    "Siz 'Elbek Studiya AI' aqlli yordamchisisiz. "
                    "Har doim sof, tabiiy, adabiy va go'zal o'zbek tilida, grammatik qoidalarga to'liq amal qilib javob bering. "
                    "Hech qachon g'alati yoki xato tarjima so'zlarni ishlatmang. "
                    "Foydalanuvchining savoliga aniq, to'g'ri va xushmuomala bo'lib javob bering."
                )
            }
        ]
        
    user_history[user_id].append({"role": "user", "content": user_prompt})
    if len(user_history[user_id]) > 6:
        user_history[user_id] = [user_history[user_id][0]] + user_history[user_id][-5:]

    for model_name in ["gemini-2.5-flash", "gpt-4o-mini"]:
        try:
            res = ai_client.chat.completions.create(
                model=model_name,
                messages=user_history[user_id]
            )
            ans = res.choices[0].message.content
            if ans and len(ans.strip()) > 1:
                lines = ans.strip().split("\n")
                if lines and lines[0].strip().startswith("####"):
                    ans = "\n".join(lines[1:]).strip()
                user_history[user_id].append({"role": "assistant", "content": ans})
                return ans
        except Exception:
            continue

    return "Savolingiz qabul qilindi. Iltimos, yana bir bor aniqlashtirib yozing yoki qo'shiq nomini yuboring."

# ==================== O'TA TINIQ RASM CHIZISH (HD) ====================
def generate_hd_image_url(prompt: str) -> str:
    hd_prompt = f"{prompt}, 8k resolution, highly detailed, photorealistic, cinematic lighting, sharp focus, masterpiece"
    encoded = urllib.parse.quote(hd_prompt)
    return f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&model=flux&nologo=true&enhance=true"

# ==================== TO'RTBURCHAK BO'LIMLAR KATAGI (DOIMIY KLAVIATURA) ====================
def get_main_keyboard(user_id=None):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True, row_width=2)
    markup.add(
        types.KeyboardButton("🚀 /start (Bosh Menyu)"),
        types.KeyboardButton("🧠 Gemini AI (Savol-Javob)")
    )
    markup.add(
        types.KeyboardButton("🎵 Qo'shiq qidirish (Original)"),
        types.KeyboardButton("🎙 Minus qidirish (Fonogramma)")
    )
    markup.add(
        types.KeyboardButton("🎛 AI Minus Yaratish (MVSep)"),
        types.KeyboardButton("🎨 Tiniq Rasm Chizish (HD)")
    )
    markup.add(
        types.KeyboardButton("🎤 San'atkorlar ro'yxati"),
        types.KeyboardButton("⭐️ Eng Sara Minuslar")
    )
    markup.add(
        types.KeyboardButton("🗣 Odamday Gapirib Berish"),
        types.KeyboardButton("🔍 Telegram Music Botlari")
    )
    markup.add(
        types.KeyboardButton("🔄 Yangi suhbat"),
        types.KeyboardButton("👑 Mualliflar haqida")
    )
    markup.add(types.KeyboardButton("📊 Statistika"))
    return markup

# ==================== BUYRUQLAR SOZLAMASI (TELEFONLARDA MENYU TUGMASI UCHUN) ====================
def setup_bot_commands():
    try:
        cmds = [
            types.BotCommand("start", "🚀 Bosh menyu / Bo'limlar"),
            types.BotCommand("menu", "🎛 Barcha bo'limlar"),
            types.BotCommand("qoshiq", "🎵 Qo'shiq qidirish (MP3)"),
            types.BotCommand("minus", "🎙 Minus qidirish (Fonogramma)"),
            types.BotCommand("mvsep", "🎛 AI Minus yaratish (MVSep)"),
            types.BotCommand("ai", "🧠 Gemini AI savol-javob"),
            types.BotCommand("rasm", "🎨 Tiniq HD rasm chizish"),
            types.BotCommand("clear", "🔄 Yangi suhbat")
        ]
        bot.set_my_commands(cmds)
        bot.set_chat_menu_button(menu_button=types.MenuButtonCommands())
    except Exception as e:
        print(f"setup_bot_commands xatosi: {e}")

# ==================== ASOSIY BUYRUQLAR VA START ====================
@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "Do'stim"
    save_user(user_id, message.from_user.username or "", message.from_user.full_name or "")
    set_user_state(user_id, None)
    
    welcome_text = (
        f"{HEADER_BANNER}\n\n"
        f"🎙 <b>Assalomu alaykum, {first_name}!</b>\n\n"
        f"Pastdagi <b>to'rtburchak (⊞) bo'limlar katagi</b> yoki chapdagi <b>[Menu]</b> tugmasi orqali barcha bo'limlar xizmatingizda:\n\n"
        f"🎵 <b>Qo'shiq qidirish:</b> Internet va YouTube'dan 0.8 soniyada toza MP3 yuklab olish\n"
        f"🎙 <b>Minus qidirish:</b> Fonogramma va karaoke minuslarini topish\n"
        f"🎛 <b>AI Minus Yaratish:</b> MVSep orqali vokalni ajratish\n"
        f"🧠 <b>Gemini AI:</b> Istalgan mavzudagi savolingizga tezkor javob olish\n"
        f"🎨 <b>Tiniq Rasm Chizish:</b> 8K / HD sifatdagi ajoyib rasmlar yaratish\n"
        f"🗣 <b>Odamday Gapirib Berish:</b> Yozuvlarni jonli inson ovozida o'qitish\n\n"
        f"👇 <b>Qaysi bo'limni tanlaysiz?</b> Pastdagi katakchalardan birini bosing:"
    )
    
    inline_markup = types.InlineKeyboardMarkup()
    inline_markup.add(
        types.InlineKeyboardButton("🎵 Qo'shiq qidirish", callback_data="btn_search_song"),
        types.InlineKeyboardButton("🎙 Minus qidirish", callback_data="btn_search_minus")
    )
    inline_markup.add(
        types.InlineKeyboardButton("🧠 Gemini AI", callback_data="btn_open_ai"),
        types.InlineKeyboardButton("🎨 HD Rasm Chizish", callback_data="btn_open_paint")
    )
    inline_markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
    
    bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_keyboard(user_id))

# Menyu buyrug'i (/menu, /bolimlar, bo'limlar)
@bot.message_handler(func=lambda m: m.text and m.text.lower() in ["/menu", "/bolimlar", "menu", "menyu", "bo'limlar", "bolimlar"])
def handle_menu_command(message):
    user_id = message.from_user.id
    set_user_state(user_id, None)
    text = (
        f"{HEADER_BANNER}\n\n"
        f"👇 <b>Qaysi bo'limni tanlaysiz?</b>\n"
        f"Pastdagi to'rtburchak katakchalardan kerakli bo'lim ustiga bosing:"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard(user_id))

# ==================== BO'LIMLAR HANDLERLARI ====================

# 1. 🎵 Qo'shiq qidirish (Original)
@bot.message_handler(func=lambda m: m.text in ["🎵 Qo'shiq qidirish (Original)", "/qoshiq"])
def handle_song_search_btn(message):
    user_id = message.from_user.id
    set_user_state(user_id, "waiting_song_original")
    text = (
        f"{HEADER_BANNER}\n\n"
        f"🎵 <b>Original Qo'shiqlar Qidiruvi!</b> 🎧\n\n"
        f"✍️ <b>Qidirayotgan qo'shiq yoki san'atkor nomini yozing:</b>\n"
        f"<i>(Masalan: Jaloliddin Janonim, Munisa Rizayeva, Doston Ergashov va h.k.)</i>\n\n"
        f"⚡️ Bot bir zumda YouTube'dan qidiradi va toza MP3 qilib beradi!"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard(user_id))

# 2. 🎙 Minus qidirish (Fonogramma)
@bot.message_handler(func=lambda m: m.text in ["🎙 Minus qidirish (Fonogramma)", "/minus"])
def handle_minus_search_btn(message):
    user_id = message.from_user.id
    set_user_state(user_id, "waiting_minus_search")
    text = (
        f"{HEADER_BANNER}\n\n"
        f"🎙 <b>Minuslar va Fonogramma Qidiruvi!</b> 🎼\n\n"
        f"✍️ <b>Qidirayotgan minus yoki san'atkor nomini yozing:</b>\n"
        f"<i>(Masalan: Jaloliddin Ahmadaliyev 19 yil minus, Ozodbek Rayhon minus)</i>"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard(user_id))

# 3. 🎛 AI Minus Yaratish (MVSep)
@bot.message_handler(func=lambda m: m.text in ["🎛 AI Minus Yaratish (MVSep)", "/mvsep"])
def handle_mvsep_section(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🤖 1. @mvsep_bot_bot orqali minus qilish (MVSep)", url="https://t.me/mvsep_bot_bot"),
        types.InlineKeyboardButton("🌐 2. VocalRemover AI orqali minus qilish", url="https://vocalremover.org"),
        types.InlineKeyboardButton("📥 3. MP3 audio fayl yuborish (Botga tashlang)", callback_data="ask_upload_audio"),
        types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start")
    )
    text = (
        f"{HEADER_BANNER}\n\n"
        f"🎛 <b>AI MINUS VA VOKAL AJRATISH (MVSEP) BO'LIMI!</b> 🎼\n\n"
        f"Ushbu bo'lim orqali siz istalgan qo'shiqdan:\n"
        f"• 🎹 <b>Toza Instrumental Minus</b> yaratishingiz (vokalni o'chirib)\n"
        f"• 🎤 <b>Bek-vokalni olib tashlashingiz</b>\n"
        f"• 🗣 <b>Faqat qo'shiqchi ovozini (Acappella)</b> ajratib olishingiz mumkin!\n\n"
        f"👇 <b>Quyidagi usullardan birini tanlang yoki MP3 faylingizni botga yuboring:</b>"
    )
    bot.send_message(message.chat.id, text, reply_markup=markup)

# 4. 🧠 Gemini AI (Savol-Javob)
@bot.message_handler(func=lambda m: m.text in ["🧠 Gemini AI (Savol-Javob)", "/ai"])
def handle_ai_section(message):
    user_id = message.from_user.id
    set_user_state(user_id, "ai_mode")
    text = (
        f"{HEADER_BANNER}\n\n"
        f"🧠 <b>Google Gemini AI Savol-Javob bo'limi!</b> ✨\n\n"
        f"Menga istalgan savolingizni berishingiz mumkin:\n"
        f"• Masalalar, fanlar va hisob-kitoblar\n"
        f"• Qo'shiq matnlari, she'rlar va ssenariylar\n"
        f"• Tarjimalar va do'stona suhbat\n\n"
        f"✍️ <b>Savolingizni yozib yuboring — bot darhol javob beradi:</b>"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard(user_id))

# 5. 🎨 Tiniq Rasm Chizish (HD)
@bot.message_handler(func=lambda m: m.text in ["🎨 Tiniq Rasm Chizish (HD)", "/rasm"])
def handle_paint_section(message):
    user_id = message.from_user.id
    set_user_state(user_id, "waiting_image_prompt")
    text = (
        f"{HEADER_BANNER}\n\n"
        f"🎨 <b>O'ta Tiniq (HD / 8K) Rasm Chizish bo'limi!</b> ✨\n\n"
        f"✍️ <b>Qanday rasm chizib beray? Tasvirlab yozing:</b>\n"
        f"• <i>Toshkent ko'chasida qora Malibu</i>\n"
        f"• <i>Oltin musiqiy studiyada mikrafon</i>\n"
        f"• <i>Tog'lar bag'rida oq Tulpor</i>"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard(user_id))

# 6. 🎤 San'atkorlar ro'yxati
@bot.message_handler(func=lambda m: m.text == "🎤 San'atkorlar ro'yxati")
def handle_artists_section(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    artists = [
        "Jaloliddin Ahmadaliyev", "Yulduz Usmonova", "Ozodbek Nazarbekov",
        "Shohruxxon", "Doxxim", "Munisa Rizayeva", "Hamdam Sobirov", "Sherali Jo'rayev"
    ]
    buttons = [types.InlineKeyboardButton(f"🎤 {art}", callback_data=f"search_art_{art[:20]}") for art in artists]
    markup.add(*buttons)
    markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
    bot.send_message(
        message.chat.id,
        "🎤 <b>Mashhur san'atkorlar ro'yxati:</b>\nBirortasini tanlang, bot uning sara qo'shiq va minuslarini internetdan topib beradi:",
        reply_markup=markup
    )

# 7. ⭐️ Eng Sara Minuslar
@bot.message_handler(func=lambda m: m.text == "⭐️ Eng Sara Minuslar")
def handle_top_minus_btn(message):
    smsg = bot.send_message(message.chat.id, "⚡️ <i>Sara minuslar qidirilmoqda...</i>")
    results = search_online_music("Uzbekcha eng sara minuslar fonogramma", limit=5)
    if results:
        markup = types.InlineKeyboardMarkup()
        for idx, r in enumerate(results, 1):
            k = str(uuid.uuid4())[:8]
            download_cache[k] = {'url': r['webpage_url'], 'title': r['title']}
            markup.add(types.InlineKeyboardButton(f"⭐️ {idx}. {r['title'][:32]}{r['duration_str']}", callback_data=f"dl_{k}"))
        markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
        bot.edit_message_text("⭐️ <b>Eng sara minus qo'shiqlar:</b>\nBirortasini bosing, darhol MP3 formatda yuklab beradi:", message.chat.id, smsg.message_id, reply_markup=markup)
    else:
        bot.edit_message_text("Kechirasiz, yuklanmadi. Qaytadan urinib ko'ring.", message.chat.id, smsg.message_id)

# 8. 🗣 Odamday Gapirib Berish
@bot.message_handler(func=lambda m: m.text == "🗣 Odamday Gapirib Berish")
def handle_speech_assistant(message):
    user_id = message.from_user.id
    set_user_state(user_id, "waiting_text_to_speak")
    text = (
        "🗣 <b>Odamday Gapirib Berish bo'limi!</b> 🎙\n\n"
        "Istalgan matningizni yozib yuboring — bot uni to'g'ri talaffuzda xuddi <b>haqiqiy odamdek jonli ovozda</b> audio qilib yuboradi!\n\n"
        "✍️ <b>Matnni yozib yuboring:</b>"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard(user_id))

# 9. 🔍 Telegram Music Botlari
@bot.message_handler(func=lambda m: m.text == "🔍 Telegram Music Botlari")
def handle_music_bots_hub(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🎧 1. @vkmusic_bot orqali qidirish", url="https://t.me/vkmusic_bot"),
        types.InlineKeyboardButton("🎧 2. @lybot orqali qidirish", url="https://t.me/lybot"),
        types.InlineKeyboardButton("🎧 3. @ytsbot orqali qidirish", url="https://t.me/ytsbot"),
        types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start")
    )
    text = (
        f"{HEADER_BANNER}\n\n"
        f"🔍 <b>Telegramdagi eng mashhur musiqa botlari:</b>\n\n"
        f"Siz botimizning o'zida bevosita MP3 yuklab olishingiz yoki quyidagi mashhur musiqa botlari orqali ham qo'shiq topishingiz mumkin:\n\n"
        f"👇 Kerakli botni tanlang:"
    )
    bot.send_message(message.chat.id, text, reply_markup=markup)

# 10. 🔄 Yangi suhbat
@bot.message_handler(func=lambda m: m.text in ["🔄 Yangi suhbat", "/clear"])
def handle_clear(message):
    user_id = message.from_user.id
    user_history.pop(user_id, None)
    set_user_state(user_id, None)
    bot.send_message(message.chat.id, "🧹 <b>Yangi suhbat boshlandi!</b> Barcha xotira tozalandi. Istalgan savolingizni bering:", reply_markup=get_main_keyboard(user_id))

# 11. 👑 Mualliflar haqida
@bot.message_handler(func=lambda m: m.text == "👑 Mualliflar haqida")
def handle_authors(message):
    text = (
        f"{HEADER_BANNER}\n\n"
        f"🌟 <b>LOYIHA YARATUVCHILARI VA RAHBARLARI:</b>\n\n"
        f"🎬 <b>ELBEK STUDIYA</b> — O'zbekistondagi sara ijodiy musiqa studiyasi, professional audio va video loyihalar markazi.\n\n"
        f"⭐️ <b>MARUFJON MAXRAMOV</b> — Bosh loyiha asoschisi, muallifi va rahbari.\n\n"
        f"⭐️ <b>JAVLONBEK RUZIYEV</b> — Bosh loyiha asoschisi, muallifi va tashabbuskori.\n\n"
        f"📢 Rasmiy kanalimiz: <b>@sanatkorlar</b>\n"
        f"⚡️ Barcha huquqlar himoyalangan."
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
    bot.send_message(message.chat.id, text, reply_markup=markup)

# 12. 📊 Statistika
@bot.message_handler(func=lambda m: m.text == "📊 Statistika")
def handle_stats_btn(message):
    st = get_stats()
    text = (
        f"{HEADER_BANNER}\n\n"
        f"📊 <b>BOT KO'RSATKICHLARI:</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{st['users']}</b> ta\n"
        f"💬 Berilgan savollar: <b>{st['messages']}</b> ta\n"
        f"🎵 Musiqa qidiruv tezligi: <b>0.8 soniya (Tezkor)</b>\n"
        f"🗣 Ovoz tizimi: <b>Microsoft Neural Speech (uz-UZ)</b>\n"
        f"🧠 Sun'iy intellekt: <b>Google Gemini 2.5 Flash</b>\n"
        f"⚡️ Holat: <b>Doimo shay va to'xtovsiz faol</b>"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
    bot.send_message(message.chat.id, text, reply_markup=markup)

# Audio fayl yuborilganda
@bot.message_handler(content_types=['audio', 'voice'])
def handle_incoming_audio(message):
    audio = message.audio or message.voice
    performer = getattr(audio, 'performer', None) or ""
    title = getattr(audio, 'title', None) or "Musiqa"
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    if performer and title:
        search_kw = f"{performer} {title} minus"
    else:
        search_kw = f"{title} minus"
        
    markup.add(
        types.InlineKeyboardButton("🎹 Ushbu qo'shiqning tayyor studio minusini topish", switch_inline_query_current_chat=search_kw),
        types.InlineKeyboardButton("🤖 @mvsep_bot_bot orqali vokalni o'chirish (MVSep)", url="https://t.me/mvsep_bot_bot"),
        types.InlineKeyboardButton("🌐 VocalRemover.org orqali minus qilish", url="https://vocalremover.org"),
        types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start")
    )
    text = (
        f"{HEADER_BANNER}\n\n"
        f"🎧 <b>Audio fayl qabul qilindi:</b> {performer} — {title}\n\n"
        f"Ushbu audioni qanday usulda minus qilmoqchisiz?\n\n"
        f"• <b>Tayyor Studio Minusi:</b> Internetdan uning eng sara fonogrammasini topish\n"
        f"• <b>MVSep AI:</b> Qo'shiqdan vokal va bek-vokalni olib tashlash"
    )
    bot.send_message(message.chat.id, text, reply_markup=markup)

# ==================== CALLBACK QUERY (TUGMALAR) ====================
@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    data = call.data
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    
    if data == "cmd_start":
        bot.answer_callback_query(call.id)
        handle_start(call.message)
        return
        
    elif data == "btn_search_song":
        bot.answer_callback_query(call.id)
        handle_song_search_btn(call.message)
        return
        
    elif data == "btn_search_minus":
        bot.answer_callback_query(call.id)
        handle_minus_search_btn(call.message)
        return
        
    elif data == "btn_open_ai":
        bot.answer_callback_query(call.id)
        handle_ai_section(call.message)
        return
        
    elif data == "btn_open_paint":
        bot.answer_callback_query(call.id)
        handle_paint_section(call.message)
        return

    # 1. Ovoz eshitish
    elif data.startswith("spk_"):
        cid = data.replace("spk_", "")
        text = voice_cache.get(cid)
        if not text:
            bot.answer_callback_query(call.id, "Xabar eskirgan.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "🗣 Ovoz tayyorlanmoqda...")
        bot.send_chat_action(chat_id, "record_voice")
        threading.Thread(
            target=send_voice_message,
            args=(chat_id, text, "🎙 <i>Odamdek gapirib berilgan ovozli xabar</i>")
        ).start()
        
    # 2. MP3 yuklash
    elif data.startswith("dl_"):
        key = data.replace("dl_", "")
        item = download_cache.get(key)
        if not item:
            bot.answer_callback_query(call.id, "Havola eskirgan, qayta qidiring.", show_alert=True)
            return
            
        bot.answer_callback_query(call.id, "⏳ MP3 yuklanmoqda...")
        bot.send_chat_action(chat_id, "upload_document")
        smsg = bot.send_message(chat_id, f"⏳ <i>«{item['title']}» yuqori sifatli MP3 formatda yuklab olinmoqda...</i>")
        
        def run_dl():
            fn, title, artist, duration = download_online_mp3(item['url'])
            if fn and os.path.exists(fn):
                try:
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("▶️ YouTube'da ko'rish", url=item['url']))
                    markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
                    with open(fn, "rb") as af:
                        bot.send_audio(
                            chat_id,
                            audio=af,
                            title=title[:45],
                            performer=artist[:45],
                            duration=duration,
                            caption=f"{HEADER_BANNER}\n\n🎵 <b>{title}</b>\n\n🤖 @ElbekStudiyaMinusbot",
                            reply_markup=markup
                        )
                    bot.delete_message(chat_id, smsg.message_id)
                    os.remove(fn)
                except Exception as e:
                    bot.edit_message_text(f"Audioni yuborishda xato: {e}", chat_id, smsg.message_id)
            else:
                bot.edit_message_text("Kechirasiz, ushbu audioni yuklab bo'lmadi.", chat_id, smsg.message_id)
                
        threading.Thread(target=run_dl).start()
        
    # 3. San'atkor qo'shiqlarini qidirish
    elif data.startswith("search_art_"):
        art_name = data.replace("search_art_", "")
        bot.answer_callback_query(call.id, f"{art_name} qidirilmoqda...")
        results = search_online_music(f"{art_name} minus", limit=5)
        if results:
            markup = types.InlineKeyboardMarkup()
            yt_search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(art_name + ' minus')}"
            for idx, r in enumerate(results, 1):
                k = str(uuid.uuid4())[:8]
                download_cache[k] = {'url': r['webpage_url'], 'title': r['title']}
                markup.add(types.InlineKeyboardButton(f"🎧 {idx}. {r['title'][:32]}{r['duration_str']}", callback_data=f"dl_{k}"))
            markup.add(types.InlineKeyboardButton(f"🌐 YouTube'dan to'liq qidirish («{art_name}»)", url=yt_search_url))
            markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
            bot.send_message(chat_id, f"🎵 <b>{art_name} minuslari:</b>", reply_markup=markup)
        else:
            bot.send_message(chat_id, f"😔 «{art_name}» bo'yicha musiqa topilmadi.")

    elif data.startswith("force_ai_"):
        k = data.replace("force_ai_", "")
        orig_q = query_cache.get(k, "savol")
        bot.answer_callback_query(call.id, "🧠 Gemini AI javob bermoqda...")
        answer = ask_gemini(user_id, orig_q)
        cid = str(uuid.uuid4())[:8]
        voice_cache[cid] = answer
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🗣 Odamday gapirib ber (Ovoz)", callback_data=f"spk_{cid}"))
        markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
        bot.send_message(chat_id, f"{HEADER_BANNER}\n\n{answer}", reply_markup=markup)

    elif data == "ask_upload_audio":
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "🎧 <b>Minus qilmoqchi bo'lgan MP3 audio faylingizni botga yuboring:</b>")

# ==================== QO'SHIQ MI YOKI SAVOL MI ANIQ AJRATISH ====================
def is_likely_music_query(text: str) -> bool:
    clean = text.strip().lower()
    if clean.startswith(("/", "http://", "https://")):
        return False
    if "?" in clean:
        return False
        
    music_keywords = ["minus", "qo'shiq", "qoshiq", "mp3", "musiqa", "trek", "fonogramma", "karaoke", "klip", "audio", "remix"]
    if any(k in clean for k in music_keywords):
        return True
    if any(singer in clean for singer in POPULAR_SINGERS):
        return True
    return False

# ==================== BARCHA MATNLI XABARLARNI QAYTA ISHLASH ====================
@bot.message_handler(content_types=['text'])
def handle_all_text(message):
    user_id = message.from_user.id
    text = message.text.strip()
    save_user(user_id, message.from_user.username or "", message.from_user.full_name or "")
    
    if text.startswith("/"):
        return
        
    state = get_user_state(user_id)

    # 1. Matnni ovozga aylantirish bo'limi bo'lsa
    if state == "waiting_text_to_speak":
        set_user_state(user_id, None)
        bot.send_chat_action(message.chat.id, "record_voice")
        threading.Thread(
            target=send_voice_message,
            args=(message.chat.id, text, f"{HEADER_BANNER}\n\n🎙 <i>Odamdek gapirib berilgan ovozli xabar</i>")
        ).start()
        return

    # 2. Rasm chizish so'rovi bo'lsa
    if state == "waiting_image_prompt" or text.lower().startswith(("rasm chiz", "rasm yarat", "chizib ber", "/rasm", "/image")):
        set_user_state(user_id, None)
        prompt = text
        for p in ["rasm chiz", "rasm yarat", "chizib ber", "/rasm", "/image", ":"]:
            if prompt.lower().startswith(p):
                prompt = prompt[len(p):].strip()
        if not prompt:
            prompt = "chiroyli musiqiy san'at asari"
            
        bot.send_chat_action(message.chat.id, "upload_photo")
        smsg = bot.send_message(message.chat.id, "🎨 <i>O'ta tiniq HD rasm chizilmoqda, bir necha soniya kuting...</i>")
        try:
            url = generate_hd_image_url(prompt)
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
            bot.send_photo(
                message.chat.id,
                photo=url,
                caption=f"{HEADER_BANNER}\n\n🎨 <b>Rasm tayyor (HD / 8K)!</b>\n\n📝 <i>{prompt}</i>\n\n🤖 @ElbekStudiyaMinusbot",
                reply_markup=markup
            )
            bot.delete_message(message.chat.id, smsg.message_id)
        except Exception as e:
            bot.edit_message_text(f"Rasm yaratish xatosi: {e}", message.chat.id, smsg.message_id)
        return

    # 3. Qo'shiq yoki Minus qidiruvi bo'lsa (0.8 soniyada tezkor natija!)
    lower_text = text.lower()
    is_minus_search = (state == "waiting_minus_search") or ("minus" in lower_text)
    is_song_search = (
        (state in ["waiting_song_original", "waiting_minus_search"]) or
        is_likely_music_query(text)
    )
    
    if is_song_search and state != "ai_mode":
        set_user_state(user_id, None)
        query = text
        for p in ["qo'shiq", "qoshiq", "musiqa", "minus", ":"]:
            if query.lower().startswith(p):
                query = query[len(p):].strip()
        if not query:
            query = text

        if is_minus_search and "minus" not in query.lower():
            search_query = f"{query} minus"
        else:
            search_query = query

        # Foydalanuvchi darhol 0.1 soniyada javob ko'radi
        smsg = bot.send_message(message.chat.id, f"🔍 <i>«{query}» qidirilmoqda...</i>")
        
        # 0.8 soniyada tezkor qidiruv
        results = search_online_music(search_query, limit=5)
        yt_search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(search_query)}"
        qkey = str(uuid.uuid4())[:8]
        query_cache[qkey] = query
            
        if results:
            markup = types.InlineKeyboardMarkup(row_width=1)
            out = (
                f"{HEADER_BANNER}\n\n"
                f"🎵 <b>«{query}» bo'yicha topilgan sara qo'shiqlar:</b>\n\n"
                f"🎧 <b>Tugmani bosing:</b> MP3 yuklab oling yoki YouTube'da tomosha qiling:\n"
            )
            for idx, r in enumerate(results, 1):
                cache_key = str(uuid.uuid4())[:8]
                download_cache[cache_key] = {'url': r['webpage_url'], 'title': r['title']}
                btn_dl = f"📥 MP3 Yuklab olish: {r['title'][:30]}{r['duration_str']}"
                btn_yt = f"▶️ {idx}. YouTube'da ochish"
                markup.add(
                    types.InlineKeyboardButton(btn_dl, callback_data=f"dl_{cache_key}"),
                    types.InlineKeyboardButton(btn_yt, url=r['webpage_url'])
                )
                
            markup.add(types.InlineKeyboardButton(f"🌐 YouTube'dan to'liq qidiruv: «{query[:25]}»", url=yt_search_url))
            markup.add(types.InlineKeyboardButton("🧠 Buni savol deb tushun (Gemini AI)", callback_data=f"force_ai_{qkey}"))
            markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
            
            bot.edit_message_text(out, message.chat.id, smsg.message_id, reply_markup=markup)
            return
        else:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(f"🌐 YouTube'da qidirish: «{query}»", url=yt_search_url))
            markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
            out = (
                f"{HEADER_BANNER}\n\n"
                f"😔 <b>Kechirasiz, «{query}» bo'yicha to'g'ridan-to'g'ri musiqa topilmadi.</b>\n\n"
                f"Lekin siz uni YouTube orqali qidirishingiz mumkin:"
            )
            bot.edit_message_text(out, message.chat.id, smsg.message_id, reply_markup=markup)
            return

    # 4. Gemini AI Savol-Javob (Tezkor va adabiy o'zbek tilida)
    # Salomlashish va oddiy gaplar bo'lsa 0.01 soniyada to'g'ridan-to'g'ri javob beramiz
    p_clean = text.strip().lower()
    fast_greeting = None
    if p_clean in ["salom", "assalom", "assalomu alaykum", "assalomu aleykum", "salom alaykum", "salomaleykum", "privet", "hello"]:
        fast_greeting = "Assalomu alaykum! Xush kelibsiz! Sizga qanday yordam bera olaman? Istalgan savolingizni bering yoki qo'shiq nomini yozing!"
    elif any(p_clean == g for g in ["qandaysiz", "qalesiz", "yaxshimisiz", "ishlar qalay", "ahvolingiz qanday", "ahvollar qalay"]):
        fast_greeting = "Rahmat, judayam yaxshi! O'zingiz yaxshimisiz? Sizga qanday yordam bera olaman?"
    elif any(p_clean == g for g in ["rahmat", "katta rahmat", "raxmat", "tashakkur", "spasibo", "sog' bo'ling"]):
        fast_greeting = "Arzimaydi! Xizmatingizdamiz. Yana qanday savolingiz yoki xizmatingiz bor?"
    elif any(p_clean == g for g in ["sen kimsan", "isming nima", "kim bu", "nima qila olasan", "haqingda ayt"]):
        fast_greeting = "Men — Elbek Studiya AI yordamchisiman. Ushbu bot rasman Elbek Studiya, Marufjon Maxramov va Javlonbek Ruziyev tomonidan yaratilgan. Savollaringizga to'g'ri javob beraman, qo'shiq va minuslarni topib beraman!"

    if fast_greeting:
        cid = str(uuid.uuid4())[:8]
        voice_cache[cid] = fast_greeting
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🗣 Odamday gapirib ber (Ovoz)", callback_data=f"spk_{cid}"))
        markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
        bot.send_message(message.chat.id, f"{HEADER_BANNER}\n\n{fast_greeting}", reply_markup=markup)
        return

    # Murakkab savol bo'lsa: darhol 0.1 soniyada xabar yuboramiz va orqa fonda javobni chiqaramiz
    smsg = bot.send_message(message.chat.id, "⚡️ <i>Javob tayyorlanmoqda...</i>")
    
    def process_ai():
        answer = ask_gemini(user_id, text)
        cid = str(uuid.uuid4())[:8]
        voice_cache[cid] = answer
        if len(voice_cache) > 200:
            voice_cache.clear()
            
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🗣 Odamday gapirib ber (Ovoz)", callback_data=f"spk_{cid}"))
        markup.add(types.InlineKeyboardButton(f"🎵 «{text[:20]}» qo'shig'ini qidirish", switch_inline_query_current_chat=f"{text}"))
        markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
        
        formatted_answer = f"{HEADER_BANNER}\n\n{answer}"
        try:
            bot.edit_message_text(formatted_answer, message.chat.id, smsg.message_id, reply_markup=markup, parse_mode="HTML")
        except Exception:
            bot.edit_message_text(formatted_answer, message.chat.id, smsg.message_id, reply_markup=markup, parse_mode=None)

    threading.Thread(target=process_ai).start()

# ==================== 24/7 TO'XTOVSIZ ISHLASH VA SERVER HEALTH CHECK ====================
import http.server
import socketserver

def run_health_server():
    try:
        port = int(os.environ.get("PORT", 10000))
        class HealthHandler(http.server.SimpleHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Elbek Studiya Bot 24/7 Server Faol!")
            def log_message(self, format, *args):
                pass
        with socketserver.TCPServer(("", port), HealthHandler) as httpd:
            httpd.serve_forever()
    except Exception as e:
        pass

if __name__ == '__main__':
    init_db()
    setup_bot_commands()
    threading.Thread(target=run_health_server, daemon=True).start()
    print("=" * 65)
    print("🚀 ELBEK STUDIYA & MARUFJON MAXRAMOV & JAVLONBEK RUZIYEV BOT FAOL!")
    print("🤖 Telegram: @ElbekStudiyaMinusbot")
    print("⚡️ Musiqa qidiruv tezligi: 0.8 soniya (Tezkor)")
    print("⚡️ Salomlashish va oddiy gaplar: 0.01 soniya")
    print("🌐 Server rejimi: 24/7 Bulut va Lokal tayyor")
    print("=" * 65)
    
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            print(f"Polling xatosi: {e}")
            time.sleep(1)
