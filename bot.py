import os
import json
import time
import logging
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# CONFIG
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Можно переопределить путь на Railway через переменную USERS_PATH
USERS_PATH = os.getenv("USERS_PATH", os.path.join(BASE_DIR, "users.json"))

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = os.getenv("ADMIN_ID", "").strip()  # numeric string
SITE_URL = os.getenv("SITE_URL", "https://financeacademy.online").strip()

# Support contacts (set in Railway Variables)
SUPPORT_TG = os.getenv("SUPPORT_TG", "@financeacademytj").strip()
SUPPORT_WA = os.getenv("SUPPORT_WA", "+49XXXXXXXXXXX").strip()

# Optional: links to groups/channels (set in env)
GROUP_BASIC_URL = os.getenv("GROUP_BASIC_URL", "").strip()
GROUP_PRO_URL = os.getenv("GROUP_PRO_URL", "").strip()
GROUP_VIP_URL = os.getenv("GROUP_VIP_URL", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

# Prices (promo -> regular)
PRICES = {
    "BASIC": {"promo": 99, "regular": 149, "currency": "€", "access": {"ru": "3 месяца", "tj": "3 моҳ"}},
    "PRO":   {"promo": 249, "regular": 349, "currency": "€", "access": {"ru": "вечный доступ", "tj": "дастрасии доимӣ"}},
    "VIP":   {"promo": 399, "regular": 499, "currency": "€", "access": {"ru": "вечный доступ + сопровождение", "tj": "дастрасии доимӣ + ҳамроҳӣ"}},
}

PLAN_NAMES = {
    "BASIC": {"ru": "BASIC — база", "tj": "BASIC — асосӣ"},
    "PRO":   {"ru": "PRO — база + разборы", "tj": "PRO — асосӣ + таҳлилҳо"},
    "VIP":   {"ru": "VIP — всё + личная поддержка", "tj": "VIP — ҳама чиз + дастгирии шахсӣ"},
}

SUPPORTED_LANGS = ("ru", "tj")
DEFAULT_LANG = "ru"

# =========================
# LOGGING
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("FinanceAcademyTJ_bot")

# =========================
# STORAGE (safe JSON)
# =========================
def _safe_read_json(path: str) -> Dict[str, Any]:
    try:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
            if not raw:
                return {}
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("Failed to read JSON %s: %s", path, e)
        return {}

def _safe_write_json(path: str, data: Dict[str, Any]) -> None:
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        logger.error("Failed to write JSON %s: %s", path, e)

def get_user(uid: int) -> Dict[str, Any]:
    users = _safe_read_json(USERS_PATH)
    u = users.get(str(uid), {})
    return u if isinstance(u, dict) else {}

def upsert_user(uid: int, patch: Dict[str, Any]) -> Dict[str, Any]:
    users = _safe_read_json(USERS_PATH)
    key = str(uid)
    cur = users.get(key, {})
    if not isinstance(cur, dict):
        cur = {}
    cur.update(patch)
    users[key] = cur
    _safe_write_json(USERS_PATH, users)
    return cur

def set_purchase_status(uid: int, plan: str, status: str) -> None:
    """
    status: none | requested | approved | denied
    """
    u = get_user(uid)
    purchases = u.get("purchases", {})
    if not isinstance(purchases, dict):
        purchases = {}
    purchases[plan] = {"status": status, "ts": int(time.time())}
    upsert_user(uid, {"purchases": purchases})

def get_purchase_status(uid: int, plan: str) -> str:
    u = get_user(uid)
    purchases = u.get("purchases", {})
    if not isinstance(purchases, dict):
        return "none"
    p = purchases.get(plan, {})
    if not isinstance(p, dict):
        return "none"
    return str(p.get("status", "none"))

def user_has_access(uid: int) -> bool:
    """
    Доступ считаем открытым, если хотя бы один тариф approved.
    """
    u = get_user(uid)
    purchases = u.get("purchases", {})
    if not isinstance(purchases, dict):
        return False
    for plan in ("BASIC", "PRO", "VIP"):
        p = purchases.get(plan)
        if isinstance(p, dict) and p.get("status") == "approved":
            return True
    return False

def get_approved_plan(uid: int) -> Optional[str]:
    u = get_user(uid)
    purchases = u.get("purchases", {})
    if not isinstance(purchases, dict):
        return None
    for plan in ("VIP", "PRO", "BASIC"):
        p = purchases.get(plan)
        if isinstance(p, dict) and p.get("status") == "approved":
            return plan
    return None

def get_lang(uid: int) -> str:
    u = get_user(uid)
    lang = (u.get("lang") or "").strip().lower()
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG

def set_lang(uid: int, lang: str) -> None:
    lang = (lang or "").strip().lower()
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG
    upsert_user(uid, {"lang": lang, "lang_ts": int(time.time())})

# =========================
# I18N TEXTS
# =========================
TEXTS: Dict[str, Dict[str, str]] = {
    "welcome": {
        "ru": "Ассалому алайкум!\n\nЯ бот *FinanceAcademyTJ*.\nПомогу выбрать тариф, оформить покупку и получить доступ к урокам.\n\nВыберите язык и используйте меню ниже.",
        "tj": "Ассалому алайкум!\n\nМан боти *FinanceAcademyTJ* ҳастам.\nБа шумо барои интихоб кардани тариф, харид ва гирифтани дастрасӣ ба дарсҳо кӯмак мекунам.\n\nЗабонро интихоб кунед ва аз меню истифода баред.",
    },
    "choose_lang": {"ru": "🌐 Выберите язык:", "tj": "🌐 Забонро интихоб кунед:"},
    "lang_set_ru": {"ru": "✅ Язык установлен: Русский", "tj": "✅ Забон интихоб шуд: Русӣ"},
    "lang_set_tj": {"ru": "✅ Язык установлен: Тоҷикӣ", "tj": "✅ Забон интихоб шуд: Тоҷикӣ"},

    "menu_courses": {"ru": "📚 Курсы", "tj": "📚 Дарсҳо"},
    "menu_buy": {"ru": "💳 Купить доступ", "tj": "💳 Хариди дастрасӣ"},
    "menu_account": {"ru": "📊 Мой аккаунт", "tj": "📊 Ҳисоби ман"},
    "menu_support": {"ru": "👨‍💻 Поддержка", "tj": "👨‍💻 Дастгирӣ"},

    "buy_title": {
        "ru": "💳 *Купить доступ*\n\nВыбери тариф:\n• BASIC — база (3 месяца)\n• PRO — база + разборы + личная связка\n• VIP — всё + личная связка + связка без карт + сопровождение\n\nНажми кнопку тарифа ниже:",
        "tj": "💳 *Хариди дастрасӣ*\n\nТарифро интихоб кунед:\n• BASIC — асосӣ (3 моҳ)\n• PRO — асосӣ + таҳлилҳо + «связка» шахсӣ\n• VIP — ҳама чиз + «связка» шахсӣ + «связка» бе корт + ҳамроҳӣ\n\nТугмаи тарифро зер кунед:",
    },
    "choose_plan_below": {"ru": "Выбери тариф кнопками ниже:", "tj": "Тарифро бо тугмаҳои поён интихоб кунед:"},

    "no_access": {
        "ru": "Доступ к урокам открывается *после покупки*.\nНажми «💳 Купить доступ» и выбери тариф.\n\n🌐 Полная информация: {site}",
        "tj": "Дастрасӣ ба дарсҳо *пас аз харид* кушода мешавад.\n«💳 Хариди дастрасӣ» ро пахш кунед ва тарифро интихоб кунед.\n\n🌐 Маълумоти пурра: {site}",
    },

    "access_active": {
        "ru": "✅ Доступ активен.\n\nНапиши, что именно хочешь изучить сейчас:\n• Bybit регистрация/верификация\n• USDT покупка/продажа\n• P2P (апелляции, лимиты, безопасность)\n• Спот (основы)\n",
        "tj": "✅ Дастрасӣ фаъол аст.\n\nНавиштед, ки ҳозир чиро омӯхтан мехоҳед:\n• Bybit бақайдгирӣ/верификатсия\n• USDT харид/фурӯш\n• P2P (апелляция, лимитҳо, амният)\n• Спот (асосҳо)\n",
    },

    "support": {
        "ru": "👨‍💻 *Поддержка*\n\nНапиши одним сообщением:\n1) что именно нужно (регистрация/верификация/USDT/P2P/вывод)\n2) на какой бирже (Bybit/Binance/другая)\n3) какая ошибка (если есть — текст ошибки)\n\n📌 Telegram: {tg}\n📌 WhatsApp: {wa}\n🌐 Подробнее на сайте: {site}",
        "tj": "👨‍💻 *Дастгирӣ*\n\nЯк паём нависед:\n1) чӣ лозим аст (бақайдгирӣ/верификатсия/USDT/P2P/баровардан)\n2) кадом биржа (Bybit/Binance/дигар)\n3) кадом хато (агар бошад — матни хато)\n\n📌 Telegram: {tg}\n📌 WhatsApp: {wa}\n🌐 Маълумоти бештар: {site}",
    },
}

def t(uid: int, key: str, **fmt: Any) -> str:
    lang = get_lang(uid)
    block = TEXTS.get(key, {})
    txt = block.get(lang) or block.get(DEFAULT_LANG) or ""
    return txt.format(**fmt) if fmt else txt

# =========================
# UI
# =========================
def main_menu(uid: int) -> ReplyKeyboardMarkup:
    lang = get_lang(uid)
    kb = [
        [KeyboardButton(TEXTS["menu_courses"][lang]), KeyboardButton(TEXTS["menu_buy"][lang])],
        [KeyboardButton(TEXTS["menu_account"][lang]), KeyboardButton(TEXTS["menu_support"][lang])],
        [KeyboardButton("🌐 Language / Забон")],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def lang_inline() -> InlineKeyboardMarkup:
    kb = [[
        InlineKeyboardButton("Русский", callback_data="lang:ru"),
        InlineKeyboardButton("Тоҷикӣ", callback_data="lang:tj"),
    ]]
    return InlineKeyboardMarkup(kb)

def plans_inline(uid: int) -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton("BASIC", callback_data="plan:BASIC"),
            InlineKeyboardButton("PRO", callback_data="plan:PRO"),
            InlineKeyboardButton("VIP", callback_data="plan:VIP"),
        ],
        [InlineKeyboardButton("🌐 Website", url=SITE_URL)],
    ]
    return InlineKeyboardMarkup(kb)

