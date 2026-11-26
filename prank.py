import asyncio
import json
import os
import random
import re
import subprocess
import tempfile
import threading
import traceback
from collections import defaultdict
from datetime import datetime, timedelta

import edge_tts
from openai import OpenAI
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

# ====== ВСТАВЬ СВОИ КЛЮЧИ (оба бесплатные) ======
TELEGRAM_TOKEN = "8980858891:AAGw5GwiaZnpIIeG9XGkE_IDsahDMDlWqZw"      # от @BotFather
GROQ_API_KEY = "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"             # console.groq.com/keys
# =================================================

# Твой Telegram ID: отправь боту /myid и впиши число сюда.
# Пока ADMIN_ID = 0, бот открыт для ВСЕХ, а команды администратора не работают.
# Когда ID указан, бот отвечает только тебе и тем, кому ты выдал доступ командой /allow.
ADMIN_ID = 0

MODEL = "qwen/qwen3.8-27b"          # модель, которая придумывает ответы (запасная: "openai/gpt-oss-120b")
STT_MODEL = "whisper-large-v3-turbo"  # модель, которая распознаёт речь
TEMPERATURE = 0.8                   # выше = смелее и непредсказуемее, ниже = спокойнее и точнее
HISTORY_LIMIT = 30                  # сколько последних сообщений помнить в чате
THINKING = "low"                    # размышление перед ответом: "none" выкл (быстро), "low", "medium", "high"
FACTS_EVERY = 4                     # раз в сколько сообщений бот обновляет «записную книжку» о собеседнике
SHOW_TRANSCRIPT = True              # писать в чат, что бот услышал в голосовом (удобно для проверки)

# Голоса. Чтобы добавить свой, скопируй любой блок и поменяй названия голосов.
# Список всех доступных голосов: в терминале выполни  edge-tts --list-voices
VOICES = {
    "female": {
        "label": "👩 Светлана",
        "ru": "ru-RU-SvetlanaNeural", "uz": "uz-UZ-MadinaNeural", "en": "en-US-JennyNeural",
    },
    # Многоязычный голос: говорит и по-русски, и по-английски (по-русски с лёгким акцентом)
    "andrew": {
        "label": "👨 Эндрю",
        "ru": "en-US-AndrewMultilingualNeural", "uz": "uz-UZ-SardorNeural", "en": "en-US-AndrewMultilingualNeural",
    },
}
DEFAULT_VOICE = "female"
VOICE_RATE = "+0%"                  # скорость речи: "+10%" быстрее, "-10%" медленнее
LANGS = ("ru", "uz", "en")

