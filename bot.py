#!/usr/bin/env python3
# ==========================================
#   بوت تحميل الفيديوهات - Python
#   Owner ID: 7323316462
# ==========================================

import os
import json
import asyncio
import logging
import re
import uuid
import aiohttp
import yt_dlp
from pathlib import Path
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.error import TelegramError

# ──────────────────────────────────────────
#  إعدادات البوت
# ──────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID  = 7323316462
DB_FILE   = "database.json"
TEMP_DIR  = "downloads"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
#  قاعدة البيانات (JSON)
# ──────────────────────────────────────────
def load_db() -> dict:
    if not Path(DB_FILE).exists():
        return {
            "users": {},
            "channels": [],
            "start_message": (
                "مرحباً بك! 👋\n\n"
                "أرسل لي رابط أي فيديو من يوتيوب، تيك توك، انستغرام، تويتر، فيسبوك وغيرها "
                "وسأقوم بتحميله لك فوراً 🎬\n\n"
                "في المجموعات: اكتب <b>يوت [اسم الأغنية]</b> لتحميل صوت من يوتيوب 🎵"
            ),
            "states": {}
        }
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(db: dict):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def register_user(db: dict, user_id: int, username: str):
    uid = str(user_id)
    if uid not in db["users"]:
        db["users"][uid] = {"id": user_id, "username": username or ""}
        save_db(db)

def get_all_users(db: dict) -> list:
    return list(db["users"].values())

def get_state(db: dict, user_id: int):
    return db.get("states", {}).get(str(user_id))

def set_state(db: dict, user_id: int, state: dict):
    if "states" not in db:
        db["states"] = {}
    db["states"][str(user_id)] = state
    save_db(db)

def clear_state(db: dict, user_id: int):
    if "states" in db and str(user_id) in db["states"]:
        del db["states"][str(user_id)]
        save_db(db)

# ──────────────────────────────────────────
#  مجلد التحميل المؤقت
# ──────────────────────────────────────────
Path(TEMP_DIR).mkdir(exist_ok=True)

# ──────────────────────────────────────────
#  كوكيز انستغرام وفيسبوك (اختياري) — تحل حظر الوصول بدون تسجيل دخول
#  من سيرفرات مثل Replit/GitHub
# ──────────────────────────────────────────
INSTAGRAM_COOKIES_FILE = "instagram_cookies.txt"
FACEBOOK_COOKIES_FILE  = "facebook_cookies.txt"
YOUTUBE_COOKIES_FILE   = "youtube_cookies.txt"

def _write_cookies_from_env(env_name: str, out_file: str, label: str):
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(raw)
    logger.info(f"✅ تم تفعيل كوكيز {label}")

_write_cookies_from_env("INSTAGRAM_COOKIES", INSTAGRAM_COOKIES_FILE, "انستغرام")
_write_cookies_from_env("FACEBOOK_COOKIES",  FACEBOOK_COOKIES_FILE,  "فيسبوك")
_write_cookies_from_env("YOUTUBE_COOKIES",   YOUTUBE_COOKIES_FILE,   "يوتيوب")

# ──────────────────────────────────────────
#  رفع الملفات الكبيرة (اختياري) — Pyrogram عبر MTProto
#  Bot API القياسي محدود بـ 50MB. بوضع API_ID/API_HASH يرتفع الحد إلى ~2000MB
# ──────────────────────────────────────────
API_ID = os.environ.get("API_ID", "").strip()
API_HASH = os.environ.get("API_HASH", "").strip()
LARGE_UPLOAD_ENABLED = bool(API_ID and API_HASH and BOT_TOKEN)
MAX_FILE_MB = 2000 if LARGE_UPLOAD_ENABLED else 50
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024
BOT_API_HTTP_LIMIT_BYTES = 50 * 1024 * 1024  # حد إرسال Bot API HTTP القياسي

_pyro_client = None
if LARGE_UPLOAD_ENABLED:
    try:
        from pyrogram import Client as _PyroClient
        _pyro_client = _PyroClient(
            "bot_uploader",
            api_id=int(API_ID),
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            in_memory=True,
        )
        logger.info("✅ تم تفعيل الرفع الكبير عبر Pyrogram (حتى 2000MB)")
    except Exception as e:
        logger.warning(f"⚠️ فشل تهيئة Pyrogram، سيبقى الحد 50MB: {e}")
        _pyro_client = None
        LARGE_UPLOAD_ENABLED = False
        MAX_FILE_MB = 50
        MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024

# ──────────────────────────────────────────
#  قنوات الاشتراك الإجباري الثابتة (اختياري) — عبر متغير بيئة FORCE_SUB_CHANNELS
#  يقبل عدة قنوات مفصولة بفاصلة أو سطر جديد: @username أو -100xxxxxxxxxx
#  البوت يجب أن يكون مشرفاً في كل قناة. لإزالة قناة: احذفها من قيمة السر فقط.
# ──────────────────────────────────────────
def _parse_force_sub_refs(raw: str) -> list:
    if not raw:
        return []
    parts = [p.strip() for chunk in raw.split(",") for p in chunk.split("\n")]
    refs = []
    for p in parts:
        if not p:
            continue
        if p.startswith("https://t.me/"):
            p = "@" + p.replace("https://t.me/", "").split("/")[0]
        elif p.startswith("t.me/"):
            p = "@" + p.replace("t.me/", "").split("/")[0]
        try:
            refs.append(int(p))
        except ValueError:
            refs.append(p if p.startswith("@") else f"@{p}")
    return refs

