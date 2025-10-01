import os
import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# ----------------------------
# Config (env vars on Railway)
# ----------------------------
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not TOKEN:
    raise RuntimeError("Set env var TOKEN with your bot token")
if not DATABASE_URL:
    raise RuntimeError("Set env var DATABASE_URL with your Postgres connection string")

# Manual Spanish month abbreviations (capitalized)
MONTHS_SHORT = {
    1: "Ene",  2: "Feb",  3: "Mar",  4: "Abr",
    5: "May",  6: "Jun",  7: "Jul",  8: "Ago",
    9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"
}

# In-memory cache of current planning window (overlayed from DB on start or /plan)
weeks = {}  # {start_iso: {"start": date, "end": date, "familia": str|None, "turno": str|None}}
pending_edits = {}  # {user_id: {"week": key, "field": "familia"|"turno"}}

# ----------------------------
# Database helpers
# ----------------------------
def get_conn():
    # One global connection; Railway keeps a stable network for the container
    # Reconnect if needed
    global _conn
    try:
        if _conn and _conn.closed == 0:
            return _conn
    except NameError:
        pass
    _conn = psycopg2.connect(DATABASE_URL)
    _conn.autocommit = True
    return _conn

def init_db():
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS schedule (
            week_start DATE PRIMARY KEY,
            familia TEXT,
            turno   TEXT
        );
        """)
    return conn

def upsert_week(week_start: datetime.date, familia, turno):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO schedule (week_start, familia, turno)
            VALUES (%s, %s, %s)
            ON CONFLICT (week_start)
            DO UPDATE SET familia = EXCLUDED.familia, turno = EXCLUDED.turno;
        """, (week_start, familia, turno))

def load_all_weeks_from_db():
    conn = get_conn()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT week_start, familia, turno FROM schedule;")
        return cur.fetchall()

# ----------------------------
# Planning helpers
# ----------------------------
def format_short_date(d: datetime.date) -> str:
    return f"{d.day} {MONTHS_SHORT[d.month]}"

def generate_weeks():
    """Create in-memory weeks from current week to end of June (this year or next). Then overlay DB values."""
    today = datetime.date.today()
    end = datetime.date(today.year, 6, 30) if today.month <= 6 else datetime.date(today.year + 1, 6, 30)

    weeks.clear()
    start = today - datetime.timedelta(days=today.weekday())  # Monday of current week
    while start <= end:
        end_week = start + datetime.timedelta(days=6)
        key = start.isoformat()
        weeks[key] = {"start": start, "end": end_week, "familia": None, "turno": None}
        start += datetime.timedelta(weeks=1)

    # Overlay with DB data (only for weeks in our window)
    for row in load_all_weeks_from_db():
        wk = row["week_start"]
        key = wk.isoformat()
        if key in weeks:
            weeks[key]["familia"] = row["familia"]
            weeks[key]["turno"] = row["turno"]

def build_week_table(show_all: bool = False) -> InlineKeyboardMarkup:
    rows = []

    # Header row (labels only)
    rows.append([
        InlineKeyboardButton("📅 Semana", callback_data="noop"),
        InlineKeyboardButton("👨‍👩‍👧 Familia", callback_data="noop"),
        InlineKeyboardButton("⏰ Turno", callback_data="noop"),
    ])

    today = datetime.date.today()
    cutoff = today + datetime.timedelta(weeks=12)  # ~3 months

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

    if not show_all:
        rows.append([InlineKeyboardButton("📅 Mostrar todo", callback_data="show_all")])
    else:
        rows.append([InlineKeyboardButton("◀ Volver a 3 meses", callback_data="show_3m")])

    return InlineKeyboardMarkup(rows)

# ----------------------------
# Handlers
# ----------------------------
async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_db()
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
        await query.edit_message_text("📅 Planificación completa (hasta junio):", reply_markup=kb)

    elif field == "show_3m":
        kb = build_week_table(show_all=False)
        await query.edit_message_text("📅 Planificación (próximos 3 meses):", reply_markup=kb)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in pending_edits:
        return

    edit = pending_edits.pop(user_id)
    week_key = edit["week"]
    field = edit["field"]

    # Update in memory
    if update.message.text.strip().lower() == "/remove":
        weeks[week_key][field] = None
    else:
        weeks[week_key][field] = update.message.text.strip()

    # Persist to DB (upsert both fields for that week_start)
    week_start_date = datetime.date.fromisoformat(week_key)
    familia = weeks[week_key]["familia"]
    turno = weeks[week_key]["turno"]
    upsert_week(week_start_date, familia, turno)

    # Refresh 3-month view
    kb = build_week_table(show_all=False)
    await update.message.reply_text("✅ Planificación actualizada:", reply_markup=kb)

# ----------------------------
# Main
# ----------------------------
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

if __name__ == "__main__":
    main()
