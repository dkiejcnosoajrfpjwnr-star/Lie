#!/usr/bin/env python3
# ============================================================
#   Telegram Auto Views Bot
#   Owner ID: 6668195885
#   Co-Owner ID: 5685233553
# ============================================================

import asyncio
import json
import logging
import os
import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from re import compile, search
from threading import Thread, active_count, Lock
from time import sleep, time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

# ===================== CONFIG =====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = 6668195885
# المالك الثاني الدائم - يمكنه إضافة وإزالة مالكين آخرين
PERMANENT_CO_OWNERS = [5685233553]
MAX_THREADS = 600
PROXY_TIMEOUT = (3, 4)
DATA_FILE = "bot_data.json"
PROXY_CACHE_TTL = 90  # seconds

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.WARNING
)
logger = logging.getLogger(__name__)

# ===================== PROXY SOURCES =====================
HTTP_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http",
    "https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&protocol=http",
    "https://openproxylist.xyz/http.txt",
    "https://proxyspace.pro/http.txt",
    "https://proxyspace.pro/https.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt",
    "https://raw.githubusercontent.com/mmpx12/proxy-list/master/https.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/https.txt",
    "https://www.proxy-list.download/api/v1/get?type=http",
    "https://www.proxy-list.download/api/v1/get?type=https",
    "https://www.proxyscan.io/download?type=http",
    "https://raw.githubusercontent.com/B4RC0DE-TM/proxy-list/main/HTTP.txt",
    "https://raw.githubusercontent.com/HyperBeats/proxy-list/main/http.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-https.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
    "https://raw.githubusercontent.com/saschazesiger/Free-Proxies/master/proxies/http.txt",
    "https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/proxies.txt",
    "https://raw.githubusercontent.com/saisuiu/uiu/main/free.txt",
    "https://raw.githubusercontent.com/hendrikbgr/Free-Proxy-Repo/master/proxy_list.txt",
    "https://raw.githubusercontent.com/hanwayTech/free-proxy-list/main/http.txt",
    "https://raw.githubusercontent.com/hanwayTech/free-proxy-list/main/https.txt",
    "https://raw.githubusercontent.com/almroot/proxylist/master/list.txt",
    "https://raw.githubusercontent.com/aslisk/proxyhttps/main/https.txt",
    "https://rootjazz.com/proxies/proxies.txt",
    "https://sheesh.rip/http.txt",
    "https://spys.me/proxy.txt",
    "https://proxyhub.me/en/all-http-proxy-list.html",
    "https://proxyhub.me/en/all-https-proxy-list.html",
    "https://proxy-tools.com/proxy/http",
    "https://proxy-tools.com/proxy/https",
    "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc&protocols=http",
    "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc&protocols=https",
    "https://proxylist.geonode.com/api/proxy-list?limit=500&page=2&sort_by=lastChecked&sort_type=desc&protocols=http",
    "https://multiproxy.org/txt_all/proxy.txt",
    "https://raw.githubusercontent.com/mertguvencli/http-proxy-list/main/proxy-list/data.txt",
]

SOCKS4_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks4",
    "https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&protocol=socks4",
    "https://openproxylist.xyz/socks4.txt",
    "https://proxyspace.pro/socks4.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
    "https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks4.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks4.txt",
    "https://www.proxy-list.download/api/v1/get?type=socks4",
    "https://www.proxyscan.io/download?type=socks4",
    "https://raw.githubusercontent.com/B4RC0DE-TM/proxy-list/main/SOCKS4.txt",
    "https://raw.githubusercontent.com/HyperBeats/proxy-list/main/socks4.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks4.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS4_RAW.txt",
    "https://raw.githubusercontent.com/saschazesiger/Free-Proxies/master/proxies/socks4.txt",
    "https://raw.githubusercontent.com/hanwayTech/free-proxy-list/main/socks4.txt",
    "https://spys.me/socks.txt",
    "https://proxyhub.me/en/all-socks4-proxy-list.html",
    "https://proxy-tools.com/proxy/socks4",
    "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc&protocols=socks4",
]