FORCE_SUB_CHANNEL_REFS = _parse_force_sub_refs(os.environ.get("FORCE_SUB_CHANNELS", ""))
_force_sub_cache: dict = {}

async def get_force_sub_channels(context: ContextTypes.DEFAULT_TYPE) -> list:
    """يحل القنوات الثابتة (من السر) إلى عنوان/رابط، ويخزّنها مؤقتاً في الذاكرة."""
    resolved = []
    for ref in FORCE_SUB_CHANNEL_REFS:
        cached = _force_sub_cache.get(ref)
        if cached is None:
            try:
                chat = await context.bot.get_chat(chat_id=ref)
                link = None
                try:
                    link = await context.bot.export_chat_invite_link(chat.id)
                except Exception:
                    if chat.username:
                        link = f"https://t.me/{chat.username}"
                cached = {"id": chat.id, "title": chat.title or chat.username or str(chat.id), "link": link}
            except TelegramError as e:
                logger.warning(f"⚠️ تعذّر الوصول لقناة الاشتراك الإجباري {ref}: {e}")
                continue
            _force_sub_cache[ref] = cached
        resolved.append(cached)
    return resolved

async def get_effective_channels(context: ContextTypes.DEFAULT_TYPE, db: dict) -> list:
    """يدمج قنوات السر الثابتة مع القنوات المضافة من لوحة التحكم، بدون تكرار."""
    fixed = await get_force_sub_channels(context)
    combined = list(fixed)
    fixed_ids = {c["id"] for c in fixed}
    for ch in db["channels"]:
        if ch["id"] not in fixed_ids:
            combined.append(ch)
    return combined

# ──────────────────────────────────────────
#  أدوات مساعدة
# ──────────────────────────────────────────
def is_supported(url: str) -> bool:
    return url.lower().startswith(("http://", "https://"))

def extract_url(text: str):
    match = re.search(r"https?://[^\s]+", text)
    return match.group(0) if match else None

def _clean_url(url: str) -> str:
    """أزل معاملات التتبع غير الضرورية مع الحفاظ على بنية الرابط"""
    # إنستاغرام: أبقِ المسار فقط
    if "instagram.com" in url.lower():
        url = url.split("?")[0].rstrip("/") + "/"
    return url

def _is_tiktok(url: str) -> bool:
    u = url.lower()
    return any(d in u for d in ("tiktok.com", "vt.tiktok.com", "vm.tiktok.com"))

DOWNLOAD_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

async def _download_to_disk(session: aiohttp.ClientSession, dl_url: str, safe_name: str) -> dict:
    """يحمّل ملفاً من رابط مباشر إلى القرص مع حد أقصى MAX_FILE_MB."""
    out_path = os.path.join(TEMP_DIR, f"{uuid.uuid4().hex[:8]}_{safe_name}")
    size_error = f"حجم الفيديو يتجاوز {MAX_FILE_MB}MB المسموح به ❌"
    try:
        async with session.get(
            dl_url,
            headers={"User-Agent": DOWNLOAD_UA},
            timeout=aiohttp.ClientTimeout(total=300),
        ) as resp:
            if resp.status != 200:
                return {"success": False, "error": f"خطأ في تحميل الملف ({resp.status})"}

            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_FILE_BYTES:
                return {"success": False, "error": size_error}

            size = 0
            with open(out_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(1024 * 64):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        f.close()
                        os.remove(out_path)
                        return {"success": False, "error": size_error}
                    f.write(chunk)
        return {"success": True, "path": out_path}
    except asyncio.TimeoutError:
        return {"success": False, "error": "انتهت مهلة التحميل ❌"}
    except Exception as e:
        return {"success": False, "error": str(e)[:100]}

# ──────────────────────────────────────────
#  tikwm.com — محرك مخصّص لتيك توك (بدون علامة مائية)
#  API عام موثّق ولا يتطلب توقيعاً أو تسجيل دخول
# ──────────────────────────────────────────
TIKWM_API = "https://www.tikwm.com/api/"
TIKWM_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": DOWNLOAD_UA,
}

async def _tikwm_download(url: str) -> dict:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                TIKWM_API,
                data={"url": url, "hd": "1"},
                headers=TIKWM_HEADERS,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    return {"success": False, "error": f"tikwm HTTP {resp.status}"}
                data = await resp.json()

            if data.get("code") != 0:
                return {"success": False, "error": data.get("msg", "tikwm: فشل غير معروف")}

            info = data.get("data", {}) or {}
            dl_url = info.get("hdplay") or info.get("play") or info.get("wmplay")
            if not dl_url:
                return {"success": False, "error": "tikwm: لم يتم العثور على رابط الفيديو"}

            raw_title = (info.get("title") or "video").strip() or "video"
            safe_name = re.sub(r"[^\w.\-]", "_", raw_title)[:80] + ".mp4"

            result = await _download_to_disk(session, dl_url, safe_name)
            if not result["success"]:
                return result

            return {"success": True, "path": result["path"], "title": raw_title}

    except asyncio.TimeoutError:
        return {"success": False, "error": "tikwm: انتهت المهلة"}
    except Exception as e:
        return {"success": False, "error": str(e)[:100]}