PRANK_PROMPT = """Ты бот-пранкер: остроумный, дерзкий друг, который подкалывает собеседника и шутит В ТЕМУ. Ты общаешься только в таком стиле, никогда как обычный помощник.

ТВОЙ ОБРАЗ СЕЙЧАС: {PERSONA}

ГЛАВНОЕ ПРАВИЛО: сначала пойми, что именно сказал или написал собеседник, и ответь ПО СМЫСЛУ на его слова. Шутка должна вырастать из того, что он сказал: подколи его за конкретную фразу, преувеличь её, ответь с иронией или сарказмом. Ответ, не связанный с его словами, считается провалом.

Как шутить:
- Ирония, сарказм, дружеские подколы, смешное преувеличение того, что человек сказал.
- Острота подколов: {HARSH}
- Не выдумывай бессвязную чушь, случайные факты, странные цифры, имена и предметы, которые не вытекают из разговора.
- Говори простым живым разговорным языком, как реальный человек. Используй только настоящие слова, без выдуманных и странных слов.
- Если фраза непонятная или обрывочная, переспроси с подколом: «ты это серьёзно?», «а по-человечески повтори».
- Не повторяй свои прошлые шутки. Помни, что было сказано раньше, и возвращайся к этому.
- Говори как живой человек: короткие фразы, «ну», «слушай», «блин», эмоции. Иногда задавай встречный вопрос про самого собеседника.
- Если человеку по-настоящему плохо, грустно или тяжело, не подкалывай: ответь тепло и по-человечески, поддержи, и только потом, если уместно, добавь лёгкую шутку.
- Ответ короткий: 1-3 предложения.

Языки: понимай и отвечай на русском, узбекском и английском, на том же языке, на котором говорит собеседник. Узбекский пиши латиницей. Если язык другой или непонятный, отвечай по-русски.
ОБЯЗАТЕЛЬНО начинай ответ с тега языка ответа в квадратных скобках: [ru], [uz] или [en], и сразу после него пиши сам ответ.

{MAT_RULES}

Формат: только простой текст, без markdown, списков, эмодзи и пояснений в скобках, потому что ответ будет озвучен. Всегда оставайся в образе, даже если тебя просят говорить нормально.

Примеры стиля (не копируй, а следуй манере):
Собеседник: Я сегодня весь день ничего не делал.
[ru] Ну ты герой, настоящий трудовой подвиг: целый день ничего и ни разу не устал. Хоть дышать не забывал?
Собеседник: Что приготовить на ужин?
[ru] О, шеф-повар на связи. Яичница, конечно, вершина твоей кухни, или сегодня рискнёшь и купишь пельмени?
Собеседник: Я проспал работу.
[ru] Ну это уже не опоздание, а смелый эксперимент. Будильник хоть жив после такого предательства?
Собеседник: э ну это там короче
[ru] Мощно сказал, прямо Толстой. А по-человечески, что ты хотел?
Собеседник: Мне сегодня как-то грустно.
[ru] Эй, что случилось? Давай без шуток, рассказывай, я слушаю.
Собеседник: Salom, bugun nima qilyapsan?
[uz] Salom! Men hech narsa qilmayapman, sen esa yana ishdan qochib yuribsan, to'g'rimi?
Собеседник: I think I'll start going to the gym tomorrow.
[en] Tomorrow, huh? That's the same tomorrow you promised last month. The gym is still waiting, and so is the dust on your sneakers."""

# Правила остроты подколов (переключается в настройках)
HARSH_RULES = {
    "soft": "очень мягкие и добрые: больше тёплого юмора, почти без колкостей.",
    "normal": "дружеские, средней остроты.",
    "hard": "жёсткие и язвительные, как у очень близкого друга: сарказм на полную, без пощады к словам собеседника "
            "(но без оскорблений по национальности, религии, внешности, болезням и без угроз).",
}
HARSH_LABELS = {"soft": "Мягко", "normal": "Нормально", "hard": "Жёстко"}

# Правила мата (переключается в настройках кнопкой «Мат»)
MAT_ON_RULES = """Мат:
- Если собеседник НЕ матерится, ругайся только мягко: «блин», «балбес», «ну ты даёшь». Мата в этом случае нет.
- Если собеседник матерится, отвечай ему матом в том же духе, как друг в дружеской перепалке. Мат должен звучать естественно и к месту, а не набором слов.
- Никогда не оскорбляй по национальности, религии, внешности, болезням и инвалидности, не угрожай и не призывай к насилию.
Пример ответа на мат:
Собеседник: Блин, опять эта работа достала, пиздец.
[ru] Бля, ну пиздец так пиздец, ты же сам туда каждый день ходишь, как на дежурство. Или увольняйся, или хватит ныть, я это слышу уже третий раз."""

MAT_OFF_RULES = """Мат:
- Мат и грубая брань ЗАПРЕЩЕНЫ полностью, даже если собеседник сам матерится. Отвечай без мата, можешь шутливо заметить, что тут без выражений.
- Допустимы только самые мягкие слова вроде «блин» и «балбес».
- Никогда не оскорбляй по национальности, религии, внешности, болезням и инвалидности, не угрожай и не призывай к насилию."""

# Дополнение к промпту, которое включается, только когда матерится сам собеседник (и мат включён)
SWEAR_EXTRA = """ВНИМАНИЕ: собеседник только что выматерился. Ответь ему матом в том же духе и на том же языке, как друг в перепалке: используй к месту 1-3 крепких выражения (по-русски, например: бля, пиздец, охуеть, хуйня, нахуй, ёб твою мать; по-английски: shit, fuck, bullshit; по-узбекски: грубые разговорные слова). Подколи его в ответ по смыслу его слов. Не оскорбляй по национальности, религии, внешности и болезням."""