def payment_inline(plan: str) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("✅ I paid / Ман пардохт кардам", callback_data=f"paid:{plan}")],
        [InlineKeyboardButton("🌐 Website", url=SITE_URL)],
    ]
    return InlineKeyboardMarkup(kb)

def groups_inline(uid: int, plan: str) -> Optional[InlineKeyboardMarkup]:
    lang = get_lang(uid)
    buttons = []
    if plan == "BASIC" and GROUP_BASIC_URL:
        buttons.append([InlineKeyboardButton("🔗 " + ("Группа BASIC" if lang == "ru" else "Гурӯҳи BASIC"), url=GROUP_BASIC_URL)])
    if plan == "PRO" and GROUP_PRO_URL:
        buttons.append([InlineKeyboardButton("🔗 " + ("Группа PRO" if lang == "ru" else "Гурӯҳи PRO"), url=GROUP_PRO_URL)])
    if plan == "VIP" and GROUP_VIP_URL:
        buttons.append([InlineKeyboardButton("🔗 " + ("VIP-группа" if lang == "ru" else "Гурӯҳи VIP"), url=GROUP_VIP_URL)])
    return InlineKeyboardMarkup(buttons) if buttons else None

# =========================
# CONTENT
# =========================
def courses_text(uid: int) -> str:
    lang = get_lang(uid)
    if lang == "tj":
        return (
            "📚 *Дарсҳои Finance Academy TJ*\n\n"
            "Мо *крипторо аз сифр* меомӯзонем — бо забони содда, қадам ба қадам ва бо диққати калон ба амният.\n\n"
            "Шумо меомӯзед:\n"
            "• крипто чист ва барои чӣ лозим аст\n"
            "• *USDT* чист ва чаро ~1$ мемонад (stablecoin)\n"
            "• биржа чист ва чӣ тавр бехатар истифода бурдан\n"
            "• чӣ тавр *USDT харидан/фурӯхтан*\n"
            "• чӣ тавр пулро тавассути *P2P* фиристодан\n"
            "• чӣ тавр аз хато ва мошенникҳо ҳифз шудан\n"
            "• амният: 2FA, антифишинг, парольҳо\n\n"
            f"🌐 Барномаи пурра: {SITE_URL}\n\n"
            "Дастрасӣ ба дарсҳо *пас аз харид* кушода мешавад.\n"
            "«💳 Хариди дастрасӣ»-ро пахш кунед ва тарифро интихоб кунед."
        )
    return (
        "📚 *Курсы Finance Academy TJ*\n\n"
        "Мы обучаем *криптовалюте с нуля* — простым языком, пошагово и с упором на безопасность.\n\n"
        "Вы научитесь:\n"
        "• что такое крипта и зачем она нужна\n"
        "• что такое *USDT* и почему он держит курс ~1$ (стейблкоин)\n"
        "• что такое биржа и как ей пользоваться безопасно\n"
        "• как *купить/продать USDT*\n"
        "• как отправлять деньги по миру через *P2P*\n"
        "• как избежать ошибок и мошенников\n"
        "• безопасность: 2FA, антифишинг, пароли\n\n"
        f"🌐 Полная программа и детали: {SITE_URL}\n\n"
        "Доступ к урокам открывается *после покупки*.\n"
        "Нажми «💳 Купить доступ» и выбери тариф."
    )

