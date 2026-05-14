import os
import io
import csv
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

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

# Database
partite_db = []
counter = {"id": 0}

def auth(update):
    return update.effective_chat.id == AUTHORIZED_CHAT_ID

def get_next_id():
    counter["id"] += 1
    return counter["id"]

def parse_num(val):
    """Converte numeri italiani (virgola) in float"""
    try:
        return float(str(val).replace(",", ".").replace('"', '').strip())
    except:
        return None

def detect_strategy(filename, headers):
    """Rileva la strategia dal nome file o dalle colonne"""
    fname = filename.lower()
    if "live" in fname or "o05" in fname or "over05" in fname:
        return "Over 0.5 Live"
    elif "gg" in fname:
        return "GG"
    elif "overino" in fname or "over15" in fname or "1.5" in fname:
        return "Over 1.5"
    elif "over" in fname or "over25" in fname or "2.5" in fname:
        return "Over 2.5"
    # Prova dalle colonne
    headers_str = " ".join(headers).lower()
    if "o05 casa" in headers_str or "o05 trasf" in headers_str:
        return "Over 0.5 Live"
    elif "gg casa" in headers_str or "quota gg" in headers_str:
        return "GG"
    elif "over 1.5" in headers_str or "1.5" in headers_str:
        return "Over 1.5"
    elif "over25" in headers_str or "2.5" in headers_str:
        return "Over 2.5"
    return "Sconosciuta"

def parse_csv(content, filename):
    """Legge il CSV e ritorna lista di partite"""
    partite = []
    try:
        # Rimuovi BOM se presente
        if content.startswith('\ufeff'):
            content = content[1:]

        reader = csv.DictReader(io.StringIO(content))
        headers = reader.fieldnames or []
        strategia = detect_strategy(filename, headers)

        for row in reader:
            try:
                casa = row.get("Squadra Casa", "").strip()
                trasferta = row.get("Squadra Ospite", "").strip()

                if not casa or not trasferta:
                    continue

                match = f"{casa} vs {trasferta}"
                data_ora = row.get("Data/Ora", "").strip()
                campionato = row.get("Campionato", "").strip()

                # Quota e probabilità in base alla strategia
                media_gol = parse_num(row.get("{MEDIA GOL}", "0"))
                media_gol_trasf = parse_num(row.get("{MEDIA GOL TRASF}", "0"))
                elo_gap = parse_num(row.get("{ELO GAP}", "0"))

                if strategia == "Over 0.5 Live":
                    quota = None  # nessuna quota pre-partita
                    o05_casa = parse_num(row.get("{O05 CASA}", "0"))
                    o05_trasf = parse_num(row.get("{O05 TRASF}", "0"))
                    prob = round((o05_casa + o05_trasf) / 2, 1) if o05_casa and o05_trasf else None
                    extra = f"O0.5 Casa: {o05_casa}% | O0.5 Trasf: {o05_trasf}% | Media Gol: {media_gol}"

                elif strategia == "GG":
                    quota = parse_num(row.get("{QUOTA GG}", "0"))
                    gg_casa = parse_num(row.get("{GG CASA}", "0"))
                    gg_trasf = parse_num(row.get("{GG TRASFERTA}", "0"))
                    prob = round((gg_casa + gg_trasf) / 2, 1) if gg_casa and gg_trasf else None
                    extra = f"GG Casa: {gg_casa}% | GG Trasf: {gg_trasf}%"

                elif strategia == "Over 2.5":
                    quota = parse_num(row.get("{QUOTA 02.5}", "0"))
                    o25_casa = parse_num(row.get("{Over25Casa10}", "0"))
                    o25_trasf = parse_num(row.get("{Over25Trasf10}", "0"))
                    prob = round((o25_casa + o25_trasf) / 2, 1) if o25_casa and o25_trasf else None
                    extra = f"O2.5 Casa: {o25_casa}% | O2.5 Trasf: {o25_trasf}%"

                elif strategia == "Over 1.5":
                    quota = parse_num(row.get("{QUOTE}", "0"))
                    o15_casa = parse_num(row.get("{over 1.5 casa}", "0"))
                    o15_trasf = parse_num(row.get("{Over 1.5 Trasfe}", "0"))
                    prob = round((o15_casa + o15_trasf) / 2, 1) if o15_casa and o15_trasf else None
                    extra = f"O1.5 Casa: {o15_casa}% | O1.5 Trasf: {o15_trasf}%"
                else:
                    continue

                if strategia != "Over 0.5 Live" and (not quota or quota <= 1):
                    continue

                partite.append({
                    "match": match,
                    "campionato": campionato,
                    "data_ora": data_ora,
                    "strategia": strategia,
                    "quota": quota,
                    "prob": prob,
                    "media_gol": media_gol,
                    "media_gol_trasf": media_gol_trasf,
                    "elo_gap": elo_gap,
                    "extra": extra
                })

            except Exception as e:
                logger.error(f"Errore riga: {e}")
                continue

    except Exception as e:
        logger.error(f"Errore CSV: {e}")

    return partite, strategia