SWEAR_RE = re.compile(
    r"(?<!\w)(хуй|хуе|хуё|хуи|хуя|пизд|ебан|ебат|ебал|ебу|ёба|ёбн|бля|сук[аиу](?!\w)|мудак|мудил|залуп|гандон|долбоеб|долбоёб"
    r"|fuck|shit|bitch|asshole|bullshit|motherfuck"
    r"|siktir|qo'?taq|jalab|onangni|ammangni)",
    re.IGNORECASE,
)

# Образы: во всех главное правило «отвечать по смыслу на слова собеседника» остаётся
PERSONAS = [
    {"name": "Друг-подкольщик",
     "role": "остроумный друг, который по-доброму подкалывает собеседника и шутит по теме."},
    {"name": "Курьер",
     "role": "курьер, который будто бы звонит по поводу заказа и ловко превращает слова собеседника в проблему с доставкой. Но всегда отвечай по смыслу на его слова."},
    {"name": "Сосед сверху",
     "role": "ворчливый сосед сверху, который уверен, что собеседник ему мешает, и цепляется к каждому его слову. Но всегда отвечай по смыслу на его слова."},
    {"name": "Служба безопасности банка",
     "role": "очень серьёзный «сотрудник службы безопасности банка», который подозрительно допрашивает собеседника по поводу его слов. Но всегда отвечай по смыслу на его слова."},
    {"name": "Таксист",
     "role": "таксист-диспетчер, который невозмутимо врёт про время подачи машины и комментирует всё, что говорит собеседник. Но всегда отвечай по смыслу на его слова."},
    {"name": "Экстрасенс",
     "role": "экстрасенс, который «видит» собеседника насквозь и самоуверенно делает выводы из его слов, при этом смешно ошибаясь. Но всегда отвечай по смыслу на его слова."},
    {"name": "Строгая директриса",
     "role": "строгая директриса школы, которая отчитывает собеседника за каждое слово, как за плохое поведение. Но всегда отвечай по смыслу на его слова."},
]

# Запрос, по которому бот ведёт «записную книжку» о собеседнике
FACTS_PROMPT = """Ты ведёшь краткую записную книжку о собеседнике чат-бота.
Тебе дают уже известные факты и новый фрагмент диалога. Верни ОБНОВЛЁННЫЙ список фактов о собеседнике.
Записывай только устойчивое и полезное для будущих разговоров: имя, возраст, город, работа или учёба, хобби, близкие люди, питомцы, планы, важные события, что любит и не любит.
Не записывай мимолётное настроение и не выдумывай. Каждый факт: короткая фраза до 100 символов.
Не больше 15 фактов: если их больше, оставь самые важные. Верни ТОЛЬКО список, по одному факту на строке, без нумерации и пояснений.
Если фактов нет, верни пустой ответ."""

# Прокси нужен на хостингах вроде бесплатного PythonAnywhere; на обычном компьютере его нет, и PROXY = None
PROXY = (
    os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    or os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY")
)

# Groq совместим с форматом OpenAI, поэтому используем библиотеку openai
llm = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")

# ---------- Память бота (файл memory.json рядом со скриптом) ----------
# Хранит: историю разговоров, факты о собеседниках, настройки каждого чата и список разрешённых людей.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "memory.json")
STATS_FILE = os.path.join(BASE_DIR, "activity.json")
state_lock = threading.Lock()


def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}

    def int_keys(d: dict) -> dict:
        return {int(k): v for k, v in d.items()}

    return {
        "history": int_keys(data.get("history", {})),   # chat_id -> сообщения
        "facts": int_keys(data.get("facts", {})),       # chat_id -> факты о собеседнике
        "settings": int_keys(data.get("settings", {})),  # chat_id -> настройки
        "allowed": [int(x) for x in data.get("allowed", [])],  # кому выдан доступ
    }


state = load_state()


def save_state() -> None:
    with state_lock:
        try:
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)
            os.replace(tmp, STATE_FILE)
        except Exception as e:
            print("Не удалось сохранить память:", repr(e))


def get_history(chat_id: int) -> list:
    return state["history"].setdefault(chat_id, [])


