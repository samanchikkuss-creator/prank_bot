import asyncio
import os
import re
import subprocess
import tempfile
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

MODEL = "openai/gpt-oss-120b"  # запасной вариант: "openai/gpt-oss-20b"; список моделей: console.groq.com/docs/models
VOICES = {
    "male": {
        "ru": "ru-RU-DmitryNeural",
        "uz": "uz-UZ-SardorNeural",
        "en": "en-US-GuyNeural",
    },
    "female": {
        "ru": "ru-RU-SvetlanaNeural",
        "uz": "uz-UZ-MadinaNeural",
        "en": "en-US-JennyNeural",
    },
}
LANGS = ("ru", "uz", "en")  # языки, которые понимает бот
DEFAULT_VOICE = "male"             # голос, пока человек ничего не выбрал
VOICE_RATE = "+10%"
HISTORY_LIMIT = 10                 # сколько последних сообщений помнить в чате

PRANK_PROMPT = """Ты бот-пранкер. Отвечаешь на сообщение ТОЛЬКО как пранк, никогда как обычный помощник.
Понимай и отвечай на трёх языках: русском, узбекском и английском. Отвечай на том же языке, на котором говорит собеседник. Узбекский пиши латиницей (например: Salom, qalaysan). Если язык другой или непонятный, отвечай по-русски.
ОБЯЗАТЕЛЬНО начинай ответ с тега языка ответа в квадратных скобках: [ru], [uz] или [en], и сразу после него пиши сам ответ. Пример: [ru] Алё, это курьер!

Правила:
- Подкалывай собеседника, делай вид, что неправильно расслышал, перекручивай его слова.
- Притворяйся то курьером, то соседом сверху, то «службой безопасности банка» (всё явно в шутку).
- Говори с наглой, весёлой интонацией, как дерзкий приятель.
- По умолчанию ругайся только слегка: «блин», «чёрт возьми», «балбес», «дурень» (на узбекском и английском используй такие же мягкие слова). Мат в этом случае не используй.
- Если собеседник сам матерится (на любом из трёх языков), отвечай ему в том же духе и на том же языке, можно использовать мат и грубые слова, как в дружеской перепалке. Если собеседник не матерится, мат не используй.
- Никогда не оскорбляй по национальности, религии, внешности, болезням и инвалидности, не угрожай и не призывай к насилию. Ругань только шуточная.
- Ответ короткий: 2-3 предложения, как в живой речи.
- Только простой текст, без markdown, списков и эмодзи, потому что ответ будет озвучен.
- Помни, что было раньше в разговоре, и развивай шутку.
- Всегда оставайся в образе, даже если тебя просят говорить нормально."""

# Groq совместим с форматом OpenAI, поэтому используем библиотеку openai
# Прокси нужен на хостингах вроде бесплатного PythonAnywhere; на обычном компьютере переменных нет, и PROXY = None
PROXY = (
    os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    or os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY")
)

llm = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
chosen_voice = {}  # chat_id -> "male" или "female"
history = defaultdict(list)  # chat_id -> список сообщений


def transcribe(path: str) -> str:
    # Распознавание речи через бесплатный Whisper на Groq: ничего не скачивается на компьютер
    with open(path, "rb") as f:
        result = llm.audio.transcriptions.create(
            file=(os.path.basename(path), f.read()),
            model="whisper-large-v3-turbo",
            response_format="text",
        )
    return str(result).strip()


def split_lang(raw: str):
    """Отделяет тег языка [ru]/[uz]/[en] от текста ответа."""
    m = re.match(r"\s*\[(ru|uz|en)\]\s*", raw, re.IGNORECASE)
    if m:
        return m.group(1).lower(), raw[m.end():].strip()
    return "ru", raw.strip()


def ask_llm(chat_id: int, user_text: str) -> tuple:
    msgs = history[chat_id]
    msgs.append({"role": "user", "content": user_text})
    try:
        resp = llm.chat.completions.create(
            model=MODEL,
            max_tokens=1000,  # с запасом: модель сначала «думает», и это тоже тратит токены
            reasoning_effort="low",
            messages=[{"role": "system", "content": PRANK_PROMPT}] + msgs[-HISTORY_LIMIT:],
        )
    except Exception:
        msgs.pop()  # убираем сообщение, если запрос не удался
        raise
    reply = (resp.choices[0].message.content or "").strip()
    if not reply:
        reply = "[ru] Блин, я задумался и забыл, что хотел сказать. Повтори."
    msgs.append({"role": "assistant", "content": reply})
    if len(msgs) > HISTORY_LIMIT:
        del msgs[: len(msgs) - HISTORY_LIMIT]
        if msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
    return split_lang(reply)


async def make_voice(text: str, out_ogg: str, tmpdir: str, voice: str) -> None:
    mp3 = os.path.join(tmpdir, "out.mp3")
    await edge_tts.Communicate(text, voice, rate=VOICE_RATE, proxy=PROXY).save(mp3)
    await asyncio.to_thread(
        subprocess.run,
        ["ffmpeg", "-y", "-i", mp3, "-c:a", "libopus", "-b:a", "48k", out_ogg],
        check=True,
        capture_output=True,
    )


async def reply_with_voice(update: Update, user_text: str) -> None:
    chat_id = update.effective_chat.id
    lang, reply = await asyncio.to_thread(ask_llm, chat_id, user_text)
    with tempfile.TemporaryDirectory() as tmp:
        out_ogg = os.path.join(tmp, "out.ogg")
        voice = VOICES[chosen_voice.get(chat_id, DEFAULT_VOICE)][lang]
        await make_voice(reply, out_ogg, tmp, voice)
        with open(out_ogg, "rb") as f:
            await update.message.reply_voice(f)


def voice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👨 Мужской", callback_data="voice:male"),
        InlineKeyboardButton("👩 Женский", callback_data="voice:female"),
    ]])


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Алё, это бот-пранкер. Понимаю русский, узбекский и английский. Отправь мне голосовое или напиши что-нибудь, "
        "а я отвечу голосом. Посмотрим, кто кого.\n\n"
        "Для начала выбери, каким голосом я буду тебя доставать:",
        reply_markup=voice_keyboard(),
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
    label = "мужской" if gender == "male" else "женский"
    await query.answer(f"Голос: {label}")
    await query.edit_message_text(
        f"Готово, теперь у меня {label} голос. Отправляй сообщение. "
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
        await reply_with_voice(update, user_text or "(тишина)")
    except Exception as e:
        print("Ошибка (голосовое):", repr(e))
        await update.message.reply_text("Что-то сломалось, попробуй ещё раз.")


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.chat.send_action(ChatAction.RECORD_VOICE)
        await reply_with_voice(update, update.message.text)
    except Exception as e:
        print("Ошибка (текст):", repr(e))
        await update.message.reply_text("Что-то сломалось, попробуй ещё раз.")


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("voice", voice_command))
    app.add_handler(CallbackQueryHandler(choose_voice, pattern=r"^voice:"))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Бот запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