# --- COMANDI ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    msg = (
        "⚽ *KICKORA BOT v2* — Sistema Doppie\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📥 *AGGIUNGI PARTITE*\n"
        "`/aggiungi Squadra1 vs Squadra2 - Mercato - quota X.XX - prob XX`\n\n"
        "📂 *CARICA CSV DA CGMBET*\n"
        "Invia direttamente il file CSV al bot!\n"
        "Nomina i file: `gg.csv` `over.csv` `overino.csv`\n\n"
        "📋 *VISUALIZZA*\n"
        "`/lista` — Tutte le partite candidate\n\n"
        "🎯 *ANALISI DOPPIE*\n"
        "`/combina` — Tutte le combinazioni con Kelly\n"
        "`/doppia` — Migliore doppia del giorno\n\n"
        "⚡ *LIVE — Over 0.5*\n"
        "`/live Casa vs Trasferta - capitale XX`\n\n"
        "✅ *RISULTATI*\n"
        "`/vinta ID puntata` — Segna come vinta\n"
        "`/persa ID puntata` — Segna come persa\n"
        "`/riepilogo` — Statistiche giornata\n\n"
        "🗑️ *GESTIONE*\n"
        "`/cancella ID` — Rimuovi partita\n"
        "`/reset` — Svuota lista\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🧮 Kelly Calculator: {KELLY_URL}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def handle_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce i file CSV inviati al bot"""
    if not auth(update): return

    doc = update.message.document
    if not doc or not doc.file_name.endswith('.csv'):
        return

    await update.message.reply_text("📂 *CSV ricevuto, elaborazione in corso...*", parse_mode="Markdown")

    try:
        file = await context.bot.get_file(doc.file_id)
        content_bytes = await file.download_as_bytearray()
        content = content_bytes.decode('utf-8-sig')

        partite_parsed, strategia = parse_csv(content, doc.file_name)

        if not partite_parsed:
            await update.message.reply_text(
                "❌ *Nessuna partita trovata nel CSV.*\n"
                "Controlla il formato del file.",
                parse_mode="Markdown"
            )
            return

        aggiunte = []
        for p in partite_parsed:
            # Controlla duplicati
            exists = any(x["match"] == p["match"] and x["strategia"] == p["strategia"] for x in partite_db)
            if not exists:
                partita = {
                    "id": get_next_id(),
                    "match": p["match"],
                    "campionato": p["campionato"],
                    "data_ora": p["data_ora"],
                    "mercato": p["strategia"],
                    "quota": p["quota"],
                    "prob": p["prob"],
                    "media_gol": p.get("media_gol"),
                    "media_gol_trasf": p.get("media_gol_trasf"),
                    "elo_gap": p.get("elo_gap"),
                    "extra": p.get("extra", ""),
                    "esito": None,
                    "puntata": 0,
                    "profitto": 0,
                    "data": datetime.now().strftime("%H:%M")
                }
                partite_db.append(partita)
                aggiunte.append(partita)

        if not aggiunte:
            await update.message.reply_text(
                "⚠️ *Tutte le partite erano già nella lista.*",
                parse_mode="Markdown"
            )
            return

        is_live = strategia == "Over 0.5 Live"
        icon = "⚡" if is_live else "✅"
        msg = f"{icon} *{len(aggiunte)} partite aggiunte — {strategia}*\n"
        msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

        for p in aggiunte:
            prob_text = f" | 📊 {p['prob']}%" if p['prob'] else ""
            if is_live:
                msg += f"⚡ *#{p['id']}* {p['match']}\n"
                msg += f"   📊 O0.5 prob: *{p['prob']}%* | 📈 Media gol: {p['media_gol']}\n"
                msg += f"   📅 {p['data_ora']}\n"
                msg += f"   ➡️ `/live {p['match']}`\n\n"
            else:
                media_text = f"\n   📈 Media gol: {p['media_gol']}" if p.get('media_gol') else ""
                msg += f"*#{p['id']}* {p['match']}\n"
                msg += f"   💰 {p['quota']}{prob_text}"
                msg += f"{media_text}\n"
                msg += f"   📅 {p['data_ora']}\n\n"

        msg += f"━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"📋 Totale candidate: *{len(partite_db)}*\n\n"
        if is_live:
            msg += f"➡️ Usa /live per ogni partita da seguire!"
        else:
            msg += f"➡️ Usa /combina per vedere le combinazioni!"

        await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Errore CSV upload: {e}")
        await update.message.reply_text(
            f"❌ *Errore nell'elaborazione del file.*\n`{str(e)}`",
            parse_mode="Markdown"
        )


