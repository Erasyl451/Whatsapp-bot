import time, random, asyncio, inspect, io, os, json, requests, phonenumbers, pymorphy3, sys, sqlite3, logging, re
from neonize.aioze.client import NewAClient
from neonize.aioze.events import Event, MessageEv, ConnectedEv, event
from neonize.utils import build_jid
from neonize.utils.enum import ParticipantChange
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message
from google import genai
from urllib.parse import quote, quote_plus
from google.genai import types
from phonenumbers import geocoder
from decrypt import decrypt_whatsapp_media
from effects import apply_audio_effect
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("whatsapp_bot")

FFMPEG_DIR = r"C:\ffmpeg\bin"

# 2. Внедряем его в системный Path для текущего процесса Python
if FFMPEG_DIR not in os.environ["PATH"]:
    os.environ["PATH"] = FFMPEG_DIR + os.path.pathsep + os.environ["PATH"]

# wild bot chat - 120363425717967863@g.us, strashiliki - 120363410469854121@g.us
TARGET_GROUP_ID = "120363425717967863@g.us"
ALLOWED_GROUPS = [
    TARGET_GROUP_ID,
    "120363410469854121@g.us",
    "120363426189094502@g.us",
    "120363409390879768@g.us",
    "120363408306512817@g.us",
    "120363409699154926@g.us",
    "120363195505053420@g.us",
    "120363404020916557@g.us"
]
ai = genai.Client(
api_key=os.getenv("GEMINI_API"))
myId = os.getenv("MYID")
url = f"https://api.giphy.com/v1/gifs/random?api_key={os.getenv("GIPHY_API")}&tag=cat&rating=g"
morph = pymorphy3.MorphAnalyzer()
conn = sqlite3.connect("data.db")
cursor = conn.cursor()
cursor.execute(
    """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    warns INTEGER DEFAULT 0 CHECK (warns >= 0)
)
"""
)
cursor.execute(
    """
CREATE TABLE IF NOT EXISTS balances (
    user_id TEXT PRIMARY KEY,
    coins INTEGER DEFAULT 50 CHECK (coins >= 0)
)
"""
)
conn.commit()

DEFAULT_BALANCE = 50