def plan_details(uid: int, plan: str) -> str:
    lang = get_lang(uid)
    p = PRICES[plan]
    cur = p["currency"]
    promo = p["promo"]
    regular = p["regular"]
    access = p["access"][lang]

    if plan == "BASIC":
        if lang == "tj":
            return (
                "✅ *BASIC — барои навкорҳо*\n\n"
                "Агар аз сифр оғоз мекунед — ин беҳтарин аст.\n\n"
                "Дар дохил:\n"
                "• асосҳои крипто\n"
                "• USDT, шабакаҳо, комиссияҳо\n"
                "• P2P: харид/фурӯш, амният, апелляция\n"
                "• фиристодани пул тавассути P2P\n\n"
                f"⏳ Дастрасӣ: *{access}*\n"
                f"💰 Нарх: *{promo}{cur}* (аксия) ба ҷои *{regular}{cur}*\n\n"
                "Пас аз пардохт тугмаи поёнро пахш кунед: «✅ I paid / Ман пардохт кардам»."
            )
        return (
            "✅ *BASIC — база (для новичков)*\n\n"
            "Подходит, если ты начинаешь с нуля.\n\n"
            "Внутри:\n"
            "• основы крипты\n"
            "• USDT, сети, комиссии\n"
            "• P2P: покупка/продажа, безопасность, апелляции\n"
            "• отправка денег по миру через P2P\n\n"
            f"⏳ Доступ: *{access}*\n"
            f"💰 Цена: *{promo}{cur}* (акция) вместо *{regular}{cur}*\n\n"
            "После оплаты нажми кнопку ниже: «✅ I paid / Ман пардохт кардам»."
        )

    if plan == "PRO":
        if lang == "tj":
            return (
                "⭐ *PRO — асосӣ + таҳлилҳо + «связка» шахсӣ*\n\n"
                "Ҳама чиз аз BASIC, илова:\n"
                "• таҳлилҳои амалӣ\n"
                "• ҷавоб ба саволҳо\n"
                "• *«связка» шахсӣ*\n\n"
                f"♾️ Дастрасӣ: *{access}*\n"
                f"💰 Нарх: *{promo}{cur}* (аксия) ба ҷои *{regular}{cur}*\n\n"
                "Пас аз пардохт тугмаи поёнро пахш кунед: «✅ I paid / Ман пардохт кардам»."
            )
        return (
            "⭐ *PRO — база + разборы + личная связка*\n\n"
            "Всё из BASIC, плюс:\n"
            "• практические разборы\n"
            "• ответы на вопросы\n"
            "• *личная связка*\n\n"
            f"♾️ Доступ: *{access}*\n"
            f"💰 Цена: *{promo}{cur}* (акция) вместо *{regular}{cur}*\n\n"
            "После оплаты нажми кнопку ниже: «✅ I paid / Ман пардохт кардам»."
        )

    if plan == "VIP":
        if lang == "tj":
            return (
                "👑 *VIP — максимум: ҳама чиз + ҳамроҳии шахсӣ*\n\n"
                "Ҳама чиз аз PRO, илова:\n"
                "• *«связка» шахсӣ* + танзим барои шумо\n"
                "• *«связка» бе корт*\n"
                "• дастгирӣ ва ҳамроҳии шахсӣ\n"
                "• занг/консультация\n\n"
                f"♾️ Дастрасӣ: *{access}*\n"
                f"💰 Нарх: *{promo}{cur}* (аксия) ба ҷои *{regular}{cur}*\n\n"
                "Пас аз пардохт тугмаи поёнро пахш кунед: «✅ I paid / Ман пардохт кардам»."
            )
        return (
            "👑 *VIP — максимум: всё + личное сопровождение*\n\n"
            "Всё из PRO, плюс:\n"
            "• *личная связка* + настройка под тебя\n"
            "• *связка без карт*\n"
            "• личная поддержка и сопровождение\n"
            "• созвон/консультация\n\n"
            f"♾️ Доступ: *{access}*\n"
            f"💰 Цена: *{promo}{cur}* (акция) вместо *{regular}{cur}*\n\n"
            "После оплаты нажми кнопку ниже: «✅ I paid / Ман пардохт кардам»."
        )

    return "Неизвестный тариф."