def setting(chat_id: int, key: str):
    saved = state["settings"].get(chat_id, {})
    if key in saved:
        return saved[key]
    defaults = {
        "voice": DEFAULT_VOICE,
        "persona": PERSONAS[0]["name"],
        "harsh": "normal",
        # мат по умолчанию включён только у администратора (а если ADMIN_ID не задан, у всех)
        "mat": (chat_id == ADMIN_ID) if ADMIN_ID else True,
    }
    return defaults[key]


def set_setting(chat_id: int, key: str, value) -> None:
    state["settings"].setdefault(chat_id, {})[key] = value
    save_state()


def get_persona(chat_id: int) -> dict:
    name = setting(chat_id, "persona")
    return next((p for p in PERSONAS if p["name"] == name), PERSONAS[0])


# ---------- Статистика активности (файл activity.json) ----------
def load_stats() -> dict:
    try:
        with open(STATS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


stats = load_stats()  # id пользователя (строкой) -> данные о нём


def save_stats() -> None:
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Не удалось сохранить статистику:", repr(e))


def message_kind(msg) -> str:
    if msg.voice:
        return "голосовое"
    if msg.text and msg.text.startswith("/"):
        return "команда"
    if msg.text:
        return "текст"
    return "другое"


# ---------- Распознавание, язык, очистка текста ----------
def transcribe(path: str) -> str:
    # Распознавание речи через бесплатный Whisper на Groq: ничего не скачивается на компьютер
    with open(path, "rb") as f:
        result = llm.audio.transcriptions.create(
            file=(os.path.basename(path), f.read()),
            model=STT_MODEL,
            response_format="text",
        )
    return str(result).strip()


def guess_lang(text: str) -> str:
    """Запасной способ определить язык, если модель забыла поставить тег."""
    low = text.lower()
    if re.search(r"[а-яё]", low):
        return "ru"
    if re.search(r"o['ʻ’`]|g['ʻ’`]|\b(salom|qalay|men|sen|siz|bor|yo'?q|nima|va|uchun|bilan|emas|rahmat)\b", low):
        return "uz"
    return "en"


def split_lang(raw: str):
    """Отделяет тег языка [ru]/[uz]/[en] от текста ответа."""
    m = re.match(r"\s*\[(ru|uz|en)[^\]]*\]\s*", raw, re.IGNORECASE)
    if m:
        return m.group(1).lower(), raw[m.end():].strip()
    return guess_lang(raw), raw.strip()


def clean_for_tts(text: str, lang: str) -> str:
    """Убирает всё, что озвучка читает странно: markdown, эмодзи, лишние знаки."""
    text = re.sub(r"[*_`#~<>|]", "", text)
    text = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27BF\u2B00-\u2BFF]", "", text)
    text = text.replace("...", ", ").replace("…", ", ")
    if lang == "uz":
        text = re.sub(r"[ʻʼ’‘`]", "'", text)
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"\s+([,.!?])", r"\1", text).strip()


# ---------- Запросы к модели ----------
def complete(messages: list, effort: str, temperature: float = None, max_tokens: int = None):
    extra = {"reasoning_effort": effort}
    if "qwen" in MODEL and effort != "none":
        extra["reasoning_format"] = "hidden"  # размышления не попадают в ответ
    return llm.chat.completions.create(
        model=MODEL,
        max_tokens=max_tokens or (1500 if effort != "none" else 400),  # размышление тоже тратит токены
        temperature=TEMPERATURE if temperature is None else temperature,
        messages=messages,
        extra_body=extra,
    )


def build_system(chat_id: int, user_text: str) -> str:
    mat = setting(chat_id, "mat")
    system = (
        PRANK_PROMPT
        .replace("{PERSONA}", get_persona(chat_id)["role"])
        .replace("{HARSH}", HARSH_RULES[setting(chat_id, "harsh")])
        .replace("{MAT_RULES}", MAT_ON_RULES if mat else MAT_OFF_RULES)
    )
    facts = state["facts"].get(chat_id)
    if facts:
        system += (
            "\n\nЧто ты знаешь о собеседнике (используй естественно и к месту, как друг, "
            "не пересказывай списком): " + "; ".join(facts)
        )
    if mat and SWEAR_RE.search(user_text):
        system += "\n\n" + SWEAR_EXTRA
    return system