async def aggiungi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    try:
        testo = " ".join(context.args)
        parti = [p.strip() for p in testo.split("-")]
        if len(parti) < 3: raise ValueError()

        match = parti[0].strip()
        mercato = parti[1].strip().upper()
        quota = float(parti[2].strip().lower().replace("quota","").strip())
        prob = None
        if len(parti) >= 4:
            prob = float(parti[3].strip().lower().replace("prob","").replace("%","").strip())

        partita = {
            "id": get_next_id(),
            "match": match,
            "campionato": "",
            "data_ora": "",
            "mercato": mercato,
            "quota": quota,
            "prob": prob,
            "esito": None,
            "puntata": 0,
            "profitto": 0,
            "data": datetime.now().strftime("%H:%M")
        }
        partite_db.append(partita)

        prob_text = f"\n📊 Probabilità: *{prob}%*" if prob else ""
        await update.message.reply_text(
            f"✅ *Partita aggiunta #{partita['id']}*\n\n"
            f"⚽ {match}\n"
            f"🎯 {mercato} | 💰 {quota}{prob_text}\n\n"
            f"📋 Candidate oggi: *{len(partite_db)}*",
            parse_mode="Markdown"
        )
    except:
        await update.message.reply_text(
            "❌ Formato:\n`/aggiungi Squadra1 vs Squadra2 - Mercato - quota X.XX - prob XX`",
            parse_mode="Markdown"
        )


async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return

    if not partite_db:
        await update.message.reply_text("📋 *Nessuna partita.* Invia un CSV o usa /aggiungi", parse_mode="Markdown")
        return

    candidate = [p for p in partite_db if p["esito"] is None]
    giocate = [p for p in partite_db if p["esito"] is not None]

    msg = f"📋 *PARTITE CANDIDATE* — {datetime.now().strftime('%d/%m/%Y')}\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    # Raggruppa per strategia
    strategie = {}
    for p in candidate:
        s = p["mercato"]
        if s not in strategie:
            strategie[s] = []
        strategie[s].append(p)

    for strat, ps in strategie.items():
        msg += f"🎯 *{strat}*\n"
        for p in ps:
            prob_text = f" | {p['prob']}%" if p['prob'] else ""
            msg += f"  *#{p['id']}* {p['match']}\n"
            msg += f"  💰 {p['quota']}{prob_text}\n"
        msg += "\n"

    if giocate:
        msg += "━━━━━━━━━━━━━━━━━━━━\n✅ *Giocate:*\n"
        for p in giocate:
            icon = "✅" if p["esito"] == "vinta" else "❌"
            prof = f"+€{p['profitto']}" if p['profitto'] > 0 else f"-€{abs(p['profitto'])}"
            msg += f"  {icon} #{p['id']} {p['match']} → {prof}\n"

    msg += f"\n━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📈 Candidate: *{len(candidate)}* | Giocate: *{len(giocate)}*"

    await update.message.reply_text(msg, parse_mode="Markdown")