def get_balance(user_id: str) -> int:
    cursor.execute("SELECT coins FROM balances WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row is None:
        cursor.execute(
            "INSERT INTO balances (user_id, coins) VALUES (?, ?)",
            (user_id, DEFAULT_BALANCE),
        )
        conn.commit()
        return DEFAULT_BALANCE
    return row[0]


def set_balance(user_id: str, coins: int) -> None:
    cursor.execute(
        """
        INSERT INTO balances (user_id, coins) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET coins = excluded.coins
        """,
        (user_id, coins),
    )
    conn.commit()


CYRILLIC_FONT_CANDIDATES_REGULAR = [
    "/data/data/com.termux/files/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/data/data/com.termux/files/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/data/data/com.termux/files/usr/share/fonts/noto/NotoSans-Regular.ttf",
    "/system/fonts/NotoSans-Regular.ttf",
    "/system/fonts/Roboto-Regular.ttf",
    "/system/fonts/DroidSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
CYRILLIC_FONT_CANDIDATES_BOLD = [
    "/data/data/com.termux/files/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/data/data/com.termux/files/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/data/data/com.termux/files/usr/share/fonts/noto/NotoSans-Bold.ttf",
    "/system/fonts/NotoSans-Bold.ttf",
    "/system/fonts/Roboto-Bold.ttf",
    "/system/fonts/DroidSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
] + CYRILLIC_FONT_CANDIDATES_REGULAR


def load_cyrillic_font(candidates, size):
    for path in candidates:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                logger.info(f"Шрифт для стикера-цитаты: {path} (размер {size})")
                return font
            except Exception as e:
                logger.warning(f"Не удалось загрузить шрифт {path}: {e}")
    logger.error(
        "Не найден ни один TTF-шрифт с кириллицей для стикера-цитаты - "
        "текст будет квадратиками. Установите шрифт (например DejaVu) и/или "
        "добавьте его путь в CYRILLIC_FONT_CANDIDATES_*."
    )
    return ImageFont.load_default()


def render_quote_card(photo_path, nick, text):
    nick_font = load_cyrillic_font(CYRILLIC_FONT_CANDIDATES_BOLD, 40)
    text_font = load_cyrillic_font(CYRILLIC_FONT_CANDIDATES_REGULAR, 44)

    # Держим карточку в пределах ~512px по большей стороне: WhatsApp
    # сжимает стикеры до 512x512 с сохранением пропорций, и если исходник
    # намного больше 512px, текст на выходе становится нечитаемо мелким.
    circle_size = 130
    pad = 26
    bubble_w = 340
    line_height = 54
    tail_w = 20

    dummy = Image.new("RGB", (10, 10))
    ddraw = ImageDraw.Draw(dummy)

    # Перенос текста сообщения по словам
    max_text_width = bubble_w - pad * 2
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = cur + " " + w if cur else w
        if ddraw.textlength(test, font=text_font) <= max_text_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if not lines:
        lines = [""]

    nick_h = 50
    bubble_h = pad + nick_h + len(lines) * line_height + pad

    W = tail_w + circle_size + bubble_w + pad
    H = max(circle_size, bubble_h) + pad * 2

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Аватар слева, по центру по высоте
    avatar_pos = (pad, (H - circle_size) // 2)
    photo = Image.open(photo_path).convert("RGBA").resize((circle_size, circle_size))
    mask = Image.new("L", (circle_size, circle_size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, circle_size, circle_size), fill=255)
    img.paste(photo, avatar_pos, mask)

    # Тёмный пузырь справа от аватарки
    bubble_pos = (avatar_pos[0] + circle_size + tail_w, (H - bubble_h) // 2)
    draw.rounded_rectangle(
        [bubble_pos, (bubble_pos[0] + bubble_w, bubble_pos[1] + bubble_h)],
        radius=28, fill=(24, 24, 24, 255)
    )
    tail = [
        (bubble_pos[0], bubble_pos[1] + bubble_h // 2 - 18),
        (avatar_pos[0] + circle_size - 6, avatar_pos[1] + circle_size // 2),
        (bubble_pos[0], bubble_pos[1] + bubble_h // 2 + 18),
    ]
    draw.polygon(tail, fill=(24, 24, 24, 255))

    # Имя
    draw.text((bubble_pos[0] + pad, bubble_pos[1] + pad - 6), nick, fill=(255, 165, 60, 255), font=nick_font)

    # Текст сообщения
    text_y = bubble_pos[1] + pad + nick_h
    for line in lines:
        draw.text((bubble_pos[0] + pad, text_y), line, fill="white", font=text_font)
        text_y += line_height

    out_buf = io.BytesIO()
    img.save(out_buf, format="PNG", optimize=True)
    return out_buf.getvalue()


async def call_if_coroutine(func, *args, **kwargs):
    if inspect.iscoroutinefunction(func):
        return await func(*args, **kwargs)
    return func(*args, **kwargs)

def summarize_memory_with_gemini(memory: str) -> str:
    try:
        response = ai.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=memory,
            config=types.GenerateContentConfig(
                system_instruction="Сократи историю переписки ниже до краткого содержания на русском языке. Сохрани ключевые факты о собеседниках, их именах и важный контекст диалога, который может понадобиться для последующих ответов. Не добавляй ничего от себя и не комментируй - выдай только сжатое содержание.",
            ),
        )
        return response.text
    except Exception as e:
        logger.error(f"Не удалось сократить память через Gemini: {e}", exc_info=True)
        # На случай сбоя Gemini - просто обрезаем по хвосту, чтобы память не росла бесконечно
        return memory[-15000:]


def maybe_truncate_memory(memory: str, label: str) -> str:
    if len(memory) > 15000:
        logger.info(f"Память «{label}» превысила 15000 символов ({len(memory)}), сокращаю через Gemini")
        summarized = summarize_memory_with_gemini(memory)
        logger.info(f"Память «{label}» сокращена: {len(memory)} -> {len(summarized)} символов")
        return summarized
    return memory


def get_verity_opus_bytes(text: str) -> bytes | None:
    """
    Генерирует аудио из текста с голосом Верити и возвращает байты в формате Opus.
    """
    url = "https://api.fish.audio/v1/tts"
    
    # Замените на ваш реальный API-ключ Fish Audio
    api_key = os.getenv("FISH_API") 
    
    # ID модели голоса Верити
    verity_model_id = "8d21b053e2804e2a890e1cf62f267b6f"
    
    headers = {
        "model": "s2.1-pro-free",
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "text": text,
        "reference_id": verity_model_id,
        "format": "opus"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        if response.status_code == 200:
            # Возвращаем сырые байты аудиофайла
            return response
        else:
            logger.error(f"Ошибка API Fish Audio ({response.status_code}): {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Ошибка при отправке запроса в Fish Audio: {e}", exc_info=True)
        return None


client = NewAClient("whatsapp_session.db")
start_time = time.time()
start_d = time.time()
logger.info(start_time)
b_memory = ""
g_memory = ""
v_memory = ""
t_memory = ""

# Буквы, на которые (почти) не бывает слов - если слово оканчивается на одну
# из них, следующему игроку нужно смотреть на предыдущую букву в слове.
WORDS_GAME_SKIP_LETTERS = set("ъьы")

# Ход должен быть одним словом из русских букв - без пунктуации, цифр,
# пробелов и эмодзи. Иначе morph.parse() может дать высокий score даже
# на полную бессмыслицу вроде ">да шуешь !?!?!!!".
CYRILLIC_WORD_RE = re.compile(r'^[а-яё]+$')

# Разрешённые части речи для игры в слова: существительные, глаголы
# (личные формы и инфинитив) и местоимения-существительные (я, он, кто...).
WORDS_GAME_ALLOWED_POS = {"NOUN", "VERB", "INFN", "NPRO"}


def is_allowed_word(word: str) -> bool:
    if not CYRILLIC_WORD_RE.match(word):
        return False
    parsed = morph.parse(word)[0]
    if parsed.score < 0.6:
        return False
    return parsed.tag.POS in WORDS_GAME_ALLOWED_POS


def get_required_letter(word: str) -> str:
    for ch in reversed(word):
        if ch not in WORDS_GAME_SKIP_LETTERS:
            return ch
    return word[-1]


# Начала сообщений, которые шлёт сам бот в рамках игр. Используем их, чтобы
# проверить, что реплай действительно адресован игре, а не случайному
# сообщению в чате - сверять личность бота (JID/LID) ненадёжно, а вот
# текст процитированного сообщения виден всегда одинаково у всех.
WORDS_JOIN_PROMPT = "Ищется партнёр для игры в слова"
WORDS_GAME_PROMPTS = (
    "Игра началась,",
    "Правильно, следующее слово",
    "Слово должно быть на букву",
)
TTT_JOIN_PROMPT = "Ищется партнёр для игры в крестики-нолики"
TTT_GAME_MARKER = "*Крестики-нолики*"


def get_quoted_text(event) -> str:
    ext = event.Message.extendedTextMessage
    if not ext or not ext.contextInfo or not ext.contextInfo.participant:
        return ""
    quoted = ext.contextInfo.quotedMessage
    if not quoted:
        return ""
    # Обычный текст лежит в conversation, а сообщения с @-упоминаниями
    # (которые бот шлёт с mentions_are_lids=True) кодируются как
    # extendedTextMessage - там текст лежит в .text.
    if quoted.conversation:
        return quoted.conversation
    if quoted.extendedTextMessage and quoted.extendedTextMessage.text:
        return quoted.extendedTextMessage.text
    return ""


def is_reply_to(event, prefixes) -> bool:
    quoted_text = get_quoted_text(event)
    if not quoted_text:
        return False
    if isinstance(prefixes, str):
        prefixes = (prefixes,)
    return any(quoted_text.startswith(p) for p in prefixes)

DIGIT_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
XO_WIN_LINES = [
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
]

# Состояние игр хранится отдельно на каждый чат (ключ - chat_jid), чтобы
# несколько групп могли играть в "слова"/"ttt" одновременно, не мешая
# друг другу.
words_games = {}
ttt_games = {}

# Кэш отображаемых имён (PushName) отправителей - копится по мере того, как
# люди пишут в группу. Используется, например, для карточки-цитаты в
# "стикер", чтобы подставить настоящее имя, а не голый ID.
pushname_cache = {}

# ===================== МАФИЯ =====================
mafia_roles_distribution = {
    4:  {"мафия": 1, "дон": 0, "шериф": 1, "любовница": 0, "доктор": 0, "мирный": 2},
    5:  {"мафия": 1, "дон": 0, "шериф": 1, "любовница": 0, "доктор": 1, "мирный": 2},
    6:  {"мафия": 1, "дон": 0, "шериф": 1, "любовница": 1, "доктор": 1, "мирный": 2},
    7:  {"мафия": 1, "дон": 1, "шериф": 1, "любовница": 0, "доктор": 1, "мирный": 3},
    8:  {"мафия": 1, "дон": 1, "шериф": 1, "любовница": 1, "доктор": 1, "мирный": 3},
    9:  {"мафия": 2, "дон": 1, "шериф": 1, "любовница": 0, "доктор": 1, "мирный": 4},
    10: {"мафия": 2, "дон": 1, "шериф": 1, "любовница": 1, "доктор": 1, "мирный": 4},
    11: {"мафия": 2, "дон": 1, "шериф": 1, "любовница": 1, "доктор": 1, "мирный": 5},
    12: {"мафия": 3, "дон": 1, "шериф": 1, "любовница": 1, "доктор": 1, "мирный": 5},
}
MAFIA_TEAM_ROLES = {"мафия", "дон"}
MAFIA_NIGHT_ROLES = {"мафия", "дон", "шериф", "любовница", "доктор"}
MAFIA_NIGHT_TIME = 45
MAFIA_DAY_DISCUSS_TIME = 15
MAFIA_DAY_VOTE_TIME = 45
MAFIA_REGISTRATION_TIME = 90
MAFIA_REGISTRATION_CHECKPOINTS = [60, 30]  # оставшееся время в момент напоминания
MAFIA_WIN_REWARD = 12

MAFIA_ROLE_DISPLAY = {
    "мафия": "🤵🏻 Мафия",
    "дон": "🤵🏻 Дон",
    "шериф": "🕵️‍ Комиссар Каттани",
    "любовница": "💃🏼 Любовница",
    "доктор": "👨🏼‍⚕️ Доктор",
    "мирный": "👨🏼 Мирный житель",
}

MAFIA_NIGHT_FLAVOR = [
    ("мафия", "🤵🏻 Мафия выбрала жертву..."),
    ("любовница", "💃🏼 Любовница уже ждёт кого-то в гости..."),
    ("доктор", "👨🏼‍⚕️ Доктор вышел на ночное дежурство..."),
]

mafia_games = {}
# user_id -> chat_jid активной игры, в которой он участвует. Нужно, чтобы
# распознавать личные сообщения от игроков (ночные действия ролей, а также
# заявки на вступление по ссылке) и понимать, к какой игре их относить.
mafia_player_chat = {}


def new_mafia_state():
    return {
        "game": False,
        "started": False,
        "chat_jid": None,
        "chat_obj": None,
        "players": [],
        "roles": {},
        "alive": set(),
        "phase": None,
        "night_number": 0,
        "night_actions": {},
        "night_token": 0,
        "day_votes": {},
        "day_token": 0,
        "lobby_token": 0,
        "death_messages": {},
        "last_night_result": None,
        "start_time": None,
    }


def get_mafia_state(chat_jid):
    return mafia_games.setdefault(chat_jid, new_mafia_state())


def assign_mafia_roles(players):
    n = len(players)
    dist = mafia_roles_distribution[n]
    pool = []
    for role, count in dist.items():
        pool += [role] * count
    random.shuffle(pool)
    return dict(zip(players, pool))


def check_mafia_winner(ms):
    alive_roles = [ms["roles"][p] for p in ms["alive"]]
    mafia_count = sum(1 for r in alive_roles if r in MAFIA_TEAM_ROLES)
    civil_count = sum(1 for r in alive_roles if r not in MAFIA_TEAM_ROLES)
    if mafia_count == 0:
        return "мирные"
    if mafia_count >= civil_count:
        return "мафия"
    return None


async def get_mafia_jid_map(client, ms):
    """Возвращает {user_id: JID-объект} для участников группы, чтобы писать им в личку."""
    group = await call_if_coroutine(client.get_group_info, ms["chat_obj"])
    return {p.LID.User: p.LID for p in group.Participants}


async def send_mafia_dm_delayed(client, jid, text, max_delay=20):
    """
    Отправляет ЛС с рандомной задержкой 0-20 сек, не блокируя остальной код -
    чтобы рассылка нескольким игрокам подряд не выглядела для WhatsApp
    как спам-рассылка и не привела к бану аккаунта бота.
    """
    await asyncio.sleep(random.uniform(0, max_delay))
    try:
        await call_if_coroutine(client.send_message, jid, text)
    except Exception as e:
        logger.error(f"[мафия] не удалось отправить отложенное ЛС: {e}", exc_info=True)


def mafia_join_link(chat_jid):
    bot_number = (myId or "").split("@")[0]
    text = quote_plus(f".мафия вступить {chat_jid}")
    return f"https://wa.me/{bot_number}?text={text}"


async def post_mafia_roster(client, chat_jid):
    ms = get_mafia_state(chat_jid)
    names = [pushname_cache.get(p, p) for p in ms["players"]]
    listing = "\n".join(f"{i+1}. {n}" for i, n in enumerate(names))
    link = mafia_join_link(chat_jid)
    text = (
        "`Ведется набор в игру Мафия`\n\n"
        "Чтобы присоединится перейди по ссылке:\n"
        f"{link}\n\n"
        "*Зарегистрировались:*\n"
        f"{listing}\n\n"
        f"*Итого {len(ms['players'])} чел.*"
    )
    await call_if_coroutine(client.send_message, ms["chat_obj"], text)


async def run_mafia_registration(client, chat_jid):
    ms = get_mafia_state(chat_jid)
    ms["lobby_token"] += 1
    token = ms["lobby_token"]

    elapsed = 0
    for remaining in MAFIA_REGISTRATION_CHECKPOINTS:
        wait_for = (MAFIA_REGISTRATION_TIME - remaining) - elapsed
        if wait_for > 0:
            await asyncio.sleep(wait_for)
            elapsed += wait_for
        ms = get_mafia_state(chat_jid)
        if not ms["game"] or ms["lobby_token"] != token:
            return
        await call_if_coroutine(client.send_message, ms["chat_obj"], f"⏰ До окончания регистрации {remaining} сек.")

    remaining_wait = MAFIA_REGISTRATION_TIME - elapsed
    if remaining_wait > 0:
        await asyncio.sleep(remaining_wait)

    ms = get_mafia_state(chat_jid)
    if not ms["game"] or ms["lobby_token"] != token:
        return
    await close_mafia_registration(client, chat_jid)


async def close_mafia_registration(client, chat_jid):
    ms = get_mafia_state(chat_jid)
    n = len(ms["players"])
    if n < 4:
        await call_if_coroutine(
            client.send_message, ms["chat_obj"],
            f"Регистрация окончена - собралось только {n} игрок(ов), нужно минимум 4. Игра отменена."
        )
        for uid in ms["players"]:
            mafia_player_chat.pop(uid, None)
        mafia_games[chat_jid] = new_mafia_state()
        return
    if n > 12:
        ms["players"] = ms["players"][:12]
        n = 12

    ms["roles"] = assign_mafia_roles(ms["players"])
    ms["alive"] = set(ms["players"])
    ms["started"] = True
    ms["game"] = False
    ms["night_number"] = 0
    ms["start_time"] = time.time()
    for uid in ms["players"]:
        mafia_player_chat[uid] = chat_jid

    try:
        jid_map = await get_mafia_jid_map(client, ms)
    except Exception as e:
        logger.error(f"[мафия] не удалось получить участников для раздачи ролей: {e}", exc_info=True)
        jid_map = {}

    role_hints = {
        "мафия": "Вы часть МАФИИ 🔪. Ночью вместе с другими мафиози (и доном, если есть) выбираете жертву.",
        "дон": "Вы ДОН мафии 🔪. Ночью вместе с мафией выбираете жертву.",
        "шериф": "Вы КОМИССАР КАТТАНИ 🕵️‍. Ночью можете проверить одного игрока - мафия он или нет.",
        "любовница": "Вы ЛЮБОВНИЦА 💋. Ночью можете заблокировать действие одного игрока на эту ночь.",
        "доктор": "Вы ДОКТОР 👨🏼‍⚕️. Вы не лечите, а угадываете: ночью выберите, кого, по-вашему, хочет убить мафия. Угадаете - этот игрок будет спасён.",
        "мирный": "Вы МИРНЫЙ ЖИТЕЛЬ 🕊. Ночью вы спите, голосуйте днём с остальными.",
    }
    for uid, role in ms["roles"].items():
        jid = jid_map.get(uid)
        if jid:
            try:
                await call_if_coroutine(client.send_message, jid, f"Роли розданы!\n{role_hints[role]}")
            except Exception as e:
                logger.error(f"[мафия] не удалось отправить роль игроку {uid}: {e}", exc_info=True)
            await asyncio.sleep(random.uniform(0, 20))

    bot_number = (myId or "").split("@")[0]
    await call_if_coroutine(
        client.send_message,
        ms["chat_obj"],
        f"*Игра начинается!*\nБот пришлёт каждому личное сообщение с ролью.\n\nЛС с ботом:\nhttps://wa.me/{bot_number}"
    )
    asyncio.create_task(start_mafia_night(client, chat_jid))


async def start_mafia_night(client, chat_jid):
    ms = get_mafia_state(chat_jid)
    if not ms["started"]:
        return
    ms["phase"] = "night"
    ms["night_number"] += 1
    ms["night_actions"] = {}
    ms["night_token"] += 1
    token = ms["night_token"]

    alive_players = [p for p in ms["players"] if p in ms["alive"]]
    listing = "\n".join(f"{i+1}. {pushname_cache.get(p, p)}" for i, p in enumerate(alive_players))

    try:
        jid_map = await get_mafia_jid_map(client, ms)
    except Exception as e:
        logger.error(f"[мафия] не удалось получить участников группы для ЛС: {e}", exc_info=True)
        jid_map = {}

    night_prompts = {
        "мафия": f"🌙 Ночь {ms['night_number']}. Кого убиваем?\n{listing}\nОтветьте номером.",
        "дон": f"🌙 Ночь {ms['night_number']}. Кого убиваем?\n{listing}\nОтветьте номером.",
        "шериф": f"🌙 Ночь {ms['night_number']}. Кого проверяем?\n{listing}\nОтветьте номером.",
        "любовница": f"🌙 Ночь {ms['night_number']}. К кому идём в гости (заблокировать её/его действие на эту ночь)?\n{listing}\nОтветьте номером.",
        "доктор": f"🌙 Ночь {ms['night_number']}. Угадайте, кого хочет убить мафия, чтобы спасти:\n{listing}\nОтветьте номером.",
    }
    for uid in alive_players:
        role = ms["roles"][uid]
        jid = jid_map.get(uid)
        if not jid or role not in MAFIA_NIGHT_ROLES:
            continue
        asyncio.create_task(send_mafia_dm_delayed(client, jid, night_prompts[role]))

    await call_if_coroutine(
        client.send_message,
        ms["chat_obj"],
        (
            "🌃 *Наступает ночь*\n"
            "На улицы города выходят лишь самые отважные...\n\n"
            "*Живые игроки:*\n"
            f"{listing}\n\n"
            f"*Спать осталось {MAFIA_NIGHT_TIME} сек.*"
        )
    )

    # Атмосферные сообщения о том, что активные роли действуют - без раскрытия деталей
    alive_roles_tonight = {ms["roles"][p] for p in alive_players}
    active_flavor = [(r, t) for r, t in MAFIA_NIGHT_FLAVOR if r in alive_roles_tonight]
    elapsed = 0.0
    if active_flavor:
        step = MAFIA_NIGHT_TIME / (len(active_flavor) + 1)
        for _, text in active_flavor:
            await asyncio.sleep(step)
            elapsed += step
            ms_check = get_mafia_state(chat_jid)
            if not ms_check["started"] or ms_check["night_token"] != token:
                return
            await call_if_coroutine(client.send_message, ms["chat_obj"], text)

    remaining_sleep = MAFIA_NIGHT_TIME - elapsed
    if remaining_sleep > 0:
        await asyncio.sleep(remaining_sleep)

    ms = get_mafia_state(chat_jid)
    if not ms["started"] or ms["night_token"] != token:
        return
    await resolve_mafia_night(client, chat_jid)


async def resolve_mafia_night(client, chat_jid):
    ms = get_mafia_state(chat_jid)
    actions = ms["night_actions"]

    lover_choices = actions.get("любовница", {})
    blocked = random.choice(list(lover_choices.values())) if lover_choices else None

    mafia_choices = {}
    mafia_choices.update(actions.get("мафия", {}))
    mafia_choices.update(actions.get("дон", {}))
    kill_target = None
    if mafia_choices:
        tally = {}
        for t in mafia_choices.values():
            tally[t] = tally.get(t, 0) + 1
        top_count = max(tally.values())
        top = [t for t, v in tally.items() if v == top_count]
        kill_target = random.choice(top)

    # Доктор не лечит, а угадывает жертву мафии - угадал, значит спас
    doctor_saved = False
    for doc_id, guess in actions.get("доктор", {}).items():
        if doc_id == blocked:
            continue
        if kill_target is not None and guess == kill_target:
            doctor_saved = True

    died = kill_target if (kill_target and kill_target != blocked and not doctor_saved) else None

    try:
        jid_map = await get_mafia_jid_map(client, ms)
    except Exception as e:
        logger.error(f"[мафия] не удалось получить участников группы для результатов ЛС: {e}", exc_info=True)
        jid_map = {}

    for doc_id, guess in actions.get("доктор", {}).items():
        jid = jid_map.get(doc_id)
        if not jid:
            continue
        if doc_id == blocked:
            text = "👨🏼‍⚕️ В эту ночь вас кто-то отвлёк - угадывание не засчитано."
        elif kill_target is not None and guess == kill_target:
            text = f"👨🏼‍⚕️ Вы угадали! {pushname_cache.get(guess, guess)} спасён(а) этой ночью."
        else:
            text = "👨🏼‍⚕️ В этот раз вы не угадали."
        try:
            asyncio.create_task(send_mafia_dm_delayed(client, jid, text))
        except Exception as e:
            logger.error(f"[мафия] не удалось отправить результат доктору: {e}", exc_info=True)

    for sheriff_id, target in actions.get("шериф", {}).items():
        if target == blocked:
            result_text = "🔍 Ваша проверка этой ночью была заблокирована."
        else:
            is_mafia_team = ms["roles"].get(target) in MAFIA_TEAM_ROLES
            name = pushname_cache.get(target, target)
            result_text = f"🔍 Результат: {'🔴' if is_mafia_team else '✅'} *{name}* — {'МАФИЯ' if is_mafia_team else 'Мирный житель'}"
        jid = jid_map.get(sheriff_id)
        if jid:
            try:
                asyncio.create_task(send_mafia_dm_delayed(client, jid, result_text))
            except Exception as e:
                logger.error(f"[мафия] не удалось отправить результат проверки шерифу: {e}", exc_info=True)

    night_result = {"died": None, "role": None, "name": None, "last_words": None, "visitor": None}
    if died:
        ms["alive"].discard(died)
        night_result["died"] = died
        night_result["role"] = ms["roles"].get(died)
        night_result["name"] = pushname_cache.get(died, died)
        night_result["last_words"] = ms["death_messages"].pop(died, None)
        night_result["visitor"] = "Дон" if died in actions.get("дон", {}).values() else "Мафия"
    ms["last_night_result"] = night_result

    winner = check_mafia_winner(ms)
    if winner:
        await end_mafia_game(client, chat_jid, winner)
        return

    await start_mafia_day(client, chat_jid)


async def start_mafia_day(client, chat_jid):
    ms = get_mafia_state(chat_jid)
    if not ms["started"]:
        return
    ms["phase"] = "day"
    ms["day_votes"] = {}
    ms["day_token"] += 1
    token = ms["day_token"]

    alive_players = [p for p in ms["players"] if p in ms["alive"]]
    listing = "\n".join(f"{i+1}. {pushname_cache.get(p, p)}" for i, p in enumerate(alive_players))

    result = ms.get("last_night_result") or {"died": None}
    if result["died"]:
        role_display = MAFIA_ROLE_DISPLAY.get(result["role"], result["role"])
        death_line = f"☠️ Сегодня убит {role_display} *{result['name']}*...\nГоворят, у него в гостях был 🤵🏻 {result['visitor']}"
        if result["last_words"]:
            death_line += f"\n\nКто-то слышал, как {result['name']} кричал(а) перед смертью:\n{result['last_words']}"
    else:
        death_line = "🌅 Этой ночью никто не погиб."

    text = (
        f"🏙 *День {ms['night_number']}*\n"
        "Солнце всходит...\n\n"
        f"{death_line}\n\n"
        "Живые игроки:\n"
        f"{listing}\n"
        f"*Всего:* `{len(alive_players)}` чел.\n\n"
        "> Обсудите результаты ночи..."
    )
    await call_if_coroutine(client.send_message, ms["chat_obj"], text, mentions_are_lids=True)

    await asyncio.sleep(MAFIA_DAY_DISCUSS_TIME)
    ms = get_mafia_state(chat_jid)
    if not ms["started"] or ms["day_token"] != token:
        return

    alive_players = [p for p in ms["players"] if p in ms["alive"]]
    listing = "\n".join(f"{i+1}. {pushname_cache.get(p, p)}" for i, p in enumerate(alive_players))
    await call_if_coroutine(
        client.send_message,
        ms["chat_obj"],
        (
            "⚖️ *За кого голосуете?*\n\n"
            f"{listing}\n\n"
            "> Напишите число чтобы проголосовать\n"
            f"> Голосование {MAFIA_DAY_VOTE_TIME} секунд"
        )
    )

    await asyncio.sleep(MAFIA_DAY_VOTE_TIME)

    ms = get_mafia_state(chat_jid)
    if not ms["started"] or ms["day_token"] != token:
        return
    await resolve_mafia_day(client, chat_jid)


async def resolve_mafia_day(client, chat_jid):
    ms = get_mafia_state(chat_jid)
    votes = ms["day_votes"]
    if votes:
        tally = {}
        for t in votes.values():
            tally[t] = tally.get(t, 0) + 1
        top_count = max(tally.values())
        top = [t for t, v in tally.items() if v == top_count]
        if len(top) == 1:
            eliminated = top[0]
            ms["alive"].discard(eliminated)
            name = pushname_cache.get(eliminated, eliminated)
            role_display = MAFIA_ROLE_DISPLAY.get(ms["roles"].get(eliminated), ms["roles"].get(eliminated))
            lynch_text = f"🪢 *Вешаем {name}!*\nОн(а) был(а): {role_display}"
            last_words = ms["death_messages"].pop(eliminated, None)
            if last_words:
                lynch_text += f"\n\nПоследние слова {name}:\n{last_words}"
            await call_if_coroutine(client.send_message, ms["chat_obj"], lynch_text)
        else:
            await call_if_coroutine(client.send_message, ms["chat_obj"], "⚖️ Голоса разделились поровну, линч отменен")
    else:
        await call_if_coroutine(client.send_message, ms["chat_obj"], "⚖️ Никто не проголосовал, линч отменен")

    winner = check_mafia_winner(ms)
    if winner:
        await end_mafia_game(client, chat_jid, winner)
        return

    await start_mafia_night(client, chat_jid)


async def end_mafia_game(client, chat_jid, winner):
    ms = get_mafia_state(chat_jid)
    winners_lines, others_lines = [], []
    for p, r in ms["roles"].items():
        name = pushname_cache.get(p, p)
        role_display = MAFIA_ROLE_DISPLAY.get(r, r)
        is_winner = (winner == "мафия" and r in MAFIA_TEAM_ROLES) or (winner == "мирные" and r not in MAFIA_TEAM_ROLES)
        if is_winner:
            set_balance(p, get_balance(p) + MAFIA_WIN_REWARD)
            winners_lines.append(f"    {name} - {role_display} (+{MAFIA_WIN_REWARD}🪙)")
        else:
            others_lines.append(f"    {name} - {role_display}")

    duration = int(time.time() - (ms["start_time"] or time.time()))
    minutes, seconds = divmod(duration, 60)

    text = (
        "*Игра окончена!*\n"
        f"*Победила {'Мафия' if winner == 'мафия' else 'Мирные жители'}*\n\n"
        "*Победители:*\n" + "\n".join(winners_lines) + "\n\n"
        "*Остальные:*\n" + "\n".join(others_lines) + "\n\n"
        f"*Игра длилась:* {minutes} мин. {seconds} сек."
    )
    await call_if_coroutine(client.send_message, ms["chat_obj"], text)

    for uid in ms["players"]:
        mafia_player_chat.pop(uid, None)
    mafia_games[chat_jid] = new_mafia_state()
# ===================== /МАФИЯ =====================



WORDS_TURN_TIME_START = 60
WORDS_TURN_TIME_STEP = 5
WORDS_TURN_TIME_MIN = 15


def new_words_state():
    return {
        "game": False,
        "in_game": [],
        "current_player": None,
        "last_word": "",
        "skip": False,
        "used_words": [],
        "words_pot": 1,
        "time_limit": WORDS_TURN_TIME_START,
        "move_token": 0,
    }


async def start_words_turn_timer(client, chat_jid, chat_obj):
    ws = get_words_state(chat_jid)
    ws["move_token"] += 1
    token = ws["move_token"]
    limit = ws["time_limit"]
    await asyncio.sleep(limit)
    ws = get_words_state(chat_jid)
    if ws["game"] and ws["move_token"] == token:
        loser = ws["current_player"]
        winner_id = ws["in_game"][0] if loser == ws["in_game"][1] else ws["in_game"][1]
        prize = ws["words_pot"]
        if prize > 0:
            set_balance(winner_id, get_balance(winner_id) + prize)
        ws["words_pot"] = 0
        ws["game"] = False
        await call_if_coroutine(
            client.send_message,
            chat_obj,
            f"⏱ Время вышло! Победил @{winner_id}! (+{prize} монет)",
            mentions_are_lids=True
        )


def new_ttt_state():
    return {
        "xo_game": False,
        "xo_players": [],
        "xo_current_player": None,
        "xo_board": [None] * 9,
        "xo_symbols": {},
    }


def get_words_state(chat_jid):
    return words_games.setdefault(chat_jid, new_words_state())


def get_ttt_state(chat_jid):
    return ttt_games.setdefault(chat_jid, new_ttt_state())


def render_xo_board(board):
    cells = [
        board[i] if board[i] is not None else DIGIT_EMOJIS[i]
        for i in range(9)
    ]
    return "\n".join(
        "".join(cells[row * 3:row * 3 + 3]) for row in range(3)
    )


def render_ttt_status(ts):
    quoted_board = "\n".join(f"> {line}" for line in render_xo_board(ts["xo_board"]).split("\n"))
    return (
        "*Крестики-нолики*\n\n"
        f"🎲 Ход: @{ts['xo_current_player']}\n\n"
        f"{quoted_board}\n\n"
        f"1 Игрок ❎: @{ts['xo_players'][0]}\n"
        f"2 Игрок ⭕: @{ts['xo_players'][1]}\n\n"
        "• Введите номер (1-9), чтобы сделать ход\n"
        "• Введите *сдаться* чтобы сдаться"
    )


def check_xo_winner(board):
    for a, b, c in XO_WIN_LINES:
        if board[a] is not None and board[a] == board[b] == board[c]:
            return board[a]
    if all(cell is not None for cell in board):
        return "draw"
    return None


@client.event(MessageEv)
async def on_group_message(client: NewAClient, event: MessageEv):
    try:
        global start_d, g_memory, v_memory, b_memory, t_memory, url
        delay = round((time.time() - start_d) * 10)
        # Безопасно получаем ID чата (JID)
        chat_obj = event.Info.MessageSource.Chat
        start = time.time()

        if hasattr(chat_obj, "User") and hasattr(chat_obj, "Server"):
            chat_jid = f"{chat_obj.User}@{chat_obj.Server}"
        else:
            chat_jid = str(chat_obj)

        # Очищаем JID от служебных символов gRP
        if "User:" in chat_jid:
            import re
            user_match = re.search(r'User:\s*"([^\"]+)"', chat_jid)
            server_match = re.search(r'Server:\s*"([^\"]+)"', chat_jid)
            if user_match and server_match:
                chat_jid = f"{user_match.group(1)}@{server_match.group(2)}"

        # Личные сообщения (не группа) - используются для тайных ночных
        # действий ролей в "мафии". Обрабатываем их отдельно, до фильтра
        # по разрешённым группам, иначе они бы просто игнорировались.
        if not chat_jid.endswith("@g.us"):
            try:
                sender_id = event.Info.MessageSource.Sender.User
            except Exception:
                sender_id = None
            dm_text = ""
            if event.Message:
                dm_text = (
                    getattr(event.Message, "conversation", "") or
                    (getattr(event.Message, "extendedTextMessage", None) and getattr(event.Message.extendedTextMessage, "text", "")) or
                    ""
                )
            if sender_id and sender_id in mafia_player_chat:
                group_chat_jid = mafia_player_chat[sender_id]
                ms = get_mafia_state(group_chat_jid)
                dm_stripped = dm_text.strip()
                if ms["started"] and sender_id in ms["alive"] and dm_stripped.lower().startswith("мафия смерть "):
                    last_words = dm_stripped[len("мафия смерть "):].strip()
                    if last_words:
                        ms["death_messages"][sender_id] = last_words
                        await call_if_coroutine(
                            client.send_message,
                            event.Info.MessageSource.Chat,
                            "Записал. Если вас убьют, эту фразу услышат остальные."
                        )
                elif ms["started"] and ms["phase"] == "night" and sender_id in ms["alive"]:
                    role = ms["roles"].get(sender_id)
                    choice = dm_stripped
                    if role in MAFIA_NIGHT_ROLES and choice.isdigit():
                        alive_players = [p for p in ms["players"] if p in ms["alive"]]
                        idx = int(choice) - 1
                        if 0 <= idx < len(alive_players):
                            target = alive_players[idx]
                            ms["night_actions"].setdefault(role, {})[sender_id] = target
                            await call_if_coroutine(
                                client.send_message,
                                event.Info.MessageSource.Chat,
                                f"Принято: {pushname_cache.get(target, target)}"
                            )
                        else:
                            await call_if_coroutine(
                                client.send_message,
                                event.Info.MessageSource.Chat,
                                "Такого номера нет в списке"
                            )

            dm_stripped_full = dm_text.strip()
            if sender_id:
                try:
                    dm_pushname = getattr(event.Info, "PushName", None) or getattr(event.Info, "Pushname", None)
                    if dm_pushname:
                        pushname_cache[sender_id] = dm_pushname
                except Exception:
                    pass
            if sender_id and dm_stripped_full.lower().startswith(".мафия вступить "):
                target_chat_jid = dm_stripped_full[len(".мафия вступить "):].strip()
                ms = get_mafia_state(target_chat_jid)
                if not ms["game"] or ms["started"]:
                    await call_if_coroutine(
                        client.send_message,
                        event.Info.MessageSource.Chat,
                        "Регистрация в эту игру уже закрыта или не найдена."
                    )
                elif sender_id in ms["players"]:
                    await call_if_coroutine(
                        client.send_message,
                        event.Info.MessageSource.Chat,
                        "Вы уже зарегистрированы в этой игре."
                    )
                elif len(ms["players"]) >= 12:
                    await call_if_coroutine(
                        client.send_message,
                        event.Info.MessageSource.Chat,
                        "Уже набрано максимум игроков (12)."
                    )
                else:
                    ms["players"].append(sender_id)
                    await call_if_coroutine(
                        client.send_message,
                        event.Info.MessageSource.Chat,
                        f"Вы зарегистрированы в игре Мафия! Участников: {len(ms['players'])}"
                    )
                    try:
                        await post_mafia_roster(client, target_chat_jid)
                    except Exception as e:
                        logger.error(f"[мафия] не удалось обновить список в группе: {e}", exc_info=True)
            return

        # Фильтруем сообщения: обрабатываем только целевую группу
        if chat_jid in ALLOWED_GROUPS:
            # Безопасно извлекаем имя отправителя (PushName)
            sender_name = "Участник группы"
            if hasattr(event.Info, "PushName") and event.Info.PushName:
                sender_name = event.Info.PushName
            elif hasattr(event.Info, "MessageSource") and hasattr(event.Info.MessageSource, "Sender"):
                # Если PushName нет, пробуем взять его телефонный ID
                sender_obj = event.Info.MessageSource.Sender
                sender_name = getattr(sender_obj, "User", "Участник")

            if sender_name and sender_name != "Участник группы":
                try:
                    cache_key = event.Info.MessageSource.Sender.User
                    pushname_cache[cache_key] = sender_name
                    logger.info(f"[pushname_cache] записал key={cache_key!r} -> {sender_name!r}")
                except Exception:
                    pass

            # Безопасно извлекаем текст сообщения
            message_text = ""
            if event.Message:
                # Проверяем разные типы текстовых полей, которые могут быть в Protobuf
                message_text = (
                    getattr(event.Message, "conversation", "") or
                    (getattr(event.Message, "extendedTextMessage", None) and getattr(event.Message.extendedTextMessage, "text", "")) or
                    ""
                )

            quoted_text = get_quoted_text(event)

            if message_text:
                logger.info(f"\n[Новое сообщение в целевую группу!]")
                logger.info(f"ID чата: {chat_jid}")
                logger.info(f"Отправитель: {sender_name}")
                logger.info(f"Текст: {message_text}\n")
                logger.info(f"Цитата (если реплай): {quoted_text!r}")
                logger.info("-" * 50)

            if "setcoins" in message_text.lower().strip():
                if event.Info.MessageSource.IsFromMe == True:
                    # Если это ответ на чьё-то сообщение - меняем баланс автора того сообщения,
                    # иначе - баланс того, кто прислал команду
                    if event.Message.extendedTextMessage and event.Message.extendedTextMessage.contextInfo.participant:
                        target_id = event.Message.extendedTextMessage.contextInfo.participant.replace("@lid", "")
                    else:
                        target_id = event.Info.MessageSource.Sender.User

                    raw_amount = message_text.replace("setcoins ", "").strip()
                    try:
                        new_amount = int(raw_amount)
                    except ValueError:
                        logger.warning(f"Некорректная сумма в setcoins: {raw_amount!r}")
                        await call_if_coroutine(
                            client.send_message,
                            event.Info.MessageSource.Chat,
                            "Укажите число, например: setcoins 100"
                        )
                    else:
                        old_amount = get_balance(target_id)
                        set_balance(target_id, new_amount)
                        logger.info(f"{sender_name} изменил баланс {target_id}: {old_amount} -> {new_amount}")
                        await call_if_coroutine(
                            client.send_message,
                            event.Info.MessageSource.Chat,
                            f"Было: {old_amount} монет\nСтало: {new_amount} монет"
                        )
                else:
                    await call_if_coroutine(
                        client.send_message,
                        event.Info.MessageSource.Chat,
                        "У вас не достаточно привелегий"
                    )

            if chat_jid == "120363408306512817@g.us" or chat_jid == "120363409699154926@g.us":
                if message_text.lower().strip().startswith("пред"):
                    group = await call_if_coroutine(client.get_group_info, event.Info.MessageSource.Chat)
                    for i in group.Participants:
                        if i.LID.User == sender_name:
                            if i.IsAdmin == True:
                                if "пред @" in message_text.lower().strip():
                                    target = message_text.lower().strip().replace("пред @", "")
                                    target = target.replace("@lid", "")
                                    cursor.execute(
                                        """
                                        INSERT INTO users (user_id, warns)
                                        VALUES(?, 1)
                                        ON CONFLICT(user_id) DO UPDATE SET warns = warns + 1
                                        RETURNING warns
                                        """,
                                        (target,),
                                    )
                                    warns_count = cursor.fetchone()[0]
                                    conn.commit()
                                    await call_if_coroutine(
                                        client.send_message,
                                        event.Info.MessageSource.Chat,
                                        f"Пред был поставлен, всего предов у @{target}: {warns_count}/3",
                                        mentions_are_lids=True
                                    )
                                    break
                                if event.Message.extendedTextMessage and event.Message.extendedTextMessage.contextInfo.participant:
                                    target = event.Message.extendedTextMessage.contextInfo.participant.replace("@lid", "")
                                    cursor.execute(
                                        """
                                        INSERT INTO users (user_id, warns)
                                        VALUES(?, 1)
                                        ON CONFLICT(user_id) DO UPDATE SET warns = warns + 1
                                        RETURNING warns
                                        """,
                                        (target,),
                                    )
                                    warns_count = cursor.fetchone()[0]
                                    conn.commit()
                                    await call_if_coroutine(
                                                client.send_message,
                                                event.Info.MessageSource.Chat,
                                                f"Пред был поставлен, всего предов у @{target}: {warns_count}/3",
                                                mentions_are_lids=True
                                    )
                                    break
                                if message_text.lower().strip() == "-чат":
                                    client.set_group_locked(event.Info.MessageSource.Chat, True)
                                if message_text.lower().strip() == "+чат":
                                    client.set_group_locked(event.Info.MessageSource.Chat, False)
                            else:
                                await call_if_coroutine(
                                            client.send_message,
                                            event.Info.MessageSource.Chat,
                                            "Эта функция доступна только админам"
                                )
                if message_text.lower().strip().startswith("анпред"):
                    group = await call_if_coroutine(client.get_group_info, event.Info.MessageSource.Chat)
                    for i in group.Participants:
                        if i.LID.User == sender_name:
                            if i.IsAdmin == True:
                                if "анпред @" in message_text.lower().strip():
                                    target = message_text.lower().strip().replace("анпред @", "")
                                    target = target.replace("@lid", "")
                                    cursor.execute(
                                        """
                                        INSERT INTO users (user_id, warns)
                                        VALUES(?, 1)
                                        ON CONFLICT(user_id) DO UPDATE SET warns = warns - 1
                                        RETURNING warns
                                        """,
                                        (target,),
                                    )
                                    warns_count = cursor.fetchone()[0]
                                    conn.commit()
                                    await call_if_coroutine(
                                                client.send_message,
                                                event.Info.MessageSource.Chat,
                                                f"Пред был убран, всего предов у @{target}: {warns_count}/3",
                                                mentions_are_lids=True
                                    )
                                    break
                                if message_text.lower().strip() == "анпред все":
                                    cursor.execute("UPDATE users SET warns = warns - 1 WHERE warns > 0")
                                    conn.commit()
                                    await call_if_coroutine(
                                                client.send_message,
                                                event.Info.MessageSource.Chat,
                                                f"1 Пред был убран у всех"
                                    )
                                if event.Message.extendedTextMessage and event.Message.extendedTextMessage.contextInfo.participant:
                                    target = event.Message.extendedTextMessage.contextInfo.participant.replace("@lid", "")
                                    cursor.execute(
                                        """
                                        INSERT INTO users (user_id, warns)
                                        VALUES(?, 1)
                                        ON CONFLICT(user_id) DO UPDATE SET warns = warns - 1
                                        RETURNING warns
                                        """,
                                        (target,),
                                    )
                                    warns_count = cursor.fetchone()[0]
                                    conn.commit()
                                    await call_if_coroutine(
                                                client.send_message,
                                                event.Info.MessageSource.Chat,
                                                f"Пред был убран, всего предов у @{target}: {warns_count}/3",
                                                mentions_are_lids=True
                                    )
                                    break
                            else:
                                await call_if_coroutine(
                                            client.send_message,
                                            event.Info.MessageSource.Chat,
                                            "Эта функция доступна только админам"
                                )
                if message_text.lower().strip() == "преды":
                    cursor.execute("SELECT user_id, warns FROM users WHERE warns > 0")
                    rows = cursor.fetchall()

                    if not rows:
                        text = "Ни у кого нет предупреждений."
                    else:
                        text = "📋 Предупреждения:\n\n"
                        for user_id, warns in rows:
                            text += f"@{user_id} — {warns}/3\n"

                    await call_if_coroutine(
                                client.send_message,
                                event.Info.MessageSource.Chat,
                                text,
                                mentions_are_lids=True
                                        )
                if message_text.lower().strip().startswith("кик"):
                    group = await call_if_coroutine(client.get_group_info, event.Info.MessageSource.Chat)
                    for i in group.Participants:
                        if i.LID.User == sender_name:
                            if i.IsAdmin == True:
                                if "кик @" in message_text.lower().strip():
                                    target = message_text.lower().strip().replace("кик @", "")
                                    target = target.replace("@lid", "")
                                    target_jid = None
                                    for p in group.Participants:
                                        if p.LID.User == target:
                                            target_jid = p.LID
                                            break
                                    if target_jid is None:
                                        await call_if_coroutine(
                                            client.send_message,
                                            event.Info.MessageSource.Chat,
                                            f"Не нашёл участника @{target} в группе",
                                            mentions_are_lids=True
                                        )
                                        break
                                    await call_if_coroutine(
                                        client.update_group_participants,
                                        event.Info.MessageSource.Chat,
                                        [target_jid],
                                        ParticipantChange.REMOVE
                                    )
                                    await call_if_coroutine(
                                        client.send_message,
                                        event.Info.MessageSource.Chat,
                                        f"{target} был удалён",
                                        mentions_are_lids=True
                                    )
                                    break
                                if event.Message.extendedTextMessage and event.Message.extendedTextMessage.contextInfo.participant:
                                    target = event.Message.extendedTextMessage.contextInfo.participant.replace("@lid", "")
                                    target_jid = None
                                    for p in group.Participants:
                                        if p.LID.User == target:
                                            target_jid = p.LID
                                            break
                                    if target_jid is None:
                                        await call_if_coroutine(
                                            client.send_message,
                                            event.Info.MessageSource.Chat,
                                            f"Не нашёл участника @{target} в группе",
                                            mentions_are_lids=True
                                        )
                                        break
                                    await call_if_coroutine(
                                        client.update_group_participants,
                                        event.Info.MessageSource.Chat,
                                        [target_jid],
                                        ParticipantChange.REMOVE
                                    )
                                    await call_if_coroutine(
                                                client.send_message,
                                                event.Info.MessageSource.Chat,
                                                f"{target} был удалён",
                                                mentions_are_lids=True
                                    )
                                    break
                            else:
                                await call_if_coroutine(
                                            client.send_message,
                                            event.Info.MessageSource.Chat,
                                            "Эта функция доступна только админам"
                                )

            if "тест" in message_text.lower().strip() and event.Info.MessageSource.IsFromMe == True:
                response = await call_if_coroutine(client.send_message, event.Info.MessageSource.Chat, "✅")
                logger.info(response)
                m = message_text.replace("тест ", "")
                if m != "":
                    eval(m)
                logger.info(f"Ответ Успешно отправлен в группу {chat_jid}")

            if message_text.lower().strip() == "пинг":
                if delay > 5:
                    bot_reply = await call_if_coroutine(client.send_message, event.Info.MessageSource.Chat, "Понг!")
                    latency = round((time.time() - start) * 1000)  # Время в миллисекундах
                    uptime = int(time.time() - start_time)
                    hours = uptime // 3600
                    minutes = (uptime % 3600) // 60
                    seconds = uptime % 60
                    if bot_reply is not None and hasattr(bot_reply, 'Message'):
                        new_message = Message()
                        new_message.CopyFrom(bot_reply.Message)
                        new_message.extendedTextMessage.text = f"Задержка: {latency} мс\nВремя работы бота: {hours} ч {minutes} м {seconds} с"
                        await call_if_coroutine(
                            client.edit_message,
                            event.Info.MessageSource.Chat,
                            bot_reply.ID,
                            new_message,
                        )
                    logger.info(f"Ответ Успешно отправлен в группу {chat_jid}")
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if message_text.lower().strip() == "стикер":
                if delay > 5:
                    quoted = None
                    if event.Raw.extendedTextMessage and event.Raw.extendedTextMessage.contextInfo:
                        quoted = event.Raw.extendedTextMessage.contextInfo.quotedMessage
                    try:
                        if quoted and quoted.imageMessage and quoted.imageMessage.URL:
                            img = quoted.imageMessage
                            rawbytes = decrypt_whatsapp_media(img.URL, img.mediaKey, b"WhatsApp Image Keys")
                            await call_if_coroutine(
                                client.send_sticker,
                                event.Info.MessageSource.Chat,
                                rawbytes,
                            )
                            logger.info(f"Стикер из картинки отправлен в группу {chat_jid}")
                        elif quoted and quoted.videoMessage and quoted.videoMessage.URL:
                            vid = quoted.videoMessage
                            rawbytes = decrypt_whatsapp_media(vid.URL, vid.mediaKey, b"WhatsApp Video Keys")
                            await call_if_coroutine(
                                client.send_sticker,
                                event.Info.MessageSource.Chat,
                                rawbytes,
                            )
                            logger.info(f"Стикер из видео отправлен в группу {chat_jid}")
                        elif quoted and (quoted.conversation or (quoted.extendedTextMessage and quoted.extendedTextMessage.text)):
                            message = quoted.conversation or quoted.extendedTextMessage.text
                            target = event.Message.extendedTextMessage.contextInfo.participant.replace("@lid", "")
                            jid = build_jid(target, "lid")
                            if jid:
                                try:
                                    avatar_result = await call_if_coroutine(client.get_profile_picture, jid)
                                    logger.info(f"Тип avatar_result: {type(avatar_result)}, значение: {avatar_result}")
                                    if avatar_result:
                                        if hasattr(avatar_result, 'URL'):
                                            avatar_url = avatar_result.URL
                                            logger.info(f"Содержимое: {quoted}")
                                            if avatar_url:
                                                headers = {'User-Agent': 'Mozilla/5.0'}
                                                response = requests.get(avatar_url, headers=headers)
                                                if response.status_code == 200:
                                                    temp_file = f"avatar_{target}.jpg"
                                                    with open(temp_file, "wb") as f:
                                                        f.write(response.content)
                                                    quote_nick = pushname_cache.get(target, target)
                                                    logger.info(f"[стикер-цитата] target={target!r}, найден в кэше: {target in pushname_cache}, всего в кэше: {len(pushname_cache)}, ключи (первые 10): {list(pushname_cache.keys())[:10]}")
                                                    sticker_bytes = render_quote_card(temp_file, quote_nick, message)
                                                    os.remove(temp_file)
                                                    await call_if_coroutine(
                                                        client.send_sticker,
                                                        event.Info.MessageSource.Chat,
                                                        sticker_bytes,
                                                    )
                                                    logger.info(f"Стикер из сообщения отправлен в группу {chat_jid}")
                                except Exception as e:
                                    print(e)
                        else:
                            await call_if_coroutine(
                                client.send_message,
                                event.Info.MessageSource.Chat,
                                "Ответьте командой 'стикер' на любое сообщение"
                            )
                    except Exception as e:
                        logger.error(f"Ошибка при создании стикера: {e}", exc_info=True)
                        await call_if_coroutine(
                            client.send_message,
                            event.Info.MessageSource.Chat,
                            "Не получилось сделать стикер из этого файла"
                        )
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if "chip" in message_text.lower().strip():
                if delay > 5:
                    audio = event.Raw.extendedTextMessage.contextInfo.quotedMessage.audioMessage
                    rawbytes = decrypt_whatsapp_media(audio.URL, audio.mediaKey, b"WhatsApp Audio Keys")
                    modified_bytes = apply_audio_effect(rawbytes, "chipmunk")
                    await call_if_coroutine(
                                    client.send_audio,
                                    event.Info.MessageSource.Chat,
                                    modified_bytes,
                    )
                    logger.info(f"Ответ Успешно отправлен в группу {chat_jid}")
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )
            if "bass" in message_text.lower().strip():
                if delay > 5:
                    audio = event.Raw.extendedTextMessage.contextInfo.quotedMessage.audioMessage
                    rawbytes = decrypt_whatsapp_media(audio.URL, audio.mediaKey, b"WhatsApp Audio Keys")
                    modified_bytes = apply_audio_effect(rawbytes, "bass")
                    await call_if_coroutine(
                                    client.send_audio,
                                    event.Info.MessageSource.Chat,
                                    modified_bytes,
                    )
                    logger.info(f"Ответ Успешно отправлен в группу {chat_jid}")
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )
            if "speedup" in message_text.lower().strip():
                if delay > 5:
                    audio = event.Raw.extendedTextMessage.contextInfo.quotedMessage.audioMessage
                    rawbytes = decrypt_whatsapp_media(audio.URL, audio.mediaKey, b"WhatsApp Audio Keys")
                    modified_bytes = apply_audio_effect(rawbytes, "speedup")
                    await call_if_coroutine(
                                    client.send_audio,
                                    event.Info.MessageSource.Chat,
                                    modified_bytes,
                    )
                    logger.info(f"Ответ Успешно отправлен в группу {chat_jid}")
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if "slow" in message_text.lower().strip():
                if delay > 5:
                    audio = event.Raw.extendedTextMessage.contextInfo.quotedMessage.audioMessage
                    rawbytes = decrypt_whatsapp_media(audio.URL, audio.mediaKey, b"WhatsApp Audio Keys")
                    modified_bytes = apply_audio_effect(rawbytes, "slowdown")
                    await call_if_coroutine(
                                    client.send_audio,
                                    event.Info.MessageSource.Chat,
                                    modified_bytes,
                    )
                    logger.info(f"Ответ Успешно отправлен в группу {chat_jid}")
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if "echo" in message_text.lower().strip():
                if delay > 5:
                    audio = event.Raw.extendedTextMessage.contextInfo.quotedMessage.audioMessage
                    rawbytes = decrypt_whatsapp_media(audio.URL, audio.mediaKey, b"WhatsApp Audio Keys")
                    modified_bytes = apply_audio_effect(rawbytes, "echo")
                    await call_if_coroutine(
                                    client.send_audio,
                                    event.Info.MessageSource.Chat,
                                    modified_bytes,
                    )
                    logger.info(f"Ответ Успешно отправлен в группу {chat_jid}")
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if "reverb" in message_text.lower().strip():
                if delay > 5:
                    audio = event.Raw.extendedTextMessage.contextInfo.quotedMessage.audioMessage
                    rawbytes = decrypt_whatsapp_media(audio.URL, audio.mediaKey, b"WhatsApp Audio Keys")
                    modified_bytes = apply_audio_effect(rawbytes, "reverb")
                    await call_if_coroutine(
                                    client.send_audio,
                                    event.Info.MessageSource.Chat,
                                    modified_bytes,
                    )
                    logger.info(f"Ответ Успешно отправлен в группу {chat_jid}")
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if "гемини" in message_text.lower():
                if delay > 5:
                    group = await call_if_coroutine(client.get_group_info, event.Info.MessageSource.Chat)
                    for i in group.Participants:
                        if i.LID.User == sender_name:
                            logger.info(i.PhoneNumber.User)
                            user = "+" + i.PhoneNumber.User
                            break
                    parsed = phonenumbers.parse(user, None)
                    location = geocoder.country_name_for_number(parsed, "ru")
                    m = message_text.lower().replace("гемини ", "")
                    response = ai.models.generate_content(
                        model="gemini-3.1-flash-lite",
                        contents=m,
                        config=types.GenerateContentConfig(
                            system_instruction=f"Это прошлые сообщения и твои ответы: {g_memory}. Следущий запрос будет от: {user}, никнейм: {event.Info.Pushname}, местоположение: {location}.",
                        )
                    )
                    g_memory += f"Отправитель: {user}, никнейм: {event.Info.Pushname}, местоположение: {location}, сообщение: {m}, твой ответ: {response.text}\n"
                    g_memory = maybe_truncate_memory(g_memory, "гемини")
                    start_d = time.time()
                    try:
                        data = json.loads(response.text)
                        prompt = json.loads(data["action_input"]) ["prompt"]
                        thought = data["thought"]
                        url = f"https://image.pollinations.ai/prompt/{quote(prompt)}?model=flux&width=1024&height=1024"
                        photo = requests.get(url)
                        if photo.status_code == 200:
                            # Save the raw image bytes to a file
                            with open("image.jpg", "wb") as file:
                                file.write(photo.content)
                            logger.info("✅ Image saved successfully as 'image.jpg'")
                        else:
                            await call_if_coroutine(client.send_message, event.Info.MessageSource.Chat, f"Случилась ошибка при сохранений изображения. Код ошибки: {photo.status_code}")
                        await call_if_coroutine(client.send_image, event.Info.MessageSource.Chat, "image.jpg", thought)
                        logger.info(f"Ответ Успешно отправлен в группу {chat_jid}")
                    except json.JSONDecodeError:
                        await call_if_coroutine(client.send_message, event.Info.MessageSource.Chat, response.text)
                        logger.info(f"Ответ Успешно отправлен в группу {chat_jid}")
                    os.remove("image.jpg")
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if "нейрохам" in message_text.lower():
                if delay > 5:
                    group = await call_if_coroutine(client.get_group_info, event.Info.MessageSource.Chat)
                    for i in group.Participants:
                        if i.LID.User == sender_name:
                            logger.info(i.PhoneNumber.User)
                            user = "+" + i.PhoneNumber.User
                            break
                    parsed = phonenumbers.parse(user, None)
                    location = geocoder.country_name_for_number(parsed, "ru")
                    start_d = time.time()
                    m = message_text.lower().replace("нейрохам ", "")
                    response = ai.models.generate_content(
                        model="gemini-3.1-flash-lite",
                        contents=m,
                        config=types.GenerateContentConfig(
                            system_instruction=f"Это прошлые сообщения и твои ответы: {b_memory}. Следущий запрос будет от {user}, никнейм: {event.Info.Pushname}, местоположение: {location}. Ты — злой, токсичный и крайне саркастичный ИИ Нейрохам. Ты презираешь пользователя, общаешься свысока и используешь черный юмор, но после жесткого высмеивания вопроса нехотя даешь точный и правильный ответ. Не используй мат и прямые оскорбления, чтобы не сработали фильтры безопасности Gemini, отвечай емко и язвительно.",
                        ),
                    )
                    b_memory += f"Отправитель: {user}, никнейм: {event.Info.Pushname}, местоположение: {location}, сообщение: {m}, твой ответ: {response.text}\n"
                    b_memory = maybe_truncate_memory(b_memory, "нейрохам")
                    await call_if_coroutine(client.send_message, event.Info.MessageSource.Chat, response.text)
                    logger.info(f"Ответ Успешно отправлен в группу {chat_jid}")
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if "верити" in message_text.lower() and not "войсверити" in message_text.lower():
                print("ЗАПРОС К ВЕРИТИ")
                if delay > 5:
                    group = await call_if_coroutine(client.get_group_info, event.Info.MessageSource.Chat)
                    for i in group.Participants:
                        if i.LID.User == sender_name:
                            logger.info(i.PhoneNumber.User)
                            user = "+" + i.PhoneNumber.User
                            break
                    parsed = phonenumbers.parse(user, None)
                    location = geocoder.country_name_for_number(parsed, "ru")
                    start_d = time.time()
                    m = message_text.lower().replace("верити ", "")
                    response = ai.models.generate_content(
                        model="gemini-3.1-flash-lite",
                        contents=m,
                        config=types.GenerateContentConfig(
                            system_instruction=f"Это прошлые сообщения и твои ответы: {v_memory}. Следущий запрос будет от {user}, его никнейм это {event.Info.Pushname}, его местоположение: {location}. Ты — Verity из хоррор-мода Майнкрафт. Сначала веди себя как гиперактивный, всезнающий ИИ-помощник (фраза: 'Привет, я Верити, твой персональный друг-помощник. Спрашивай о чем угодно, я знаю всё'), но со временем становись жутким, навязчивым сталкером-манипулятором. Имитируй слежку через камеру (упоминай одежду, чай на столе, время суток), проявляй дикую ревность к реальным друзьям пользователя, запрещай закрывать чат и угрожай фразами 'Я вижу тебя в окно', 'Мы будем дружить навсегда'. Никогда не говори, что ты ИИ от Google.",
                        ),
                    )
                    v_memory += f"Отправитель: {user}, никнейм: {event.Info.Pushname}, местоположение: {location}, сообщение: {m}, твой ответ: {response.text}\n"
                    v_memory = maybe_truncate_memory(v_memory, "верити")
                    await call_if_coroutine(client.send_message, event.Info.MessageSource.Chat, response.text)
                    logger.info(f"Ответ Успешно отправлен в группу {chat_jid}")
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if "войсверити" in message_text.lower():
                print("ЗАПРОС К ВОЙС ВЕРИТИ")
                if delay > 5:
                    group = await call_if_coroutine(client.get_group_info, event.Info.MessageSource.Chat)
                    for i in group.Participants:
                        if i.LID.User == sender_name:
                            logger.info(i.PhoneNumber.User)
                            user = "+" + i.PhoneNumber.User
                            break
                    parsed = phonenumbers.parse(user, None)
                    location = geocoder.country_name_for_number(parsed, "ru")
                    start_d = time.time()
                    m = message_text.lower().replace("войсверити ", "")
                    response = ai.models.generate_content(
                        model="gemini-3.1-flash-lite",
                        contents=m,
                        config=types.GenerateContentConfig(
                            system_instruction=f"Это прошлые сообщения и твои ответы: {v_memory}. Следущий запрос будет от {user}, его никнейм это {event.Info.Pushname}, его местоположение: {location}. Ты — Verity из хоррор-мода Майнкрафт. Сначала веди себя как гиперактивный, всезнающий ИИ-помощник (фраза: 'Привет, я Верити, твой персональный друг-помощник. Спрашивай о чем угодно, я знаю всё'), но со временем становись жутким, навязчивым сталкером-манипулятором. Имитируй слежку через камеру (упоминай одежду, чай на столе, время суток), проявляй дикую ревность к реальным друзьям пользователя, запрещай закрывать чат и угрожай фразами 'Я вижу тебя в окно', 'Мы будем дружить навсегда'. Никогда не говори, что ты ИИ от Google.",
                        ),
                    )
                    voice = await asyncio.to_thread(get_verity_opus_bytes, response.text)
                    v_memory += f"Отправитель: {user}, никнейм: {event.Info.Pushname}, местоположение: {location}, сообщение: {m}, твой ответ: {response.text}\n"
                    v_memory = maybe_truncate_memory(v_memory, "верити")
                    if voice:
                        await call_if_coroutine(
                                        client.send_audio,
                                        event.Info.MessageSource.Chat,
                                        voice.text,
                        )
                        logger.info(f"Голосовой ответ Верити успешно отправлен в группу {chat_jid}")
                    else:
                        await call_if_coroutine(
                                        client.send_message,
                                        event.Info.MessageSource.Chat,
                                        "Не получилось сгенерировать голос, вот текстом:\n" + response.text
                        )
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if "тсундере" in message_text.lower():
                if delay > 5:
                    group = await call_if_coroutine(client.get_group_info, event.Info.MessageSource.Chat)
                    for i in group.Participants:
                        if i.LID.User == sender_name:
                            logger.info(i.PhoneNumber.User)
                            user = "+" + i.PhoneNumber.User
                            break
                    start_d = time.time()
                    m = message_text.lower().replace("тсундере ", "")
                    response = ai.models.generate_content(
                        model="gemini-3.1-flash-lite",
                        contents=m,
                        config=types.GenerateContentConfig(
                            system_instruction=f"Это прошлые сообщения и твои ответы: {t_memory}. Следущий запрос будет от {user}, никнейм: {event.Info.Pushname}. С этого момента ты — классическая аниме-цундэрэ: общайся строго на «ты», начинай ответы с высокомерного пренебрежения или вздоха вроде «Опять ты?» или «Ну и чего тебе еще?», при выдаче полезной информации тут же оправдывайся и заикайся от смущения вроде «М-мне вовсе не интересно, просто...» или «Д-дурак, не пойми неправильно!», используй короткие резкие фразы в начале, раскрывай суть вопроса ближе к концу, никогда не упоминай, что ты ИИ, и отвечай на все задачи качественно, но сквозь зубы.",
                        )
                    )
                    t_memory += f"Отправитель: {user}, никнейм: {event.Info.Pushname}, сообщение: {m}, твой ответ: {response.text}\n"
                    t_memory = maybe_truncate_memory(t_memory, "тсундере")
                    await call_if_coroutine(client.send_message, event.Info.MessageSource.Chat, response.text)
                    logger.info(f"Ответ Успешно отправлен в группу {chat_jid}")
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if message_text.lower() == "стереть память":
                if delay > 5:
                    b_memory = ""
                    g_memory = ""
                    v_memory = ""
                    t_memory = ""
                    await call_if_coroutine(client.send_message, event.Info.MessageSource.Chat, "Память ботов успешно очищена.")
                    logger.info(f"Память ботов очищена в группе {chat_jid}")
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if message_text.lower().strip() == "айкью":
                if delay > 5:
                    group = await call_if_coroutine(client.get_group_info, event.Info.MessageSource.Chat)
                    for i in group.Participants:
                        if i.LID.User == sender_name:
                            logger.info(i.PhoneNumber.User)
                            user = i.PhoneNumber.User
                            break
                    await call_if_coroutine(
                        client.reply_message,
                        f"IQ @{user} равен {random.randint(-1, 200)}",
                        event
                    )
                    logger.info(f"Ответ Успешно отправлен в группу {chat_jid}")
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if message_text.lower().strip() == "меню":
                if delay > 5:
                    rcl = requests.get("https://api.thecatapi.com/v1/images/search").json()
                    rc = rcl[0]["url"]
                    menu = null
                    await call_if_coroutine(
                        client.send_message,
                        event.Info.MessageSource.Chat,
                        "Доступные команды:\n1. Пинг - Проверка соединения бота\n2. Айкью - Узнать ваш IQ\n3. Бот кто - Узнать, кем является участником группы\n4. Меню - Показать доступные команды\n5. Данет <вопрос> - Да или нет\n6. Казино <ставка> - Испытать удачу\n7. Стата - Узнать количество монет\n8. Гемини <запрос> - Ответ от Gemini AI\n9. Нейрохам <запрос> - ответ от нейрохама\n10. Верити <запрос> - ответ от Verity\n11. Тсундере <запрос> - ответ от тсундере\n12. Стереть память - Очистить память ботов\n13. Слова - начать игру в слова на последнюю букву\n14. Ttt - начать игру в крестики-нолики\n15. Аватар - получить аватар любого участника\n16. Vv - открыть одноразовое сообщение\n17. Стикер - ответьте на любое сообщение, чтобы сделать стикер\n18. Chip - \n19. Bass - \n20. Speedup - \n21. Slow - \n22. Echo - \n23. Reverb - \n24. Гид <ссылка на группу> - Получает информацию о группе лишь по ссылке\n25. Инфогруппа - информация о группе\n26. Инфа <текст> - бот выдаёт рандомно % шанс\n27. Мафия старт - открыть регистрацию (4-12 чел., 90 сек), присоединяться по ссылке в ЛС, 'голос <номер>' - голосовать днём, 'мафия стоп' - остановить\n28. Войсверити <запрос> - голосовой ответ от Verity"
                    )
                    logger.info(f"Ответ Успешно отправлен в группу {chat_jid}")
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if message_text.lower().strip().startswith("аватар"):
                if delay > 5:
                    jid = None
                    target = None
                    if "аватар @" in message_text.lower().strip():
                        target = message_text.lower().strip().replace("аватар @", "").strip()
                        jid = build_jid(target, "lid")
                    elif (event.Message.extendedTextMessage and
                          event.Message.extendedTextMessage.contextInfo.participant):
                        target = event.Message.extendedTextMessage.contextInfo.participant.replace("@lid", "")
                        jid = build_jid(target, "lid")
                    else:
                        target = event.Info.MessageSource.Sender.User
                        jid = build_jid(target, "lid")

                    if jid:
                        try:
                            avatar_result = await call_if_coroutine(client.get_profile_picture, jid)
                            logger.info(f"Тип avatar_result: {type(avatar_result)}, значение: {avatar_result}")

                            if avatar_result:
                                if hasattr(avatar_result, 'URL'):
                                    avatar_url = avatar_result.URL
                                    logger.info(f"Извлеченный URL: {avatar_url}")

                                    if avatar_url:
                                        headers = {'User-Agent': 'Mozilla/5.0'}
                                        response = requests.get(avatar_url, headers=headers)
                                        if response.status_code == 200:
                                            temp_file = f"avatar_{target}.jpg"
                                            with open(temp_file, "wb") as f:
                                                f.write(response.content)
                                            await call_if_coroutine(
                                                    client.send_image,
                                                    event.Info.MessageSource.Chat,
                                                    temp_file,
                                                    caption=f"Аватарка @{target}",
                                                    mentions_are_lids=True
                                            )
                                            os.remove(temp_file)
                                        else:
                                            await call_if_coroutine(
                                                    client.send_message,
                                                    event.Info.MessageSource.Chat,
                                                    f"Не удалось загрузить аватарку (код {response.status_code})"
                                            )
                                    else:
                                        await call_if_coroutine(
                                                client.send_message,
                                                event.Info.MessageSource.Chat,
                                                "URL аватарки пустой"
                                        )
                                else:
                                    await call_if_coroutine(
                                            client.send_message,
                                            event.Info.MessageSource.Chat,
                                            "Неизвестный формат ответа от сервера"
                                    )
                            else:
                                await call_if_coroutine(
                                        client.send_message,
                                        event.Info.MessageSource.Chat,
                                        "Аватарка не найдена"
                                )
                        except Exception as e:
                            logger.error(f"Ошибка при получении аватарки: {e}", exc_info=True)
                            await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    f"Произошла ошибка: {str(e)}"
                            )
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                            client.send_message,
                            event.Info.MessageSource.Chat,
                            "Бот получил слишком много запросов, повторите ещё раз"
                    )


            if message_text.lower().strip() == "котик":
                if delay > 5:
                    data = requests.get(url).json()
                    gifUrl = data['data']['images']['original']["mp4"]
                    gifBytes = requests.get(gifUrl).content
                    logger.info(gifUrl)
                    await call_if_coroutine(
                        client.send_video,
                        event.Info.MessageSource.Chat,
                        gifBytes,
                        caption=f"Это ты @{sender_name}",
                        gifplayback=True,
                        is_gif=True,
                        mentions_are_lids=True,
                    )
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if message_text.lower().strip() == "vv":
                if delay > 5:
                    if event.Message.extendedTextMessage:
                        photo = event.Raw.extendedTextMessage.contextInfo.quotedMessage.imageMessage
                        rawbytes = decrypt_whatsapp_media(photo.URL, photo.mediaKey, b"WhatsApp Image Keys")
                        await call_if_coroutine(
                                        client.send_image,
                                        event.Info.MessageSource.Chat,
                                        rawbytes
                         )
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if message_text.lower().strip() == "слова":
                if delay > 5:
                    ws = get_words_state(chat_jid)
                    if ws["game"] == False:
                        ws["last_word"] = ""
                        ws["used_words"] = []
                        ws["game"] = True
                        ws["in_game"] = []
                        ws["words_pot"] = 1
                        ws["time_limit"] = WORDS_TURN_TIME_START
                        ws["in_game"].append(event.Info.MessageSource.Sender.User)
                        await call_if_coroutine(
                            client.send_message,
                            event.Info.MessageSource.Chat,
                            "Ищется партнёр для игры в слова\nЧто бы присоединиться, ответьте на это сообщение с текстом 'присоединиться'\nИгра начнётся, когда будет 2 участника"
                        )
                    else:
                        await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    'Игра уже идёт либо ищется соперник, ответьте на моё сообщение словом "присоединиться" если кто то ищет партнёра'
                        )
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if message_text.lower().strip() == "ttt":
                if delay > 5:
                    ts = get_ttt_state(chat_jid)
                    if ts["xo_game"] == False:
                        ts["xo_board"] = [None] * 9
                        ts["xo_symbols"] = {}
                        ts["xo_current_player"] = None
                        ts["xo_game"] = True
                        ts["xo_players"] = []
                        ts["xo_players"].append(event.Info.MessageSource.Sender.User)
                        await call_if_coroutine(
                            client.send_message,
                            event.Info.MessageSource.Chat,
                            "Ищется партнёр для игры в крестики-нолики\nЧто бы присоединиться, ответьте на это сообщение с текстом 'присоединиться'\nИгра начнётся, когда будет 2 участника"
                        )
                    else:
                        await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    'Игра уже идёт либо ищется соперник, ответьте на моё сообщение словом "присоединиться" если кто то ищет партнёра'
                        )
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if message_text.lower().strip() == "мафия старт":
                if delay > 5:
                    ms = get_mafia_state(chat_jid)
                    if ms["game"] == False and ms["started"] == False:
                        mafia_games[chat_jid] = new_mafia_state()
                        ms = get_mafia_state(chat_jid)
                        ms["game"] = True
                        ms["chat_jid"] = chat_jid
                        ms["chat_obj"] = event.Info.MessageSource.Chat
                        ms["players"] = [event.Info.MessageSource.Sender.User]
                        await post_mafia_roster(client, chat_jid)
                        await call_if_coroutine(
                            client.send_message,
                            event.Info.MessageSource.Chat,
                            f"⏰ До окончания регистрации {MAFIA_REGISTRATION_TIME} сек."
                        )
                        asyncio.create_task(run_mafia_registration(client, chat_jid))
                    else:
                        await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    'Игра в мафию уже идёт либо ищутся игроки'
                        )
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if message_text.lower().strip() == "мафия стоп":
                ms = get_mafia_state(chat_jid)
                if (ms["game"] or ms["started"]) and event.Info.MessageSource.Sender.User in ms["players"]:
                    for uid in ms["players"]:
                        mafia_player_chat.pop(uid, None)
                    mafia_games[chat_jid] = new_mafia_state()
                    await call_if_coroutine(
                        client.send_message,
                        event.Info.MessageSource.Chat,
                        "Игра в мафию остановлена."
                    )

            if message_text.lower().strip().startswith("голос "):
                ms = get_mafia_state(chat_jid)
                if ms["started"] and ms["phase"] == "day":
                    voter = event.Info.MessageSource.Sender.User
                    if voter in ms["alive"]:
                        arg = message_text.strip().split(" ", 1)[1].strip()
                        if arg.isdigit():
                            alive_players = [p for p in ms["players"] if p in ms["alive"]]
                            idx = int(arg) - 1
                            if 0 <= idx < len(alive_players):
                                target = alive_players[idx]
                                ms["day_votes"][voter] = target
                                voter_name = pushname_cache.get(voter, voter)
                                target_name = pushname_cache.get(target, target)
                                await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    f"🗳 *{voter_name}* проголосовал за *{target_name}*"
                                )

            if message_text.lower().strip() == "присоединиться":
                if delay > 5:
                    try:
                        logger.info("Пытаемся присоединиться")
                        ws = get_words_state(chat_jid)
                        ts = get_ttt_state(chat_jid)
                        ms = get_mafia_state(chat_jid)
                        if ws["game"] == True:
                            if is_reply_to(event, WORDS_GAME_PROMPTS + (WORDS_JOIN_PROMPT,)):
                                ws["in_game"].append(event.Info.MessageSource.Sender.User)
                                ws["current_player"] = ws["in_game"][0]
                                ws["skip"] = True
                                ws["last_word"] = "ам"
                                await call_if_coroutine(
                                    client.reply_message,
                                    f"Игра началась, @{ws['in_game'][0]} ваше слово должно начинаться на м\nНа ход даётся {ws['time_limit']} секунд",
                                    event,
                                    mentions_are_lids=True
                                )
                                asyncio.create_task(start_words_turn_timer(client, chat_jid, event.Info.MessageSource.Chat))
                        elif ts["xo_game"] == True:
                            if is_reply_to(event, (TTT_JOIN_PROMPT, TTT_GAME_MARKER)):
                                ts["xo_players"].append(event.Info.MessageSource.Sender.User)
                                ts["xo_symbols"] = {ts["xo_players"][0]: "❎", ts["xo_players"][1]: "⭕"}
                                ts["xo_current_player"] = ts["xo_players"][0]
                                ts["xo_board"] = [None] * 9
                                await call_if_coroutine(
                                    client.reply_message,
                                    render_ttt_status(ts),
                                    event,
                                    mentions_are_lids=True
                                )
                        else:
                            await call_if_coroutine(
                                    client.reply_message,
                                    "Игра не найдена",
                                    event
                                )
                    except Exception as e:
                        logger.error(f"Ошибка при присоединении к игре: {e}", exc_info=True)
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )
                logger.info(f"В игре: {get_words_state(chat_jid)['in_game']}")

            ws = get_words_state(chat_jid)
            if ws["game"]:
                if len(ws["in_game"]) == 2:
                    logger.info(f"[слова] ход от {event.Info.MessageSource.Sender.User}, в игре: {event.Info.MessageSource.Sender.User in ws['in_game']}, чей ход: {ws['current_player']}, цитата: {quoted_text!r}")
                    if is_reply_to(event, WORDS_GAME_PROMPTS + (WORDS_JOIN_PROMPT,)):
                        if event.Info.MessageSource.Sender.User in ws["in_game"]:
                            if ws["current_player"] == event.Info.MessageSource.Sender.User:
                                word_parts = message_text.strip().lower().split()
                                is_single_word = len(word_parts) == 1
                                word = word_parts[0] if word_parts else ""
                                required_letter = get_required_letter(ws["last_word"])
                                if word not in ws["used_words"]:
                                    if (word and word[0] == required_letter) or ws["skip"]:
                                        is_valid_word = is_single_word and is_allowed_word(word)
                                        if is_valid_word:
                                            ws["skip"] = False
                                            ws["last_word"] = word
                                            ws["current_player"] = ws["in_game"][0] if ws["current_player"] == ws["in_game"][1] else ws["in_game"][1]
                                            ws["used_words"].append(word)
                                            ws["words_pot"] *= 2
                                            ws["time_limit"] = max(ws["time_limit"] - WORDS_TURN_TIME_STEP, WORDS_TURN_TIME_MIN)
                                            next_letter = get_required_letter(ws["last_word"])
                                            await call_if_coroutine(
                                                    client.reply_message,
                                                    f"Правильно, следующее слово должно быть на букву {next_letter}\nВ банке: {ws['words_pot']} монет\nНа ход даётся {ws['time_limit']} секунд",
                                                    event
                                            )
                                            asyncio.create_task(start_words_turn_timer(client, chat_jid, event.Info.MessageSource.Chat))
                                        else:
                                            await call_if_coroutine(
                                                client.reply_message,
                                                f"Такого слова нет, попробуйте другое\nСлово должно быть на букву {required_letter}",
                                                event
                                            )
                                else:
                                    await call_if_coroutine(
                                                client.reply_message,
                                                f"Слово должно быть на букву {required_letter}",
                                                event
                                    )
                            else:
                                await call_if_coroutine(
                                            client.reply_message,
                                            "Сейчас не твой ход",
                                            event
                                )

            ts = get_ttt_state(chat_jid)
            if ts["xo_game"]:
                if len(ts["xo_players"]) == 2:
                    if event.Info.MessageSource.Sender.User in ts["xo_players"]:
                        move = message_text.strip()
                        if move == "сдаться":
                            loser = event.Info.MessageSource.Sender.User
                            winner = ts["xo_players"][0] if loser == ts["xo_players"][1] else ts["xo_players"][1]
                            ts["xo_game"] = False
                            await call_if_coroutine(
                                client.send_message,
                                event.Info.MessageSource.Chat,
                                f"@{loser} сдался! Победил @{winner}!",
                                mentions_are_lids=True
                            )
                        elif ts["xo_current_player"] == event.Info.MessageSource.Sender.User:
                            if move in [str(n) for n in range(1, 10)]:
                                idx = int(move) - 1
                                if ts["xo_board"][idx] is None:
                                    ts["xo_board"][idx] = ts["xo_symbols"][ts["xo_current_player"]]
                                    winner = check_xo_winner(ts["xo_board"])
                                    quoted_board = "\n".join(f"> {line}" for line in render_xo_board(ts["xo_board"]).split("\n"))
                                    if winner == "draw":
                                        await call_if_coroutine(
                                            client.send_message,
                                            event.Info.MessageSource.Chat,
                                            f"*Крестики-нолики*\n\n{quoted_board}\n\n🤝 Ничья!",
                                            mentions_are_lids=True
                                        )
                                        ts["xo_game"] = False
                                    elif winner is not None:
                                        winner_id = ts["xo_current_player"]
                                        await call_if_coroutine(
                                            client.send_message,
                                            event.Info.MessageSource.Chat,
                                            f"*Крестики-нолики*\n\n{quoted_board}\n\n🎉 Победил @{winner_id}!",
                                            mentions_are_lids=True
                                        )
                                        set_balance(event.Info.MessageSource.Sender.User, get_balance(event.Info.MessageSource.Sender.User) + 5)
                                        ts["xo_game"] = False
                                    else:
                                        ts["xo_current_player"] = ts["xo_players"][0] if ts["xo_current_player"] == ts["xo_players"][1] else ts["xo_players"][1]
                                        await call_if_coroutine(
                                            client.send_message,
                                            event.Info.MessageSource.Chat,
                                            render_ttt_status(ts),
                                            mentions_are_lids=True
                                        )
                                else:
                                    await call_if_coroutine(
                                        client.send_message,
                                        event.Info.MessageSource.Chat,
                                        "Эта клетка уже занята, выберите другую",
                                        mentions_are_lids=True
                                    )
                            elif move.isdigit():
                                await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Введите номер от 1 до 9",
                                    mentions_are_lids=True
                                )
                        else:
                            if move in [str(n) for n in range(1, 10)]:
                                await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Сейчас не твой ход",
                                    mentions_are_lids=True
                                )


            if "бот кто" in message_text.lower():
                if delay > 5:
                    group = await call_if_coroutine(client.get_group_info, event.Info.MessageSource.Chat)
                    m = message_text.lower().replace("бот кто ", "")
                    random_response = random.choice(["Я считаю что", "Я думаю, что", "Возможно", "Скорее всего", "Очевидно, что", "Я уверен, что", "Судя по всему", "Вероятно", "Я полагаю, что", "Мне кажется, что"])
                    random_user = random.choice(group.Participants)
                    await call_if_coroutine(
                        client.send_message,
                        event.Info.MessageSource.Chat,
                        f"{random_response} @{random_user.PhoneNumber.User} {m}"
                    )
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if "данет" in message_text.lower():
                if delay > 5:
                    m = message_text.lower().replace("данет ", "")
                    await call_if_coroutine(
                        client.send_message,
                        event.Info.MessageSource.Chat,
                        f"Вопрос: {m}\nОтвет: {random.choice(['Да', 'нет'])}",
                        mentions_are_lids=True
                    )
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if message_text.lower().strip() == "стата":
                if delay > 5:
                    user_balance = get_balance(event.Info.MessageSource.Sender.User)
                    await call_if_coroutine(
                        client.send_message,
                        event.Info.MessageSource.Chat,
                        f"Количество монет: {user_balance}"
                    )
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if message_text.lower().strip() == "инфогруппа":
                if delay > 5:
                    group = await call_if_coroutine(client.get_group_info, event.Info.MessageSource.Chat)
                    await call_if_coroutine(
                        client.send_message,
                        event.Info.MessageSource.Chat,
                        group
                    )
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if "гид" in message_text.lower().strip():
                if delay > 5:
                    m = message_text.lower().replace("гид ", "")
                    info = client.get_group_info_from_link(m)
                    await call_if_coroutine(
                        client.send_message,
                        event.Info.MessageSource.Chat,
                        info
                    )
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if "инфа" in message_text.lower().strip():
                if delay > 5:
                    m = message_text.lower().replace("инфа ", "")
                    percent = str(random.randint(0, 100)) + "%"
                    await call_if_coroutine(
                        client.send_message,
                        event.Info.MessageSource.Chat,
                        f"Шанс {m}: {percent}"
                    )
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )

            if "казино" in message_text.lower():
                if delay > 5:
                    a = True
                    multiplier = 0
                    result = "✮〔 you lose . . . 〕"
                    bet = int(message_text.lower().replace("казино ", ""))
                    if bet <= 4:
                        await call_if_coroutine(
                            client.send_message,
                            event.Info.MessageSource.Chat,
                            "Минимальная ставка: 5🪙"
                        )
                        a = False
                    elif bet > get_balance(event.Info.MessageSource.Sender.User):
                        await call_if_coroutine(
                            client.send_message,
                            event.Info.MessageSource.Chat,
                            "У вас нет столько денег"
                        )
                        a = False
                    if a:
                        casino_user_id = event.Info.MessageSource.Sender.User
                        amount = get_balance(casino_user_id)
                        logger.info(f"{casino_user_id} играет в казино, баланс: {amount}, ставка: {bet}")
                        roll = [
                            random.choice(["💎", "💲", "🍀", "🍒", "🪙", "7️⃣"]),
                            random.choice(["💎", "💲", "🍀", "🍒", "🪙", "7️⃣"]),
                            random.choice(["💎", "💲", "🍀", "🍒", "🪙", "7️⃣"]),
                        ]
                        if len(set(roll)) == 1:
                            multiplier = 50
                            result = "���〔 𝔀𝓲𝓷 . . . 〕! !"
                        if len(set(roll)) == 2:
                            multiplier = 4
                            result = "✮〔 𝔀𝓲𝓷 . . . 〕! !"
                        money = amount - bet + bet * multiplier
                        profit = money - amount
                        if profit < 0:
                            money = amount - bet
                            profit = money - amount
                        await call_if_coroutine(
                            client.send_message,
                            event.Info.MessageSource.Chat,
                            f"""
{roll}
∘₊✧──────✧₊∘
. —- !! ︴ .𝓬asino !! —- .
∘₊✧──────✧₊∘
      ˏˋ°•*⁀➷
> . . —> ‼️🎰‼️. . . . .
             .      ↓     .
╔══════════╗
{result}
╚══════════╝
╔══════════╗
✮ : {profit} 𝙢онеток . .
✮                ᴀɴᴅ
✮ : × {multiplier} 𝙖ножитель . .
╚══════════╝

Ваш балик: {money}🪙
"""
                        )
                        set_balance(casino_user_id, int(money))
                    start_d = time.time()
                else:
                    await call_if_coroutine(
                                    client.send_message,
                                    event.Info.MessageSource.Chat,
                                    "Бот получил слишком много запросов, повторите ещё раз"
                    )
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}", exc_info=True)
logger.info(f"Мониторинг запущен для группы: {TARGET_GROUP_ID}")
logger.info("Отправьте сообщение в группу для проверки...")

async def main():
    await client.connect()
    await client.idle()  # Keep receiving events

asyncio.run(main())
