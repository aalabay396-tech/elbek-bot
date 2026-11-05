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
import g4f
from g4f.client import Client
import requests

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# ==================== ASOSIY SOZLAMALAR ====================
BOT_TOKEN = "9060761508:AAHlWfubDseZGYOMcUIJ--Okl5UYn16pS70"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
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
            language TEXT DEFAULT 'uz',
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
        if "language" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'uz'")
    except Exception:
        pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

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

user_languages = {}

def get_setting(key, default=""):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        c.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = c.fetchone()
        conn.close()
        return row[0] if (row and row[0]) else default
    except Exception:
        return default

def set_setting(key, value):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"set_setting xatosi: {e}")

def get_gemini_api_key():
    import config
    k = get_setting("gemini_api_key")
    if k:
        return k
    k = os.environ.get("GEMINI_API_KEY", "")
    if k:
        return k
    return getattr(config, "GEMINI_API_KEY", "")

def get_user_language(user_id):
    if user_id in user_languages:
        return user_languages[user_id]
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        conn.close()
        lang = row[0] if (row and row[0]) else "uz"
        user_languages[user_id] = lang
        return lang
    except Exception:
        return "uz"

def set_user_language(user_id, lang):
    if lang not in ["uz", "ru", "en"]:
        lang = "uz"
    user_languages[user_id] = lang
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"set_user_language xatosi: {e}")

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

async def async_create_voice(text: str, file_path: str, lang: str = "uz"):
    clean = clean_for_speech(text)
    tail_map = {
        "uz": "... Davomini o'qib olishingiz mumkin.",
        "ru": "... Продолжение читайте в сообщении.",
        "en": "... Continue reading in text."
    }
    if len(clean) > 800:
        clean = clean[:800] + tail_map.get(lang, tail_map["uz"])
    voice_map = {
        "uz": "uz-UZ-MadinaNeural",
        "ru": "ru-RU-SvetlanaNeural",
        "en": "en-US-JennyNeural"
    }
    v_name = voice_map.get(lang, "uz-UZ-MadinaNeural")
    communicate = edge_tts.Communicate(clean, voice=v_name, rate="+4%")
    await communicate.save(file_path)

def generate_voice(text: str, lang: str = "uz") -> str:
    fid = str(uuid.uuid4())[:8]
    out_file = os.path.join(TEMP_DIR, f"voice_{fid}.ogg")
    try:
        asyncio.run(async_create_voice(text, out_file, lang=lang))
        if os.path.exists(out_file) and os.path.getsize(out_file) > 100:
            return out_file
    except Exception as e:
        print(f"Ovoz yaratishda xato: {e}")
    return None

def send_voice_message(chat_id, text, caption=None, lang: str = "uz"):
    try:
        vf = generate_voice(text, lang=lang)
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

