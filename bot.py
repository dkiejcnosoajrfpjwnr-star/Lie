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
                "أرسل لي رابط أي فيديو من تيك توك، انستغرام، تويتر، فيسبوك وغيرها "
                "وسأقوم بتحميله لك فوراً 🎬\n\n"
                "ملاحظة: يوتيوب غير مدعوم."
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
#  كوكيز انستغرام (اختياري) — يحل حظر "empty media response"
#  الناتج عن وصول انستغرام بدون تسجيل دخول من سيرفرات مثل Replit/GitHub
# ──────────────────────────────────────────
INSTAGRAM_COOKIES_FILE = "instagram_cookies.txt"

def _setup_instagram_cookies():
    raw = os.environ.get("INSTAGRAM_COOKIES", "").strip()
    if not raw:
        return
    with open(INSTAGRAM_COOKIES_FILE, "w", encoding="utf-8") as f:
        f.write(raw)
    logger.info("✅ تم تفعيل كوكيز انستغرام")

_setup_instagram_cookies()

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
    """يحمّل ملفاً من رابط مباشر إلى القرص مع حد أقصى 50MB."""
    out_path = os.path.join(TEMP_DIR, f"{uuid.uuid4().hex[:8]}_{safe_name}")
    try:
        async with session.get(
            dl_url,
            headers={"User-Agent": DOWNLOAD_UA},
            timeout=aiohttp.ClientTimeout(total=120),
        ) as resp:
            if resp.status != 200:
                return {"success": False, "error": f"خطأ في تحميل الملف ({resp.status})"}

            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) > 50 * 1024 * 1024:
                return {"success": False, "error": "حجم الفيديو يتجاوز 50MB المسموح به ❌"}

            size = 0
            with open(out_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(1024 * 64):
                    size += len(chunk)
                    if size > 50 * 1024 * 1024:
                        f.close()
                        os.remove(out_path)
                        return {"success": False, "error": "حجم الفيديو يتجاوز 50MB المسموح به ❌"}
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
def _build_ydl_opts(extra: dict = {}) -> dict:
    base = {
        "outtmpl": os.path.join(TEMP_DIR, "%(title).80s.%(ext)s"),
        "format": (
            "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]"
            "/best[ext=mp4][height<=720]/best[height<=720]/best"
        ),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "max_filesize": 50 * 1024 * 1024,
        "socket_timeout": 30,
    }
    if os.path.exists(INSTAGRAM_COOKIES_FILE):
        base["cookiefile"] = INSTAGRAM_COOKIES_FILE
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
            _build_ydl_opts({"extractor_args": {"youtube": {"player_client": ["web"]}}}),
            _build_ydl_opts({"extractor_args": {"youtube": {"player_client": ["ios"]}}}),
            _build_ydl_opts({"extractor_args": {"youtube": {"player_client": ["android"]}}}),
        ]
    return [
        _build_ydl_opts(),
        _build_ydl_opts({"format": "best[ext=mp4]/best"}),
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
    """يستخرج بيانات منشور انستغرام حتى لو لم توجد صيغ فيديو (منشور صورة)."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignore_no_formats_error": True,
        "noplaylist": True,
    }
    if os.path.exists(INSTAGRAM_COOKIES_FILE):
        opts["cookiefile"] = INSTAGRAM_COOKIES_FILE
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info is None:
            return None
        if info.get("_type") in ("playlist", "multi_video") and info.get("entries"):
            info = next((e for e in info["entries"] if e), info)
        return info

async def _instagram_image_download(url: str) -> dict:
    """تحميل منشور صورة من انستغرام مباشرة عبر رابط الصورة (لا يدعمه yt-dlp للتنزيل)."""
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

    # منشور صورة (لا صيغ فيديو) — خاص بانستغرام
    if no_formats and _is_instagram(url):
        return await _instagram_image_download(url)

    return {"success": False, "error": last_error}

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
        sub = await check_subscription(context, user.id, db["channels"])
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

        try:
            await processing.edit_text("📤 جاري الإرسال...")
            if is_image:
                with open(file_path, "rb") as pf:
                    await update.message.reply_photo(
                        photo=InputFile(pf, filename=f"{title}{ext}"),
                        caption=f"🖼 <b>{title}</b>",
                        parse_mode="HTML",
                    )
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

    await update.message.reply_text(
        "أرسل لي رابط فيديو من أي موقع (عدا يوتيوب) وسأحمله لك! 🎬"
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
        sub = await check_subscription(context, user.id, db["channels"])
        if sub["ok"]:
            await query.edit_message_text("✅ شكراً! يمكنك الآن إرسال روابط الفيديوهات 🎬")
        else:
            await query.edit_message_text(
                "❌ لم تشترك في جميع القنوات بعد. يرجى الاشتراك ثم المحاولة.",
                reply_markup=build_subscribe_keyboard(sub["missing"])
            )
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
        if not channels:
            await query.edit_message_text(
                "📋 لا توجد قنوات أو مجموعات مضافة.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")
                ]])
            )
            return
        text = "📋 <b>القنوات والمجموعات المضافة:</b>\n\n"
        buttons = []
        for i, ch in enumerate(channels):
            text += f"{i+1}. <b>{ch['title']}</b> (<code>{ch['id']}</code>)\n"
            buttons.append([InlineKeyboardButton(
                f"🗑 حذف: {ch['title']}", callback_data=f"del_ch:{ch['id']}"
            )])
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

# ──────────────────────────────────────────
#  تشغيل البوت
# ──────────────────────────────────────────
def main():
    if not BOT_TOKEN:
        raise SystemExit("❌ متغيّر البيئة BOT_TOKEN غير مضبوط. اضبطه كسر (secret) قبل التشغيل.")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("✅ البوت يعمل...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
