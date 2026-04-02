import json
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
USERS_FILE = DATA_DIR / "users.json"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# --- storage helpers ---

def _path(user_id: int) -> Path:
    return DATA_DIR / f"{user_id}.data"


def load_tasks(user_id: int) -> list[dict]:
    p = _path(user_id)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def save_tasks(user_id: int, tasks: list[dict]) -> None:
    _path(user_id).write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")


def load_known_users() -> set[int]:
    if not USERS_FILE.exists():
        return set()
    raw = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return set()
    out: set[int] = set()
    for v in raw:
        try:
            out.add(int(v))
        except (TypeError, ValueError):
            continue
    return out


def save_known_users(user_ids: set[int]) -> None:
    USERS_FILE.write_text(
        json.dumps(sorted(user_ids), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def register_user(user_id: int) -> None:
    user_ids = load_known_users()
    if user_id not in user_ids:
        user_ids.add(user_id)
        save_known_users(user_ids)


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def list_user_ids_who_used_bot() -> list[int]:
    # Union of explicit registry + any existing per-user data files
    user_ids = set(load_known_users())
    for p in DATA_DIR.glob("*.data"):
        try:
            user_ids.add(int(p.stem))
        except ValueError:
            continue
    return sorted(user_ids)


# --- inline keyboard builders ---

STATUS_LABEL = {"open": "\u2b55", "done": "\u2705"}


def tasks_keyboard(tasks: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for i, t in enumerate(tasks):
        num = i + 1
        toggle_label = "\u2705" if t["status"] == "open" else "\u21a9\ufe0f"
        buttons.append([
            InlineKeyboardButton(text=f"{num}. {toggle_label}", callback_data=f"toggle:{i}"),
            InlineKeyboardButton(text=f"{num}. \u270f\ufe0f", callback_data=f"edit:{i}"),
            InlineKeyboardButton(text=f"{num}. \U0001f5d1", callback_data=f"delete:{i}"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_todo_text(tasks: list[dict]) -> str:
    if not tasks:
        return "\U0001f4dd Список задач пуст. Отправьте сообщение, чтобы добавить задачу."
    total = len(tasks)
    done = sum(1 for t in tasks if t["status"] == "done")
    lines = [f"\U0001f4dd Ваши задачи ({done}/{total} выполнено):\n"]
    for i, t in enumerate(tasks):
        icon = STATUS_LABEL[t["status"]]
        text = t["text"]
        if t["status"] == "done":
            text = f"<s>{text}</s>"
        lines.append(f"{i + 1}. {icon} {text}")
    return "\n".join(lines)


# --- state for edit mode ---
# simple in-memory dict: user_id -> task index being edited
edit_state: dict[int, int] = {}


# --- handlers ---

@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    register_user(message.from_user.id)
    await message.answer(
        "\U0001f44b \u041f\u0440\u0438\u0432\u0435\u0442! \u042f \u0431\u043e\u0442 \u0434\u043b\u044f \u0432\u0435\u0434\u0435\u043d\u0438\u044f \u0441\u043f\u0438\u0441\u043a\u0430 \u0437\u0430\u0434\u0430\u0447.\n\n"
        "\u041e\u0442\u043f\u0440\u0430\u0432\u044c\u0442\u0435 \u043c\u043d\u0435 \u0442\u0435\u043a\u0441\u0442\u043e\u0432\u043e\u0435 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435 \u2014 \u044f \u0441\u043e\u0445\u0440\u0430\u043d\u044e \u0435\u0433\u043e \u043a\u0430\u043a \u0437\u0430\u0434\u0430\u0447\u0443.\n"
        "/todo \u2014 \u043f\u043e\u043a\u0430\u0437\u0430\u0442\u044c \u0441\u043f\u0438\u0441\u043e\u043a \u0437\u0430\u0434\u0430\u0447"
    )


@router.message(Command("todo"))
async def cmd_todo(message: Message) -> None:
    register_user(message.from_user.id)
    tasks = load_tasks(message.from_user.id)
    text = format_todo_text(tasks)
    if tasks:
        await message.answer(text, reply_markup=tasks_keyboard(tasks), parse_mode="HTML")
    else:
        await message.answer(text, parse_mode="HTML")


@router.message(Command("users"))
async def cmd_users(message: Message) -> None:
    register_user(message.from_user.id)
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Команда доступна только администратору.")
        return
    user_ids = list_user_ids_who_used_bot()
    if not user_ids:
        await message.answer("Пока никто не пользовался ботом.")
        return
    text = "👥 Пользователи, которые уже использовали бота:\n\n" + "\n".join(str(x) for x in user_ids)
    await message.answer(text)


@router.callback_query(F.data.startswith("toggle:"))
async def cb_toggle(callback: CallbackQuery) -> None:
    register_user(callback.from_user.id)
    idx = int(callback.data.split(":")[1])
    tasks = load_tasks(callback.from_user.id)
    if idx >= len(tasks):
        await callback.answer("\u0417\u0430\u0434\u0430\u0447\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430")
        return
    tasks[idx]["status"] = "done" if tasks[idx]["status"] == "open" else "open"
    save_tasks(callback.from_user.id, tasks)
    await callback.message.edit_text(format_todo_text(tasks), reply_markup=tasks_keyboard(tasks), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("delete:"))
async def cb_delete(callback: CallbackQuery) -> None:
    register_user(callback.from_user.id)
    idx = int(callback.data.split(":")[1])
    tasks = load_tasks(callback.from_user.id)
    if idx >= len(tasks):
        await callback.answer("\u0417\u0430\u0434\u0430\u0447\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430")
        return
    removed = tasks.pop(idx)
    save_tasks(callback.from_user.id, tasks)
    text = format_todo_text(tasks)
    if tasks:
        await callback.message.edit_text(text, reply_markup=tasks_keyboard(tasks), parse_mode="HTML")
    else:
        await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer(f"\u0423\u0434\u0430\u043b\u0435\u043d\u043e: {removed['text']}")


@router.callback_query(F.data.startswith("edit:"))
async def cb_edit(callback: CallbackQuery) -> None:
    register_user(callback.from_user.id)
    idx = int(callback.data.split(":")[1])
    tasks = load_tasks(callback.from_user.id)
    if idx >= len(tasks):
        await callback.answer("\u0417\u0430\u0434\u0430\u0447\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430")
        return
    edit_state[callback.from_user.id] = idx
    await callback.message.answer(
        f"\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043d\u043e\u0432\u044b\u0439 \u0442\u0435\u043a\u0441\u0442 \u0434\u043b\u044f \u0437\u0430\u0434\u0430\u0447\u0438 \u00ab{tasks[idx]['text']}\u00bb:"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("noop:"))
async def cb_noop(callback: CallbackQuery) -> None:
    register_user(callback.from_user.id)
    await callback.answer()


@router.message(F.text)
async def on_text(message: Message) -> None:
    user_id = message.from_user.id
    register_user(user_id)

    # if user is in edit mode, update the task
    if user_id in edit_state:
        idx = edit_state.pop(user_id)
        tasks = load_tasks(user_id)
        if idx < len(tasks):
            tasks[idx]["text"] = message.text
            save_tasks(user_id, tasks)
            await message.answer(f"\u2705 \u0417\u0430\u0434\u0430\u0447\u0430 \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0430: {message.text}")
        else:
            await message.answer("\u0417\u0430\u0434\u0430\u0447\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430, \u0441\u043e\u0445\u0440\u0430\u043d\u044f\u044e \u043a\u0430\u043a \u043d\u043e\u0432\u0443\u044e.")
            tasks.append({"text": message.text, "status": "open"})
            save_tasks(user_id, tasks)
        return

    # otherwise — add new task
    tasks = load_tasks(user_id)
    tasks.append({"text": message.text, "status": "open"})
    save_tasks(user_id, tasks)
    await message.answer(f"\u2705 \u0417\u0430\u0434\u0430\u0447\u0430 \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u0430: {message.text}")


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