# ==================== KO'P TILLI XABARLAR VA SOZLAMALAR (UZ, RU, EN) ====================
MESSAGES = {
    "uz": {
        "welcome": (
            f"{HEADER_BANNER}\n\n"
            f"🎙 <b>Assalomu alaykum, {{first_name}}!</b>\n\n"
            f"Pastdagi <b>to'rtburchak (⊞) bo'limlar katagi</b> yoki chapdagi <b>[Menu]</b> tugmasi orqali barcha bo'limlar xizmatingizda:\n\n"
            f"🎵 <b>Qo'shiq qidirish:</b> Internet va YouTube'dan 0.8 soniyada toza MP3 yuklab olish\n"
            f"🎙 <b>Minus qidirish:</b> Fonogramma va karaoke minuslarini topish\n"
            f"🎛 <b>AI Minus Yaratish:</b> MVSep orqali vokalni ajratish\n"
            f"🧠 <b>Gemini AI:</b> Istalgan mavzudagi savolingizga tezkor javob olish\n"
            f"🎨 <b>Tiniq Rasm Chizish:</b> 8K / HD sifatdagi ajoyib rasmlar yaratish\n"
            f"🗣 <b>Odamday Gapirib Berish:</b> Yozuvlarni jonli inson ovozida o'qitish\n\n"
            f"👇 <b>Qaysi bo'limni tanlaysiz?</b> Pastdagi katakchalardan birini bosing:"
        ),
        "menu_header": f"{HEADER_BANNER}\n\n🎛 <b>Barcha bo'limlar menyusi:</b>\nPastdagi tugmalardan kerakli bo'lim ustiga bosing:",
        "search_song_prompt": (
            f"{HEADER_BANNER}\n\n"
            f"🎵 <b>Original Qo'shiqlar Qidiruvi!</b> 🎧\n\n"
            f"✍️ <b>Qidirayotgan qo'shiq yoki san'atkor nomini yozing:</b>\n"
            f"<i>(Masalan: Jaloliddin Ahmadaliyev Janonim, Munisa Rizayeva va h.k.)</i>\n\n"
            f"⚡️ Bot bir zumda YouTube'dan qidiradi va toza MP3 qilib beradi!"
        ),
        "search_minus_prompt": (
            f"{HEADER_BANNER}\n\n"
            f"🎙 <b>Minuslar va Fonogramma Qidiruvi!</b> 🎼\n\n"
            f"✍️ <b>Qidirayotgan minus yoki san'atkor nomini yozing:</b>\n"
            f"<i>(Masalan: Jaloliddin Ahmadaliyev 19 yil minus, Ozodbek Rayhon minus)</i>"
        ),
        "ai_prompt": (
            f"{HEADER_BANNER}\n\n"
            f"🧠 <b>Google Gemini AI Savol-Javob bo'limi!</b> ✨\n\n"
            f"Menga istalgan savolingizni berishingiz mumkin:\n"
            f"• Masalalar, fanlar va hisob-kitoblar\n"
            f"• Qo'shiq matnlari, she'rlar va ssenariylar\n"
            f"• Tarjimalar va do'stona suhbat\n\n"
            f"✍️ <b>Savolingizni yozib yuboring — bot darhol javob beradi:</b>"
        ),
        "paint_prompt": (
            f"{HEADER_BANNER}\n\n"
            f"🎨 <b>O'ta Tiniq (HD / 8K) Rasm Chizish bo'limi!</b> ✨\n\n"
            f"✍️ <b>Qanday rasm chizib beray? Tasvirlab yozing:</b>\n"
            f"• <i>Toshkent ko'chasida qora Malibu</i>\n"
            f"• <i>Oltin musiqiy studiyada mikrafon</i>\n"
            f"• <i>Tog'lar bag'rida oq Tulpor</i>"
        ),
        "tts_prompt": (
            "🗣 <b>Odamday Gapirib Berish bo'limi!</b> 🎙\n\n"
            "Istalgan matningizni yozib yuboring — bot uni to'g'ri talaffuzda xuddi <b>haqiqiy odamdek jonli ovozda</b> audio qilib yuboradi!\n\n"
            "✍️ <b>Matnni yozib yuboring:</b>"
        ),
        "clear_chat": "🧹 <b>Yangi suhbat boshlandi!</b> Barcha xotira tozalandi. Istalgan savolingizni bering:",
        "lang_choose": (
            f"{HEADER_BANNER}\n\n"
            f"🌐 <b>Iltimos, muloqot tilini tanlang:</b>\n"
            f"🇷🇺 Пожалуйста, выберите язык общения:\n"
            f"🇬🇧 Please select your language:"
        ),
        "lang_selected": "🇺🇿 <b>O'zbek tili muvaffaqiyatli tanlandi!</b>"
    },
    "ru": {
        "welcome": (
            f"{HEADER_BANNER}\n\n"
            f"🎙 <b>Здравствуйте, {{first_name}}!</b>\n\n"
            f"Все разделы бота к вашим услугам через <b>кнопки внизу (⊞)</b> или меню <b>[Menu]</b>:\n\n"
            f"🎵 <b>Поиск песни:</b> Чистый MP3 из Интернета и YouTube за 0.8 сек\n"
            f"🎙 <b>Поиск минусовки:</b> Фонограммы и караоке минуса\n"
            f"🎛 <b>AI Создание минуса:</b> Удаление вокала через MVSep\n"
            f"🧠 <b>Gemini AI:</b> Быстрые и точные ответы на любые вопросы\n"
            f"🎨 <b>Рисование в HD:</b> Создание потрясающих картинок в 8K\n"
            f"🗣 <b>Озвучка голосом:</b> Чтение текста реалистичным человеческим голосом\n\n"
            f"👇 <b>Какой раздел выберете?</b> Нажмите на одну из кнопок ниже:"
        ),
        "menu_header": f"{HEADER_BANNER}\n\n🎛 <b>Меню всех разделов:</b>\nНажмите на интересующий вас раздел ниже:",
        "search_song_prompt": (
            f"{HEADER_BANNER}\n\n"
            f"🎵 <b>Раздел поиска музыки!</b> 🎧\n\n"
            f"✍️ <b>Напишите имя исполнителя или название песни:</b>\n"
            f"<i>(Например: Jony Комета, Баста Сансара и т.д.)</i>\n\n"
            f"⚡️ Бот мгновенно найдет песню на YouTube и скачает чистый MP3!"
        ),
        "search_minus_prompt": (
            f"{HEADER_BANNER}\n\n"
            f"🎙 <b>Раздел поиска минусовок и караоке!</b> 🎼\n\n"
            f"✍️ <b>Напишите название песни или исполнителя:</b>\n"
            f"<i>(Например: Баста Сансара минус, Jah Khalib Лейла минус)</i>"
        ),
        "ai_prompt": (
            f"{HEADER_BANNER}\n\n"
            f"🧠 <b>Google Gemini AI — Вопрос-Ответ!</b> ✨\n\n"
            f"Вы можете задать мне абсолютно любой вопрос:\n"
            f"• Научные, учебные или жизненные темы\n"
            f"• Стихи, тексты песен, сценарии\n"
            f"• Программирование и решение задач\n\n"
            f"✍️ <b>Напишите свой вопрос — бот сразу ответит:</b>"
        ),
        "paint_prompt": (
            f"{HEADER_BANNER}\n\n"
            f"🎨 <b>Генератор картинок (HD / 8K)!</b> ✨\n\n"
            f"✍️ <b>Опишите, какую картинку хотите создать:</b>\n"
            f"• <i>Черный спорткар на ночной улице Ташкента</i>\n"
            f"• <i>Микрофон в золотой музыкальной студии</i>\n"
            f"• <i>Белый конь на фоне красивых гор</i>"
        ),
        "tts_prompt": (
            "🗣 <b>Озвучка текста голосом!</b> 🎙\n\n"
            "Напишите любой текст — бот озвучит его приятным <b>человеческим голосом</b> в виде аудио сообщения!\n\n"
            "✍️ <b>Напишите текст:</b>"
        ),
        "clear_chat": "🧹 <b>Начат новый диалог!</b> История очищена. Задайте любой новый вопрос:",
        "lang_choose": (
            f"{HEADER_BANNER}\n\n"
            f"🌐 <b>Пожалуйста, выберите язык общения:</b>\n"
            f"🇺🇿 Iltimos, muloqot tilini tanlang:\n"
            f"🇬🇧 Please select your language:"
        ),
        "lang_selected": "🇷🇺 <b>Русский язык успешно выбран!</b>"
    },
    "en": {
        "welcome": (
            f"{HEADER_BANNER}\n\n"
            f"🎙 <b>Hello, {{first_name}}!</b>\n\n"
            f"All features are available below or via the <b>[Menu]</b> button:\n\n"
            f"🎵 <b>Search Song:</b> Download clean MP3 from YouTube in 0.8s\n"
            f"🎙 <b>Search Instrumental:</b> Backing tracks & karaoke minuses\n"
            f"🎛 <b>AI Vocal Remover:</b> Separate vocals and audio via MVSep\n"
            f"🧠 <b>Gemini AI:</b> Fast and smart answers to any query\n"
            f"🎨 <b>HD Image Generator:</b> Create photorealistic 8K art\n"
            f"🗣 <b>Text-to-Speech:</b> Realistic human voice audio generator\n\n"
            f"👇 <b>Select a section below to get started:</b>"
        ),
        "menu_header": f"{HEADER_BANNER}\n\n🎛 <b>Main Sections Menu:</b>\nChoose one of the options below:",
        "search_song_prompt": (
            f"{HEADER_BANNER}\n\n"
            f"🎵 <b>Fast Music Search!</b> 🎧\n\n"
            f"✍️ <b>Send singer name or song title to find it immediately:</b>\n"
            f"<i>(Example: Imagine Dragons Believer, Adele Someone Like You)</i>\n\n"
            f"⚡️ The bot quickly searches YouTube and converts to clean MP3!"
        ),
        "search_minus_prompt": (
            f"{HEADER_BANNER}\n\n"
            f"🎙 <b>Instrumental & Karaoke Search!</b> 🎼\n\n"
            f"✍️ <b>Send the song title or artist:</b>\n"
            f"<i>(Example: Adele Someone Like You instrumental, Queen Bohemian Rhapsody minus)</i>"
        ),
        "ai_prompt": (
            f"{HEADER_BANNER}\n\n"
            f"🧠 <b>Google Gemini AI Q&A!</b> ✨\n\n"
            f"Ask me anything you'd like:\n"
            f"• Science, education, code, calculations\n"
            f"• Song lyrics, poems, essays, summaries\n"
            f"• Friendly chat and translations\n\n"
            f"✍️ <b>Send your question:</b>"
        ),
        "paint_prompt": (
            f"{HEADER_BANNER}\n\n"
            f"🎨 <b>HD Image Generator (8K)!</b> ✨\n\n"
            f"✍️ <b>Describe the image you want to create:</b>\n"
            f"• <i>Futuristic cyber city at night, neon lights, 8k</i>\n"
            f"• <i>Golden vintage microphone in luxury studio</i>\n"
            f"• <i>Majestic white horse in alpine mountains</i>"
        ),
        "tts_prompt": (
            "🗣 <b>Realistic Text-to-Speech!</b> 🎙\n\n"
            "Send any text and the bot will convert it into high quality <b>natural human voice</b> audio!\n\n"
            "✍️ <b>Send your text:</b>"
        ),
        "clear_chat": "🧹 <b>New conversation started!</b> Memory cleared. Feel free to ask anything:",
        "lang_choose": (
            f"{HEADER_BANNER}\n\n"
            f"🌐 <b>Please select your preferred language:</b>\n"
            f"🇺🇿 Iltimos, muloqot tilini tanlang:\n"
            f"🇷🇺 Пожалуйста, выберите язык общения:"
        ),
        "lang_selected": "🇬🇧 <b>English language successfully selected!</b>"
    }
}