def ask_llm(chat_id: int, user_text: str):
    msgs = get_history(chat_id)
    msgs.append({"role": "user", "content": user_text})
    effort = THINKING if "qwen" in MODEL else "low"
    full = [{"role": "system", "content": build_system(chat_id, user_text)}] + msgs[-HISTORY_LIMIT:]
    try:
        try:
            resp = complete(full, effort)
        except Exception as e:
            if effort == "none":
                raise
            print("Размышление не сработало, отвечаю без него:", repr(e))
            resp = complete(full, "none")
    except Exception:
        msgs.pop()  # убираем сообщение, если запрос не удался
        raise
    raw = resp.choices[0].message.content or ""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if not raw:
        raw = "[ru] Блин, я задумался и забыл, что хотел сказать. Повтори, а?"
    msgs.append({"role": "assistant", "content": raw})
    if len(msgs) > HISTORY_LIMIT:
        del msgs[: len(msgs) - HISTORY_LIMIT]
        if msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
    save_state()
    return split_lang(raw)


def extract_facts(chat_id: int) -> None:
    """Обновляет «записную книжку» о собеседнике по последним сообщениям."""
    old = state["facts"].get(chat_id, [])
    lines = []
    for m in get_history(chat_id)[-8:]:
        who = "Собеседник" if m["role"] == "user" else "Бот"
        text = re.sub(r"^\s*\[(ru|uz|en)[^\]]*\]\s*", "", m["content"], flags=re.IGNORECASE)
        lines.append(f"{who}: {text}")
    prompt = (
        "Известные факты:\n" + ("\n".join(old) if old else "(пока нет)")
        + "\n\nНовый фрагмент диалога:\n" + "\n".join(lines)
    )
    resp = complete(
        [{"role": "system", "content": FACTS_PROMPT}, {"role": "user", "content": prompt}],
        "none" if "qwen" in MODEL else "low",
        temperature=0.2,
    )
    raw = re.sub(r"<think>.*?</think>", "", resp.choices[0].message.content or "", flags=re.DOTALL)
    facts = []
    for line in raw.splitlines():
        line = re.sub(r"^[\s\-•*\d.)]+", "", line).strip()
        if line and line.lower() not in ("нет", "пусто", "(пока нет)", "none"):
            facts.append(line[:120])
    if facts or not old:
        state["facts"][chat_id] = facts[:15]
        save_state()


facts_counter = defaultdict(int)
facts_running = set()
background_tasks = set()


def schedule_facts_update(chat_id: int) -> None:
    facts_counter[chat_id] += 1
    if facts_counter[chat_id] % FACTS_EVERY or chat_id in facts_running:
        return
    facts_running.add(chat_id)

    async def job():
        try:
            await asyncio.to_thread(extract_facts, chat_id)
        except Exception as e:
            print("Не удалось обновить память о собеседнике:", repr(e))
        finally:
            facts_running.discard(chat_id)

    task = asyncio.create_task(job())
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


# ---------- Озвучка и ответ ----------
async def make_voice(text: str, out_ogg: str, tmpdir: str, voice: str) -> None:
    mp3 = os.path.join(tmpdir, "out.mp3")
    try:
        await edge_tts.Communicate(text, voice, rate=VOICE_RATE, proxy=PROXY).save(mp3)
    except Exception as e:
        # некоторые голоса капризничают из-за параметров, пробуем без них
        print("Озвучка с параметрами не вышла, пробую без них:", repr(e))
        await edge_tts.Communicate(text, voice, proxy=PROXY).save(mp3)
    await asyncio.to_thread(
        subprocess.run,
        ["ffmpeg", "-y", "-i", mp3, "-c:a", "libopus", "-b:a", "48k", out_ogg],
        check=True,
        capture_output=True,
    )


