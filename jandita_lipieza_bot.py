import datetime
import locale
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# Use Spanish locale for month names (requires es_ES installed on system)
locale.setlocale(locale.LC_TIME, "es_ES.UTF-8")

TOKEN = "8164473342:AAGNBxvfm5o5r56vTIIGLN8e3ejVsR3tff4"

weeks = {}
pending_edits = {}  # {user_id: {"week": key, "field": "familia"|"turno"}}


def generate_weeks():
    """Generate all weeks until end of June next year."""
    today = datetime.date.today()
    end = datetime.date(today.year, 6, 30) if today.month <= 6 else datetime.date(today.year + 1, 6, 30)

    weeks.clear()
    start = today - datetime.timedelta(days=today.weekday())  # Monday of current week
    while start <= end:
        end_week = start + datetime.timedelta(days=6)
        key = start.isoformat()
        weeks[key] = {"start": start, "end": end_week, "familia": None, "turno": None}
        start += datetime.timedelta(weeks=1)


def format_short_date(date_obj):
    """Format date as 'DD Mmm' with capitalized short month name."""
    month = date_obj.strftime("%b")
    return f"{date_obj.day} {month[:1].upper()}{month[1:]}"


def build_week_table(show_all=False):
    """Build inline keyboard for 3 months or all weeks, with headers."""
    rows = []

    # Header row
    rows.append([
        InlineKeyboardButton("📅 Semana", callback_data="noop"),
        InlineKeyboardButton("👨‍👩‍👧 Familia", callback_data="noop"),
        InlineKeyboardButton("⏰ Turno", callback_data="noop")
    ])

    today = datetime.date.today()
    cutoff = today + datetime.timedelta(weeks=12)  # ~3 months

    for key, w in weeks.items():
        if not show_all and w['start'] > cutoff:
            continue

        semana = f"{format_short_date(w['start'])} – {format_short_date(w['end'])}"
        familia = w['familia'] if w['familia'] else "—"
        turno = w['turno'] if w['turno'] else "—"

        rows.append([
            InlineKeyboardButton(semana, callback_data=f"week:{key}"),
            InlineKeyboardButton(familia, callback_data=f"familia:{key}"),
            InlineKeyboardButton(turno, callback_data=f"turno:{key}")
        ])

    # Add "Show All" button if only 3 months
    if not show_all:
        rows.append([InlineKeyboardButton("📅 Mostrar todo", callback_data="show_all")])

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

    if field == "familia" or field == "turno":
        key = data[1]
        pending_edits[query.from_user.id] = {"week": key, "field": field}
        await query.message.reply_text(
            f"Escribe el {field} para la semana {format_short_date(weeks[key]['start'])} – {format_short_date(weeks[key]['end'])} (o /remove para borrar)."
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
        await query.edit_message_text("📅 Planificación completa (hasta junio):", reply_markup=kb)


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

    # Refresh 3-month view
    kb = build_week_table(show_all=False)
    await update.message.reply_text("✅ Planificación actualizada:", reply_markup=kb)


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()


if __name__ == "__main__":
    main()