GREETINGS_REPLIES = {
    "uz": {
        "greeting": "Assalomu alaykum! Xush kelibsiz! Sizga qanday yordam bera olaman? Istalgan savolingizni bering yoki qo'shiq nomini yozing!",
        "how_are_you": "Rahmat, judayam yaxshi! O'zingiz yaxshimisiz? Sizga qanday yordam bera olaman?",
        "thanks": "Arzimaydi! Xizmatingizdamiz. Yana qanday savolingiz yoki xizmatingiz bor?",
        "who_are_you": "Men — Elbek Studiya AI yordamchisiman. Ushbu bot rasman Elbek Studiya, Marufjon Maxramov va Javlonbek Ruziyev tomonidan yaratilgan. Savollaringizga to'g'ri javob beraman, qo'shiq va minuslarni topib beraman!"
    },
    "ru": {
        "greeting": "Здравствуйте! Добро пожаловать! Чем могу помочь? Задайте любой вопрос или напишите название песни!",
        "how_are_you": "Спасибо, отлично! Как ваши дела? Чем могу вам помочь?",
        "thanks": "Пожалуйста! Рад помочь. Есть ли у вас еще вопросы?",
        "who_are_you": "Я — искусственный интеллект Elbek Studiya AI, созданный Elbek Studiya, Marufjon Maxramov и Javlonbek Ruziyev. Я отвечаю на любые вопросы, нахожу песни и минусовки!"
    },
    "en": {
        "greeting": "Hello and welcome! How can I assist you today? Feel free to ask any question or enter a song name!",
        "how_are_you": "Thank you, doing wonderful! How are you? How can I help you today?",
        "thanks": "You're very welcome! Glad to help. Do you have any other questions?",
        "who_are_you": "I am Elbek Studiya AI, created by Elbek Studiya, Marufjon Maxramov, and Javlonbek Ruziyev. I can answer any questions and find songs or instrumentals for you!"
    }
}

def get_system_prompt_for_lang(lang: str) -> str:
    if lang == "ru":
        return (
            "Вы — 'Elbek Studiya AI', профессиональный и умный помощник. "
            "Этот бот создан Elbek Studiya, Marufjon Maxramov и Javlonbek Ruziyev. "
            "Всегда отвечайте грамотно, дружелюбно, вежливо и понятно на чистом русском языке. "
            "Давайте четкие, содержательные и исчерпывающие ответы на любые вопросы, стихи, задачи и темы."
        )
    elif lang == "en":
        return (
            "You are 'Elbek Studiya AI', a helpful and intelligent assistant. "
            "This bot was created by Elbek Studiya, Marufjon Maxramov, and Javlonbek Ruziyev. "
            "Always respond in fluent, polite, accurate, natural and grammatically correct English. "
            "Provide helpful and comprehensive answers to any questions or requests."
        )
    else:
        return (
            "Siz 'Elbek Studiya AI' aqlli yordamchisisiz. "
            "Ushbu bot rasman Elbek Studiya, Marufjon Maxramov va Javlonbek Ruziyev tomonidan yaratilgan. "
            "Har doim sof, tabiiy, adabiy va go'zal o'zbek tilida, grammatik qoidalarga to'liq amal qilib javob bering. "
            "Hech qachon g'alati yoki xato tarjima so'zlarni ishlatmang. "
            "Foydalanuvchining savoliga aniq, to'g'ri va xushmuomala bo'lib javob bering."
        )

# ==================== TEZKOR VA SOF AI SAVOL-JAVOB ====================
def is_bad_response(text: str) -> bool:
    if not text or len(text.strip()) < 2:
        return True
    bad_phrases = [
        "copilot moved",
        "install the new copilot",
        "copilot history and content will be deleted",
        "unifiedlink.svc.cloud.microsoft",
        "openappstoreonload",
        "sign in on your pc or mac",
        "sign in with the same account",
        "needs ios 26",
        "android 13 or later",
        "copilot_migration",
        "microsoft copilot",
        "copilot",
        "no cake credits",
        "bake proof-of-work",
        "sign up and repeat your request",
        "402 payment required"
    ]
    txt_lower = text.lower()
    return any(p in txt_lower for p in bad_phrases)

def call_official_gemini_api(user_id: int, user_prompt: str, api_key: str, lang: str = "uz") -> str:
    if not api_key:
        return None
    models_to_try = ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]
    sys_text = get_system_prompt_for_lang(lang)
    for m in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}]
                }
            ],
            "systemInstruction": {
                "parts": [{"text": sys_text}]
            },
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 2048
            }
        }
        try:
            r = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=15)
            if r.status_code == 200:
                data = r.json()
                cands = data.get("candidates", [])
                if cands:
                    parts = cands[0].get("content", {}).get("parts", [])
                    if parts and "text" in parts[0]:
                        ans = parts[0]["text"].strip()
                        if not is_bad_response(ans):
                            return ans
        except Exception:
            continue
    return None

def call_pollinations_api(prompt: str, lang: str = "uz") -> str:
    try:
        sys_prompt = get_system_prompt_for_lang(lang)
        url = "https://text.pollinations.ai/"
        payload = {
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": prompt}
            ],
            "model": "openai"
        }
        r = requests.post(url, json=payload, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, timeout=8)
        if r.status_code == 200 and len(r.text.strip()) > 2 and not is_bad_response(r.text):
            return r.text.strip()
    except Exception:
        pass
    return None

def ask_gemini(user_id: int, user_prompt: str) -> str:
    lang = get_user_language(user_id) or "uz"
    p_clean = user_prompt.strip().lower()
    
    # 1. Tezkor, chiroyli va tabiiy salom-aliklar (0.01 soniyada toza javob)
    if p_clean in ["salom", "assalom", "assalomu alaykum", "assalomu aleykum", "salom alaykum", "salomaleykum"]:
        return GREETINGS_REPLIES.get(lang, GREETINGS_REPLIES["uz"])["greeting"]
    if p_clean in ["privet", "hello", "hi", "здравствуйте", "привет", "добрый день"]:
        return GREETINGS_REPLIES.get(lang, GREETINGS_REPLIES["uz"])["greeting"]
        
    if any(p_clean == g for g in ["qandaysiz", "qalesiz", "yaxshimisiz", "ishlar qalay", "ahvolingiz qanday", "как дела", "how are you"]):
        return GREETINGS_REPLIES.get(lang, GREETINGS_REPLIES["uz"])["how_are_you"]
        
    if any(p_clean == g for g in ["rahmat", "katta rahmat", "raxmat", "tashakkur", "spasibo", "спасибо", "thanks", "thank you", "sog' bo'ling"]):
        return GREETINGS_REPLIES.get(lang, GREETINGS_REPLIES["uz"])["thanks"]
        
    if any(p_clean == g for g in ["sen kimsan", "isming nima", "kim bu", "кто ты", "who are you", "nima qila olasan", "haqingda ayt"]):
        return GREETINGS_REPLIES.get(lang, GREETINGS_REPLIES["uz"])["who_are_you"]

    # 2. Rasmiy Google Gemini API orqali javob
    active_key = get_gemini_api_key()
    if active_key:
        official_ans = call_official_gemini_api(user_id, user_prompt, active_key, lang=lang)
        if official_ans:
            return official_ans

    # 3. Zaxira Pollinations AI
    pol_ans = call_pollinations_api(user_prompt, lang=lang)
    if pol_ans:
        return pol_ans

    # 4. Zaxira g4f modellar
    sys_prompt = get_system_prompt_for_lang(lang)
    if user_id not in user_history:
        user_history[user_id] = [{"role": "system", "content": sys_prompt}]
        
    user_history[user_id].append({"role": "user", "content": user_prompt})
    if len(user_history[user_id]) > 6:
        user_history[user_id] = [user_history[user_id][0]] + user_history[user_id][-5:]

    models_to_try = ["gemini-2.5-flash", "gpt-4o-mini", "llama-3.3-70b", "deepseek-v3"]
    for model_name in models_to_try:
        try:
            res = ai_client.chat.completions.create(
                model=model_name,
                messages=user_history[user_id],
                timeout=6
            )
            ans = res.choices[0].message.content
            if ans and not is_bad_response(ans):
                import re
                ans = re.sub(r'<FollowUp[^>]*/>', '', ans)
                ans = re.sub(r'<FollowUp[^>]*>.*?</FollowUp>', '', ans, flags=re.DOTALL)
                lines = ans.strip().split("\n")
                if lines and lines[0].strip().startswith("####"):
                    ans = "\n".join(lines[1:]).strip()
                ans = ans.strip()
                if not is_bad_response(ans):
                    user_history[user_id].append({"role": "assistant", "content": ans})
                    return ans
        except Exception:
            continue

    if lang == "ru":
        return (
            "Здравствуйте! Ваш вопрос принят.\n\n"
            "⚠️ Чтобы бот отвечал стабильно и быстро в любой момент, вы можете подключить бесплатный официальный ключ Google Gemini API через команду:\n"
            "<code>/setkey ВАШ_КЛЮЧ</code>\n\n"
            "💡 Бесплатный ключ берется за 1 минуту: https://aistudio.google.com/app/apikey\n"
            "Или просто повторите свой вопрос через несколько секунд."
        )
    elif lang == "en":
        return (
            "Hello! Your message has been received.\n\n"
            "⚠️ For instant and uninterrupted responses, you can connect your free Google Gemini API key using:\n"
            "<code>/setkey YOUR_KEY</code>\n\n"
            "💡 Free key available in 1 minute: https://aistudio.google.com/app/apikey\n"
            "Or try sending your request again in a few moments."
        )
    else:
        return (
            "Assalomu alaykum! Savolingiz qabul qilindi.\n\n"
            "⚠️ Botning Gemini AI tizimi to'xtovsiz va chaqmoqdek tez javob berishi uchun bepul Google Gemini API kalitini kiritishingiz mumkin:\n"
            "<code>/setkey KALITINGIZ</code>\n\n"
            "💡 1 daqiqada mutlaqo bepul API kalit olish: https://aistudio.google.com/app/apikey\n"
            "Yoki savolingizni birozdan so'ng qayta yuborib ko'ring."
        )