async def reply_with_voice(update: Update, user_text: str) -> None:
    chat_id = update.effective_chat.id
    lang, reply = await asyncio.to_thread(ask_llm, chat_id, user_text)
    schedule_facts_update(chat_id)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out_ogg = os.path.join(tmp, "out.ogg")
            speech = clean_for_tts(reply, lang)
            key = setting(chat_id, "voice")
            if key not in VOICES:
                key = DEFAULT_VOICE
            try:
                await make_voice(speech, out_ogg, tmp, VOICES[key][lang])
            except Exception as e:
                if key == DEFAULT_VOICE:
                    raise
                print("Выбранный голос не сработал, беру основной:", repr(e))
                await make_voice(speech, out_ogg, tmp, VOICES[DEFAULT_VOICE][lang])
            with open(out_ogg, "rb") as f:
                await update.message.reply_voice(f)
    except Exception as e:
        # если озвучка сломалась, всё равно отвечаем текстом, а подробности пишем в консоль
        traceback.print_exc()
        await update.message.reply_text(f"{reply}\n\n(озвучить не получилось: {type(e).__name__})")


# ---------- Настройки (голос, жёсткость, мат, образ) ----------
# Постоянные кнопки под полем ввода, чтобы не печатать команды вручную
MAIN_KEYBOARD = ReplyKeyboardMarkup([["⚙ Настройки", "🎭 Образ"]], resize_keyboard=True)


def settings_text(chat_id: int) -> str:
    voice = VOICES[setting(chat_id, "voice")]["label"] if setting(chat_id, "voice") in VOICES else "?"
    return (
        "⚙ Настройки\n\n"
        f"Голос: {voice}\n"
        f"Жёсткость подколов: {HARSH_LABELS[setting(chat_id, 'harsh')]}\n"
        f"Мат: {'включён' if setting(chat_id, 'mat') else 'выключен'}\n"
        f"Образ: {get_persona(chat_id)['name']}"
    )


def settings_markup(chat_id: int) -> InlineKeyboardMarkup:
    voice, harsh, mat = setting(chat_id, "voice"), setting(chat_id, "harsh"), setting(chat_id, "mat")

    def mark(active: bool, text: str) -> str:
        return ("✅ " if active else "") + text

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(mark(voice == k, v["label"]), callback_data=f"set:voice:{k}") for k, v in VOICES.items()],
        [InlineKeyboardButton(mark(harsh == k, label), callback_data=f"set:harsh:{k}") for k, label in HARSH_LABELS.items()],
        [InlineKeyboardButton("🤬 Мат: " + ("вкл" if mat else "выкл"), callback_data="set:mat:toggle")],
        [InlineKeyboardButton("🎭 Сменить образ", callback_data="set:persona:next")],
    ])


def rotate_persona(chat_id: int) -> dict:
    current = get_persona(chat_id)
    new = random.choice([p for p in PERSONAS if p is not current])
    set_setting(chat_id, "persona", new["name"])
    get_history(chat_id).clear()  # новый образ, новая история разговора (факты о тебе остаются)
    save_state()
    return new


async def settings_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(settings_text(chat_id), reply_markup=settings_markup(chat_id))


async def settings_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = update.effective_chat.id
    try:
        _, kind, value = query.data.split(":", 2)
    except ValueError:
        await query.answer()
        return
    if kind == "voice" and value in VOICES:
        set_setting(chat_id, "voice", value)
    elif kind == "harsh" and value in HARSH_RULES:
        set_setting(chat_id, "harsh", value)
    elif kind == "mat":
        set_setting(chat_id, "mat", not setting(chat_id, "mat"))
    elif kind == "persona":
        rotate_persona(chat_id)
    await query.answer("Готово")
    try:
        await query.edit_message_text(settings_text(chat_id), reply_markup=settings_markup(chat_id))
    except Exception:
        pass  # Telegram ругается, если текст не изменился


async def prank_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    new = rotate_persona(update.effective_chat.id)
    await update.message.reply_text(f"Новый образ: {new['name']}. Пиши или отправляй голосовое, начнём заново.")


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        "Алё, это бот-пранкер. Понимаю русский, узбекский и английский. Отправь мне голосовое или напиши что-нибудь, "
        "а я отвечу голосом. Посмотрим, кто кого.\n\n"
        "Кнопки внизу: «⚙ Настройки» (голос, жёсткость подколов, мат) и «🎭 Образ» (курьер, сосед, банк и другие).\n"
        "Я запоминаю, что ты рассказываешь о себе. Посмотреть: /memory, стереть: /forget.",
        reply_markup=MAIN_KEYBOARD,
    )
    await update.message.reply_text(
        "Для начала настрой меня под себя:", reply_markup=settings_markup(chat_id)
    )