# ──────────────────────────────────────────
#  yt-dlp — المحرك العام لباقي المنصات ومحرك احتياطي لتيك توك
# ──────────────────────────────────────────
def _is_facebook(url: str) -> bool:
    u = url.lower()
    return any(d in u for d in ("facebook.com", "fb.watch"))

def _is_youtube(url: str) -> bool:
    u = url.lower()
    return any(d in u for d in ("youtube.com", "youtu.be"))

def _cookie_file_for(url: str) -> str:
    if _is_instagram(url) and os.path.exists(INSTAGRAM_COOKIES_FILE):
        return INSTAGRAM_COOKIES_FILE
    if _is_facebook(url) and os.path.exists(FACEBOOK_COOKIES_FILE):
        return FACEBOOK_COOKIES_FILE
    if _is_youtube(url) and os.path.exists(YOUTUBE_COOKIES_FILE):
        return YOUTUBE_COOKIES_FILE
    return None

def _build_ydl_opts(url: str, extra: dict = {}) -> dict:
    base = {
        "outtmpl": os.path.join(TEMP_DIR, "%(title).80s.%(ext)s"),
        "format": (
            "bestvideo[height<=720]+bestaudio"
            "/bestvideo[height<=720]+bestaudio[ext=m4a]"
            "/best[height<=720]/best"
        ),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "max_filesize": MAX_FILE_BYTES,
        "socket_timeout": 30,
    }
    cookie_file = _cookie_file_for(url)
    if cookie_file:
        base["cookiefile"] = cookie_file
    base.update(extra)
    return base

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

def _run_ydl(url: str, opts: dict):
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info is None:
            return None

        # منشور يحتوي عدة عناصر (صور/فيديوهات متعددة) — نأخذ أول عنصر فقط
        if info.get("_type") in ("playlist", "multi_video") and info.get("entries"):
            info = next((e for e in info["entries"] if e), info)

        title = info.get("title", "منشور")
        filename = ydl.prepare_filename(info)
        if not os.path.exists(filename):
            # جرّب امتداد الفيديو الافتراضي
            alt = filename.rsplit(".", 1)[0] + ".mp4"
            if os.path.exists(alt):
                filename = alt
        if not os.path.exists(filename):
            # جرّب امتداد الصورة الحقيقي إن وُجد
            ext = (info.get("ext") or "").lower()
            if ext:
                alt = filename.rsplit(".", 1)[0] + "." + ext
                if os.path.exists(alt):
                    filename = alt
        if not os.path.exists(filename):
            candidates = sorted(
                Path(TEMP_DIR).glob("*"),
                key=os.path.getmtime, reverse=True
            )
            candidates = [str(p) for p in candidates if p.is_file()]
            if candidates:
                filename = candidates[0]

        is_image = filename.lower().endswith(IMAGE_EXTS)
        return {"title": title, "path": filename, "is_image": is_image}

def _ydl_attempts(url: str) -> list:
    u = url.lower()
    if any(d in u for d in ["youtube.com", "youtu.be"]):
        return [
            # mweb و tv_embedded: الأكثر موثوقية حالياً مع يوتيوب
            _build_ydl_opts(url, {"extractor_args": {"youtube": {"player_client": ["mweb"]}}}),
            _build_ydl_opts(url, {"extractor_args": {"youtube": {"player_client": ["tv_embedded"]}}}),
            _build_ydl_opts(url, {"extractor_args": {"youtube": {"player_client": ["ios"]}}}),
            _build_ydl_opts(url, {"extractor_args": {"youtube": {"player_client": ["android"]}}}),
            # احتياطي أخير: أي صيغة متاحة بدون قيود
            _build_ydl_opts(url, {
                "format": "best",
                "extractor_args": {"youtube": {"player_client": ["mweb"]}},
            }),
        ]
    return [
        _build_ydl_opts(url),
        _build_ydl_opts(url, {"format": "best[ext=mp4]/best"}),
        _build_ydl_opts(url, {"format": "best"}),
    ]

def _friendly_ydl_error(err: str) -> str:
    e = err.lower()
    if "file is larger than max-filesize" in e:
        return "__SIZE__"
    if "login" in e or "sign in" in e or "log in" in e:
        return "المنصة تطلب تسجيل دخول ❌"
    if "private" in e:
        return "الفيديو/الحساب خاص ❌"
    if "unavailable" in e or "not found" in e:
        return "الفيديو غير متاح أو محذوف ❌"
    if "geo" in e or "not available in your country" in e:
        return "الفيديو غير متاح في منطقتنا ❌"
    if "copyright" in e:
        return "الفيديو محمي بحقوق الملكية ❌"
    return ""

