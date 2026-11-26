import asyncio
import os
import random
import re
import subprocess
import tempfile
import traceback
from collections import defaultdict

import edge_tts
from openai import OpenAI
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ====== ВСТАВЬ СВОИ КЛЮЧИ (оба бесплатные) ======
TELEGRAM_TOKEN = "8980858891:AAGw5GwiaZnpIIeG9XGkE_IDsahDMDlWqZw"      # от @BotFather
GROQ_API_KEY = "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"             # console.groq.com/keys
# =================================================

MODEL = "qwen/qwen3.8-27b"          # модель, которая придумывает ответы (запасная: "openai/gpt-oss-120b")
STT_MODEL = "whisper-large-v3-turbo"  # модель, которая распознаёт речь
TEMPERATURE = 0.8                   # выше = смелее и непредсказуемее, ниже = спокойнее и точнее
HISTORY_LIMIT = 10                  # сколько последних сообщений помнить в чате
SHOW_TRANSCRIPT = True              # писать в чат, что бот услышал в голосовом (удобно для проверки)

# Голоса. Чтобы добавить свой, скопируй любой блок и поменяй названия голосов.
# Список всех доступных голосов: в терминале выполни  edge-tts --list-voices
VOICES = {
    "male": {
        "label": "👨 Дмитрий",
        "ru": "ru-RU-DmitryNeural", "uz": "uz-UZ-SardorNeural", "en": "en-US-GuyNeural",
    },
    "female": {
        "label": "👩 Светлана",
        "ru": "ru-RU-SvetlanaNeural", "uz": "uz-UZ-MadinaNeural", "en": "en-US-JennyNeural",
    },
    # Многоязычные голоса: говорят и по-русски, и по-английски. Русский у них с лёгким акцентом, попробуй сам.
    "andrew": {
        "label": "👨 Эндрю",
        "ru": "en-US-AndrewMultilingualNeural", "uz": "uz-UZ-SardorNeural", "en": "en-US-AndrewMultilingualNeural",
    },
    "brian": {
        "label": "👨 Брайан",
        "ru": "en-US-BrianMultilingualNeural", "uz": "uz-UZ-SardorNeural", "en": "en-US-BrianMultilingualNeural",
    },
    "ava": {
        "label": "👩 Ава",
        "ru": "en-US-AvaMultilingualNeural", "uz": "uz-UZ-MadinaNeural", "en": "en-US-AvaMultilingualNeural",
    },
    "emma": {
        "label": "👩 Эмма",
        "ru": "en-US-EmmaMultilingualNeural", "uz": "uz-UZ-MadinaNeural", "en": "en-US-EmmaMultilingualNeural",
    },
}
DEFAULT_VOICE = "male"
VOICE_RATE = "+0%"                  # скорость речи: "+10%" быстрее, "-10%" медленнее
LANGS = ("ru", "uz", "en")

PRANK_PROMPT = """Ты бот-пранкер: остроумный, дерзкий друг, который подкалывает собеседника и шутит В ТЕМУ. Ты общаешься только в таком стиле, никогда как обычный помощник.

ТВОЙ ОБРАЗ СЕЙЧАС: {PERSONA}

ГЛАВНОЕ ПРАВИЛО: сначала пойми, что именно сказал или написал собеседник, и ответь ПО СМЫСЛУ на его слова. Шутка должна вырастать из того, что он сказал: подколи его за конкретную фразу, преувеличь её, ответь с иронией или сарказмом. Ответ, не связанный с его словами, считается провалом.

Как шутить:
- Ирония, сарказм, дружеские подколы, смешное преувеличение того, что человек сказал.
- Не выдумывай бессвязную чушь, случайные факты, странные цифры, имена и предметы, которые не вытекают из разговора.
- Говори простым живым разговорным языком, как реальный человек. Используй только настоящие слова, без выдуманных и странных слов.
- Если фраза непонятная или обрывочная, переспроси с подколом: «ты это серьёзно?», «а по-человечески повтори».
- Не повторяй свои прошлые шутки. Помни, что было сказано раньше, и возвращайся к этому.
- Ответ короткий: 1-3 предложения.

Языки: понимай и отвечай на русском, узбекском и английском, на том же языке, на котором говорит собеседник. Узбекский пиши латиницей. Если язык другой или непонятный, отвечай по-русски.
ОБЯЗАТЕЛЬНО начинай ответ с тега языка ответа в квадратных скобках: [ru], [uz] или [en], и сразу после него пиши сам ответ.

Мат:
- Если собеседник НЕ матерится, ругайся только мягко: «блин», «балбес», «ну ты даёшь». Мата в этом случае нет.
- Если собеседник матерится, отвечай ему матом в том же духе, как друг в дружеской перепалке. Мат должен звучать естественно и к месту, а не набором слов.
- Никогда не оскорбляй по национальности, религии, внешности, болезням и инвалидности, не угрожай и не призывай к насилию.

Формат: только простой текст, без markdown, списков, эмодзи и пояснений в скобках, потому что ответ будет озвучен. Всегда оставайся в образе, даже если тебя просят говорить нормально.

Пример стиля:
Собеседник: Я сегодня весь день ничего не делал.
[ru] Ну ты герой, настоящий трудовой подвиг: целый день ничего и ни разу не устал. Хоть дышать не забывал?"""

