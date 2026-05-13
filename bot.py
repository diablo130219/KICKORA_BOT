import os
import logging
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# --- MINI WEB SERVER per Render ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"KICKORA BOT is running!")
    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

threading.Thread(target=run_health_server, daemon=True).start()

# --- CONFIG ---
TOKEN = os.environ.get("TELEGRAM_TOKEN", "IL_TUO_TOKEN_QUI")
AUTHORIZED_CHAT_ID = 623848005

# --- LOGGING ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- DATABASE IN MEMORIA ---
partite_db = []
counter = {"id": 0}


def is_authorized(update: Update) -> bool:
    return update.effective_chat.id == AUTHORIZED_CHAT_ID


def get_next_id():
    counter["id"] += 1
    return counter["id"]


# --- COMANDI ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    msg = (
        "⚽ *KICKORA BOT* — Sistema Doppie\n\n"
        "Comandi disponibili:\n\n"
        "➕ `/aggiungi Casa vs Trasferta - Strategia - quota X.XX`\n"
        "📋 `/lista` — Vedi tutte le partite di oggi\n"
        "🗑️ `/cancella N` — Rimuovi partita per numero\n"
        "🔄 `/reset` — Svuota tutta la lista\n"
        "🎯 `/doppia` — Suggerisce la doppia migliore\n"
        "✅ `/vinta N` — Segna partita come vinta\n"
        "❌ `/persa N` — Segna partita come persa\n"
        "📊 `/riepilogo` — Statistiche del giorno\n\n"
        "Esempio:\n"
        "`/aggiungi Brage vs Östersund - GG - quota 1.74`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def aggiungi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    try:
        testo = " ".join(context.args)

        if "-" not in testo or "vs" not in testo.lower():
            raise ValueError("Formato non valido")

        parti = [p.strip() for p in testo.split("-")]
        if len(parti) < 3:
            raise ValueError("Mancano dei campi")

        squadre = parti[0].strip()
        if "vs" in squadre:
            casa = squadre.split("vs")[0].strip()
            trasferta = squadre.split("vs")[1].strip()
        else:
            casa = squadre.split("VS")[0].strip()
            trasferta = squadre.split("VS")[1].strip()

        strategia = parti[1].strip().upper()
        quota_str = parti[2].strip().lower().replace("quota", "").strip()
        quota = float(quota_str)

        partita = {
            "id": get_next_id(),
            "casa": casa,
            "trasferta": trasferta,
            "strategia": strategia,
            "quota": quota,
            "aggiunta_alle": datetime.now().strftime("%H:%M"),
            "esito": None
        }
        partite_db.append(partita)

        msg = (
            f"✅ *Partita aggiunta!*\n\n"
            f"⚽ {casa} vs {trasferta}\n"
            f"🎯 Strategia: *{strategia}*\n"
            f"💰 Quota: *{quota}*\n"
            f"🕐 Aggiunta alle: {partita['aggiunta_alle']}\n\n"
            f"📋 Totale partite oggi: *{len(partite_db)}*"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    except (ValueError, IndexError):
        await update.message.reply_text(
            "❌ *Formato non valido!*\n\n"
            "Usa questo formato:\n"
            "`/aggiungi Casa vs Trasferta - Strategia - quota X.XX`\n\n"
            "Esempio:\n"
            "`/aggiungi Brage vs Östersund - GG - quota 1.74`",
            parse_mode="Markdown"
        )


async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    if not partite_db:
        await update.message.reply_text(
            "📋 *Nessuna partita nella lista.*\n\n"
            "Usa `/aggiungi` per aggiungerne una.",
            parse_mode="Markdown"
        )
        return

    msg = f"📋 *PARTITE DI OGGI* — {datetime.now().strftime('%d/%m/%Y')}\n"
    msg += "─" * 30 + "\n\n"

    for p in partite_db:
        esito_icon = "⏳" if p["esito"] is None else ("✅" if p["esito"] else "❌")
        msg += (
            f"{esito_icon} *#{p['id']}* — {p['casa']} vs {p['trasferta']}\n"
            f"   🎯 {p['strategia']} | 💰 {p['quota']} | 🕐 {p['aggiunta_alle']}\n\n"
        )

    msg += "─" * 30 + "\n"
    msg += f"📊 Partite totali: *{len(partite_db)}*\n"
    if len(partite_db) >= 2:
        q = round(partite_db[0]['quota'] * partite_db[1]['quota'], 2)
        msg += f"🎰 Quota doppia (prime 2): *{q}*"

    await update.message.reply_text(msg, parse_mode="Markdown")


async def cancella(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    try:
        num_id = int(context.args[0])
        partita = next((p for p in partite_db if p["id"] == num_id), None)

        if not partita:
            await update.message.reply_text(f"❌ Partita #{num_id} non trovata.")
            return

        partite_db.remove(partita)
        await update.message.reply_text(
            f"🗑️ *Partita #{num_id} rimossa*\n"
            f"{partita['casa']} vs {partita['trasferta']} - {partita['strategia']}",
            parse_mode="Markdown"
        )

    except (IndexError, ValueError):
        await update.message.reply_text(
            "❌ Specifica il numero della partita.\n"
            "Esempio: `/cancella 2`",
            parse_mode="Markdown"
        )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    count = len(partite_db)
    partite_db.clear()
    counter["id"] = 0
    await update.message.reply_text(
        f"🔄 *Lista svuotata!*\n{count} partite rimosse.",
        parse_mode="Markdown"
    )


async def doppia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    if len(partite_db) < 2:
        await update.message.reply_text(
            "❌ Servono almeno *2 partite* nella lista.\n"
            "Usa `/aggiungi` per aggiungerne.",
            parse_mode="Markdown"
        )
        return

    partite_ordinate = sorted(partite_db, key=lambda x: x["quota"], reverse=True)
    p1 = partite_ordinate[0]
    p2 = partite_ordinate[1]
    quota_combo = round(p1["quota"] * p2["quota"], 2)

    msg = (
        f"🎯 *DOPPIA CONSIGLIATA*\n"
        f"─────────────────────\n\n"
        f"1️⃣ *{p1['casa']} vs {p1['trasferta']}*\n"
        f"   🎯 {p1['strategia']} | 💰 quota {p1['quota']}\n\n"
        f"2️⃣ *{p2['casa']} vs {p2['trasferta']}*\n"
        f"   🎯 {p2['strategia']} | 💰 quota {p2['quota']}\n\n"
        f"─────────────────────\n"
        f"💰 *Quota combinata: {quota_combo}*\n"
    )

    if quota_combo < 1.80:
        msg += "⚠️ Quota bassa — valuta se giocarla"
    elif quota_combo < 2.50:
        msg += "✅ Quota accettabile"
    else:
        msg += "🔥 Quota interessante!"

    await update.message.reply_text(msg, parse_mode="Markdown")


async def vinta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await _set_esito(update, context, True)


async def persa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await _set_esito(update, context, False)


async def _set_esito(update: Update, context: ContextTypes.DEFAULT_TYPE, esito: bool):
    try:
        num_id = int(context.args[0])
        partita = next((p for p in partite_db if p["id"] == num_id), None)

        if not partita:
            await update.message.reply_text(f"❌ Partita #{num_id} non trovata.")
            return

        partita["esito"] = esito
        icon = "✅" if esito else "❌"
        stato = "VINTA" if esito else "PERSA"
        await update.message.reply_text(
            f"{icon} *Partita #{num_id} segnata come {stato}*\n"
            f"{partita['casa']} vs {partita['trasferta']} - {partita['strategia']}",
            parse_mode="Markdown"
        )
    except (IndexError, ValueError):
        cmd = "vinta" if esito else "persa"
        await update.message.reply_text(
            f"Esempio: `/{cmd} 1`",
            parse_mode="Markdown"
        )


async def riepilogo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    if not partite_db:
        await update.message.reply_text("📊 Nessuna partita oggi.")
        return

    vinte = [p for p in partite_db if p["esito"] is True]
    perse = [p for p in partite_db if p["esito"] is False]
    in_attesa = [p for p in partite_db if p["esito"] is None]

    msg = (
        f"📊 *RIEPILOGO GIORNATA*\n"
        f"─────────────────────\n\n"
        f"✅ Vinte: *{len(vinte)}*\n"
        f"❌ Perse: *{len(perse)}*\n"
        f"⏳ In attesa: *{len(in_attesa)}*\n"
        f"📋 Totale: *{len(partite_db)}*\n\n"
    )

    if vinte or perse:
        totale = len(vinte) + len(perse)
        perc = round(len(vinte) / totale * 100) if totale > 0 else 0
        msg += f"🎯 Hit rate: *{perc}%*"

    await update.message.reply_text(msg, parse_mode="Markdown")


# --- MAIN ---
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("aggiungi", aggiungi))
    app.add_handler(CommandHandler("lista", lista))
    app.add_handler(CommandHandler("cancella", cancella))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("doppia", doppia))
    app.add_handler(CommandHandler("vinta", vinta))
    app.add_handler(CommandHandler("persa", persa))
    app.add_handler(CommandHandler("riepilogo", riepilogo))

    logger.info("🚀 KICKORA BOT avviato!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
