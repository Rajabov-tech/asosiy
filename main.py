# bot.py
import os
import logging
import sqlite3
import aiohttp
import openai
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types.message import ContentType
from PIL import Image
from io import BytesIO

# --- CONFIGURATION: SEN BU YERGA O'Z TOKENLARINGNI JOYLASHING ---
TELEGRAM_BOT_TOKEN = ""
OPENAI_API_KEY = ""
# --------------------------------------------------------------

# logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# OpenAI init
openai.api_key = OPENAI_API_KEY

# Telegram bot init
bot = Bot(token=TELEGRAM_BOT_TOKEN, parse_mode=types.ParseMode.HTML)
dp = Dispatcher(bot)

# Database (simple SQLite) - saqlash: user_id, language
DB_PATH = "users_lang.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            lang TEXT
        )"""
    )
    conn.commit()
    conn.close()

def set_user_language(user_id: int, lang: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO users (user_id, lang) VALUES (?, ?)", (user_id, lang))
    conn.commit()
    conn.close()

def get_user_language(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT lang FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

# Language map: code -> (display name, welcome phrase)
LANGS = {
    "uz": ("🇺🇿 Oʻzbekcha", "Salom! Men fake-xabarlarni aniqlashda yordam beraman. Xabar yuboring (matn, link yoki rasm)."),
    "ru": ("🇷🇺 Русский", "Привет! Я помогу определить фейковые новости. Отправь мне текст, ссылку или изображение."),
    "en": ("🇬🇧 English", "Hello! I can help detect fake news. Send text, a link or an image."),
}

def lang_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    for code, (label, _) in LANGS.items():
        kb.add(InlineKeyboardButton(label, callback_data=f"setlang:{code}"))
    return kb

def main_menu_keyboard(user_id: int):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("Tilni o'zgartirish / Изменить язык / Change language", callback_data="change_lang"))
    kb.add(InlineKeyboardButton("Yordam / Помощь / Help", callback_data="help"))
    return kb

# Helper: call OpenAI ChatCompletion
def build_prompt_for_analysis(content: str, lang_code: str):
    # Promptni professional qilib tuzamiz — so'rov: fake habar tekshiriuvi
    if lang_code == "uz":
        pre = ("Siz jurnalist / fakt tekshiruvchi sifatida harakat qilasiz. Quyidagi xabar yoki materialni "
               "faktlar, dalillar va noaniqliklar nuqtai nazaridan tahlil qilib bering. "
               "1) Ushbu xabarni FAKE deb baholaysizmi yoki HAQIQI deb? qisqacha (FAKE/REAL) ko'rsatib o'ting. "
               "2) Nima sababdan shunday xulosa chiqardingiz? asosiy dalillarni yozing. "
               "3) Agar kerakli bo'lsa, qaysi qo'shimcha manbalarni tekshirish kerakligi yoki qanday yo'l bilan tekshirish mumkinligi haqida tavsiya bering.\n\n")
    elif lang_code == "ru":
        pre = ("Вы выступаете как журналист / фактчекер. Проанализируйте следующий текст или материал с точки зрения фактов, доказательств и сомнений. "
               "1) Оцените: это FAKE или REAL? Кратко укажите (FAKE/REAL). "
               "2) почему вы пришли к такому выводу — укажите основные основания. "
               "3) Если нужно, предложите какие источники или шаги для дополнительной проверки.\n\n")
    else:
        pre = ("You act as a journalist / fact-checker. Analyze the following text or material for factual accuracy, evidence, and uncertainties. "
               "1) State whether this is likely FAKE or REAL (brief FAKE/REAL). "
               "2) Explain the reasons and main evidence for your conclusion. "
               "3) Recommend any additional sources or steps to verify if necessary.\n\n")
    return pre + content

async def query_openai_chat(prompt: str, system: str = "You are a helpful assistant"):
    # Simple ChatCompletion call (uses OpenAI python package). Adjust model name if you have access to other models.
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",  # agar sizda bu model yo'q bo'lsa, "gpt-4o" yoki "gpt-3.5-turbo" ga almashtiring
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            max_tokens=800,
            temperature=0.0,
        )
        text = response["choices"][0]["message"]["content"].strip()
        return text
    except Exception as e:
        logger.exception("OpenAI error")
        return f"OpenAI API xatosi: {e}"

# Start handler
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    init_db()
    text = ("<b>Fake-xabarlarni tekshiruvchi botga xush kelibsiz!</b>\n\n"
            "Iltimos, bir tilni tanlang / Пожалуйста, выберите язык / Please choose your language:")
    await message.answer(text, reply_markup=lang_keyboard())

# Callback for language setting
@dp.callback_query_handler(lambda c: c.data and c.data.startswith("setlang:"))
async def process_setlang(callback_query: types.CallbackQuery):
    code = callback_query.data.split(":", 1)[1]
    if code not in LANGS:
        await callback_query.answer("Noto'g'ri til tanlandi.")
        return
    set_user_language(callback_query.from_user.id, code)
    _, welcome = LANGS[code]
    await bot.send_message(callback_query.from_user.id, f"<b>{LANGS[code][0]}</b>\n\n{welcome}", reply_markup=main_menu_keyboard(callback_query.from_user.id))
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "change_lang")
async def process_change_lang(callback_query: types.CallbackQuery):
    await bot.send_message(callback_query.from_user.id, "Tilni tanlang / Выберите язык / Choose language:", reply_markup=lang_keyboard())
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "help")
async def process_help(callback_query: types.CallbackQuery):
    lang = get_user_language(callback_query.from_user.id) or "en"
    if lang == "uz":
        txt = "Xabar yuboring (matn, link yoki rasm). Men uni ChatGPT orqali tahlil qilib beraman va professional ko'rinishda javob yuboraman."
    elif lang == "ru":
        txt = "Отправьте текст, ссылку или изображение. Я проанализирую это с помощью ChatGPT и верну профессионально оформленный ответ."
    else:
        txt = "Send a text, link or image. I'll analyze it with ChatGPT and return a professionally formatted result."
    await bot.send_message(callback_query.from_user.id, txt)
    await callback_query.answer()

# Handler for texts (and links)
@dp.message_handler(content_types=ContentType.TEXT)
async def handle_text(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_language(user_id) or "en"
    user_text = message.text.strip()
    if not user_text:
        await message.answer("Xabaringiz bo'sh.")
        return

    # acknowledge
    if lang == "uz":
        await message.answer("Analiz qilinmoqda... Iltimos kuting.")
    elif lang == "ru":
        await message.answer("Анализируется... Пожалуйста, подождите.")
    else:
        await message.answer("Analyzing... Please wait.")

    prompt = build_prompt_for_analysis(user_text, lang)
    result = await query_openai_chat(prompt)

    # professional formatting: header, verdict, details, suggestions
    final_text = "<b>🔎 Fakt tekshiruv natijasi</b>\n\n"
    final_text += result
    final_text += "\n\n<i></i>"

    # send as HTML
    await bot.send_message(user_id, final_text)

# Handler for photos
@dp.message_handler(content_types=ContentType.PHOTO)
async def handle_photo(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_language(user_id) or "en"

    # get highest resolution photo
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    file_bytes = await bot.download_file(file_info.file_path)
    img = Image.open(BytesIO(file_bytes.read()))

    # try OCR if pytesseract available, else use caption (if any)
    ocr_text = None
    try:
        import pytesseract
        ocr_text = pytesseract.image_to_string(img)
        ocr_text = ocr_text.strip()
    except Exception as e:
        logger.info("OCR unavailable or failed: %s", e)
        ocr_text = None

    if ocr_text:
        content_for_analysis = f"Rasmdan olingan matn:\n\n{ocr_text}"
    else:
        # fallback: if caption exists use that
        if message.caption and message.caption.strip():
            content_for_analysis = f"User caption:\n\n{message.caption.strip()}\n\n(Rasmda OCR yo'q yoki mavjud emas.)"
        else:
            content_for_analysis = ("Rasm qabul qilindi, lekin OCR ishlamadi va izoh yo'q.\n"
                                    "Iltimos, rasm bilan birga matn yoki link yuboring yoki OCR imkoniyatini yoqing.")

    # Acknowledge
    if lang == "uz":
        await message.answer("Rasm qabul qilindi. Tahlil qilinmoqda...")
    elif lang == "ru":
        await message.answer("Изображение получено. Анализируется...")
    else:
        await message.answer("Image received. Analyzing...")

    prompt = build_prompt_for_analysis(content_for_analysis, lang)
    result = await query_openai_chat(prompt)

    final_text = "<b>🔎 Fakt tekshiruv natijasi (rasm asosida)</b>\n\n" + result + "\n\n<i>— Bu javob ChatGPT asosida avtomatik tayyorlandi.</i>"
    # send result
    await bot.send_message(user_id, final_text)

# Handler for documents (pdf, txt)
@dp.message_handler(content_types=ContentType.DOCUMENT)
async def handle_document(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_language(user_id) or "en"

    doc = message.document
    file_info = await bot.get_file(doc.file_id)
    file_bytes = await bot.download_file(file_info.file_path)
    raw = file_bytes.read()

    text_extract = None
    # basic attempt: if it's txt, decode; if pdf -> tell user to send text or use OCR/extraction externally
    try:
        if doc.file_name.lower().endswith(".txt"):
            text_extract = raw.decode('utf-8', errors='ignore')
        else:
            text_extract = None
    except Exception as e:
        text_extract = None

    if not text_extract:
        if lang == "uz":
            await message.answer("Hujjat qabul qilindi, lekin avtomatik matn ajratib bo'lmadi. Iltimos, matnli fayl (txt) yuboring yoki fayldan nusxa qilib yuboring.")
        elif lang == "ru":
            await message.answer("Документ получен, но автоматически извлечь текст не удалось. Пожалуйста, отправьте текстовый файл (txt) или вставьте текст.")
        else:
            await message.answer("Document received but could not extract text automatically. Please send a .txt or paste the text.")
        return

    # proceed to analyze extracted text
    if lang == "uz":
        await message.answer("Hujjat matni tahlil qilinmoqda...")
    elif lang == "ru":
        await message.answer("Текст документа анализируется...")
    else:
        await message.answer("Document text is being analyzed...")

    prompt = build_prompt_for_analysis(text_extract, lang)
    result = await query_openai_chat(prompt)
    final_text = "<b>🔎 Fakt tekshiruv natijasi (hujjat)</b>\n\n" + result + "\n\n<i>— Bu javob ChatGPT asosida avtomatik tayyorlandi.</i>"
    await bot.send_message(user_id, final_text)

# Generic fallback for other content types
@dp.message_handler()
async def default_handler(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_language(user_id) or "en"
    if lang == "uz":
        await message.answer("Iltimos, matn, rasm yoki hujjat yuboring. Yordam uchun /start ni bosing.")
    elif lang == "ru":
        await message.answer("Пожалуйста, отправьте текст, изображение или документ. Для помощи нажмите /start.")
    else:
        await message.answer("Please send text, image, or document. For help, use /start.")

if __name__ == "__main__":
    init_db()
    logger.info("Bot started")
    # NOTE: using executor.start_polling avoids asyncio.run issues in some Android environments (Pydroid3)
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