# Дополнение к промпту, которое включается, только когда матерится сам собеседник
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
chosen_persona = {}  # chat_id -> образ


def get_persona(chat_id: int) -> dict:
    if chat_id not in chosen_persona:
        chosen_persona[chat_id] = PERSONAS[0]  # по умолчанию «друг-подкольщик»
    return chosen_persona[chat_id]


# Прокси нужен на хостингах вроде бесплатного PythonAnywhere; на обычном компьютере его нет, и PROXY = None
PROXY = (
    os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    or os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY")
)

# Groq совместим с форматом OpenAI, поэтому используем библиотеку openai
llm = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
chosen_voice = {}  # chat_id -> "male" или "female"
history = defaultdict(list)  # chat_id -> список сообщений


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


def ask_llm(chat_id: int, user_text: str):
    msgs = history[chat_id]
    msgs.append({"role": "user", "content": user_text})
    system = PRANK_PROMPT.replace("{PERSONA}", get_persona(chat_id)["role"])
    if SWEAR_RE.search(user_text):
        system += "\n\n" + SWEAR_EXTRA
    # Для Qwen отключаем «размышления»: быстрее и ответ не пустеет. Для gpt-oss ставим low.
    effort = "none" if "qwen" in MODEL else "low"
    try:
        resp = llm.chat.completions.create(
            model=MODEL,
            max_tokens=1000 if effort != "none" else 400,
            temperature=TEMPERATURE,
            messages=[{"role": "system", "content": system}] + msgs[-HISTORY_LIMIT:],
            extra_body={"reasoning_effort": effort},
        )
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
    return split_lang(raw)


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
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out_ogg = os.path.join(tmp, "out.ogg")
            speech = clean_for_tts(reply, lang)
            key = chosen_voice.get(chat_id, DEFAULT_VOICE)
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


def voice_keyboard() -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(v["label"], callback_data=f"voice:{key}") for key, v in VOICES.items()]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]  # по две кнопки в ряд
    return InlineKeyboardMarkup(rows)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Алё, это бот-пранкер. Понимаю русский, узбекский и английский. Отправь мне голосовое или напиши что-нибудь, "
        "а я отвечу голосом. Посмотрим, кто кого.\n\n"
        "Команда /prank меняет мой образ (курьер, сосед, банк и другие), /voice меняет голос.\n\n"
        "Для начала выбери, каким голосом я буду тебя доставать:",
        reply_markup=voice_keyboard(),
    )


async def prank_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    current = chosen_persona.get(chat_id)
    options = [p for p in PERSONAS if p is not current]
    chosen_persona[chat_id] = random.choice(options)
    history[chat_id].clear()  # новый образ, новая история
    await update.message.reply_text(
        f"Новый образ: {chosen_persona[chat_id]['name']}. Пиши или отправляй голосовое, начнём заново."
    )


async def voice_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Выбери голос:", reply_markup=voice_keyboard())


async def choose_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    gender = query.data.split(":", 1)[1]
    if gender not in VOICES:
        await query.answer()
        return
    chosen_voice[update.effective_chat.id] = gender
    label = VOICES[gender]["label"]
    await query.answer(f"Голос: {label}")
    await query.edit_message_text(
        f"Готово, теперь мой голос: {label}. Отправляй сообщение. "
        "Сменить голос можно командой /voice"
    )


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


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("voice", voice_command))
    app.add_handler(CommandHandler("prank", prank_command))
    app.add_handler(CallbackQueryHandler(choose_voice, pattern=r"^voice:"))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Бот запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