SOCKS5_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks5",
    "https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&protocol=socks5",
    "https://openproxylist.xyz/socks5.txt",
    "https://proxyspace.pro/socks5.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    "https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks5.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt",
    "https://www.proxy-list.download/api/v1/get?type=socks5",
    "https://www.proxyscan.io/download?type=socks5",
    "https://raw.githubusercontent.com/B4RC0DE-TM/proxy-list/main/SOCKS5.txt",
    "https://raw.githubusercontent.com/HyperBeats/proxy-list/main/socks5.txt",
    "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks5.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS5_RAW.txt",
    "https://raw.githubusercontent.com/saschazesiger/Free-Proxies/master/proxies/socks5.txt",
    "https://raw.githubusercontent.com/hanwayTech/free-proxy-list/main/socks5.txt",
    "https://raw.githubusercontent.com/manuGMG/proxy-365/main/SOCKS5.txt",
    "https://spys.me/socks.txt",
    "https://proxyhub.me/en/all-sock5-proxy-list.html",
    "https://proxy-tools.com/proxy/socks5",
    "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc&protocols=socks5",
    "https://www.my-proxy.com/free-socks-5-proxy.html",
]

# ===================== PROXY REGEX =====================
PROXY_REGEX = compile(
    r"(?:^|\D)?(("
    r"(?:[1-9]|[1-9]\d|1\d{2}|2[0-4]\d|25[0-5])"
    r"\."
    r"(?:\d|[1-9]\d|1\d{2}|2[0-4]\d|25[0-5])"
    r"\."
    r"(?:\d|[1-9]\d|1\d{2}|2[0-4]\d|25[0-5])"
    r"\."
    r"(?:\d|[1-9]\d|1\d{2}|2[0-4]\d|25[0-5])"
    r"):"
    r"(?:\d|[1-9]\d{1,3}|[1-5]\d{4}|6[0-4]\d{3}|65[0-4]\d{2}|655[0-2]\d|6553[0-5])"
    r")(?:\D|$)"
)

# ===================== ARABIC UTILS =====================
def normalize_arabic(text: str) -> str:
    text = re.sub(r'[\u064B-\u065F\u0670]', '', text)
    text = re.sub(r'[أإآٱ]', 'ا', text)
    text = text.replace('ى', 'ي')
    text = text.replace('ة', 'ه')
    return text.strip()

def is_stop_command(text: str) -> bool:
    n = normalize_arabic(text.strip())
    return n in {'ايقاف', 'وقف', 'توقف', 'اوقف', 'ايقف'}

def is_another_link(text: str) -> bool:
    n = normalize_arabic(text.strip())
    return n in {'اخر', 'اخري', 'رابط اخر'}

def parse_views(views_str: str) -> int:
    try:
        s = views_str.strip().lower().replace(',', '').replace('\xa0', '')
        if 'k' in s:
            return int(float(s.replace('k', '')) * 1000)
        elif 'm' in s:
            return int(float(s.replace('m', '')) * 1_000_000)
        else:
            return int(s)
    except Exception:
        return 0

def parse_channel(text: str):
    text = text.strip()
    m = search(r"(?:https?://t\.me/)?@?([A-Za-z0-9_]{4,})", text)
    if m:
        return m.group(1).lower()
    return None