# ==================== O'TA TINIQ RASM CHIZISH (HD) ====================
def generate_hd_image_url(prompt: str) -> str:
    hd_prompt = f"{prompt}, 8k resolution, highly detailed, photorealistic, cinematic lighting, sharp focus, masterpiece"
    encoded = urllib.parse.quote(hd_prompt)
    return f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&model=flux&nologo=true&enhance=true"

# ==================== TO'RTBURCHAK BO'LIMLAR KATAGI (DOIMIY KLAVIATURA) ====================
def get_language_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="set_lang_uz"),
        types.InlineKeyboardButton("🇷🇺 Русский", callback_data="set_lang_ru"),
        types.InlineKeyboardButton("🇬🇧 English", callback_data="set_lang_en")
    )
    return markup

def get_main_keyboard(user_id=None):
    lang = get_user_language(user_id) if user_id else "uz"
    if not lang or lang not in ["uz", "ru", "en"]:
        lang = "uz"
        
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True, row_width=2)
    
    if lang == "ru":
        markup.add(
            types.KeyboardButton("🚀 /start (Главное Меню)"),
            types.KeyboardButton("🧠 Gemini AI (Вопрос-Ответ)")
        )
        markup.add(
            types.KeyboardButton("🎵 Поиск песни (Оригинал)"),
            types.KeyboardButton("🎙 Поиск минусовки (Фонограмма)")
        )
        markup.add(
            types.KeyboardButton("🎛 AI создание минуса (MVSep)"),
            types.KeyboardButton("🎨 Рисование в HD")
        )
        markup.add(
            types.KeyboardButton("🗣 Озвучка текста голосом"),
            types.KeyboardButton("🌐 Сменить язык")
        )
        markup.add(
            types.KeyboardButton("🎤 Список артистов"),
            types.KeyboardButton("⭐️ Лучшие минусовки")
        )
        markup.add(
            types.KeyboardButton("🔄 Новый диалог"),
            types.KeyboardButton("👑 Об авторах")
        )
        markup.add(types.KeyboardButton("📊 Статистика"))
    elif lang == "en":
        markup.add(
            types.KeyboardButton("🚀 /start (Main Menu)"),
            types.KeyboardButton("🧠 Gemini AI (Q&A)")
        )
        markup.add(
            types.KeyboardButton("🎵 Search Song (Original)"),
            types.KeyboardButton("🎙 Search Instrumental (Minus)")
        )
        markup.add(
            types.KeyboardButton("🎛 AI Vocal Remover (MVSep)"),
            types.KeyboardButton("🎨 HD Image Generator")
        )
        markup.add(
            types.KeyboardButton("🗣 Text-to-Speech"),
            types.KeyboardButton("🌐 Change Language")
        )
        markup.add(
            types.KeyboardButton("🎤 Popular Artists"),
            types.KeyboardButton("⭐️ Best Instrumentals")
        )
        markup.add(
            types.KeyboardButton("🔄 New Chat"),
            types.KeyboardButton("👑 About Authors")
        )
        markup.add(types.KeyboardButton("📊 Statistics"))
    else:
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
            types.KeyboardButton("🗣 Odamday Gapirib Berish"),
            types.KeyboardButton("🌐 Tilni o'zgartirish")
        )
        markup.add(
            types.KeyboardButton("🎤 San'atkorlar ro'yxati"),
            types.KeyboardButton("⭐️ Eng Sara Minuslar")
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
            types.BotCommand("start", "🚀 Bosh menyu / Til tanlash / Start"),
            types.BotCommand("lang", "🌐 Tilni o'zgartirish / Сменить язык / Change Language"),
            types.BotCommand("menu", "🎛 Barcha bo'limlar"),
            types.BotCommand("qoshiq", "🎵 Qo'shiq qidirish (MP3)"),
            types.BotCommand("minus", "🎙 Minus qidirish (Fonogramma)"),
            types.BotCommand("mvsep", "🎛 AI Minus yaratish (MVSep)"),
            types.BotCommand("ai", "🧠 Gemini AI savol-javob"),
            types.BotCommand("rasm", "🎨 Tiniq HD rasm chizish"),
            types.BotCommand("setkey", "🔑 Gemini API kalitini kiritish"),
            types.BotCommand("clear", "🔄 Yangi suhbat")
        ]
        bot.set_my_commands(cmds)
        bot.set_chat_menu_button(menu_button=types.MenuButtonCommands())
    except Exception as e:
        print(f"setup_bot_commands xatosi: {e}")