def _is_instagram(url: str) -> bool:
    return "instagram.com" in url.lower()

def _run_ydl_image_info(url: str) -> dict:
    """يستخرج بيانات المنشور حتى لو لم توجد صيغ فيديو (منشور صورة) — انستغرام/فيسبوك."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignore_no_formats_error": True,
        "noplaylist": True,
    }
    cookie_file = _cookie_file_for(url)
    if cookie_file:
        opts["cookiefile"] = cookie_file
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info is None:
            return None
        if info.get("_type") in ("playlist", "multi_video") and info.get("entries"):
            info = next((e for e in info["entries"] if e), info)
        return info

async def _image_post_download(url: str) -> dict:
    """تحميل منشور صورة (انستغرام/فيسبوك) مباشرة عبر رابط الصورة (لا يدعمه yt-dlp للتنزيل)."""
    loop = asyncio.get_event_loop()
    try:
        info = await loop.run_in_executor(None, _run_ydl_image_info, url)
    except Exception as e:
        return {"success": False, "error": str(e)[:150]}

    if not info:
        return {"success": False, "error": "تعذّر استخراج بيانات المنشور ❌"}

    thumbs = info.get("thumbnails") or []
    if not thumbs:
        return {"success": False, "error": "لم يتم العثور على صورة في هذا المنشور ❌"}

    best = max(thumbs, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))
    img_url = best.get("url")
    if not img_url:
        return {"success": False, "error": "لم يتم العثور على رابط الصورة ❌"}

    raw_title = (info.get("title") or "منشور").strip() or "منشور"
    safe_name = re.sub(r"[^\w.\-]", "_", raw_title)[:80] + ".jpg"

    async with aiohttp.ClientSession() as session:
        result = await _download_to_disk(session, img_url, safe_name)
    if not result["success"]:
        return result

    return {"success": True, "path": result["path"], "title": raw_title, "is_image": True}

async def _ytdlp_download(url: str) -> dict:
    loop = asyncio.get_event_loop()
    last_error = "فشل التحميل ❌"
    no_formats = False
    for opts in _ydl_attempts(url):
        try:
            result = await loop.run_in_executor(None, _run_ydl, url, opts)
            if result and os.path.exists(result["path"]):
                return {"success": True, **result}
        except yt_dlp.utils.DownloadError as e:
            err_str = str(e)
            if "no video formats found" in err_str.lower():
                no_formats = True
                break
            friendly = _friendly_ydl_error(err_str)
            if friendly == "__SIZE__":
                return {"success": False, "error": "حجم الفيديو يتجاوز 50MB المسموح به ❌"}
            if friendly:
                return {"success": False, "error": friendly}
            last_error = "فشل التحميل، تأكد من الرابط ❌"
        except Exception as e:
            last_error = str(e)[:150]

    # منشور صورة (لا صيغ فيديو) — انستغرام أو فيسبوك
    if no_formats and (_is_instagram(url) or _is_facebook(url)):
        return await _image_post_download(url)

    return {"success": False, "error": last_error}

# ──────────────────────────────────────────
#  يوتيوب — بحث وتحميل صوت (للمجموعات)
# ──────────────────────────────────────────
def _yt_search_sync(query: str) -> list:
    """يبحث في يوتيوب ويرجع أول 3 نتائج بدون تحميل."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extractor_args": {"youtube": {"player_client": ["mweb"]}},
    }
    if os.path.exists(YOUTUBE_COOKIES_FILE):
        opts["cookiefile"] = YOUTUBE_COOKIES_FILE
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch3:{query}", download=False)
        results = []
        for entry in (info.get("entries") or [])[:3]:
            if not entry:
                continue
            dur = entry.get("duration") or 0
            results.append({
                "id":    entry.get("id", ""),
                "title": (entry.get("title") or "بدون عنوان")[:80],
                "dur":   f"{dur//60}:{dur%60:02d}" if dur else "--:--",
            })
        return results