# ===================== DATA MANAGER =====================
class DataManager:
    def __init__(self):
        self.data = {
            "co_owners": list(PERMANENT_CO_OWNERS),  # المالكون الدائمون مُضافون مسبقاً
            "users": [],
            "banned": [],
            "monitors": {}
        }
        self.load()
        # تأكد من وجود المالكين الدائمين دائماً
        for uid in PERMANENT_CO_OWNERS:
            if uid not in self.data["co_owners"]:
                self.data["co_owners"].append(uid)
        self.save()

    def load(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if "admins" in loaded and "co_owners" not in loaded:
                        loaded["co_owners"] = loaded.pop("admins")
                    self.data.update(loaded)
            except Exception:
                pass

    def save(self):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def is_owner(self, uid: int) -> bool:
        return uid == OWNER_ID or uid in self.data["co_owners"]

    def is_permanent_co_owner(self, uid: int) -> bool:
        """المالكون الدائمون (المضمنون في الكود) لا يمكن إزالتهم إلا من المالك الأصلي"""
        return uid in PERMANENT_CO_OWNERS

    def is_banned(self, uid: int) -> bool:
        return uid in self.data["banned"]

    def add_user(self, uid: int):
        if uid not in self.data["users"]:
            self.data["users"].append(uid)
            self.save()

    def add_co_owner(self, uid: int):
        if uid != OWNER_ID and uid not in self.data["co_owners"]:
            self.data["co_owners"].append(uid)
            self.save()
            return True
        return False

    def remove_co_owner(self, uid: int, requester_uid: int):
        """
        إزالة مالك - المالك الأصلي يمكنه إزالة أي مالك.
        المالكون الآخرون لا يمكنهم إزالة المالكين الدائمين.
        """
        if uid not in self.data["co_owners"]:
            return False
        # فقط المالك الأصلي يمكنه إزالة المالكين الدائمين
        if self.is_permanent_co_owner(uid) and requester_uid != OWNER_ID:
            return None  # None = ممنوع
        self.data["co_owners"].remove(uid)
        self.save()
        return True

    def add_monitor(self, channel: str, mode: str, count: int, uid: int):
        if "monitors" not in self.data:
            self.data["monitors"] = {}
        self.data["monitors"][channel] = {"mode": mode, "count": count, "uid": uid}
        self.save()

    def remove_monitor(self, channel: str):
        if channel in self.data.get("monitors", {}):
            del self.data["monitors"][channel]
            self.save()

    def get_monitors(self) -> dict:
        return self.data.get("monitors", {})


db = DataManager()


# ===================== BOOST SESSIONS =====================
class BoostSession:
    def __init__(self):
        self.active = False
        self.channel = ""
        self.post = ""
        self.real_views = "0"
        self.proxy_errors = 0
        self.token_errors = 0
        self.proxies = []
        self.start_time = None
        self.thread_count = 0
        self._stop = False
        self._lock = Lock()
        self.target_views = -1
        self.base_views = 0
        self.chat_id = None
        self.bot = None
        self.loop = None
        self.uid = None
        self.status_message = None

    def stop(self):
        self._stop = True
        self.active = False

    def reset(self):
        self._stop = False
        self.proxy_errors = 0
        self.token_errors = 0
        self.proxies = []
        self.start_time = time()
        self.thread_count = 0

    def elapsed(self):
        if self.start_time:
            secs = int(time() - self.start_time)
            m, s = divmod(secs, 60)
            h, m = divmod(m, 60)
            return f"{h:02d}:{m:02d}:{s:02d}"
        return "00:00:00"


# uid -> list of BoostSession
user_sessions: dict[int, list] = {}

# uid -> state
user_state: dict[int, str] = {}

# uid -> pending data
user_pending: dict[int, dict] = {}


def get_sessions(uid: int) -> list:
    if uid not in user_sessions:
        user_sessions[uid] = []
    return user_sessions[uid]

def stop_all_sessions(uid: int):
    for s in get_sessions(uid):
        s.stop()
    user_sessions[uid] = []


# ===================== PROXY SCRAPER =====================
_proxy_cache: list = []
_proxy_cache_time: float = 0.0
_proxy_cache_lock = Lock()


def _fetch_one_source(url: str, proxy_type: str):
    results = []
    try:
        resp = requests.get(url, timeout=8, headers={
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        for m in PROXY_REGEX.finditer(resp.text):
            results.append((proxy_type, m.group(1)))
    except Exception:
        pass
    return results


def collect_all_proxies():
    global _proxy_cache, _proxy_cache_time

    with _proxy_cache_lock:
        if _proxy_cache and (time() - _proxy_cache_time) < PROXY_CACHE_TTL:
            return list(_proxy_cache)

    all_tasks = []
    for url in HTTP_SOURCES:
        all_tasks.append((url, "http"))
    for url in SOCKS4_SOURCES:
        all_tasks.append((url, "socks4"))
    for url in SOCKS5_SOURCES:
        all_tasks.append((url, "socks5"))

    result = []
    with ThreadPoolExecutor(max_workers=80) as exe:
        futures = {exe.submit(_fetch_one_source, url, ptype): (url, ptype)
                   for url, ptype in all_tasks}
        for fut in as_completed(futures):
            try:
                result.extend(fut.result())
            except Exception:
                pass

    with _proxy_cache_lock:
        _proxy_cache = result
        _proxy_cache_time = time()

    return result


# ===================== VIEW SENDER =====================
def fetch_real_views(session: BoostSession):
    try:
        url = f"https://t.me/{session.channel}/{session.post}"
        resp = requests.get(
            url,
            params={"embed": "1", "mode": "tme"},
            headers={"referer": url, "user-agent": "Mozilla/5.0"},
            timeout=10
        )
        m = search(r'<span class="tgme_widget_message_views">([^<]+)', resp.text)
        if m:
            session.real_views = m.group(1)
    except Exception:
        pass


def send_one_view(session: BoostSession, proxy, proxy_type):
    if session._stop:
        return
    try:
        s = requests.Session()
        url = f"https://t.me/{session.channel}/{session.post}"
        resp = s.get(
            url,
            params={"embed": "1", "mode": "tme"},
            headers={
                "referer": url,
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/106.0.0.0 Safari/537.36"
            },
            proxies={"http": f"{proxy_type}://{proxy}", "https": f"{proxy_type}://{proxy}"},
            timeout=PROXY_TIMEOUT,
        )
        cookies = s.cookies.get_dict()
        view_val = search(r'data-view="([^"]+)', resp.text)
        if not view_val:
            with session._lock:
                session.token_errors += 1
            return
        s.get(
            "https://t.me/v/",
            params={"views": view_val.group(1)},
            cookies={
                "stel_dt": "-240",
                "stel_web_auth": "https%3A%2F%2Fweb.telegram.org%2Fz%2F",
                "stel_ssid": cookies.get("stel_ssid"),
                "stel_on": cookies.get("stel_on"),
            },
            headers={
                "referer": f"https://t.me/{session.channel}/{session.post}?embed=1&mode=tme",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "x-requested-with": "XMLHttpRequest",
            },
            proxies={"http": f"{proxy_type}://{proxy}", "https": f"{proxy_type}://{proxy}"},
            timeout=PROXY_TIMEOUT,
        )
    except Exception:
        with session._lock:
            session.proxy_errors += 1


def boost_worker(session: BoostSession):
    while not session._stop:
        try:
            proxies = collect_all_proxies()
            if not proxies or session._stop:
                sleep(5)
                continue
            threads = []
            for proxy_type, proxy in proxies:
                if session._stop:
                    break
                while active_count() > MAX_THREADS and not session._stop:
                    sleep(0.05)
                t = Thread(target=send_one_view, args=(session, proxy, proxy_type), daemon=True)
                threads.append(t)
                t.start()
            for t in threads:
                t.join(timeout=2)
        except Exception:
            sleep(3)
    session.active = False


def views_monitor(session: BoostSession):
    while session.active and not session._stop:
        fetch_real_views(session)
        if session.target_views > 0:
            current = parse_views(session.real_views)
            if current >= session.base_views + session.target_views:
                session.stop()
                _notify_complete(session)
                break
        sleep(5)


def _notify_complete(session: BoostSession):
    if session.bot and session.loop:
        msg = (
            f"تم الاكمال\n\n"
            f"تم رفع {session.target_views} مشاهدة\n"
            f"القناة: {session.channel}\n"
            f"المنشور: {session.post}\n"
            f"المشاهدات الحالية: {session.real_views}"
        )
        if session.status_message:
            asyncio.run_coroutine_threadsafe(
                session.status_message.edit_text(msg),
                session.loop
            )
        elif session.chat_id:
            asyncio.run_coroutine_threadsafe(
                session.bot.send_message(chat_id=session.chat_id, text=msg),
                session.loop
            )
    if session.uid is not None and session.uid in user_sessions:
        try:
            user_sessions[session.uid].remove(session)
        except ValueError:
            pass


# ===================== KEYBOARDS =====================
def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("رفع مشاهدات", callback_data="boost_start")],
        [
            InlineKeyboardButton("مراقبة القنوات", callback_data="monitor_menu"),
            InlineKeyboardButton("تعيين مالك", callback_data="add_owner_menu"),
        ],
    ])

