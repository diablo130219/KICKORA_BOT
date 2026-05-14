import os
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.environ.get("TELEGRAM_TOKEN")
AUTHORIZED_CHAT_ID = 623848005
KELLY_URL = "https://kelly-calculator-production.up.railway.app"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"KICKORA BOT running")
    def log_message(self, format, *args):
        pass

def run_health():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()

threading.Thread(target=run_health, daemon=True).start()

# Database in memoria
partite_db = []
counter = {"id": 0}

def auth(update):
    return update.effective_chat.id == AUTHORIZED_CHAT_ID

def get_next_id():
    counter["id"] += 1
    return counter["id"]

# --- COMANDI ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    msg = (
        "⚽ *KICKORA BOT v2* — Sistema Doppie\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📥 *AGGIUNGI PARTITE*\n"
        "`/aggiungi Squadra1 vs Squadra2 - Mercato - quota X.XX - prob XX`\n\n"
        "📋 *VISUALIZZA*\n"
        "`/lista` — Tutte le partite candidate\n\n"
        "🎯 *ANALISI*\n"
        "`/combina` — Tutte le combinazioni con Kelly\n"
        "`/doppia` — Migliore doppia del giorno\n\n"
        "✅ *RISULTATI*\n"
        "`/vinta ID puntata` — Segna come vinta\n"
        "`/persa ID puntata` — Segna come persa\n"
        "`/riepilogo` — Statistiche giornata\n\n"
        "🗑️ *GESTIONE*\n"
        "`/cancella ID` — Rimuovi partita\n"
        "`/reset` — Svuota lista\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📊 Esempio:\n"
        "`/aggiungi Orlando vs Philadelphia - GG - quota 1.57 - prob 60`\n\n"
        f"🧮 Kelly Calculator: {KELLY_URL}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def aggiungi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    try:
        testo = " ".join(context.args)
        parti = [p.strip() for p in testo.split("-")]

        if len(parti) < 3:
            raise ValueError("Formato non valido")

        match = parti[0].strip()
        mercato = parti[1].strip().upper()
        quota = float(parti[2].strip().lower().replace("quota","").strip())

        # Probabilità opzionale
        prob = None
        if len(parti) >= 4:
            prob_str = parti[3].strip().lower().replace("prob","").replace("%","").strip()
            prob = float(prob_str)

        partita = {
            "id": get_next_id(),
            "match": match,
            "mercato": mercato,
            "quota": quota,
            "prob": prob,
            "esito": None,
            "puntata": 0,
            "profitto": 0,
            "data": datetime.now().strftime("%H:%M")
        }
        partite_db.append(partita)

        prob_text = f"\n📊 Probabilità: *{prob}%*" if prob else "\n📊 Probabilità: *non inserita*"
        msg = (
            f"✅ *Partita aggiunta #{partita['id']}*\n\n"
            f"⚽ {match}\n"
            f"🎯 Mercato: *{mercato}*\n"
            f"💰 Quota: *{quota}*"
            f"{prob_text}\n\n"
            f"📋 Candidate oggi: *{len(partite_db)}*"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    except:
        await update.message.reply_text(
            "❌ *Formato non valido!*\n\n"
            "Usa:\n"
            "`/aggiungi Squadra1 vs Squadra2 - Mercato - quota X.XX - prob XX`\n\n"
            "Esempi:\n"
            "`/aggiungi Orlando vs Philadelphia - GG - quota 1.57 - prob 60`\n"
            "`/aggiungi Seattle vs San Jose - Over 2.5 - quota 1.85 - prob 55`",
            parse_mode="Markdown"
        )


async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return

    candidate = [p for p in partite_db if p["esito"] is None]
    giocate = [p for p in partite_db if p["esito"] is not None]

    if not partite_db:
        await update.message.reply_text(
            "📋 *Nessuna partita nella lista.*\n\nUsa `/aggiungi` per aggiungerne una.",
            parse_mode="Markdown"
        )
        return

    msg = f"📋 *PARTITE CANDIDATE* — {datetime.now().strftime('%d/%m/%Y')}\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    if candidate:
        msg += "⏳ *In attesa:*\n"
        for p in candidate:
            prob_text = f" | 📊 {p['prob']}%" if p['prob'] else ""
            msg += f"  *#{p['id']}* {p['match']}\n"
            msg += f"  🎯 {p['mercato']} | 💰 {p['quota']}{prob_text}\n\n"

    if giocate:
        msg += "━━━━━━━━━━━━━━━━━━━━\n"
        msg += "📊 *Giocate:*\n"
        for p in giocate:
            icon = "✅" if p["esito"] == "vinta" else "❌"
            prof = f"+€{p['profitto']}" if p['profitto'] > 0 else f"-€{abs(p['profitto'])}"
            msg += f"  {icon} *#{p['id']}* {p['match']} → {prof}\n"

    msg += f"\n━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📈 Candidate: *{len(candidate)}* | Giocate: *{len(giocate)}*"

    await update.message.reply_text(msg, parse_mode="Markdown")


async def combina(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return

    candidate = [p for p in partite_db if p["esito"] is None]

    if len(candidate) < 2:
        await update.message.reply_text(
            "❌ Servono almeno *2 partite candidate* per combinare.\n"
            "Usa `/aggiungi` per aggiungerne.",
            parse_mode="Markdown"
        )
        return

    # Calcola tutte le combinazioni possibili
    combinazioni = []
    for i in range(len(candidate)):
        for j in range(i+1, len(candidate)):
            p1 = candidate[i]
            p2 = candidate[j]
            quota_combo = round(p1["quota"] * p2["quota"], 2)

            # Calcola probabilità combo se disponibili
            prob_combo = None
            if p1["prob"] and p2["prob"]:
                prob_combo = round((p1["prob"]/100) * (p2["prob"]/100) * 100, 1)

            # Calcola edge se probabilità disponibile
            edge = None
            if prob_combo:
                edge = round((prob_combo/100) * quota_combo - 1, 3) * 100
                edge = round(edge, 1)

            combinazioni.append({
                "p1": p1,
                "p2": p2,
                "quota_combo": quota_combo,
                "prob_combo": prob_combo,
                "edge": edge
            })

    # Ordina per edge (se disponibile) o per quota
    combinazioni_con_edge = [c for c in combinazioni if c["edge"] is not None]
    combinazioni_senza_edge = [c for c in combinazioni if c["edge"] is None]

    if combinazioni_con_edge:
        combinazioni_con_edge.sort(key=lambda x: x["edge"], reverse=True)
        combinazioni_ordinate = combinazioni_con_edge + combinazioni_senza_edge
    else:
        combinazioni_ordinate = sorted(combinazioni, key=lambda x: x["quota_combo"], reverse=True)

    msg = "🎯 *TUTTE LE COMBINAZIONI*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, c in enumerate(combinazioni_ordinate[:8], 1):  # Max 8 combinazioni
        icon = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."

        msg += f"{icon} *#{c['p1']['id']} + #{c['p2']['id']}*\n"
        msg += f"  ⚽ {c['p1']['match']}\n"
        msg += f"  ⚽ {c['p2']['match']}\n"
        msg += f"  💰 Quota combo: *{c['quota_combo']}*\n"

        if c["prob_combo"]:
            msg += f"  📊 Prob combo: *{c['prob_combo']}%*\n"
            if c["edge"] is not None:
                edge_icon = "✅" if c["edge"] > 0 else "❌"
                msg += f"  📈 Edge: *{c['edge']}%* {edge_icon}\n"
        else:
            msg += f"  📊 Prob: *inserisci prob per vedere edge*\n"

        msg += "\n"

    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"🧮 Calcola puntata: {KELLY_URL}"

    await update.message.reply_text(msg, parse_mode="Markdown")


async def doppia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return

    candidate = [p for p in partite_db if p["esito"] is None]

    if len(candidate) < 2:
        await update.message.reply_text(
            "❌ Servono almeno *2 partite candidate*.",
            parse_mode="Markdown"
        )
        return

    # Trova la combinazione migliore
    migliore = None
    migliore_edge = -999

    for i in range(len(candidate)):
        for j in range(i+1, len(candidate)):
            p1 = candidate[i]
            p2 = candidate[j]
            quota_combo = round(p1["quota"] * p2["quota"], 2)

            if p1["prob"] and p2["prob"]:
                prob_combo = (p1["prob"]/100) * (p2["prob"]/100) * 100
                edge = round(prob_combo/100 * quota_combo - 1, 3) * 100

                if edge > migliore_edge:
                    migliore_edge = edge
                    migliore = {
                        "p1": p1, "p2": p2,
                        "quota_combo": quota_combo,
                        "prob_combo": round(prob_combo, 1),
                        "edge": round(edge, 1)
                    }
            else:
                # Se non ci sono probabilità usa quota più alta
                if migliore is None:
                    migliore = {
                        "p1": p1, "p2": p2,
                        "quota_combo": quota_combo,
                        "prob_combo": None,
                        "edge": None
                    }

    if not migliore:
        await update.message.reply_text("❌ Errore nel calcolo.", parse_mode="Markdown")
        return

    edge_text = ""
    consiglio = ""
    if migliore["edge"] is not None:
        if migliore["edge"] > 5:
            edge_text = f"\n📈 Edge: *+{migliore['edge']}%* ✅"
            consiglio = "\n\n💡 *Doppia con valore — giocabile!*"
        elif migliore["edge"] > 0:
            edge_text = f"\n📈 Edge: *+{migliore['edge']}%* ⚠️"
            consiglio = "\n\n💡 *Edge basso — valuta con attenzione*"
        else:
            edge_text = f"\n📈 Edge: *{migliore['edge']}%* ❌"
            consiglio = "\n\n🚫 *Nessun valore — considera di non giocare*"

    prob_text = f"\n📊 Prob combo: *{migliore['prob_combo']}%*" if migliore["prob_combo"] else ""

    msg = (
        f"🎯 *MIGLIORE DOPPIA DEL GIORNO*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"1️⃣ *{migliore['p1']['match']}*\n"
        f"   🎯 {migliore['p1']['mercato']} | 💰 {migliore['p1']['quota']}"
        f"{' | 📊 ' + str(migliore['p1']['prob']) + '%' if migliore['p1']['prob'] else ''}\n\n"
        f"2️⃣ *{migliore['p2']['match']}*\n"
        f"   🎯 {migliore['p2']['mercato']} | 💰 {migliore['p2']['quota']}"
        f"{' | 📊 ' + str(migliore['p2']['prob']) + '%' if migliore['p2']['prob'] else ''}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Quota combo: *{migliore['quota_combo']}*"
        f"{prob_text}"
        f"{edge_text}"
        f"{consiglio}\n\n"
        f"🧮 Calcola puntata:\n{KELLY_URL}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def vinta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    try:
        id = int(context.args[0])
        puntata = float(context.args[1]) if len(context.args) > 1 else 10.0
        partita = next((p for p in partite_db if p["id"] == id), None)
        if not partita:
            await update.message.reply_text(f"❌ Partita #{id} non trovata.")
            return
        partita["esito"] = "vinta"
        partita["puntata"] = puntata
        partita["profitto"] = round((partita["quota"] - 1) * puntata, 2)
        await update.message.reply_text(
            f"✅ *Partita #{id} VINTA!*\n"
            f"⚽ {partita['match']}\n"
            f"💰 Puntata: €{puntata} | Profitto: *+€{partita['profitto']}*",
            parse_mode="Markdown"
        )
    except:
        await update.message.reply_text(
            "Formato: `/vinta ID puntata`\nEs: `/vinta 1 10`",
            parse_mode="Markdown"
        )


async def persa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    try:
        id = int(context.args[0])
        puntata = float(context.args[1]) if len(context.args) > 1 else 10.0
        partita = next((p for p in partite_db if p["id"] == id), None)
        if not partita:
            await update.message.reply_text(f"❌ Partita #{id} non trovata.")
            return
        partita["esito"] = "persa"
        partita["puntata"] = puntata
        partita["profitto"] = -round(puntata, 2)
        await update.message.reply_text(
            f"❌ *Partita #{id} persa.*\n"
            f"⚽ {partita['match']}\n"
            f"💰 Perdita: *-€{puntata}*",
            parse_mode="Markdown"
        )
    except:
        await update.message.reply_text(
            "Formato: `/persa ID puntata`\nEs: `/persa 1 10`",
            parse_mode="Markdown"
        )


async def riepilogo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return

    if not partite_db:
        await update.message.reply_text("📊 Nessuna partita oggi.")
        return

    vinte = [p for p in partite_db if p["esito"] == "vinta"]
    perse = [p for p in partite_db if p["esito"] == "persa"]
    in_attesa = [p for p in partite_db if p["esito"] is None]
    profitto = sum(p["profitto"] for p in partite_db)
    giocate = len(vinte) + len(perse)
    hr = round(len(vinte)/giocate*100) if giocate else 0

    msg = (
        f"📊 *RIEPILOGO GIORNATA*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 Candidate totali: *{len(partite_db)}*\n"
        f"⏳ In attesa: *{len(in_attesa)}*\n"
        f"✅ Vinte: *{len(vinte)}*\n"
        f"❌ Perse: *{len(perse)}*\n\n"
        f"🎯 Hit rate: *{hr}%*\n"
        f"💰 Profitto: *{'+'if profitto>=0 else ''}€{round(profitto,2)}*"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cancella(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    try:
        id = int(context.args[0])
        partita = next((p for p in partite_db if p["id"] == id), None)
        if not partita:
            await update.message.reply_text(f"❌ Partita #{id} non trovata.")
            return
        partite_db.remove(partita)
        await update.message.reply_text(
            f"🗑️ *Partita #{id} rimossa*\n{partita['match']}",
            parse_mode="Markdown"
        )
    except:
        await update.message.reply_text("Formato: `/cancella ID`", parse_mode="Markdown")


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    count = len(partite_db)
    partite_db.clear()
    counter["id"] = 0
    await update.message.reply_text(
        f"🔄 *Lista svuotata!*\n{count} partite rimosse.",
        parse_mode="Markdown"
    )


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("aggiungi", aggiungi))
    app.add_handler(CommandHandler("lista", lista))
    app.add_handler(CommandHandler("combina", combina))
    app.add_handler(CommandHandler("doppia", doppia))
    app.add_handler(CommandHandler("vinta", vinta))
    app.add_handler(CommandHandler("persa", persa))
    app.add_handler(CommandHandler("riepilogo", riepilogo))
    app.add_handler(CommandHandler("cancella", cancella))
    app.add_handler(CommandHandler("reset", reset))
    logger.info("🚀 KICKORA BOT v2 avviato!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