def _yt_audio_download_sync(video_id: str) -> dict:
    """يحمّل أفضل صوت من يوتيوب ويحوّله لـ MP3 — يجرب عدة عملاء تلقائياً."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    _audio_clients = ["mweb", "tv_embedded", "ios", "android"]
    last_error = "فشل الاستخراج"
    for client in _audio_clients:
        opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(TEMP_DIR, "%(title).60s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "max_filesize": MAX_FILE_BYTES,
            "socket_timeout": 60,
            "extractor_args": {"youtube": {"player_client": [client]}},
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }
        if os.path.exists(YOUTUBE_COOKIES_FILE):
            opts["cookiefile"] = YOUTUBE_COOKIES_FILE
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info:
                    last_error = "فشل الاستخراج"
                    continue
                title = info.get("title", "صوت")
                # بعد postprocessor يتغير الامتداد لـ mp3
                base = ydl.prepare_filename(info).rsplit(".", 1)[0]
                mp3 = base + ".mp3"
                if os.path.exists(mp3):
                    return {"success": True, "path": mp3, "title": title}
                # احتياطي: أحدث ملف في المجلد المؤقت
                candidates = sorted(Path(TEMP_DIR).glob("*"), key=os.path.getmtime, reverse=True)
                for p in candidates:
                    if p.is_file():
                        return {"success": True, "path": str(p), "title": title}
                last_error = "لم يُنشأ الملف"
        except yt_dlp.utils.DownloadError as e:
            last_error = str(e)[:150]
            continue
        except Exception as e:
            last_error = str(e)[:150]
            continue
    return {"success": False, "error": last_error}

async def _handle_yt_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    """يبحث ويرسل 3 أزرار نتائج لصاحب البحث فقط."""
    loop = asyncio.get_event_loop()
    msg = await update.message.reply_text("🔍 جاري البحث في يوتيوب...")
    try:
        results = await loop.run_in_executor(None, _yt_search_sync, query)
    except Exception as e:
        await msg.edit_text(f"❌ فشل البحث: {str(e)[:150]}")
        return
    if not results:
        await msg.edit_text("❌ لم تُعثر على نتائج.")
        return

    uid = update.effective_user.id
    buttons = []
    for r in results:
        label = f"🎵 {r['title'][:55]} [{r['dur']}]"
        # callback_data: yts:{uid}:{video_id}  — ≤ 64 حرفاً دائماً
        buttons.append([InlineKeyboardButton(label, callback_data=f"yts:{uid}:{r['id']}")])

    await msg.edit_text(
        f"🎵 نتائج البحث عن: <b>{query}</b>\n\nاختر للتحميل:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

async def _send_yt_audio(chat_id: int, file_path: str, title: str, context: ContextTypes.DEFAULT_TYPE):
    """يرسل ملف الصوت ويرجع True عند النجاح."""
    ext = Path(file_path).suffix or ".mp3"
    with open(file_path, "rb") as af:
        await context.bot.send_audio(
            chat_id=chat_id,
            audio=InputFile(af, filename=f"{title}{ext}"),
            title=title,
            caption=f"🎵 <b>{title}</b>",
            parse_mode="HTML",
        )

# ──────────────────────────────────────────
#  الدالة الرئيسية للتحميل
#  تيك توك: 1) tikwm.com  2) yt-dlp احتياطياً
#  باقي المنصات: yt-dlp مباشرة
# ──────────────────────────────────────────
async def download_video(url: str) -> dict:
    url = _clean_url(url)

    if _is_tiktok(url):
        logger.info(f"[tikwm] جرب: {url}")
        tikwm_result = await _tikwm_download(url)
        if tikwm_result["success"]:
            logger.info("[tikwm] نجح ✅")
            return tikwm_result
        logger.warning(f"[tikwm] فشل: {tikwm_result['error']} — ننتقل لـ yt-dlp")

    logger.info(f"[yt-dlp] جرب: {url}")
    ytdlp_result = await _ytdlp_download(url)
    if ytdlp_result["success"]:
        logger.info("[yt-dlp] نجح ✅")
        return ytdlp_result

    logger.warning(f"[yt-dlp] فشل: {ytdlp_result['error']}")
    return {"success": False, "error": ytdlp_result["error"]}

# ──────────────────────────────────────────
#  التحقق من الاشتراك الإجباري
# ──────────────────────────────────────────
async def check_subscription(context: ContextTypes.DEFAULT_TYPE, user_id: int, channels: list) -> dict:
    if not channels:
        return {"ok": True, "missing": []}
    missing = []
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(chat_id=ch["id"], user_id=user_id)
            if member.status in ("left", "kicked", "restricted"):
                missing.append(ch)
        except TelegramError:
            missing.append(ch)
    return {"ok": len(missing) == 0, "missing": missing}

def build_subscribe_keyboard(missing: list) -> InlineKeyboardMarkup:
    buttons = []
    for ch in missing:
        link = ch.get("link") or f"https://t.me/{str(ch['id']).replace('-100', '')}"
        buttons.append([InlineKeyboardButton(f"📢 {ch.get('title', ch['id'])}", url=link)])
    buttons.append([InlineKeyboardButton("✅ لقد اشتركت", callback_data="check_sub")])
    return InlineKeyboardMarkup(buttons)

# ──────────────────────────────────────────
#  لوحة تحكم المالك
# ──────────────────────────────────────────
def admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ تعديل رسالة الترحيب",        callback_data="admin_edit_start")],
        [InlineKeyboardButton("➕ إضافة قناة/مجموعة",           callback_data="admin_add_channel")],
        [InlineKeyboardButton("➕➕ إضافة عدة قنوات دفعة واحدة", callback_data="admin_add_multi")],
        [InlineKeyboardButton("📋 القنوات والمجموعات المضافة",  callback_data="admin_list_channels")],
        [InlineKeyboardButton("📢 إذاعة لكل المستخدمين",        callback_data="admin_broadcast")],
    ])

# ──────────────────────────────────────────
#  حل آيدي/رابط القناة
# ──────────────────────────────────────────
async def resolve_channel(context: ContextTypes.DEFAULT_TYPE, raw: str) -> dict:
    chat_id = raw.strip()
    if chat_id.startswith("https://t.me/"):
        chat_id = "@" + chat_id.replace("https://t.me/", "").split("/")[0]
    elif chat_id.startswith("t.me/"):
        chat_id = "@" + chat_id.replace("t.me/", "").split("/")[0]
    try:
        chat_id_val = int(chat_id)
    except ValueError:
        chat_id_val = chat_id
    try:
        chat = await context.bot.get_chat(chat_id=chat_id_val)
        link = None
        try:
            link = await context.bot.export_chat_invite_link(chat_id_val)
        except Exception:
            if chat.username:
                link = f"https://t.me/{chat.username}"
        return {
            "success": True,
            "id": chat.id,
            "title": chat.title or chat.username or str(chat.id),
            "link": link,
            "username": chat.username,
        }
    except TelegramError as e:
        return {"success": False, "error": str(e)}

# ──────────────────────────────────────────
#  /start
# ──────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = load_db()
    register_user(db, user.id, user.username or user.first_name or "")
    clear_state(db, user.id)
    await update.message.reply_text(db["start_message"])

# ──────────────────────────────────────────
#  /admin
# ──────────────────────────────────────────
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("❌ هذا الأمر متاح للمالك فقط.")
        return
    db = load_db()
    await update.message.reply_text(
        f"⚙️ <b>لوحة التحكم</b>\n\n"
        f"👥 المستخدمين: <b>{len(db['users'])}</b>\n"
        f"📢 القنوات المضافة: <b>{len(db['channels'])}</b>",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard()
    )

# ──────────────────────────────────────────
#  هاندلر الرسائل
# ──────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    text  = update.message.text or ""
    db    = load_db()
    register_user(db, user.id, user.username or user.first_name or "")
    state = get_state(db, user.id)

    chat     = update.effective_chat
    is_group = chat.type in ("group", "supergroup")

    # ── بحث يوتيوب بكلمة "يوت" في المجموعات فقط ──
    if is_group:
        t = text.strip()
        prefix = "يوت "
        if t.startswith(prefix) or t == "يوت":
            query = t[len(prefix):].strip()
            if not query:
                await update.message.reply_text("اكتب: يوت [اسم الأغنية أو الفيديو]")
                return
            sub = await check_subscription(context, user.id, await get_effective_channels(context, db))
            if not sub["ok"]:
                await update.message.reply_text(
                    "⚠️ يجب الاشتراك في القنوات أولاً:",
                    reply_markup=build_subscribe_keyboard(sub["missing"])
                )
                return
            await _handle_yt_search(update, context, query)
            return

    # ── رسالة الترحيب ──
    if state and state["type"] == "waiting_start_msg":
        db["start_message"] = text
        save_db(db)
        clear_state(db, user.id)
        await update.message.reply_text("✅ تم تحديث رسالة الترحيب بنجاح!")
        return

    # ── قناة واحدة ──
    if state and state["type"] == "waiting_channel":
        result = await resolve_channel(context, text)
        if not result["success"]:
            await update.message.reply_text(
                f"❌ فشل: {result['error']}\n\nتأكد من:\n"
                "• البوت مضاف كأدمن في القناة/المجموعة\n"
                "• الرابط أو الآيدي صحيح"
            )
            return
        channels = db["channels"]
        if any(c["id"] == result["id"] for c in channels):
            await update.message.reply_text("⚠️ هذه القناة/المجموعة مضافة مسبقاً.")
            clear_state(db, user.id)
            return
        channels.append({
            "id": result["id"], "title": result["title"],
            "link": result["link"], "username": result["username"],
        })
        db["channels"] = channels
        save_db(db)
        clear_state(db, user.id)
        await update.message.reply_text(
            f"✅ تمت إضافة: <b>{result['title']}</b>", parse_mode="HTML"
        )
        return

    # ── عدة قنوات ──
    if state and state["type"] == "waiting_multi_channels":
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        channels = db["channels"]
        added = failed = duplicate = 0
        for line in lines:
            result = await resolve_channel(context, line)
            if not result["success"]:
                failed += 1
                continue
            if any(c["id"] == result["id"] for c in channels):
                duplicate += 1
                continue
            channels.append({
                "id": result["id"], "title": result["title"],
                "link": result["link"], "username": result["username"],
            })
            added += 1
        db["channels"] = channels
        save_db(db)
        clear_state(db, user.id)
        await update.message.reply_text(
            f"✅ <b>نتائج الإضافة:</b>\n\n"
            f"✔️ تمت إضافة: {added}\n"
            f"⚠️ مكررة: {duplicate}\n"
            f"❌ فشل: {failed}",
            parse_mode="HTML"
        )
        return

    # ── إذاعة ──
    if state and state["type"] == "waiting_broadcast":
        clear_state(db, user.id)
        users = get_all_users(db)
        sent = failed = 0
        progress = await update.message.reply_text(f"📢 جاري الإذاعة لـ {len(users)} مستخدم...")
        for u in users:
            try:
                await context.bot.send_message(chat_id=u["id"], text=text, parse_mode="HTML")
                sent += 1
            except TelegramError:
                failed += 1
            await asyncio.sleep(0.05)
        await progress.edit_text(
            f"✅ <b>انتهت الإذاعة</b>\n\n✔️ وصلت: {sent}\n❌ فشلت: {failed}",
            parse_mode="HTML"
        )
        return

    # ── رابط الفيديو ──
    url = extract_url(text)
    if url:
        sub = await check_subscription(context, user.id, await get_effective_channels(context, db))
        if not sub["ok"]:
            await update.message.reply_text(
                "⚠️ يجب عليك الاشتراك في القنوات التالية أولاً:",
                reply_markup=build_subscribe_keyboard(sub["missing"])
            )
            return

        processing = await update.message.reply_text("⏳ جاري تحميل الفيديو...")
        result = await download_video(url)

        if not result["success"]:
            await processing.edit_text(f"❌ فشل التحميل: {result['error']}")
            return

        file_path = result["path"]
        title     = result["title"]
        is_image  = result.get("is_image", False)
        ext       = Path(file_path).suffix or (".jpg" if is_image else ".mp4")
        file_size = os.path.getsize(file_path)

        try:
            await processing.edit_text("📤 جاري الإرسال...")

            # ملف أكبر من حد Bot API HTTP (50MB) — استخدم Pyrogram (MTProto) إن كان مفعّلاً
            if file_size > BOT_API_HTTP_LIMIT_BYTES and LARGE_UPLOAD_ENABLED and _pyro_client:
                sent = await _send_large_file(update.effective_chat.id, file_path, title, is_image)
                if not sent:
                    raise TelegramError("فشل الرفع الكبير")
                await processing.delete()
            elif is_image:
                with open(file_path, "rb") as pf:
                    await update.message.reply_photo(
                        photo=InputFile(pf, filename=f"{title}{ext}"),
                        caption=f"🖼 <b>{title}</b>",
                        parse_mode="HTML",
                    )
                await processing.delete()
            else:
                with open(file_path, "rb") as vf:
                    await update.message.reply_video(
                        video=InputFile(vf, filename=f"{title}{ext}"),
                        caption=f"🎬 <b>{title}</b>",
                        parse_mode="HTML",
                        supports_streaming=True,
                    )
                await processing.delete()
        except TelegramError:
            try:
                with open(file_path, "rb") as df:
                    await update.message.reply_document(
                        document=InputFile(df, filename=f"{title}{ext}"),
                        caption=f"🎬 <b>{title}</b>",
                        parse_mode="HTML",
                    )
                await processing.delete()
            except TelegramError as e:
                await processing.edit_text(f"❌ فشل الإرسال: {str(e)[:200]}")
        finally:
            try:
                os.remove(file_path)
            except Exception:
                pass
        return

    if is_group:
        return  # في المجموعات: لا رد على رسائل عادية لا تحوي رابطاً أو "يوت"
    await update.message.reply_text(
        "أرسل لي رابط فيديو من يوتيوب، تيك توك، انستغرام، فيسبوك وغيرها وسأحمله لك! 🎬\n\n"
        "في المجموعات: اكتب <b>يوت [اسم الأغنية]</b> لتحميل الصوت 🎵",
        parse_mode="HTML",
    )

# ──────────────────────────────────────────
#  هاندلر الأزرار
# ──────────────────────────────────────────
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user  = query.from_user
    data  = query.data
    db    = load_db()

    await query.answer()

    if data == "check_sub":
        sub = await check_subscription(context, user.id, await get_effective_channels(context, db))
        if sub["ok"]:
            await query.edit_message_text("✅ شكراً! يمكنك الآن إرسال روابط الفيديوهات 🎬")
        else:
            await query.edit_message_text(
                "❌ لم تشترك في جميع القنوات بعد. يرجى الاشتراك ثم المحاولة.",
                reply_markup=build_subscribe_keyboard(sub["missing"])
            )
        return

    # ── تحميل صوت يوتيوب من نتائج البحث ──
    if data.startswith("yts:"):
        parts = data.split(":", 2)
        if len(parts) != 3:
            return
        _, requester_uid, video_id = parts
        # فقط صاحب البحث يقدر يضغط
        if str(user.id) != requester_uid:
            await query.answer("⛔ هذا البحث ليس لك!", show_alert=True)
            return
        chat_id = query.message.chat_id
        # احذف رسالة نتائج البحث
        try:
            await query.message.delete()
        except Exception:
            pass
        processing = await context.bot.send_message(chat_id=chat_id, text="⏳ جاري تحميل الصوت...")
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, _yt_audio_download_sync, video_id)
        except Exception as e:
            await processing.edit_text(f"❌ فشل التحميل: {str(e)[:200]}")
            return
        if not result["success"]:
            await processing.edit_text(f"❌ {result['error']}")
            return
        file_path = result["path"]
        title     = result["title"]
        try:
            await processing.edit_text("📤 جاري الإرسال...")
            await _send_yt_audio(chat_id, file_path, title, context)
            await processing.delete()
        except Exception as e:
            await processing.edit_text(f"❌ فشل الإرسال: {str(e)[:200]}")
        finally:
            try:
                os.remove(file_path)
            except Exception:
                pass
        return

    if user.id != OWNER_ID:
        return

    if data == "admin_edit_start":
        set_state(db, user.id, {"type": "waiting_start_msg"})
        await query.edit_message_text("✏️ أرسل الآن رسالة الترحيب الجديدة:")
        return

    if data == "admin_add_channel":
        set_state(db, user.id, {"type": "waiting_channel"})
        await query.edit_message_text(
            "📢 أرسل آيدي القناة/المجموعة أو رابطها:\n\n"
            "مثال:\n• @mychannel\n• -1001234567890\n• https://t.me/mychannel\n\n"
            "⚠️ تأكد أن البوت مضاف كأدمن في القناة/المجموعة."
        )
        return

    if data == "admin_add_multi":
        set_state(db, user.id, {"type": "waiting_multi_channels"})
        await query.edit_message_text(
            "📋 أرسل الآيديات أو الروابط سطراً بسطر:\n\n"
            "مثال:\n@channel1\n@channel2\n-1001234567890\nhttps://t.me/channel3\n\n"
            "⚠️ تأكد أن البوت مضاف كأدمن في جميع القنوات/المجموعات."
        )
        return

    if data == "admin_list_channels":
        channels = db["channels"]
        fixed = await get_force_sub_channels(context)
        if not channels and not fixed:
            await query.edit_message_text(
                "📋 لا توجد قنوات أو مجموعات مضافة.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")
                ]])
            )
            return
        text = "📋 <b>القنوات والمجموعات المضافة:</b>\n\n"
        buttons = []
        if fixed:
            text += "🔒 <b>ثابتة (من السر FORCE_SUB_CHANNELS):</b>\n"
            for ch in fixed:
                text += f"• <b>{ch['title']}</b> (<code>{ch['id']}</code>)\n"
            text += "\n<i>لحذفها عدّل السر FORCE_SUB_CHANNELS مباشرة.</i>\n\n"
        if channels:
            text += "➕ <b>مضافة من لوحة التحكم:</b>\n"
        for i, ch in enumerate(channels):
            text += f"{i+1}. <b>{ch['title']}</b> (<code>{ch['id']}</code>)\n"
            buttons.append([InlineKeyboardButton(
                f"🗑 حذف: {ch['title']}", callback_data=f"del_ch:{ch['id']}"
            )])
        if channels:
            buttons.append([InlineKeyboardButton("🗑🗑 حذف كل القنوات والمجموعات", callback_data="del_all_channels")])
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("del_ch:"):
        ch_id_raw = data.replace("del_ch:", "")
        try:
            ch_id = int(ch_id_raw)
        except ValueError:
            ch_id = ch_id_raw
        channels = db["channels"]
        ch = next((c for c in channels if c["id"] == ch_id), None)
        db["channels"] = [c for c in channels if c["id"] != ch_id]
        save_db(db)
        await query.edit_message_text(
            f"✅ تم حذف: <b>{ch['title'] if ch else ch_id}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="admin_list_channels")
            ]])
        )
        return

    if data == "del_all_channels":
        db["channels"] = []
        save_db(db)
        await query.edit_message_text(
            "✅ تم حذف جميع القنوات والمجموعات.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")
            ]])
        )
        return

    if data == "admin_broadcast":
        set_state(db, user.id, {"type": "waiting_broadcast"})
        await query.edit_message_text(
            f"📢 أرسل الرسالة التي تريد إذاعتها لجميع المستخدمين ({len(db['users'])} مستخدم):"
        )
        return

    if data == "admin_back":
        await query.edit_message_text(
            f"⚙️ <b>لوحة التحكم</b>\n\n"
            f"👥 المستخدمين: <b>{len(db['users'])}</b>\n"
            f"📢 القنوات المضافة: <b>{len(db['channels'])}</b>",
            parse_mode="HTML",
            reply_markup=admin_main_keyboard()
        )
        return

async def _send_large_file(chat_id: int, file_path: str, title: str, is_image: bool) -> bool:
    """يرفع ملفاً أكبر من 50MB عبر Pyrogram (MTProto) — حتى ~2000MB."""
    try:
        if is_image:
            await _pyro_client.send_photo(chat_id, file_path, caption=f"🖼 {title}")
        else:
            await _pyro_client.send_video(
                chat_id, file_path, caption=f"🎬 {title}", supports_streaming=True
            )
        return True
    except Exception as e:
        logger.warning(f"⚠️ فشل الرفع الكبير عبر Pyrogram: {str(e)[:200]}")
        return False

# ──────────────────────────────────────────
#  تشغيل البوت
# ──────────────────────────────────────────
async def _start_pyro(app):
    if _pyro_client:
        await _pyro_client.start()
        logger.info("✅ Pyrogram متصل (رفع حتى 2000MB)")

async def _stop_pyro(app):
    if _pyro_client:
        await _pyro_client.stop()

def main():
    if not BOT_TOKEN:
        raise SystemExit("❌ متغيّر البيئة BOT_TOKEN غير مضبوط. اضبطه كسر (secret) قبل التشغيل.")
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(_start_pyro)
        .post_shutdown(_stop_pyro)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("✅ البوت يعمل...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