# ==================== ASOSIY XUSH KELIBSIZ FUNKSIYASI ====================
def send_main_welcome(chat_id, user_id, first_name, lang="uz"):
    lang_data = MESSAGES.get(lang, MESSAGES["uz"])
    welcome_tmpl = lang_data["welcome"]
    welcome_text = welcome_tmpl.replace("{{first_name}}", first_name)
    
    inline_markup = types.InlineKeyboardMarkup()
    if lang == "ru":
        inline_markup.add(
            types.InlineKeyboardButton("🎵 Поиск песни", callback_data="btn_search_song"),
            types.InlineKeyboardButton("🎙 Поиск минусовки", callback_data="btn_search_minus")
        )
        inline_markup.add(
            types.InlineKeyboardButton("🧠 Gemini AI", callback_data="btn_open_ai"),
            types.InlineKeyboardButton("🎨 Рисование в HD", callback_data="btn_open_paint")
        )
        inline_markup.add(
            types.InlineKeyboardButton("🌐 Сменить язык", callback_data="btn_choose_lang")
        )
    elif lang == "en":
        inline_markup.add(
            types.InlineKeyboardButton("🎵 Search Song", callback_data="btn_search_song"),
            types.InlineKeyboardButton("🎙 Search Instrumental", callback_data="btn_search_minus")
        )
        inline_markup.add(
            types.InlineKeyboardButton("🧠 Gemini AI", callback_data="btn_open_ai"),
            types.InlineKeyboardButton("🎨 HD Art Generator", callback_data="btn_open_paint")
        )
        inline_markup.add(
            types.InlineKeyboardButton("🌐 Change Language", callback_data="btn_choose_lang")
        )
    else:
        inline_markup.add(
            types.InlineKeyboardButton("🎵 Qo'shiq qidirish", callback_data="btn_search_song"),
            types.InlineKeyboardButton("🎙 Minus qidirish", callback_data="btn_search_minus")
        )
        inline_markup.add(
            types.InlineKeyboardButton("🧠 Gemini AI", callback_data="btn_open_ai"),
            types.InlineKeyboardButton("🎨 HD Rasm Chizish", callback_data="btn_open_paint")
        )
        inline_markup.add(
            types.InlineKeyboardButton("🌐 Tilni o'zgartirish", callback_data="btn_choose_lang")
        )
        
    bot.send_message(chat_id, welcome_text, reply_markup=get_main_keyboard(user_id))
    choose_prompt = {
        "uz": "👇 <b>Qaysi bo'limni tanlaysiz?</b> Pastdagi tugmalardan birini bosing:",
        "ru": "👇 <b>Какой раздел выберете?</b> Нажмите на одну из кнопок ниже:",
        "en": "👇 <b>Which section do you choose?</b> Click one of the buttons below:"
    }.get(lang, "👇 <b>Bo'limni tanlang:</b>")
    bot.send_message(chat_id, choose_prompt, reply_markup=inline_markup)

# ==================== ASOSIY BUYRUQLAR VA START ====================
@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "Do'stim"
    save_user(user_id, message.from_user.username or "", message.from_user.full_name or "")
    set_user_state(user_id, None)
    
    current_lang = get_user_language(user_id)
    
    # Har doim start bosilganda O'zbek, Rus, Ingliz tilini tanlash tugmalari chiqadi
    lang_prompt = (
        f"{HEADER_BANNER}\n\n"
        f"👋 <b>Assalomu alaykum, {first_name}!</b>\n\n"
        f"🌐 <b>Iltimos, muloqot tilini tanlang:</b>\n"
        f"🇷🇺 Пожалуйста, выберите язык общения:\n"
        f"🇬🇧 Please select your language:"
    )
    bot.send_message(message.chat.id, lang_prompt, reply_markup=get_language_keyboard())
    


# Tilni o'zgartirish buyrug'i
@bot.message_handler(commands=['lang', 'language', 'til'])
@bot.message_handler(func=lambda m: m.text and m.text.strip() in [
    "🌐 Tilni o'zgartirish", "🌐 Сменить язык", "🌐 Change Language"
])
def handle_language_command(message):
    bot.send_message(
        message.chat.id,
        f"{HEADER_BANNER}\n\n"
        f"🌐 <b>Iltimos, muloqot tilini tanlang:</b>\n"
        f"🇷🇺 Пожалуйста, выберите язык общения:\n"
        f"🇬🇧 Please select your language:",
        reply_markup=get_language_keyboard()
    )

# Google Gemini API kalitini o'rnatish (/setkey)
@bot.message_handler(commands=['setkey', 'apikey', 'geminikey'])
def handle_set_key(message):
    user_id = message.from_user.id
    lang = get_user_language(user_id) or "uz"
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        if lang == "ru":
            bot.send_message(
                message.chat.id,
                "🔑 <b>Установка ключа Google Gemini API:</b>\n\n"
                "Чтобы подключить ключ, отправьте команду:\n"
                "<code>/setkey ВАШ_КЛЮЧ</code>\n\n"
                "💡 <i>Бесплатный ключ берется за 1 минуту: https://aistudio.google.com/app/apikey</i>"
            )
        elif lang == "en":
            bot.send_message(
                message.chat.id,
                "🔑 <b>Google Gemini API Key Setup:</b>\n\n"
                "Send command with your key:\n"
                "<code>/setkey YOUR_KEY</code>\n\n"
                "💡 <i>Get 100% free key in 1 minute: https://aistudio.google.com/app/apikey</i>"
            )
        else:
            bot.send_message(
                message.chat.id,
                "🔑 <b>Google Gemini API kalitini o'rnatish:</b>\n\n"
                "Kalitni ulash uchun quyidagicha yuboring:\n"
                "<code>/setkey KALITINGIZ</code>\n\n"
                "💡 <i>1 daqiqada mutlaqo bepul API kalit olish: https://aistudio.google.com/app/apikey</i>"
            )
        return
        
    new_key = parts[1].strip()
    smsg = bot.send_message(message.chat.id, "🔄 <i>API kalit tekshirilmoqda...</i>")
    test_ans = call_official_gemini_api(user_id, "Salom, test", new_key, lang=lang)
    if test_ans:
        set_setting("gemini_api_key", new_key)
        global GEMINI_API_KEY
        GEMINI_API_KEY = new_key
        success_msg = {
            "uz": "✅ <b>Google Gemini API kaliti muvaffaqiyatli saqlandi va tekshirildi!</b>\n\nEndi bot har qanday savolingizga 0.5 soniyada chaqmoqdek tez va aniq javob beradi! 🚀",
            "ru": "✅ <b>Ключ Google Gemini API успешно сохранен и проверен!</b>\n\nТеперь бот отвечает молниеносно на любые вопросы! 🚀",
            "en": "✅ <b>Google Gemini API key successfully verified and saved!</b>\n\nBot will now respond in 0.5s! 🚀"
        }.get(lang, "✅ Google Gemini API kaliti muvaffaqiyatli saqlandi!")
        bot.edit_message_text(success_msg, message.chat.id, smsg.message_id)
    else:
        err_msg = {
            "uz": "⚠️ <b>API kalit tekshirilmadi yoki yaroqsiz bo'lishi mumkin.</b>\nIltimos, kalitni to'g'ri nusxalaganligingizni tekshirib qayta yuboring.",
            "ru": "⚠️ <b>Ключ не прошел проверку.</b>\nПожалуйста, убедитесь в правильности ключа и попробуйте снова.",
            "en": "⚠️ <b>API key verification failed.</b>\nPlease check your key and try again."
        }.get(lang, "⚠️ API kalit tekshirilmadi!")
        bot.edit_message_text(err_msg, message.chat.id, smsg.message_id)

# Menyu buyrug'i (/menu, /bolimlar, bo'limlar)
@bot.message_handler(func=lambda m: m.text and m.text.lower() in ["/menu", "/bolimlar", "menu", "menyu", "bo'limlar", "bolimlar", "меню", "sections"])
def handle_menu_command(message):
    user_id = message.from_user.id
    set_user_state(user_id, None)
    lang = get_user_language(user_id) or "uz"
    text = MESSAGES.get(lang, MESSAGES["uz"])["menu_header"]
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard(user_id))

# ==================== BO'LIMLAR HANDLERLARI ====================

# 1. 🎵 Qo'shiq qidirish (Original)
@bot.message_handler(func=lambda m: m.text in [
    "🎵 Qo'shiq qidirish (Original)", "🎵 Поиск песни (Оригинал)", "🎵 Search Song (Original)", "/qoshiq", "/song"
])
def handle_song_search_btn(message):
    user_id = message.from_user.id
    set_user_state(user_id, "waiting_song_original")
    lang = get_user_language(user_id) or "uz"
    text = MESSAGES.get(lang, MESSAGES["uz"])["search_song_prompt"]
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard(user_id))