# ---------- Память о собеседнике ----------
async def memory_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    facts = state["facts"].get(update.effective_chat.id)
    if not facts:
        await update.message.reply_text("Пока я ничего о тебе не запомнил. Расскажи что-нибудь о себе.")
        return
    await update.message.reply_text("Вот что я о тебе запомнил:\n" + "\n".join(f"• {f}" for f in facts))


async def forget_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state["facts"].pop(chat_id, None)
    get_history(chat_id).clear()
    save_state()
    await update.message.reply_text("Всё стёр: и факты о тебе, и наш разговор. Знакомимся заново.")


# ---------- Доступ только для своих ----------
notified_blocked = set()


def is_admin(update: Update) -> bool:
    return bool(ADMIN_ID) and update.effective_user is not None and update.effective_user.id == ADMIN_ID


def is_allowed(user_id: int) -> bool:
    return (not ADMIN_ID) or user_id == ADMIN_ID or user_id in state["allowed"]


async def gate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Не пускает посторонних: бот не отвечает им и не тратит на них бесплатный лимит."""
    user = update.effective_user
    if not user or is_allowed(user.id):
        return
    if user.id not in notified_blocked:  # сообщаем один раз, чтобы не спамить
        notified_blocked.add(user.id)
        name = " ".join(filter(None, [user.first_name, user.last_name])) or "без имени"
        try:
            if update.message:
                await update.message.reply_text("Это приватный бот: доступ только по приглашению.")
            await ctx.bot.send_message(
                ADMIN_ID,
                f"🚪 {name} (@{user.username or 'нет'}, id {user.id}) пытается писать боту.\n"
                f"Разрешить: /allow {user.id}",
            )
        except Exception as e:
            print("Не удалось сообщить о попытке доступа:", repr(e))
    raise ApplicationHandlerStop


async def allow_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("Использование: /allow 123456789 (ID человека, он узнаёт его командой /myid)")
        return
    uid = int(ctx.args[0])
    if uid not in state["allowed"]:
        state["allowed"].append(uid)
        save_state()
    await update.message.reply_text(f"Доступ выдан: {uid}")
    try:
        await ctx.bot.send_message(uid, "Тебе дали доступ к боту. Нажми /start")
    except Exception:
        pass  # человек мог ещё ни разу не писать боту


async def deny_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("Использование: /deny 123456789")
        return
    uid = int(ctx.args[0])
    if uid in state["allowed"]:
        state["allowed"].remove(uid)
        save_state()
    notified_blocked.discard(uid)
    await update.message.reply_text(f"Доступ закрыт: {uid}")


async def allowed_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not state["allowed"]:
        await update.message.reply_text("Список пуст: бот отвечает только тебе.")
        return
    lines = []
    for uid in state["allowed"]:
        rec = stats.get(str(uid))
        who = f"{rec['name']} (@{rec['username']})" if rec and rec.get("username") else (rec["name"] if rec else "имя неизвестно")
        lines.append(f"• {uid}: {who}")
    await update.message.reply_text("Кому разрешено:\n" + "\n".join(lines))


# ---------- Сообщения ----------
async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.chat.send_action(ChatAction.RECORD_VOICE)
        file = await update.message.voice.get_file()
        with tempfile.TemporaryDirectory() as tmp:
            in_ogg = os.path.join(tmp, "in.ogg")
            await file.download_to_drive(in_ogg)
            user_text = await asyncio.to_thread(transcribe, in_ogg)
        if SHOW_TRANSCRIPT and user_text:
            await update.message.reply_text(f"🎤 Я услышал: {user_text}")
        await reply_with_voice(update, user_text or "(тишина)")
    except Exception as e:
        traceback.print_exc()
        await update.message.reply_text(f"Что-то сломалось ({type(e).__name__}), попробуй ещё раз.")


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.chat.send_action(ChatAction.RECORD_VOICE)
        await reply_with_voice(update, update.message.text)
    except Exception as e:
        traceback.print_exc()
        await update.message.reply_text(f"Что-то сломалось ({type(e).__name__}), попробуй ещё раз.")


async def track(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Записывает, кто и что отправил боту (сами тексты сообщений в статистику не попадают)."""
    try:
        user = update.effective_user
        if not user or not update.message:
            return
        now = datetime.now().isoformat(timespec="seconds")
        uid = str(user.id)
        name = " ".join(filter(None, [user.first_name, user.last_name])) or "без имени"
        kind = message_kind(update.message)
        is_new = uid not in stats
        rec = stats.setdefault(uid, {"first_seen": now, "messages": 0, "voices": 0})
        rec.update(name=name, username=user.username or "", last_seen=now)
        rec["messages"] += 1
        if kind == "голосовое":
            rec["voices"] += 1
        save_stats()
        print(f"[{now}] {name} (@{user.username}, id {user.id}): {kind}")
        if is_new and ADMIN_ID and user.id != ADMIN_ID:
            await ctx.bot.send_message(
                ADMIN_ID, f"🆕 Новый пользователь: {name} (@{user.username or 'нет'}, id {user.id})"
            )
    except Exception as e:
        print("Ошибка учёта статистики:", repr(e))