def mode_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("ارسال عدد", callback_data="mode_count"),
            InlineKeyboardButton("تلقائي لا نهائي", callback_data="mode_infinite")
        ]
    ])

def monitor_mode_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("عدد محدد لكل منشور", callback_data="monitor_mode_count"),
            InlineKeyboardButton("لا نهائي", callback_data="monitor_mode_infinite")
        ],
        [InlineKeyboardButton("رجوع", callback_data="monitor_menu")]
    ])

def monitor_menu_kb():
    monitors = db.get_monitors()
    rows = []
    for channel, info in monitors.items():
        if info["mode"] == "infinite":
            label = f"@{channel} - لا نهائي"
        else:
            label = f"@{channel} - {info.get('count', 0)} مشاهدة"
        rows.append([InlineKeyboardButton(f"ايقاف: {label}", callback_data=f"monitor_del_{channel}")])
    rows.append([InlineKeyboardButton("اضافة قناة للمراقبة", callback_data="monitor_add")])
    rows.append([InlineKeyboardButton("رجوع", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

def owners_menu_kb(requester_uid: int):
    co_owners = db.data.get("co_owners", [])
    rows = []
    for uid in co_owners:
        label = f"ازالة: {uid}"
        if db.is_permanent_co_owner(uid):
            label += " ⭐"  # نجمة للمالكين الدائمين
        # المالك الأصلي يمكنه إزالة الجميع
        # المالكون الآخرون لا يمكنهم إزالة المالكين الدائمين
        if requester_uid == OWNER_ID or not db.is_permanent_co_owner(uid):
            rows.append([InlineKeyboardButton(label, callback_data=f"owner_del_{uid}")])
        else:
            rows.append([InlineKeyboardButton(f"🔒 {uid} (مالك دائم)", callback_data="owner_perm_info")])
    rows.append([InlineKeyboardButton("اضافة مالك جديد", callback_data="add_owner_start")])
    rows.append([InlineKeyboardButton("رجوع", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


START_TEXT = "اهلا بك في بوت رفع المشاهدات\n\nالمطور: @c3cccc3c"

def boost_info_text(channel: str, post: str) -> str:
    return (
        f"القناة: {channel}\n"
        f"المنشور: {post}\n\n"
        f"اختر طريقة الرفع:"
    )


# ===================== CHANNEL POST HANDLER =====================
async def channel_post_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post
    if not msg:
        return

    chat = msg.chat
    channel = (chat.username or "").lower() if chat.username else str(chat.id)
    if not channel:
        return

    monitors = db.get_monitors()
    info = monitors.get(channel)
    if not info:
        return

    post_id = str(msg.message_id)
    owner_uid = info["uid"]
    mode = info["mode"]
    count = info.get("count", 0)

    tmp = BoostSession()
    tmp.channel = channel
    tmp.post = post_id
    fetch_real_views(tmp)
    base = parse_views(tmp.real_views)

    session = BoostSession()
    session.channel = channel
    session.post = post_id
    session.reset()
    session.active = True
    session.target_views = count if mode == "count" else -1
    session.base_views = base
    session.real_views = tmp.real_views
    session.chat_id = owner_uid
    session.bot = ctx.bot
    session.loop = asyncio.get_event_loop()
    session.uid = owner_uid

    get_sessions(owner_uid).append(session)

    Thread(target=boost_worker, args=(session,), daemon=True).start()
    Thread(target=views_monitor, args=(session,), daemon=True).start()

    if mode == "count":
        def status_text(views):
            return (
                f"منشور جديد في @{channel}\n"
                f"المنشور: {post_id}\n\n"
                f"جاري رفع المشاهدات الى {count} مشاهدة\n"
                f"المشاهدات الحالية: {views}\n\n"
                f"سيتم اشعارك عند الاكمال."
            )
        try:
            notif = await ctx.bot.send_message(chat_id=owner_uid, text=status_text(tmp.real_views))
            session.status_message = notif

            async def live_update():
                last_views = tmp.real_views
                while session.active and not session._stop:
                    await asyncio.sleep(5)
                    if not session.active or session._stop:
                        break
                    current = session.real_views
                    if current != last_views:
                        last_views = current
                        try:
                            await notif.edit_text(status_text(current))
                        except Exception:
                            pass

            asyncio.create_task(live_update())
        except Exception:
            pass
    else:
        try:
            await ctx.bot.send_message(
                chat_id=owner_uid,
                text=(
                    f"منشور جديد في @{channel}\n"
                    f"المنشور: {post_id}\n\n"
                    f"جاري رفع المشاهدات بشكل لا نهائي.\n"
                    f"لايقاف جميع العمليات ارسل: ايقاف"
                )
            )
        except Exception:
            pass


# ===================== HANDLERS =====================
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not db.is_owner(uid):
        return
    user_state[uid] = None
    await update.message.reply_text(START_TEXT, reply_markup=main_menu_kb())


# ===================== CALLBACK HANDLER =====================
async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    if not db.is_owner(uid):
        await query.answer()
        return
    data = query.data
    await query.answer()

    # ---- BACK ----
    if data == "back_main":
        user_state[uid] = None
        await query.edit_message_text(START_TEXT, reply_markup=main_menu_kb())

    # ---- BOOST ----
    elif data == "boost_start":
        user_state[uid] = "waiting_link"
        await query.edit_message_text(
            START_TEXT + "\n\nارسل رابط المنشور الذي تريد رفع مشاهداته:"
        )

    elif data == "mode_count":
        user_state[uid] = "waiting_count"
        await query.edit_message_text(
            "ارسل العدد الذي تريده للوصول الى المشاهدات التي تريدها:"
        )

    elif data == "mode_infinite":
        pending = user_pending.get(uid)
        if not pending or pending.get("type") != "boost":
            await query.edit_message_text("حدث خطأ. ابدا من جديد.", reply_markup=main_menu_kb())
            return

        session = BoostSession()
        session.channel = pending["channel"]
        session.post = pending["post"]
        session.reset()
        session.active = True
        session.target_views = -1
        session.uid = uid

        get_sessions(uid).append(session)
        user_pending.pop(uid, None)
        user_state[uid] = None

        Thread(target=boost_worker, args=(session,), daemon=True).start()
        Thread(target=views_monitor, args=(session,), daemon=True).start()

        await query.edit_message_text(
            f"جاري رفع المشاهدات بشكل تلقائي لا نهائي\n\n"
            f"القناة: {pending['channel']}\n"
            f"المنشور: {pending['post']}\n\n"
            f"لايقاف الرفع ارسل: ايقاف\n"
            f"لرفع رابط اخر ارسل: اخر"
        )

    # ---- MONITOR ----
    elif data == "monitor_menu":
        user_state[uid] = None
        monitors = db.get_monitors()
        if monitors:
            text = "القنوات المراقبة:\n\n"
            for ch, info in monitors.items():
                mode_label = "لا نهائي" if info["mode"] == "infinite" else f"{info.get('count', 0)} مشاهدة لكل منشور"
                text += f"@{ch} - {mode_label}\n"
            text += "\nاضغط على قناة لايقاف مراقبتها، او اضف قناة جديدة:"
        else:
            text = "لا توجد قنوات مراقبة حاليا.\n\nاضف قناة للبدء:"
        await query.edit_message_text(text, reply_markup=monitor_menu_kb())

    elif data == "monitor_add":
        user_state[uid] = "waiting_monitor_channel"
        await query.edit_message_text(
            "ارسل معرف القناة او رابطها:\n\nمثال:\n@channelname\nhttps://t.me/channelname"
        )

    elif data.startswith("monitor_del_"):
        channel = data[len("monitor_del_"):]
        db.remove_monitor(channel)
        monitors = db.get_monitors()
        if monitors:
            text = "تم ايقاف مراقبة القناة.\n\nالقنوات المراقبة الحالية:\n\n"
            for ch, info in monitors.items():
                mode_label = "لا نهائي" if info["mode"] == "infinite" else f"{info.get('count', 0)} مشاهدة لكل منشور"
                text += f"@{ch} - {mode_label}\n"
        else:
            text = "تم ايقاف مراقبة القناة.\n\nلا توجد قنوات مراقبة حاليا."
        await query.edit_message_text(text, reply_markup=monitor_menu_kb())

    elif data == "monitor_mode_count":
        pending = user_pending.get(uid)
        if not pending or pending.get("type") != "monitor":
            await query.edit_message_text("حدث خطأ. ابدا من جديد.", reply_markup=main_menu_kb())
            return
        user_state[uid] = "waiting_monitor_count"
        await query.edit_message_text(
            f"القناة: @{pending['channel']}\n\n"
            f"ارسل عدد المشاهدات الذي تريده لكل منشور جديد:"
        )

    elif data == "monitor_mode_infinite":
        pending = user_pending.get(uid)
        if not pending or pending.get("type") != "monitor":
            await query.edit_message_text("حدث خطأ. ابدا من جديد.", reply_markup=main_menu_kb())
            return
        channel = pending["channel"]
        db.add_monitor(channel, "infinite", 0, uid)
        user_pending.pop(uid, None)
        user_state[uid] = None
        await query.edit_message_text(
            f"تم تفعيل مراقبة @{channel}\n\n"
            f"كل منشور جديد سيتم رفع مشاهداته بشكل لا نهائي تلقائيا.\n"
            f"تاكد ان البوت مشرف في القناة.",
            reply_markup=main_menu_kb()
        )

    # ---- OWNERS ----
    elif data == "add_owner_menu":
        # كل المالكين يمكنهم رؤية قائمة المالكين وإضافة آخرين
        co_owners = db.data.get("co_owners", [])
        if co_owners:
            text = "المالكون الحاليون:\n\n"
            for oid in co_owners:
                star = " ⭐" if db.is_permanent_co_owner(oid) else ""
                text += f"- {oid}{star}\n"
            text += "\n⭐ = مالك دائم\n\nيمكنك اضافة مالك جديد او ازالة مالك حالي:"
        else:
            text = "لا يوجد مالكون اضافيون حاليا.\n\nاضف مالكا جديدا:"
        await query.edit_message_text(text, reply_markup=owners_menu_kb(uid))

    elif data == "add_owner_start":
        user_state[uid] = "waiting_add_owner"
        await query.edit_message_text(
            "ارسل معرف المستخدم (User ID) الذي تريد تعيينه مالكا:\n\n"
            "يمكن للمستخدم معرفة ID الخاص به من خلال @userinfobot"
        )

    elif data == "owner_perm_info":
        await query.answer("هذا مالك دائم، لا يمكن إزالته إلا من المالك الأصلي.", show_alert=True)

    elif data.startswith("owner_del_"):
        try:
            del_uid = int(data[len("owner_del_"):])
            result = db.remove_co_owner(del_uid, uid)
            if result is None:
                await query.answer("لا يمكنك إزالة مالك دائم. هذا الإذن للمالك الأصلي فقط.", show_alert=True)
                return
            elif result is False:
                await query.answer("المستخدم غير موجود في قائمة المالكين.", show_alert=True)
                return
            co_owners = db.data.get("co_owners", [])
            if co_owners:
                text = f"تم ازالة المالك {del_uid}.\n\nالمالكون الحاليون:\n\n"
                for oid in co_owners:
                    star = " ⭐" if db.is_permanent_co_owner(oid) else ""
                    text += f"- {oid}{star}\n"
            else:
                text = f"تم ازالة المالك {del_uid}.\n\nلا يوجد مالكون اضافيون."
            await query.edit_message_text(text, reply_markup=owners_menu_kb(uid))
        except Exception:
            await query.edit_message_text("حدث خطأ.", reply_markup=main_menu_kb())


# ===================== MESSAGE HANDLER =====================
async def _start_boost_with_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE, url_text: str):
    uid = update.effective_user.id
    url_match = search(r"(?:https?://t\.me/)?([^/\s]+)/(\d+)", url_text)
    if not url_match:
        await update.effective_message.reply_text(
            "رابط غير صحيح. مثال:\nhttps://t.me/channel/123"
        )
        return
    channel, post = url_match.groups()
    user_pending[uid] = {"type": "boost", "channel": channel, "post": post}
    user_state[uid] = None
    await update.effective_message.reply_text(
        boost_info_text(channel, post),
        reply_markup=mode_kb()
    )


async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not db.is_owner(uid):
        return

    text = (update.message.text or "").strip()
    if not text:
        return

    # Stop command
    if is_stop_command(text):
        sessions = get_sessions(uid)
        if sessions:
            count = len(sessions)
            stop_all_sessions(uid)
            user_state[uid] = None
            user_pending.pop(uid, None)
            await update.message.reply_text(
                f"تم الايقاف ({count} عملية نشطة)",
                reply_markup=main_menu_kb()
            )
        else:
            await update.message.reply_text(
                "لا يوجد عمليات نشطة حاليا.",
                reply_markup=main_menu_kb()
            )
        return

    # "اخر" — add another link
    if is_another_link(text):
        user_state[uid] = "waiting_link"
        await update.message.reply_text(
            "ارسل الرابط الاخر الذي تريد رفع مشاهداته:"
        )
        return

    state = user_state.get(uid)

    # ---- ADD OWNER STATE ----
    if state == "waiting_add_owner":
        try:
            new_uid = int(text.strip())
        except ValueError:
            await update.message.reply_text("ارسل معرف رقمي صحيح.")
            return
        if new_uid == OWNER_ID:
            await update.message.reply_text("هذا هو المالك الاصلي بالفعل.")
            return
        if new_uid == uid:
            await update.message.reply_text("انت مالك بالفعل!")
            return
        db.add_co_owner(new_uid)
        user_state[uid] = None
        await update.message.reply_text(
            f"تم تعيين {new_uid} مالكا بنجاح.",
            reply_markup=main_menu_kb()
        )
        return

    # ---- MONITOR STATES ----
    if state == "waiting_monitor_channel":
        channel = parse_channel(text)
        if not channel:
            await update.message.reply_text(
                "معرف القناة غير صحيح.\n\nمثال:\n@channelname\nhttps://t.me/channelname"
            )
            return
        user_pending[uid] = {"type": "monitor", "channel": channel}
        user_state[uid] = None
        await update.message.reply_text(
            f"القناة: @{channel}\n\nاختر طريقة الرفع لكل منشور جديد:",
            reply_markup=monitor_mode_kb()
        )
        return

    if state == "waiting_monitor_count":
        try:
            count = int(text.replace(',', '').replace('،', ''))
            if count <= 0:
                raise ValueError
        except (ValueError, TypeError):
            await update.message.reply_text("ارسل رقم صحيح اكبر من صفر.")
            return
        pending = user_pending.get(uid)
        if not pending or pending.get("type") != "monitor":
            user_state[uid] = None
            await update.message.reply_text("حدث خطأ. ابدا من جديد.", reply_markup=main_menu_kb())
            return
        channel = pending["channel"]
        db.add_monitor(channel, "count", count, uid)
        user_pending.pop(uid, None)
        user_state[uid] = None
        await update.message.reply_text(
            f"تم تفعيل مراقبة @{channel}\n\n"
            f"كل منشور جديد سيتم رفع مشاهداته الى {count} مشاهدة تلقائيا.\n"
            f"تاكد ان البوت مشرف في القناة.",
            reply_markup=main_menu_kb()
        )
        return

    # ---- BOOST STATES ----
    if state == "waiting_count":
        try:
            count = int(text.replace(',', '').replace('،', ''))
            if count <= 0:
                raise ValueError
        except (ValueError, TypeError):
            await update.message.reply_text("ارسل رقم صحيح اكبر من صفر.")
            return

        pending = user_pending.get(uid)
        if not pending or pending.get("type") != "boost":
            user_state[uid] = "waiting_link"
            await update.message.reply_text("ارسل رابط المنشور الذي تريد رفع مشاهداته:")
            return

        tmp_session = BoostSession()
        tmp_session.channel = pending["channel"]
        tmp_session.post = pending["post"]
        fetch_real_views(tmp_session)
        base = parse_views(tmp_session.real_views)

        session = BoostSession()
        session.channel = pending["channel"]
        session.post = pending["post"]
        session.reset()
        session.active = True
        session.target_views = count
        session.base_views = base
        session.real_views = tmp_session.real_views
        session.chat_id = update.message.chat_id
        session.bot = ctx.bot
        session.loop = asyncio.get_event_loop()
        session.uid = uid

        get_sessions(uid).append(session)
        user_pending.pop(uid, None)
        user_state[uid] = None

        Thread(target=boost_worker, args=(session,), daemon=True).start()
        Thread(target=views_monitor, args=(session,), daemon=True).start()

        def status_text(views):
            return (
                f"جاري رفع المشاهدات الى {count} مشاهدة\n\n"
                f"القناة: {pending['channel']}\n"
                f"المنشور: {pending['post']}\n"
                f"المشاهدات الحالية: {views}\n\n"
                f"سيتم اشعارك عند الاكمال.\n"
                f"يمكنك ايقافه في اي وقت بارسال: ايقاف\n"
                f"لرفع رابط اخر ارسل: اخر"
            )

        sent_msg = await update.message.reply_text(status_text(tmp_session.real_views))
        session.status_message = sent_msg

        async def live_update():
            last_views = tmp_session.real_views
            while session.active and not session._stop:
                await asyncio.sleep(5)
                if not session.active or session._stop:
                    break
                current = session.real_views
                if current != last_views:
                    last_views = current
                    try:
                        await sent_msg.edit_text(status_text(current))
                    except Exception:
                        pass

        asyncio.create_task(live_update())
        return

    # Link detection
    if "t.me/" in text or text.startswith("https://"):
        await _start_boost_with_url(update, ctx, text)
        return

    if state == "waiting_link":
        await update.message.reply_text(
            "ارسل رابط منشور تلغرام.\nمثال:\nhttps://t.me/channel/123"
        )
        return

    # Default
    await update.message.reply_text(START_TEXT, reply_markup=main_menu_kb())


# ===================== MAIN =====================
def main():
    if not BOT_TOKEN:
        print("خطأ: لم يتم تعيين BOT_TOKEN. أضفه كمتغير بيئي أو في GitHub Secrets.")
        return

    print("جاري تشغيل البوت...")
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(
        filters.ChatType.CHANNEL,
        channel_post_handler
    ))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("البوت يعمل الان!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