# 2. 🎙 Minus qidirish (Fonogramma)
@bot.message_handler(func=lambda m: m.text in [
    "🎙 Minus qidirish (Fonogramma)", "🎙 Поиск минусовки (Фонограмма)", "🎙 Search Instrumental (Minus)", "/minus"
])
def handle_minus_search_btn(message):
    user_id = message.from_user.id
    set_user_state(user_id, "waiting_minus_search")
    lang = get_user_language(user_id) or "uz"
    text = MESSAGES.get(lang, MESSAGES["uz"])["search_minus_prompt"]
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard(user_id))

# 3. 🎛 AI Minus Yaratish (MVSep)
@bot.message_handler(func=lambda m: m.text in [
    "🎛 AI Minus Yaratish (MVSep)", "🎛 AI создание минуса (MVSep)", "🎛 AI Vocal Remover (MVSep)", "/mvsep"
])
def handle_mvsep_section(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🤖 1. @mvsep_bot_bot orqali minus qilish (MVSep)", url="https://t.me/mvsep_bot_bot"),
        types.InlineKeyboardButton("🌐 2. VocalRemover AI orqali minus qilish", url="https://vocalremover.org"),
        types.InlineKeyboardButton("📥 3. MP3 audio fayl yuborish (Botga tashlang)", callback_data="ask_upload_audio"),
        types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start")
    )
    user_id = message.from_user.id
    lang = get_user_language(user_id) or "uz"
    if lang == "ru":
        text = (
            f"{HEADER_BANNER}\n\n"
            f"🎛 <b>AI СОЗДАНИЕ МИНУСА И УДАЛЕНИЕ ВОКАЛА (MVSEP)!</b> 🎼\n\n"
            f"В этом разделе вы можете из любой песни:\n"
            f"• 🎹 <b>Создать чистый инструментальный минус</b>\n"
            f"• 🎤 <b>Удалить бэк-вокал</b>\n"
            f"• 🗣 <b>Извлечь только голос исполнителя (Acappella)</b>\n\n"
            f"👇 <b>Выберите способ или отправьте MP3 файл в чат:</b>"
        )
    elif lang == "en":
        text = (
            f"{HEADER_BANNER}\n\n"
            f"🎛 <b>AI VOCAL REMOVER & INSTRUMENTAL MAKER (MVSEP)!</b> 🎼\n\n"
            f"From any song you can:\n"
            f"• 🎹 <b>Create a clean instrumental backing track</b>\n"
            f"• 🎤 <b>Remove background vocals</b>\n"
            f"• 🗣 <b>Extract vocal stem only (Acappella)</b>\n\n"
            f"👇 <b>Select a method below or send an MP3 audio file:</b>"
        )
    else:
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
@bot.message_handler(func=lambda m: m.text in [
    "🧠 Gemini AI (Savol-Javob)", "🧠 Gemini AI (Вопрос-Ответ)", "🧠 Gemini AI (Q&A)", "/ai"
])
def handle_ai_section(message):
    user_id = message.from_user.id
    set_user_state(user_id, "ai_mode")
    lang = get_user_language(user_id) or "uz"
    text = MESSAGES.get(lang, MESSAGES["uz"])["ai_prompt"]
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard(user_id))

# 5. 🎨 Tiniq Rasm Chizish (HD)
@bot.message_handler(func=lambda m: m.text in [
    "🎨 Tiniq Rasm Chizish (HD)", "🎨 Рисование в HD", "🎨 HD Image Generator", "/rasm", "/image"
])
def handle_paint_section(message):
    user_id = message.from_user.id
    set_user_state(user_id, "waiting_image_prompt")
    lang = get_user_language(user_id) or "uz"
    text = MESSAGES.get(lang, MESSAGES["uz"])["paint_prompt"]
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard(user_id))

# 6. 🎤 San'atkorlar ro'yxati
@bot.message_handler(func=lambda m: m.text in [
    "🎤 San'atkorlar ro'yxati", "🎤 Список артистов", "🎤 Popular Artists"
])
def handle_artists_section(message):
    user_id = message.from_user.id
    lang = get_user_language(user_id) or "uz"
    markup = types.InlineKeyboardMarkup(row_width=2)
    artists = [
        "Jaloliddin Ahmadaliyev", "Yulduz Usmonova", "Ozodbek Nazarbekov",
        "Shohruxxon", "Doxxim", "Munisa Rizayeva", "Hamdam Sobirov", "Sherali Jo'rayev"
    ]
    buttons = [types.InlineKeyboardButton(f"🎤 {art}", callback_data=f"search_art_{art[:20]}") for art in artists]
    markup.add(*buttons)
    markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
    prompt = {
        "uz": "🎤 <b>Mashhur san'atkorlar ro'yxati:</b>\nBirortasini tanlang, bot uning sara qo'shiq va minuslarini internetdan topib beradi:",
        "ru": "🎤 <b>Популярные артисты:</b>\nВыберите артиста, бот найдет лучшие песни и минусовки:",
        "en": "🎤 <b>Popular Artists:</b>\nSelect an artist to explore songs and instrumentals:"
    }.get(lang, "🎤 <b>San'atkorlar ro'yxati:</b>")
    bot.send_message(message.chat.id, prompt, reply_markup=markup)

# 7. ⭐️ Eng Sara Minuslar
@bot.message_handler(func=lambda m: m.text in [
    "⭐️ Eng Sara Minuslar", "⭐️ Лучшие минусовки", "⭐️ Best Instrumentals"
])
def handle_top_minus_btn(message):
    user_id = message.from_user.id
    lang = get_user_language(user_id) or "uz"
    smsg = bot.send_message(message.chat.id, "⚡️ <i>Sara minuslar qidirilmoqda...</i>")
    results = search_online_music("Uzbekcha eng sara minuslar fonogramma", limit=5)
    if results:
        markup = types.InlineKeyboardMarkup()
        for idx, r in enumerate(results, 1):
            k = str(uuid.uuid4())[:8]
            download_cache[k] = {'url': r['webpage_url'], 'title': r['title']}
            markup.add(types.InlineKeyboardButton(f"⭐️ {idx}. {r['title'][:32]}{r['duration_str']}", callback_data=f"dl_{k}"))
        markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
        out = {
            "uz": "⭐️ <b>Eng sara minus qo'shiqlar:</b>\nBirortasini bosing, darhol MP3 formatda yuklab beradi:",
            "ru": "⭐️ <b>Лучшие минусовки:</b>\nНажмите на кнопку, чтобы скачать MP3:",
            "en": "⭐️ <b>Top Instrumentals:</b>\nClick to download MP3 directly:"
        }.get(lang, "⭐️ <b>Eng sara minus qo'shiqlar:</b>")
        bot.edit_message_text(out, message.chat.id, smsg.message_id, reply_markup=markup)
    else:
        bot.edit_message_text("Kechirasiz, yuklanmadi. Qaytadan urinib ko'ring.", message.chat.id, smsg.message_id)

# 8. 🗣 Odamday Gapirib Berish
@bot.message_handler(func=lambda m: m.text in [
    "🗣 Odamday Gapirib Berish", "🗣 Озвучка текста голосом", "🗣 Text-to-Speech", "/speak", "/voice"
])
def handle_speech_assistant(message):
    user_id = message.from_user.id
    set_user_state(user_id, "waiting_text_to_speak")
    lang = get_user_language(user_id) or "uz"
    text = MESSAGES.get(lang, MESSAGES["uz"])["tts_prompt"]
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard(user_id))