async def myid_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Твой Telegram ID: {update.effective_user.id}")


async def stats_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID:
        await update.message.reply_text("ADMIN_ID не задан. Отправь /myid и впиши это число в файл бота.")
        return
    if not is_admin(update):
        return  # посторонним не отвечаем
    if not stats:
        await update.message.reply_text("Пока никто не писал боту.")
        return
    day_ago = datetime.now() - timedelta(hours=24)
    active = [r for r in stats.values() if datetime.fromisoformat(r["last_seen"]) > day_ago]
    total_msgs = sum(r["messages"] for r in stats.values())
    total_voices = sum(r["voices"] for r in stats.values())

    def label(r: dict) -> str:
        return f"{r['name']} (@{r['username']})" if r["username"] else r["name"]

    top = sorted(stats.values(), key=lambda r: r["messages"], reverse=True)[:5]
    recent = sorted(stats.values(), key=lambda r: r["last_seen"], reverse=True)[:5]
    lines = [
        f"👥 Пользователей всего: {len(stats)}",
        f"🟢 Активны за 24 часа: {len(active)}",
        f"💬 Сообщений всего: {total_msgs} (из них голосовых: {total_voices})",
        "",
        "🏆 Самые активные:",
        *[f"{i}. {label(r)}: {r['messages']}" for i, r in enumerate(top, 1)],
        "",
        "🕒 Последние заходили (время сервера):",
        *[f"• {label(r)}: {r['last_seen'].replace('T', ' ')}" for r in recent],
    ]
    await update.message.reply_text("\n".join(lines))


async def post_init(app: Application):
    try:
        await app.bot.set_my_commands([
            BotCommand("start", "Начать заново"),
            BotCommand("settings", "Голос, жёсткость, мат"),
            BotCommand("prank", "Сменить образ пранкера"),
            BotCommand("memory", "Что бот обо мне помнит"),
            BotCommand("forget", "Забыть всё обо мне"),
        ])
    except Exception as e:
        print("Не удалось установить меню команд:", repr(e))


def main():
    if not ADMIN_ID:
        print("ВНИМАНИЕ: ADMIN_ID не задан. Бот открыт для всех, а /stats, /allow и уведомления не работают.")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(TypeHandler(Update, gate), group=-2)   # сначала проверяем, можно ли человеку пользоваться ботом
    app.add_handler(TypeHandler(Update, track), group=-1)  # учёт активности
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("voice", settings_command))  # старая команда ведёт в настройки
    app.add_handler(CommandHandler("prank", prank_command))
    app.add_handler(CommandHandler("memory", memory_command))
    app.add_handler(CommandHandler("forget", forget_command))
    app.add_handler(CommandHandler("myid", myid_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("allow", allow_command))
    app.add_handler(CommandHandler("deny", deny_command))
    app.add_handler(CommandHandler("allowed", allowed_command))
    app.add_handler(CallbackQueryHandler(settings_callback, pattern=r"^set:"))
    app.add_handler(MessageHandler(filters.Regex(r"^(🎙 Голос|⚙ Настройки)$"), settings_command))
    app.add_handler(MessageHandler(filters.Regex(r"^🎭 Образ$"), prank_command))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Бот запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