async def combina(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return

    candidate = [p for p in partite_db if p["esito"] is None]

    if len(candidate) < 2:
        await update.message.reply_text("❌ Servono almeno *2 partite candidate*.", parse_mode="Markdown")
        return

    combinazioni = []
    for i in range(len(candidate)):
        for j in range(i+1, len(candidate)):
            p1, p2 = candidate[i], candidate[j]
            quota_combo = round(p1["quota"] * p2["quota"], 2)
            prob_combo = None
            edge = None

            if p1["prob"] and p2["prob"]:
                prob_combo = round((p1["prob"]/100) * (p2["prob"]/100) * 100, 1)
                edge = round(prob_combo/100 * quota_combo * 100 - 100, 1)

            combinazioni.append({
                "p1": p1, "p2": p2,
                "quota_combo": quota_combo,
                "prob_combo": prob_combo,
                "edge": edge
            })

    # Ordina per edge poi per quota
    combinazioni.sort(key=lambda x: (x["edge"] or -999, x["quota_combo"]), reverse=True)

    msg = "🎯 *COMBINAZIONI DISPONIBILI*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, c in enumerate(combinazioni[:10], 1):
        icon = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        msg += f"{icon} *#{c['p1']['id']} + #{c['p2']['id']}*\n"
        msg += f"  ⚽ {c['p1']['match']} ({c['p1']['mercato']})\n"
        msg += f"  ⚽ {c['p2']['match']} ({c['p2']['mercato']})\n"
        msg += f"  💰 Quota: *{c['quota_combo']}*"

        if c["prob_combo"]:
            msg += f" | 📊 *{c['prob_combo']}%*"
        if c["edge"] is not None:
            icon_edge = "✅" if c["edge"] > 0 else "❌"
            msg += f"\n  📈 Edge: *{c['edge']}%* {icon_edge}"
        msg += "\n\n"

    msg += f"━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"🧮 {KELLY_URL}"

    await update.message.reply_text(msg, parse_mode="Markdown")


async def doppia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return

    candidate = [p for p in partite_db if p["esito"] is None]

    if len(candidate) < 2:
        await update.message.reply_text("❌ Servono almeno *2 partite candidate*.", parse_mode="Markdown")
        return

    migliore = None
    migliore_score = -999

    for i in range(len(candidate)):
        for j in range(i+1, len(candidate)):
            p1, p2 = candidate[i], candidate[j]
            quota_combo = round(p1["quota"] * p2["quota"], 2)

            if p1["prob"] and p2["prob"]:
                prob_combo = (p1["prob"]/100) * (p2["prob"]/100) * 100
                edge = round(prob_combo/100 * quota_combo * 100 - 100, 1)
                score = edge
            else:
                prob_combo = None
                edge = None
                score = quota_combo

            if score > migliore_score:
                migliore_score = score
                migliore = {
                    "p1": p1, "p2": p2,
                    "quota_combo": quota_combo,
                    "prob_combo": round(prob_combo, 1) if prob_combo else None,
                    "edge": edge
                }

    edge_text = ""
    consiglio = ""
    if migliore["edge"] is not None:
        if migliore["edge"] > 5:
            edge_text = f"\n📈 Edge: *+{migliore['edge']}%* ✅"
            consiglio = "\n\n💡 *Doppia con valore — giocabile!*"
        elif migliore["edge"] > 0:
            edge_text = f"\n📈 Edge: *+{migliore['edge']}%* ⚠️"
            consiglio = "\n\n⚠️ *Edge basso — valuta con attenzione*"
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
        f"{prob_text}{edge_text}{consiglio}\n\n"
        f"🧮 {KELLY_URL}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def vinta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    try:
        id = int(context.args[0])
        puntata = float(context.args[1]) if len(context.args) > 1 else 10.0
        p = next((x for x in partite_db if x["id"] == id), None)
        if not p:
            await update.message.reply_text(f"❌ Partita #{id} non trovata.")
            return
        p["esito"] = "vinta"
        p["puntata"] = puntata
        p["profitto"] = round((p["quota"] - 1) * puntata, 2)
        await update.message.reply_text(
            f"✅ *#{id} VINTA!*\n{p['match']}\n💰 Profitto: *+€{p['profitto']}*",
            parse_mode="Markdown"
        )
    except:
        await update.message.reply_text("Formato: `/vinta ID puntata`", parse_mode="Markdown")


async def persa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    try:
        id = int(context.args[0])
        puntata = float(context.args[1]) if len(context.args) > 1 else 10.0
        p = next((x for x in partite_db if x["id"] == id), None)
        if not p:
            await update.message.reply_text(f"❌ Partita #{id} non trovata.")
            return
        p["esito"] = "persa"
        p["puntata"] = puntata
        p["profitto"] = -round(puntata, 2)
        await update.message.reply_text(
            f"❌ *#{id} persa.*\n{p['match']}\n💰 Perdita: *-€{puntata}*",
            parse_mode="Markdown"
        )
    except:
        await update.message.reply_text("Formato: `/persa ID puntata`", parse_mode="Markdown")


async def riepilogo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    if not partite_db:
        await update.message.reply_text("📊 Nessuna partita oggi.")
        return
    vinte = [p for p in partite_db if p["esito"] == "vinta"]
    perse = [p for p in partite_db if p["esito"] == "persa"]
    attesa = [p for p in partite_db if p["esito"] is None]
    profitto = sum(p["profitto"] for p in partite_db)
    giocate = len(vinte) + len(perse)
    hr = round(len(vinte)/giocate*100) if giocate else 0
    await update.message.reply_text(
        f"📊 *RIEPILOGO*\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 Candidate: *{len(partite_db)}*\n"
        f"⏳ In attesa: *{len(attesa)}*\n"
        f"✅ Vinte: *{len(vinte)}*\n"
        f"❌ Perse: *{len(perse)}*\n"
        f"🎯 Hit rate: *{hr}%*\n"
        f"💰 Profitto: *{'+'if profitto>=0 else ''}€{round(profitto,2)}*",
        parse_mode="Markdown"
    )


async def cancella(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    try:
        id = int(context.args[0])
        p = next((x for x in partite_db if x["id"] == id), None)
        if not p:
            await update.message.reply_text(f"❌ #{id} non trovata.")
            return
        partite_db.remove(p)
        await update.message.reply_text(f"🗑️ *#{id} rimossa*\n{p['match']}", parse_mode="Markdown")
    except:
        await update.message.reply_text("Formato: `/cancella ID`", parse_mode="Markdown")


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    count = len(partite_db)
    partite_db.clear()
    counter["id"] = 0
    await update.message.reply_text(f"🔄 *Lista svuotata!* {count} partite rimosse.", parse_mode="Markdown")


async def live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    try:
        match = " ".join(context.args).strip()
        if not match:
            raise ValueError()

        msg = (
            f"⚡ *LIVE — Over 0.5 Finale*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⚽ *{match}*\n\n"
            f"💰 *Dividi il capitale in 4 parti uguali (25% ciascuna)*\n\n"
            f"1️⃣ *Step 1* — Entra quando quota ≥ 1.70\n"
            f"2️⃣ *Step 2* — Entra quando quota sale ulteriormente\n"
            f"3️⃣ *Step 3* — Entra quando quota sale ancora\n"
            f"4️⃣ *Step 4* — Ultimo ingresso se ancora 0-0\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Quota target entrata: ≥ 1.70*\n\n"
            f"⚠️ *Regole fondamentali:*\n"
            f"🛑 Arriva gol → stop, non entrare agli step successivi\n"
            f"🛑 Espulsione in campo → stop immediato\n"
            f"🛑 Non entrare oltre il 75' — rischio troppo alto"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    except:
        await update.message.reply_text(
            "❌ Formato:\n"
            "`/live Casa vs Trasferta`\n\n"
            "Esempio:\n"
            "`/live Orlando vs Philadelphia`",
            parse_mode="Markdown"
        )


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("aggiungi", aggiungi))
    app.add_handler(CommandHandler("lista", lista))
    app.add_handler(CommandHandler("combina", combina))
    app.add_handler(CommandHandler("doppia", doppia))
    app.add_handler(CommandHandler("live", live))
    app.add_handler(CommandHandler("vinta", vinta))
    app.add_handler(CommandHandler("persa", persa))
    app.add_handler(CommandHandler("riepilogo", riepilogo))
    app.add_handler(CommandHandler("cancella", cancella))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.Document.FileExtension("csv"), handle_csv))
    logger.info("🚀 KICKORA BOT v2 avviato!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