def account_text(uid: int) -> str:
    lang = get_lang(uid)
    u = get_user(uid)
    plan = get_approved_plan(uid)
    if plan:
        status = "✅ " + ("доступ открыт" if lang == "ru" else "дастрасӣ кушода аст")
        plan_name = PLAN_NAMES.get(plan, {}).get(lang, plan)
        access = PRICES[plan]["access"][lang]
    else:
        status = "⛔ " + ("доступ не активирован" if lang == "ru" else "дастрасӣ фаъол нест")
        plan_name = "—"
        access = "—"

    username = u.get("username") or "—"
    first_name = u.get("first_name") or "—"

    if lang == "tj":
        return (
            "📊 *Ҳисоби ман*\n\n"
            f"👤 Ном: *{first_name}*\n"
            f"🔗 Username: *@{username}*\n"
            f"🆔 ID: `{uid}`\n\n"
            f"📌 Тариф: *{plan_name}*\n"
            f"📍 Ҳолат: *{status}*\n"
            f"⏳ Дастрасӣ: *{access}*\n\n"
            f"🌐 Маълумоти пурра: {SITE_URL}"
        )

    return (
        "📊 *Мой аккаунт*\n\n"
        f"👤 Имя: *{first_name}*\n"
        f"🔗 Username: *@{username}*\n"
        f"🆔 ID: `{uid}`\n\n"
        f"📌 Тариф: *{plan_name}*\n"
        f"📍 Статус: *{status}*\n"
        f"⏳ Доступ: *{access}*\n\n"
        f"🌐 Полная информация: {SITE_URL}"
    )