# 9. 🔍 Telegram Music Botlari
@bot.message_handler(func=lambda m: m.text in [
    "🔍 Telegram Music Botlari", "🔍 Музыкальные боты", "🔍 Telegram Music Bots"
])
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
@bot.message_handler(func=lambda m: m.text in [
    "🔄 Yangi suhbat", "🔄 Новый диалог", "🔄 New Chat", "/clear"
])
def handle_clear(message):
    user_id = message.from_user.id
    user_history.pop(user_id, None)
    set_user_state(user_id, None)
    lang = get_user_language(user_id) or "uz"
    bot.send_message(message.chat.id, MESSAGES.get(lang, MESSAGES["uz"])["clear_chat"], reply_markup=get_main_keyboard(user_id))

# 11. 👑 Mualliflar haqida
@bot.message_handler(func=lambda m: m.text in [
    "👑 Mualliflar haqida", "👑 Об авторах", "👑 About Authors"
])
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
@bot.message_handler(func=lambda m: m.text in [
    "📊 Statistika", "📊 Статистика", "📊 Statistics"
])
def handle_stats_btn(message):
    st = get_stats()
    text = (
        f"{HEADER_BANNER}\n\n"
        f"📊 <b>BOT KO'RSATKICHLARI:</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{st['users']}</b> ta\n"
        f"💬 Berilgan savollar: <b>{st['messages']}</b> ta\n"
        f"🎵 Musiqa qidiruv tezligi: <b>0.8 soniya (Tezkor)</b>\n"
        f"🗣 Ovoz tizimi: <b>Microsoft Neural Speech (uz/ru/en)</b>\n"
        f"🧠 Sun'iy intellekt: <b>Google Gemini 2.0 / 1.5 Flash</b>\n"
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
    first_name = call.from_user.first_name or "Do'stim"
    
    if data.startswith("set_lang_"):
        chosen_lang = data.split("_")[-1]
        set_user_language(user_id, chosen_lang)
        confirm_text = {
            "uz": "🇺🇿 O'zbek tili tanlandi!",
            "ru": "🇷🇺 Выбран русский язык!",
            "en": "🇬🇧 English selected!"
        }.get(chosen_lang, "🇺🇿 O'zbek tili tanlandi!")
        bot.answer_callback_query(call.id, confirm_text)
        send_main_welcome(chat_id, user_id, first_name, chosen_lang)
        return

    elif data == "btn_choose_lang":
        bot.answer_callback_query(call.id)
        bot.send_message(
            chat_id,
            f"{HEADER_BANNER}\n\n"
            f"🌐 <b>Iltimos, muloqot tilini tanlang:</b>\n"
            f"🇷🇺 Пожалуйста, выберите язык общения:\n"
            f"🇬🇧 Please select your language:",
            reply_markup=get_language_keyboard()
        )
        return

    elif data == "cmd_start":
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
        text_to_speak = voice_cache.get(cid)
        user_lang = get_user_language(user_id) or "uz"
        if not text_to_speak:
            expired_txt = "Xabar eskirgan." if user_lang == "uz" else "Сообщение устарело." if user_lang == "ru" else "Message expired."
            bot.answer_callback_query(call.id, expired_txt, show_alert=True)
            return
        prep_txt = "🗣 Ovoz tayyorlanmoqda..." if user_lang == "uz" else "🗣 Подготовка голоса..." if user_lang == "ru" else "🗣 Generating voice..."
        bot.answer_callback_query(call.id, prep_txt)
        bot.send_chat_action(chat_id, "record_voice")
        caption_txt = "🎙 <i>Odamdek gapirib berilgan ovozli xabar</i>" if user_lang == "uz" else "🎙 <i>Озвученное сообщение</i>" if user_lang == "ru" else "🎙 <i>Voice message</i>"
        threading.Thread(
            target=send_voice_message,
            args=(chat_id, text_to_speak, caption_txt, user_lang)
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
        
    music_keywords = ["minus", "qo'shiq", "qoshiq", "mp3", "musiqa", "trek", "fonogramma", "karaoke", "klip", "audio", "remix", "песня", "минусовка", "музыка", "song", "track"]
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
    lang = get_user_language(user_id) or "uz"

    # 1. Matnni ovozga aylantirish bo'limi bo'lsa
    if state == "waiting_text_to_speak":
        set_user_state(user_id, None)
        bot.send_chat_action(message.chat.id, "record_voice")
        caption_txt = "🎙 <i>Odamdek gapirib berilgan ovozli xabar</i>" if lang == "uz" else "🎙 <i>Озвученное сообщение</i>" if lang == "ru" else "🎙 <i>Voice message</i>"
        threading.Thread(
            target=send_voice_message,
            args=(message.chat.id, text, f"{HEADER_BANNER}\n\n{caption_txt}", lang)
        ).start()
        return

    # 2. Rasm chizish so'rovi bo'lsa
    if state == "waiting_image_prompt" or text.lower().startswith(("rasm chiz", "rasm yarat", "chizib ber", "/rasm", "/image", "нарисуй", "draw")):
        set_user_state(user_id, None)
        prompt = text
        for p in ["rasm chiz", "rasm yarat", "chizib ber", "/rasm", "/image", "нарисуй", "draw", ":"]:
            if prompt.lower().startswith(p):
                prompt = prompt[len(p):].strip()
        if not prompt:
            prompt = "chiroyli musiqiy san'at asari"
            
        bot.send_chat_action(message.chat.id, "upload_photo")
        wait_img_txt = "🎨 <i>O'ta tiniq HD rasm chizilmoqda, bir necha soniya kuting...</i>" if lang == "uz" else "🎨 <i>Рисуем HD картинку, подождите несколько секунд...</i>" if lang == "ru" else "🎨 <i>Generating HD image, please wait...</i>"
        smsg = bot.send_message(message.chat.id, wait_img_txt)
        try:
            url = generate_hd_image_url(prompt)
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
            ready_caption = f"{HEADER_BANNER}\n\n🎨 <b>Rasm tayyor (HD / 8K)!</b>\n\n📝 <i>{prompt}</i>\n\n🤖 @ElbekStudiyaMinusbot"
            bot.send_photo(
                message.chat.id,
                photo=url,
                caption=ready_caption,
                reply_markup=markup
            )
            bot.delete_message(message.chat.id, smsg.message_id)
        except Exception as e:
            bot.edit_message_text(f"Rasm yaratish xatosi: {e}", message.chat.id, smsg.message_id)
        return

    # 3. Qo'shiq yoki Minus qidiruvi bo'lsa (0.8 soniyada tezkor natija!)
    lower_text = text.lower()
    is_minus_search = (state == "waiting_minus_search") or ("minus" in lower_text) or ("минус" in lower_text)
    is_song_search = (
        (state in ["waiting_song_original", "waiting_minus_search"]) or
        is_likely_music_query(text)
    )
    
    if is_song_search and state != "ai_mode":
        set_user_state(user_id, None)
        query = text
        for p in ["qo'shiq", "qoshiq", "musiqa", "minus", "песня", "минус", "song", ":"]:
            if query.lower().startswith(p):
                query = query[len(p):].strip()
        if not query:
            query = text

        if is_minus_search and "minus" not in query.lower() and "минус" not in query.lower():
            search_query = f"{query} minus"
        else:
            search_query = query

        search_status = f"🔍 <i>«{query}» qidirilmoqda...</i>" if lang == "uz" else f"🔍 <i>Идет поиск «{query}»...</i>" if lang == "ru" else f"🔍 <i>Searching «{query}»...</i>"
        smsg = bot.send_message(message.chat.id, search_status)
        
        # 0.8 soniyada tezkor qidiruv
        results = search_online_music(search_query, limit=5)
        yt_search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(search_query)}"
        qkey = str(uuid.uuid4())[:8]
        query_cache[qkey] = query
            
        if results:
            markup = types.InlineKeyboardMarkup(row_width=1)
            out_title = f"{HEADER_BANNER}\n\n🎵 <b>«{query}» bo'yicha topilgan sara qo'shiqlar:</b>\n\n🎧 <b>Tugmani bosing:</b> MP3 yuklab oling yoki YouTube'da tomosha qiling:\n" if lang == "uz" else f"{HEADER_BANNER}\n\n🎵 <b>Найденные треки по запросу «{query}»:</b>\n\n🎧 <b>Нажмите кнопку:</b> Скачайте MP3 или откройте на YouTube:\n" if lang == "ru" else f"{HEADER_BANNER}\n\n🎵 <b>Top tracks found for «{query}»:</b>\n\n🎧 <b>Click below:</b> Download MP3 or open on YouTube:\n"
            for idx, r in enumerate(results, 1):
                cache_key = str(uuid.uuid4())[:8]
                download_cache[cache_key] = {'url': r['webpage_url'], 'title': r['title']}
                btn_dl = f"📥 MP3: {r['title'][:30]}{r['duration_str']}"
                btn_yt = f"▶️ {idx}. YouTube"
                markup.add(
                    types.InlineKeyboardButton(btn_dl, callback_data=f"dl_{cache_key}"),
                    types.InlineKeyboardButton(btn_yt, url=r['webpage_url'])
                )
                
            yt_btn_txt = f"🌐 YouTube'dan to'liq: «{query[:25]}»"
            ai_btn_txt = "🧠 Buni savol deb tushun (Gemini AI)" if lang == "uz" else "🧠 Спросить у Gemini AI" if lang == "ru" else "🧠 Ask Gemini AI"
            markup.add(types.InlineKeyboardButton(yt_btn_txt, url=yt_search_url))
            markup.add(types.InlineKeyboardButton(ai_btn_txt, callback_data=f"force_ai_{qkey}"))
            markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
            
            bot.edit_message_text(out_title, message.chat.id, smsg.message_id, reply_markup=markup)
            return
        else:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(f"🌐 YouTube'da qidirish: «{query}»", url=yt_search_url))
            markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
            out_not_found = (
                f"{HEADER_BANNER}\n\n"
                f"😔 <b>Kechirasiz, «{query}» bo'yicha to'g'ridan-to'g'ri musiqa topilmadi.</b>\n\n"
                f"Lekin siz uni YouTube orqali qidirishingiz mumkin:"
            )
            bot.edit_message_text(out_not_found, message.chat.id, smsg.message_id, reply_markup=markup)
            return

    # 4. Gemini AI Savol-Javob (Tezkor va ko'p tilli)
    p_clean = text.strip().lower()
    fast_greeting = None
    if p_clean in ["salom", "assalom", "assalomu alaykum", "assalomu aleykum", "salom alaykum", "salomaleykum"]:
        fast_greeting = GREETINGS_REPLIES.get(lang, GREETINGS_REPLIES["uz"])["greeting"]
    elif p_clean in ["privet", "hello", "hi", "здравствуйте", "привет", "добрый день"]:
        fast_greeting = GREETINGS_REPLIES.get(lang, GREETINGS_REPLIES["uz"])["greeting"]
    elif any(p_clean == g for g in ["qandaysiz", "qalesiz", "yaxshimisiz", "ishlar qalay", "ahvolingiz qanday", "как дела", "how are you"]):
        fast_greeting = GREETINGS_REPLIES.get(lang, GREETINGS_REPLIES["uz"])["how_are_you"]
    elif any(p_clean == g for g in ["rahmat", "katta rahmat", "raxmat", "tashakkur", "spasibo", "спасибо", "thanks", "thank you", "sog' bo'ling"]):
        fast_greeting = GREETINGS_REPLIES.get(lang, GREETINGS_REPLIES["uz"])["thanks"]
    elif any(p_clean == g for g in ["sen kimsan", "isming nima", "kim bu", "кто ты", "who are you", "nima qila olasan", "haqingda ayt"]):
        fast_greeting = GREETINGS_REPLIES.get(lang, GREETINGS_REPLIES["uz"])["who_are_you"]

    if fast_greeting:
        cid = str(uuid.uuid4())[:8]
        voice_cache[cid] = fast_greeting
        markup = types.InlineKeyboardMarkup()
        voice_btn_txt = "🗣 Odamday gapirib ber (Ovoz)" if lang == "uz" else "🗣 Озвучить голосом" if lang == "ru" else "🗣 Read with Voice"
        markup.add(types.InlineKeyboardButton(voice_btn_txt, callback_data=f"spk_{cid}"))
        markup.add(types.InlineKeyboardButton("🚀 Bosh Menyu / Bo'limlar (/start)", callback_data="cmd_start"))
        bot.send_message(message.chat.id, f"{HEADER_BANNER}\n\n{fast_greeting}", reply_markup=markup)
        return

    # Murakkab savol bo'lsa: darhol javob tayyorlanmoqda deb yuboriladi
    thinking_txt = "⚡️ <i>Javob tayyorlanmoqda...</i>" if lang == "uz" else "⚡️ <i>Идет генерация ответа...</i>" if lang == "ru" else "⚡️ <i>Generating response...</i>"
    smsg = bot.send_message(message.chat.id, thinking_txt)
    
    def process_ai():
        answer = ask_gemini(user_id, text)
        cid = str(uuid.uuid4())[:8]
        voice_cache[cid] = answer
        if len(voice_cache) > 200:
            voice_cache.clear()
            
        markup = types.InlineKeyboardMarkup()
        voice_btn_txt = "🗣 Odamday gapirib ber (Ovoz)" if lang == "uz" else "🗣 Озвучить голосом" if lang == "ru" else "🗣 Read with Voice"
        markup.add(types.InlineKeyboardButton(voice_btn_txt, callback_data=f"spk_{cid}"))
        markup.add(types.InlineKeyboardButton(f"🎵 «{text[:20]}»", switch_inline_query_current_chat=f"{text}"))
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
                self.wfile.write(b"Elbek Studiya Bot 24/7 Server Faol (v3.0 MultiLang Active)!")
            def log_message(self, format, *args):
                pass
        with socketserver.TCPServer(("", port), HealthHandler) as httpd:
            httpd.serve_forever()
    except Exception as e:
        pass

