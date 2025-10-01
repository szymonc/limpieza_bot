import os
import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# Read TOKEN from env (preferred for hosting like Render/Railway).
TOKEN = os.getenv("TOKEN", "YOUR_BOT_API_TOKEN")

# Manual Spanish month abbreviations (capitalized)
MONTHS_SHORT = {
    1: "Ene",  2: "Feb",  3: "Mar",  4: "Abr",
    5: "May",  6: "Jun",  7: "Jul",  8: "Ago",
    9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"
}

weeks = {}  # {start_iso: {"start": date, "end": date, "familia": str|None, "turno": str|None}}
pending_edits = {}  # {user_id: {"week": key, "field": "familia"|"turno"}}


def format_short_date(date_obj: datetime.date) -> str:
    """Return 'D Mmm' (e.g., '29 Sep') using manual Spanish abbreviations."""
    return f"{date_obj.day} {MONTHS_SHORT[date_obj.month]}"


def generate_weeks():
    """Generate all weeks from current week until end of June (this year or next)."""
    today = datetime.date.today()
    end = datetime.date(today.year, 6, 30) if today.month <= 6 else datetime.date(today.year + 1, 6, 30)

    weeks.clear()
    start = today - datetime.timedelta(days=today.weekday())  # Monday of current week
    while start <= end:
        end_week = start + datetime.timedelta(days=6)
        key = start.isoformat()
        weeks[key] = {"start": start, "end": end_week, "familia": None, "turno": None}
        start += datetime.timedelta(weeks=1)


def build_week_table(show_all: bool = False) -> InlineKeyboardMarkup:
    """Build inline keyboard showing headers + week rows. 3 months by default."""
    rows = []

    # Header row (labels; no-op callbacks)
    rows.append([
        InlineKeyboardButton("📅 Semana", callback_data="noop"),
        InlineKeyboardButton("👨‍👩‍👧 Familia", callback_data="noop"),
        InlineKeyboardButton("⏰ Turno", callback_data="noop"),
    ])

    today = datetime.date.today()
    cutoff = today + datetime.timedelta(weeks=12)  # ~3 months

    # Iterate in chronological order
    for key in sorted(weeks.keys()):
        w = weeks[key]
        if not show_all and w["start"] > cutoff:
            continue

        semana = f"{format_short_date(w['start'])} – {format_short_date(w['end'])}"
        familia = w["familia"] if w["familia"] else "—"
        turno = w["turno"] if w["turno"] else "—"

        rows.append([
            InlineKeyboardButton(semana, callback_data=f"week:{key}"),
            InlineKeyboardButton(familia, callback_data=f"familia:{key}"),
            InlineKeyboardButton(turno, callback_data=f"turno:{key}"),
        ])

    # Toggle button
    if not show_all:
        rows.append([InlineKeyboardButton("📅 Mostrar todo", callback_data="show_all")])
    else:
        rows.append([InlineKeyboardButton("◀ Volver a 3 meses", callback_data="show_3m")])

    return InlineKeyboardMarkup(rows)


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    generate_weeks()
    kb = build_week_table(show_all=False)
    await update.message.reply_text("📅 Planificación (próximos 3 meses):", reply_markup=kb)


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split(":", 1)
    field = data[0]

    if field in ("familia", "turno"):
        key = data[1]
        pending_edits[query.from_user.id] = {"week": key, "field": field}
        await query.message.reply_text(
            f"Escribe el {field} para la semana "
            f"{format_short_date(weeks[key]['start'])} – {format_short_date(weeks[key]['end'])} "
            f"(o /remove para borrar)."
        )

    elif field == "week":
        key = data[1]
        w = weeks[key]
        await query.message.reply_text(
            f"📅 {format_short_date(w['start'])} – {format_short_date(w['end'])}\n"
            f"Familia: {w['familia'] or '—'}\n"
            f"Turno: {w['turno'] or '—'}"
        )

    elif field == "show_all":
        kb = build_week_table(show_all=True)
        # Edit text + keyboard in place
        await query.edit_message_text("📅 Planificación completa (hasta junio):", reply_markup=kb)

    elif field == "show_3m":
        kb = build_week_table(show_all=False)
        await query.edit_message_text("📅 Planificación (próximos 3 meses):", reply_markup=kb)

    # ignore "noop"
    return


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in pending_edits:
        return

    edit = pending_edits.pop(user_id)
    week_key = edit["week"]
    field = edit["field"]

    if update.message.text.strip().lower() == "/remove":
        weeks[week_key][field] = None
    else:
        weeks[week_key][field] = update.message.text.strip()

    # After update, refresh current default view (3 months)
    kb = build_week_table(show_all=False)
    await update.message.reply_text("✅ Planificación actualizada:", reply_markup=kb)


def main():
    if not TOKEN or TOKEN == "YOUR_BOT_API_TOKEN":
        raise RuntimeError("Set your bot token via env var TOKEN or edit the code.")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()


if __name__ == "__main__":
    main()