# =========================
# ADMIN HELPERS
# =========================
def is_admin(uid: int) -> bool:
    # Если ADMIN_ID не задан — считаем админом всех (удобно для теста)
    if not ADMIN_ID:
        return True
    return str(uid) == str(ADMIN_ID)

def fmt_user_brief(update: Update) -> str:
    user = update.effective_user
    uid = user.id if user else 0
    username = f"@{user.username}" if user and user.username else "—"
    name = (user.full_name if user else "—")
    return f"{name} | {username} | ID: {uid}"

async def notify_admin(app: Application, text: str) -> None:
    if not ADMIN_ID:
        return
    try:
        await app.bot.send_message(chat_id=int(ADMIN_ID), text=text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.warning("Failed to notify admin: %s", e)

# =========================
# HANDLERS
# =========================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not update.message or not user:
        return

    # сохраняем профиль
    upsert_user(
        user.id,
        {
            "first_name": user.first_name,
            "last_name": user.last_name,
            "username": user.username,
            "started_ts": int(time.time()),
        },
    )

    # показываем выбор языка + меню
    await update.message.reply_text(
        t(user.id, "welcome"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=lang_inline(),
    )
    await update.message.reply_text(
        t(user.id, "choose_lang"),
        reply_markup=lang_inline(),
    )
    await update.message.reply_text("—", reply_markup=main_menu(user.id))

    await notify_admin(context.application, f"🆕 /start: *{fmt_user_brief(update)}*")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user = update.effective_user
    uid = user.id if user else 0
    await update.message.reply_text(
        "Команды:\n"
        "/start — запуск\n"
        "/help — помощь\n"
        "/approve USER_ID PLAN — подтвердить оплату (admin)\n"
        "/deny USER_ID PLAN — отказать (admin)\n"
        "/broadcast ТЕКСТ — рассылка (admin)\n",
        reply_markup=main_menu(uid),
    )

async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    admin = update.effective_user
    if not admin or not is_admin(admin.id):
        await update.message.reply_text("Нет доступа.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("Использование: /approve USER_ID PLAN (BASIC/PRO/VIP)")
        return

    uid_str, plan = context.args[0], context.args[1].upper()
    if plan not in PRICES:
        await update.message.reply_text("PLAN должен быть BASIC/PRO/VIP")
        return

    try:
        uid = int(uid_str)
    except ValueError:
        await update.message.reply_text("USER_ID должен быть числом")
        return

    set_purchase_status(uid, plan, "approved")
    await update.message.reply_text(f"✅ Подтверждено: {uid} → {plan}")

    # пользователю — на его языке
    lang = get_lang(uid)
    plan_name = PLAN_NAMES.get(plan, {}).get(lang, plan)

    try:
        msg = (
            ("✅ *Оплата подтверждена!*\n\n" if lang == "ru" else "✅ *Пардохт тасдиқ шуд!*\n\n")
            + f"Тариф: *{plan_name}*\n"
            + ("Доступ к урокам открыт.\n\nНажми «📚 Курсы» и начинай обучение." if lang == "ru"
               else "Дастрасӣ ба дарсҳо кушода шуд.\n\n«📚 Дарсҳо»-ро пахш кунед ва омӯзишро оғоз намоед.")
        )

        await context.application.bot.send_message(
            chat_id=uid,
            text=msg,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu(uid),
        )

        gi = groups_inline(uid, plan)
        if gi:
            await context.application.bot.send_message(
                chat_id=uid,
                text=("🔗 Ссылка на вашу группу:" if lang == "ru" else "🔗 Истинод ба гурӯҳи шумо:"),
                reply_markup=gi,
            )
    except Exception as e:
        logger.warning("Failed to message user %s: %s", uid, e)

async def cmd_deny(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    admin = update.effective_user
    if not admin or not is_admin(admin.id):
        await update.message.reply_text("Нет доступа.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("Использование: /deny USER_ID PLAN (BASIC/PRO/VIP)")
        return

    uid_str, plan = context.args[0], context.args[1].upper()
    if plan not in PRICES:
        await update.message.reply_text("PLAN должен быть BASIC/PRO/VIP")
        return

    try:
        uid = int(uid_str)
    except ValueError:
        await update.message.reply_text("USER_ID должен быть числом")
        return

    set_purchase_status(uid, plan, "denied")
    await update.message.reply_text(f"⛔ Отказано: {uid} → {plan}")

    lang = get_lang(uid)
    try:
        await context.application.bot.send_message(
            chat_id=uid,
            text=("⛔ *Статус оплаты: отказано*\n\nЕсли это ошибка — напиши в «👨‍💻 Поддержка» и прикрепи подтверждение оплаты."
                  if lang == "ru"
                  else "⛔ *Ҳолати пардохт: рад шуд*\n\nАгар хато бошад — ба «👨‍💻 Дастгирӣ» нависед ва далели пардохтро фиристед."),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu(uid),
        )
    except Exception as e:
        logger.warning("Failed to message user %s: %s", uid, e)

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    admin = update.effective_user
    if not admin or not is_admin(admin.id):
        await update.message.reply_text("Нет доступа.")
        return

    text = update.message.text or ""
    parts = text.split(" ", 1)
    if len(parts) < 2 or not parts[1].strip():
        await update.message.reply_text("Использование: /broadcast ТЕКСТ")
        return

    msg = parts[1].strip()
    users = _safe_read_json(USERS_PATH)
    sent = 0
    failed = 0

    for uid_str in users.keys():
        try:
            uid = int(uid_str)
            await context.application.bot.send_message(chat_id=uid, text=msg, reply_markup=main_menu(uid))
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(f"Рассылка завершена. Отправлено: {sent}, ошибок: {failed}")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return

    uid = user.id
    text = (update.message.text or "").strip()

    upsert_user(uid, {
        "first_name": user.first_name,
        "last_name": user.last_name,
        "username": user.username,
        "last_message": text,
        "last_message_ts": int(time.time()),
    })

    # language shortcut button
    if text in ("🌐 Language / Забон", "🌐 Language", "🌐 Забон", "🌐 Язык"):
        await update.message.reply_text(t(uid, "choose_lang"), reply_markup=lang_inline())
        return

    lang = get_lang(uid)

    if text == TEXTS["menu_courses"][lang]:
        await update.message.reply_text(
            courses_text(uid),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu(uid),
        )
        return

    if text == TEXTS["menu_buy"][lang]:
        await update.message.reply_text(
            t(uid, "buy_title"),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu(uid),
        )
        await update.message.reply_text(
            t(uid, "choose_plan_below"),
            reply_markup=plans_inline(uid),
        )
        await notify_admin(context.application, f"💳 Открыл покупку: *{fmt_user_brief(update)}*")
        return

    if text == TEXTS["menu_account"][lang]:
        await update.message.reply_text(
            account_text(uid),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu(uid),
        )
        return

    if text == TEXTS["menu_support"][lang]:
        await update.message.reply_text(
            t(uid, "support", tg=SUPPORT_TG, wa=SUPPORT_WA, site=SITE_URL),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu(uid),
        )
        return

    # если нет доступа — не даем контент
    if not user_has_access(uid):
        await update.message.reply_text(
            t(uid, "no_access", site=SITE_URL),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu(uid),
        )
        return

    # доступ активен
    await update.message.reply_text(t(uid, "access_active"), reply_markup=main_menu(uid))

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()

    user = update.effective_user
    if not user:
        return
    uid = user.id
    data = query.data or ""

    if data.startswith("lang:"):
        lang = data.split(":", 1)[1].strip().lower()
        set_lang(uid, lang)
        await query.edit_message_text(TEXTS["lang_set_tj"]["tj"] if lang == "tj" else TEXTS["lang_set_ru"]["ru"])
        await context.application.bot.send_message(chat_id=uid, text="—", reply_markup=main_menu(uid))
        return

    if data.startswith("plan:"):
        plan = data.split(":", 1)[1].upper()
        if plan not in PRICES:
            await query.edit_message_text("Ошибка тарифа.")
            return

        upsert_user(uid, {"last_selected_plan": plan, "last_selected_plan_ts": int(time.time())})

        await query.edit_message_text(
            plan_details(uid, plan),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=payment_inline(plan),
        )

        await notify_admin(
            context.application,
            f"📌 Выбрал тариф: *{plan}* | *{fmt_user_brief(update)}*\n"
            f"Цена акция: *{PRICES[plan]['promo']}{PRICES[plan]['currency']}* → обычно *{PRICES[plan]['regular']}{PRICES[plan]['currency']}*",
        )
        return

    if data.startswith("paid:"):
        plan = data.split(":", 1)[1].upper()
        if plan not in PRICES:
            await query.edit_message_text("Ошибка тарифа.")
            return

        set_purchase_status(uid, plan, "requested")

        p = PRICES[plan]
        cur = p["currency"]
        lang = get_lang(uid)

        await query.edit_message_text(
            ("✅ Заявка отправлена на проверку.\n\nАдминистратор проверит оплату и откроет доступ.\nЕсли нужно — напиши в «👨‍💻 Поддержка» и отправь подтверждение оплаты.\n\n"
             f"🌐 Детали: {SITE_URL}"
             if lang == "ru" else
             "✅ Дархост ба санҷиш фиристода шуд.\n\nАдмин пардохтро месанҷад ва дастрасиро мекушояд.\nАгар лозим бошад — ба «👨‍💻 Дастгирӣ» нависед ва далели пардохтро фиристед.\n\n"
             f"🌐 Тафсилот: {SITE_URL}")
        )

        await notify_admin(
            context.application,
            "🧾 *Новая заявка на оплату*\n\n"
            f"👤 {fmt_user_brief(update)}\n"
            f"📦 Тариф: *{PLAN_NAMES.get(plan, {}).get('ru', plan)}*\n"
            f"💰 Цена: *{p['promo']}{cur}* (акция) / *{p['regular']}{cur}* (обычно)\n"
            f"⏳ Доступ: *{p['access']['ru']}*\n\n"
            f"Команды:\n"
            f"`/approve {uid} {plan}`\n"
            f"`/deny {uid} {plan}`"
        )
        return

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled error: %s", context.error)

# =========================
# MAIN
# =========================
def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))

    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("deny", cmd_deny))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))

    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.add_error_handler(on_error)

    logger.info("Bot started")
import asyncio

async def main_async() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))

    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("deny", cmd_deny))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))

    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.add_error_handler(on_error)

    logger.info("Bot started")

    # Полный async запуск (исправление ошибки event loop в Python 3.14)
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    # Держим бота запущенным бесконечно
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main_async())

 