def keep_awake_ping():
    time.sleep(30)
    url = "https://elbek-studiya-minus-bot.onrender.com"
    while True:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'ElbekBotKeepAlive/1.0'})
            urllib.request.urlopen(req, timeout=15)
        except Exception:
            pass
        time.sleep(600)  # Har 10 minutda 1 marta ping yuborib serverni 24/7 uyg'oq tutadi

if __name__ == '__main__':
    init_db()
    setup_bot_commands()
    threading.Thread(target=run_health_server, daemon=True).start()
    threading.Thread(target=keep_awake_ping, daemon=True).start()
    print("=" * 65)
    print("🚀 ELBEK STUDIYA & MARUFJON MAXRAMOV & JAVLONBEK RUZIYEV BOT FAOL!")
    print("🤖 Telegram: @ElbekStudiyaMinusbot")
    print("⚡️ Musiqa qidiruv tezligi: 0.8 soniya (Tezkor)")
    print("⚡️ Salomlashish va oddiy gaplar: 0.01 soniya")
    print("🌐 Server rejimi: 24/7 Bulut va Lokal tayyor")
    print("=" * 65)
    
    try:
        bot.remove_webhook()
        time.sleep(1)
    except Exception:
        pass

    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            print(f"Polling xatosi: {e}")
            time.sleep(1)
