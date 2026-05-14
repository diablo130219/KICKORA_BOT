import os
import io
import csv
import re
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

import base64
import anthropic
import psycopg2
import psycopg2.extras
import json

TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
AUTHORIZED_CHAT_ID = 623848005
KELLY_URL = "https://kelly-calculator-production.up.railway.app"
DATABASE_URL = os.environ.get("DATABASE_URL")

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

def plu(n, sing, plur):
    """Restituisce singolare o plurale in base a n"""
    return sing if n == 1 else plur

def auth(update):
    return update.effective_chat.id == AUTHORIZED_CHAT_ID

def get_next_id():
    counter["id"] += 1
    return counter["id"]

def parse_num(val):
    try:
        return float(str(val).replace(",", ".").replace('"', '').strip())
    except:
        return None

def extract_pct(val):
    if not val: return None
    m = re.search(r'(\d+)%', str(val))
    return int(m.group(1)) if m else None

def extract_stars(val):
    return len([c for c in (val or "") if c == "⭐"])

def is_green_ou(val, threshold=70):
    if not val: return False
    return str(val).strip().startswith("O") and (extract_pct(val) or 0) >= threshold

def is_ai_csv(headers):
    h = [x.strip().lower() for x in headers]
    return "lega" in h and "o/u 0.5" in h and "affidabilità" in h

def detect_strategy(filename, headers):
    fname = filename.lower()
    if "live" in fname or "o05" in fname or "over05" in fname:
        return "Over 0.5 Live"
    elif "gg" in fname:
        return "GG"
    elif "overino" in fname or "over15" in fname or "1.5" in fname:
        return "Over 1.5"
    elif "over" in fname or "over25" in fname or "2.5" in fname:
        return "Over 2.5"
    headers_str = " ".join(headers).lower()
    if "o05 casa" in headers_str or "o05 trasf" in headers_str:
        return "Over 0.5 Live"
    elif "gg casa" in headers_str or "quota gg" in headers_str:
        return "GG"
    elif "over 1.5" in headers_str:
        return "Over 1.5"
    elif "over25" in headers_str or "2.5" in headers_str:
        return "Over 2.5"
    return "Sconosciuta"

# ── PARSER CSV AI ──────────────────────────────────────────

def get_segnali_verdi(row, soglia=70):
    """
    Raccoglie TUTTE le celle verdi della riga (% >= soglia).
    Restituisce lista di stringhe con tutti i segnali verdi trovati.
    """
    segnali = []

    # 1X2 — controlla il segno e la percentuale
    x12 = row.get("1X2", "").strip()
    pct_x12 = extract_pct(x12)
    if pct_x12 and pct_x12 >= soglia:
        # Estrai il segno (1, X, 2)
        segno = x12.split("(")[0].strip()
        segnali.append(f"1X2 {segno}: {x12}")

    # Over (dal più alto al più basso — mostra solo il massimo raggiunto)
    over_max = None
    for campo, label in [
        ("O/U 3.5", "Over 3.5"),
        ("O/U 2.5", "Over 2.5"),
        ("O/U 1.5", "Over 1.5"),
        ("O/U 0.5", "Over 0.5"),
    ]:
        val = row.get(campo, "").strip()
        if val.startswith("O") and (extract_pct(val) or 0) >= soglia:
            over_max = f"{label}: {val}"
            break  # prende il più alto e si ferma

    if over_max:
        segnali.append(over_max)

    # Under (dal più basso al più alto — mostra solo il minimo raggiunto)
    under_min = None
    for campo, label in [
        ("O/U 0.5", "Under 0.5"),
        ("O/U 1.5", "Under 1.5"),
        ("O/U 2.5", "Under 2.5"),
        ("O/U 3.5", "Under 3.5"),
    ]:
        val = row.get(campo, "").strip()
        if val.startswith("U") and (extract_pct(val) or 0) >= soglia:
            under_min = f"{label}: {val}"
            break  # prende il più difficile e si ferma

    if under_min:
        segnali.append(under_min)

    # BTTS
    btts = row.get("BTTS", "").strip()
    if btts.startswith("Y") and (extract_pct(btts) or 0) >= soglia:
        segnali.append(f"BTTS: {btts}")

    return segnali


def parse_ai_csv(content, soglia=70, soglia_stelle=3):
    partite = []
    skipped = []
    if content.startswith('\ufeff'):
        content = content[1:]
    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        casa = row.get("Squadra Casa", "").strip()
        ospite = row.get("Squadra Ospite", "").strip()
        if not casa or not ospite:
            continue

        aff    = row.get("Affidabilità", "").strip()
        lega   = row.get("Lega", "").strip()
        ora    = row.get("Ora", "").strip()
        data   = row.get("Data", "").strip()
        pr     = row.get("Partite", "").strip()
        x12    = row.get("1X2", "").strip()
        stelle = extract_stars(aff)

        segnali = get_segnali_verdi(row, soglia)

        if not segnali or stelle < soglia_stelle:
            skipped.append(f"{casa} vs {ospite}")
            continue

        partite.append({
            "match": f"{casa} vs {ospite}",
            "lega": lega, "ora": ora, "data": data,
            "partite_raw": pr, "1x2": x12,
            "stelle": stelle,
            "segnali": segnali,   # tutti i segnali verdi
        })
    return partite, skipped

# ── PARSER CSV PROSSIMAMENTE ───────────────────────────────

def parse_csv(content, filename):
    partite = []
    try:
        if content.startswith('\ufeff'):
            content = content[1:]
        reader = csv.DictReader(io.StringIO(content))
        headers = reader.fieldnames or []
        strategia = detect_strategy(filename, headers)
        for row in reader:
            try:
                casa = row.get("Squadra Casa", "").strip()
                trasferta = row.get("Squadra Ospite", "").strip()
                if not casa or not trasferta: continue
                match = f"{casa} vs {trasferta}"
                data_ora = row.get("Data/Ora", "").strip()
                campionato = row.get("Campionato", "").strip()
                media_gol = parse_num(row.get("{MEDIA GOL}", "0"))
                elo_gap = parse_num(row.get("{ELO GAP}", "0"))
                if strategia == "Over 0.5 Live":
                    quota = None
                    o05_c = parse_num(row.get("{O05 CASA}", "0"))
                    o05_t = parse_num(row.get("{O05 TRASF}", "0"))
                    prob = round((o05_c + o05_t) / 2, 1) if o05_c and o05_t else None
                    extra = f"O0.5 Casa: {o05_c}% | O0.5 Trasf: {o05_t}%"
                elif strategia == "GG":
                    quota = parse_num(row.get("{QUOTA GG}", "0"))
                    gg_c = parse_num(row.get("{GG CASA}", "0"))
                    gg_t = parse_num(row.get("{GG TRASFERTA}", "0"))
                    prob = round((gg_c + gg_t) / 2, 1) if gg_c and gg_t else None
                    extra = f"GG Casa: {gg_c}% | GG Trasf: {gg_t}%"
                elif strategia == "Over 2.5":
                    quota = parse_num(row.get("{QUOTA 02.5}", "0"))
                    o25_c = parse_num(row.get("{Over25Casa10}", "0"))
                    o25_t = parse_num(row.get("{Over25Trasf10}", "0"))
                    prob = round((o25_c + o25_t) / 2, 1) if o25_c and o25_t else None
                    extra = f"O2.5 Casa: {o25_c}% | O2.5 Trasf: {o25_t}%"
                elif strategia == "Over 1.5":
                    quota = parse_num(row.get("{QUOTE}", "0"))
                    o15_c = parse_num(row.get("{over 1.5 casa}", "0"))
                    o15_t = parse_num(row.get("{Over 1.5 Trasfe}", "0"))
                    prob = round((o15_c + o15_t) / 2, 1) if o15_c and o15_t else None
                    extra = f"O1.5 Casa: {o15_c}% | O1.5 Trasf: {o15_t}%"
                else:
                    continue
                if strategia != "Over 0.5 Live" and (not quota or quota <= 1):
                    continue
                partite.append({
                    "match": match, "campionato": campionato,
                    "data_ora": data_ora, "strategia": strategia,
                    "quota": quota, "prob": prob,
                    "media_gol": media_gol, "elo_gap": elo_gap, "extra": extra
                })
            except Exception as e:
                logger.error(f"Errore riga: {e}")
    except Exception as e:
        logger.error(f"Errore CSV: {e}")
    return partite, strategia

# ── GENERATORE BOLLETTINO ──────────────────────────────────

def genera_bollettino(partite_ai):
    oggi = datetime.now().strftime("%d/%m/%Y")
    msg = f"🤖 *CGMBET AI — Suggerimenti del {oggi}*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    if not partite_ai:
        msg += "⚠️ Nessuna partita supera i filtri oggi.\n"
        return msg
    msg += f"🟢 *{len(partite_ai)} {plu(len(partite_ai), 'PARTITA SELEZIONATA', 'PARTITE SELEZIONATE')}*\n"
    msg += "_Filtro: Over 0.5 ≥70% · ≥3⭐_\n\n"
    leghe = {}
    for p in partite_ai:
        l = p["lega"] or "Altro"
        leghe.setdefault(l, []).append(p)
    for lega, ps in leghe.items():
        msg += f"🏆 *{lega}*\n"
        for p in ps:
            ora_str = f"🕐 {p['ora']} " if p['ora'] else ""
            msg += f"\n{ora_str}*{p['match']}*\n"
            for s in p["segnali"]:
                msg += f"  ✅ {s}\n"
            if p['1x2']:
                msg += f"  📊 1X2: {p['1x2']}\n"
            msg += f"  {'⭐' * p['stelle']} · {p['partite_raw']} partite\n"
        msg += "\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    msg += "⚠️ _Solo analisi statistica. Gioca responsabilmente._"
    return msg

# ── COMANDI ────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    msg = (
        "⚽ *KICKORA BOT v2* — Sistema Doppie\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📂 *CSV DA CGMBET*\n"
        "Invia qualsiasi CSV al bot — lo riconosce automaticamente!\n"
        "• Strategie (GG/Over): nomina `gg.csv` `over.csv` ecc.\n"
        "• Suggerimenti AI: qualsiasi nome (colonna `O/U 0.5`)\n\n"
        "📥 *AGGIUNTA MANUALE*\n"
        "`/aggiungi Sq1 vs Sq2 - Mercato - quota X.XX - prob XX`\n\n"
        "📋 *VISUALIZZA*\n"
        "`/lista` — Partite strategie candidate\n"
        "`/ai` — Partite Suggerimenti AI del giorno\n\n"
        "🎯 *DOPPIE*\n"
        "`/combina` — Tutte le combinazioni\n"
        "`/doppia` — Migliore doppia\n\n"
        "📢 *CANALE*\n"
        "`/bollettino` — Genera messaggio pronto per il canale\n\n"
        "⚡ *LIVE*\n"
        "`/live Casa vs Trasferta`\n\n"
        "✅ *RISULTATI*\n"
        "`/vinta ID puntata` | `/persa ID puntata`\n"
        "`/riepilogo`\n\n"
        "🗑️ *RESET*\n"
        "`/cancella ID` | `/reset` | `/resetai`\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🧮 {KELLY_URL}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def handle_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    doc = update.message.document
    if not doc or not doc.file_name.endswith('.csv'): return
    await update.message.reply_text("📂 *Elaborazione CSV...*", parse_mode="Markdown")
    try:
        file = await context.bot.get_file(doc.file_id)
        content = (await file.download_as_bytearray()).decode('utf-8-sig')
        first_line = content.split('\n')[0]
        headers = [h.strip() for h in first_line.split(',')]
        if is_ai_csv(headers):
            await handle_ai_csv(update, context, content)
        else:
            await handle_strategy_csv(update, context, content, doc.file_name)
    except Exception as e:
        logger.error(f"Errore CSV: {e}")
        await update.message.reply_text(f"❌ Errore: `{e}`", parse_mode="Markdown")


async def handle_ai_csv(update, context, content):
    partite_trovate, skipped = parse_ai_csv(content)
    if not partite_trovate:
        await update.message.reply_text(
            f"⚠️ *Nessuna partita supera i filtri.*\n"
            f"Escluse {len(skipped)} partite (Over 0.5 <70% o <3⭐)",
            parse_mode="Markdown"
        )
        return
    aggiunte = []
    for p in partite_trovate:
        if not any(x["match"] == p["match"] for x in ai_db):
            ai_db.append(p)
            aggiunte.append(p)
    msg = f"✅ *CSV Suggerimenti AI elaborato!*\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"🟢 Selezionate: *{len(aggiunte)}* partite\n"
    msg += f"⛔ Escluse: *{len(skipped)}* partite\n\n"
    for p in aggiunte:
        msg += f"  ✅ {p['ora'] or '--:--'} *{p['match']}*\n"
        for s in p['segnali']:
            msg += f"     {s}\n"
    msg += f"\n━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📢 Usa /bollettino per generare il messaggio canale\n"
    msg += f"📋 Usa /ai per vedere il dettaglio\n➕ Usa /addai per aggiungere manualmente"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def handle_strategy_csv(update, context, content, filename):
    partite_parsed, strategia = parse_csv(content, filename)
    if not partite_parsed:
        await update.message.reply_text("❌ Nessuna partita trovata nel CSV.", parse_mode="Markdown")
        return
    aggiunte = []
    for p in partite_parsed:
        if not db_exists_partita(p["match"], p["strategia"]):
            partita = {
                "id": get_next_id(), "match": p["match"],
                "campionato": p["campionato"], "data_ora": p["data_ora"],
                "mercato": p["strategia"], "quota": p["quota"],
                "prob": p["prob"], "media_gol": p.get("media_gol"),
                "elo_gap": p.get("elo_gap"), "extra": p.get("extra", ""),
                "esito": None, "puntata": 0, "profitto": 0,
                "data": datetime.now().strftime("%H:%M")
            }
            partite_db.append(partita)
            aggiunte.append(partita)
    if not aggiunte:
        await update.message.reply_text("⚠️ Tutte le partite erano già nella lista.", parse_mode="Markdown")
        return
    is_live = strategia == "Over 0.5 Live"
    icon = "⚡" if is_live else "✅"
    msg = f"{icon} *{len(aggiunte)} partite aggiunte — {strategia}*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for p in aggiunte:
        prob_text = f" | 📊 {p['prob']}%" if p['prob'] else ""
        if is_live:
            msg += f"⚡ *#{p['id']}* {p['match']}\n   📊 {p['prob']}% | ➡️ `/live {p['match']}`\n\n"
        else:
            msg += f"*#{p['id']}* {p['match']}\n   💰 {p['quota']}{prob_text}\n   📅 {p['data_ora']}\n\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━\nTotale: *{len(db_get_partite())}* | "
    msg += "➡️ /live" if is_live else "➡️ /combina"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def ai_lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    ai_db = db_get_ai()
    if not ai_db:
        await update.message.reply_text("📋 *Nessuna partita AI.* Invia il CSV Suggerimenti AI.", parse_mode="Markdown")
        return
    oggi = datetime.now().strftime("%d/%m/%Y")
    msg = f"🤖 *SUGGERIMENTI AI — {oggi}*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"🟢 *{len(ai_db)} {plu(len(ai_db), 'partita', 'partite')}* _(Over 0.5 ≥70% · ≥3⭐)_\n\n"
    leghe = {}
    for p in ai_db:
        leghe.setdefault(p["lega"] or "Altro", []).append(p)
    for lega, ps in leghe.items():
        msg += f"🏆 *{lega}*\n"
        for p in ps:
            msg += f"  {'🕐 '+p['ora'] if p['ora'] else ''} *{p['match']}*\n"
            for s in p["segnali"]:
                msg += f"  ✅ {s}\n"
            msg += f"  {'⭐'*p['stelle']} · {p['partite_raw']} partite\n\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n📢 /bollettino per il messaggio canale"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def bollettino(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    ai_db = db_get_ai()
    if not ai_db:
        await update.message.reply_text("📋 *Nessuna partita AI.* Invia prima il CSV.", parse_mode="Markdown")
        return
    msg = genera_bollettino(ai_db)
    await update.message.reply_text(msg, parse_mode="Markdown")


async def aggiungi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    try:
        testo = " ".join(context.args)
        parti = [p.strip() for p in testo.split("-")]
        if len(parti) < 3: raise ValueError()
        match = parti[0].strip()
        mercato = parti[1].strip().upper()
        quota = float(parti[2].strip().lower().replace("quota","").strip())
        prob = float(parti[3].strip().lower().replace("prob","").replace("%","").strip()) if len(parti) >= 4 else None
        partita = {
            "id": get_next_id(), "match": match, "campionato": "",
            "data_ora": "", "mercato": mercato, "quota": quota, "prob": prob,
            "esito": None, "puntata": 0, "profitto": 0,
            "data": datetime.now().strftime("%H:%M")
        }
        new_id = db_add_partita(partita)
        partita["id"] = new_id
        prob_text = f"\n📊 Probabilità: *{prob}%*" if prob else ""
        tutte = db_get_partite()
        await update.message.reply_text(
            f"✅ *Aggiunta #{new_id}*\n⚽ {match}\n🎯 {mercato} | 💰 {quota}{prob_text}\n📋 Candidate: *{len(tutte)}*",
            parse_mode="Markdown"
        )
    except:
        await update.message.reply_text("❌ Formato:\n`/aggiungi Sq1 vs Sq2 - Mercato - quota X.XX - prob XX`", parse_mode="Markdown")


async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    partite_db = db_get_partite()
    if not partite_db:
        await update.message.reply_text("📋 *Nessuna partita.* Invia un CSV o usa /aggiungi", parse_mode="Markdown")
        return
    candidate = [p for p in partite_db if p["esito"] is None]
    giocate = [p for p in partite_db if p["esito"] is not None]
    msg = f"📋 *PARTITE CANDIDATE* — {datetime.now().strftime('%d/%m/%Y')}\n━━━━━━━━━━━━━━━━━━━━\n\n"
    strategie = {}
    for p in candidate:
        strategie.setdefault(p["mercato"], []).append(p)
    for strat, ps in strategie.items():
        msg += f"🎯 *{strat}*\n"
        for p in ps:
            prob_text = f" | {p['prob']}%" if p['prob'] else ""
            msg += f"  *#{p['id']}* {p['match']}\n  💰 {p['quota']}{prob_text}\n"
        msg += "\n"
    if giocate:
        msg += "━━━━━━━━━━━━━━━━━━━━\n✅ *Giocate:*\n"
        for p in giocate:
            icon = "✅" if p["esito"] == "vinta" else "❌"
            prof = f"+€{p['profitto']}" if p['profitto'] > 0 else f"-€{abs(p['profitto'])}"
            msg += f"  {icon} #{p['id']} {p['match']} → {prof}\n"
    msg += f"\n━━━━━━━━━━━━━━━━━━━━\nCandidate: *{len(candidate)}* | Giocate: *{len(giocate)}*"
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
            prob_combo = edge = None
            if p1["prob"] and p2["prob"]:
                prob_combo = round((p1["prob"]/100) * (p2["prob"]/100) * 100, 1)
                edge = round(prob_combo/100 * quota_combo * 100 - 100, 1)
            combinazioni.append({"p1":p1,"p2":p2,"quota_combo":quota_combo,"prob_combo":prob_combo,"edge":edge})
    combinazioni.sort(key=lambda x: (x["edge"] or -999, x["quota_combo"]), reverse=True)
    msg = "🎯 *COMBINAZIONI*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, c in enumerate(combinazioni[:10], 1):
        icon = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i}."
        msg += f"{icon} *#{c['p1']['id']} + #{c['p2']['id']}*\n"
        msg += f"  ⚽ {c['p1']['match']} ({c['p1']['mercato']})\n"
        msg += f"  ⚽ {c['p2']['match']} ({c['p2']['mercato']})\n"
        msg += f"  💰 *{c['quota_combo']}*"
        if c["prob_combo"]: msg += f" | 📊 *{c['prob_combo']}%*"
        if c["edge"] is not None:
            msg += f"\n  📈 Edge: *{c['edge']}%* {'✅' if c['edge']>0 else '❌'}"
        msg += "\n\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━\n🧮 {KELLY_URL}"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def doppia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    partite_db = db_get_partite()
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
                prob_combo = edge = None
                score = quota_combo
            if score > migliore_score:
                migliore_score = score
                migliore = {"p1":p1,"p2":p2,"quota_combo":quota_combo,
                            "prob_combo":round(prob_combo,1) if prob_combo else None,"edge":edge}
    edge_text = consiglio = ""
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
        f"🎯 *MIGLIORE DOPPIA*\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"1️⃣ *{migliore['p1']['match']}*\n"
        f"   🎯 {migliore['p1']['mercato']} | 💰 {migliore['p1']['quota']}"
        f"{' | 📊 '+str(migliore['p1']['prob'])+'%' if migliore['p1']['prob'] else ''}\n\n"
        f"2️⃣ *{migliore['p2']['match']}*\n"
        f"   🎯 {migliore['p2']['mercato']} | 💰 {migliore['p2']['quota']}"
        f"{' | 📊 '+str(migliore['p2']['prob'])+'%' if migliore['p2']['prob'] else ''}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Quota combo: *{migliore['quota_combo']}*{prob_text}{edge_text}{consiglio}\n\n"
        f"🧮 {KELLY_URL}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def vinta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    try:
        id = int(context.args[0])
        puntata = float(context.args[1]) if len(context.args) > 1 else 10.0
        partite_db = db_get_partite()
        p = next((x for x in partite_db if x["id"] == id), None)
        if not p: await update.message.reply_text(f"❌ #{id} non trovata."); return
        profitto = round((p["quota"] - 1) * puntata, 2)
        db_update_esito(id, "vinta", puntata, profitto)
        await update.message.reply_text(f"✅ *#{id} VINTA!*\n{p['match']}\n💰 *+€{profitto}*", parse_mode="Markdown")
    except:
        await update.message.reply_text("Formato: `/vinta ID puntata`", parse_mode="Markdown")


async def persa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    try:
        id = int(context.args[0])
        puntata = float(context.args[1]) if len(context.args) > 1 else 10.0
        partite_db = db_get_partite()
        p = next((x for x in partite_db if x["id"] == id), None)
        if not p: await update.message.reply_text(f"❌ #{id} non trovata."); return
        db_update_esito(id, "persa", puntata, -round(puntata, 2))
        await update.message.reply_text(f"❌ *#{id} persa.*\n{p['match']}\n💰 *-€{puntata}*", parse_mode="Markdown")
    except:
        await update.message.reply_text("Formato: `/persa ID puntata`", parse_mode="Markdown")


async def riepilogo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    partite_db = db_get_partite()
    if not partite_db:
        await update.message.reply_text("📊 Nessuna partita oggi."); return
    vinte = [p for p in partite_db if p["esito"] == "vinta"]
    perse = [p for p in partite_db if p["esito"] == "persa"]
    attesa = [p for p in partite_db if p["esito"] is None]
    profitto = sum(p["profitto"] for p in partite_db)
    giocate = len(vinte) + len(perse)
    hr = round(len(vinte)/giocate*100) if giocate else 0
    await update.message.reply_text(
        f"📊 *RIEPILOGO*\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 Candidate: *{len(partite_db)}*\n⏳ In attesa: *{len(attesa)}*\n"
        f"✅ Vinte: *{len(vinte)}*\n❌ Perse: *{len(perse)}*\n"
        f"🎯 Hit rate: *{hr}%*\n💰 Profitto: *{'+'if profitto>=0 else ''}€{round(profitto,2)}*",
        parse_mode="Markdown"
    )


async def cancella(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    try:
        id = int(context.args[0])
        p = next((x for x in partite_db if x["id"] == id), None)
        if not p: await update.message.reply_text(f"❌ #{id} non trovata."); return
        partite_db.remove(p)
        await update.message.reply_text(f"🗑️ *#{id} rimossa*\n{p['match']}", parse_mode="Markdown")
    except:
        await update.message.reply_text("Formato: `/cancella ID`", parse_mode="Markdown")


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    count = len(db_get_partite()); db_reset_partite()
    await update.message.reply_text(f"🔄 *Lista svuotata!* {count} {plu(count, 'partita rimossa', 'partite rimosse')}.", parse_mode="Markdown")


async def reset_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    count = len(db_get_ai()); db_reset_ai()
    await update.message.reply_text(f"🔄 *Lista AI svuotata!* {count} {plu(count, 'partita rimossa', 'partite rimosse')}.", parse_mode="Markdown")


async def live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update): return
    try:
        match = " ".join(context.args).strip()
        if not match: raise ValueError()
        msg = (
            f"⚡ *LIVE — Over 0.5 Finale*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⚽ *{match}*\n\n"
            f"💰 *Dividi il capitale in 4 parti (25% ciascuna)*\n\n"
            f"1️⃣ Entra quota ≥ 1.70\n2️⃣ Entra quota sale\n"
            f"3️⃣ Entra quota sale ancora\n4️⃣ Ultimo ingresso se ancora 0-0\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n🎯 *Target entrata: ≥ 1.70*\n\n"
            f"⚠️ *Regole:*\n🛑 Gol → stop\n🛑 Espulsione → stop\n🛑 Non oltre il 75'"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Formato: `/live Casa vs Trasferta`", parse_mode="Markdown")


# ── VISION AI — ANALISI SCREENSHOT ───────────────────────

PROMPT_VISION = """
Sei un assistente che analizza screenshot della sezione "Suggerimento Partite" di CGMBet.

Analizza la tabella e per ogni partita dimmi:
- Casa vs Trasferta
- Lega
- Ora (se presente)
- Affidabilità (numero di stelle ⭐)
- Tutte le celle VERDI (verde scuro) con il loro valore
- Tutte le celle GIALLE con il loro valore

Le colonne sono: 1X2, O/U 0.5, O/U 1.5, O/U 2.5, O/U 3.5, O/U 4.5, BTTS

Rispondi SOLO in formato JSON come questo esempio:
{
  "partite": [
    {
      "match": "First Vienna vs Bregenz",
      "lega": "Erste Liga",
      "ora": "17:00",
      "stelle": 4,
      "verdi": ["O/U 2.5: O (70%)", "BTTS: Yes (73%)"],
      "gialli": []
    },
    {
      "match": "Cincinnati vs Inter Miami",
      "lega": "MLS",
      "ora": "01:30",
      "stelle": 3,
      "verdi": [],
      "gialli": ["1X2 X: X (55%)", "O/U 3.5: U (60%)"]
    }
  ]
}

Se una cella non è colorata (bianca/grigia) NON includerla.
Rispondi SOLO con il JSON, niente altro.
"""

async def analizza_screenshot(image_bytes: bytes) -> dict:
    """Invia lo screenshot a Claude Vision e ottiene i segnali colorati"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": PROMPT_VISION
                    }
                ],
            }
        ],
    )
    
    import json
    testo = response.content[0].text.strip()
    # Rimuovi eventuali backtick markdown
    testo = testo.replace("```json", "").replace("```", "").strip()
    return json.loads(testo)


def genera_bollettino_vision(dati: dict) -> str:
    """Genera il messaggio Telegram dai dati estratti via Vision"""
    from datetime import datetime
    oggi = datetime.now().strftime("%d/%m/%Y")
    
    partite = dati.get("partite", [])
    
    # Filtra: almeno 1 segnale verde o giallo
    con_segnali = [p for p in partite if p.get("verdi") or p.get("gialli")]
    
    msg = f"🤖 *CGMBET AI — Suggerimenti del {oggi}*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    if not con_segnali:
        msg += "⚠️ Nessun segnale colorato trovato nell'immagine."
        return msg
    
    # Sezione VERDI
    verdi = [p for p in con_segnali if p.get("verdi")]
    if verdi:
        msg += f"🟢 *SEGNALI VERDI — {len(verdi)} {plu(len(verdi), 'partita', 'partite')}*\n\n"
        for p in verdi:
            stelle = "⭐" * p.get("stelle", 0)
            ora = f"🕐 {p['ora']} " if p.get("ora") else ""
            msg += f"{ora}*{p['match']}*\n"
            msg += f"🏆 {p.get('lega', '')} · {stelle}\n"
            for s in p["verdi"]:
                msg += f"  ✅ {s}\n"
            if p.get("gialli"):
                for s in p["gialli"]:
                    msg += f"  🟡 {s}\n"
            msg += "\n"
    
    # Sezione GIALLI (senza verdi)
    solo_gialli = [p for p in con_segnali if not p.get("verdi") and p.get("gialli")]
    if solo_gialli:
        msg += f"🟡 *SEGNALI GIALLI — {len(solo_gialli)} {plu(len(solo_gialli), 'partita', 'partite')}*\n\n"
        for p in solo_gialli:
            stelle = "⭐" * p.get("stelle", 0)
            ora = f"🕐 {p['ora']} " if p.get("ora") else ""
            msg += f"{ora}*{p['match']}*\n"
            msg += f"🏆 {p.get('lega', '')} · {stelle}\n"
            for s in p["gialli"]:
                msg += f"  🟡 {s}\n"
            msg += "\n"
    
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    msg += "⚠️ _Solo analisi statistica. Gioca responsabilmente._"
    return msg


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce le foto inviate al bot — analizza screenshot CGMBet"""
    if not auth(update): return
    
    if not ANTHROPIC_API_KEY:
        await update.message.reply_text(
            "❌ *ANTHROPIC_API_KEY non configurata.*\n"
            "Aggiungila come variabile d'ambiente su Railway.",
            parse_mode="Markdown"
        )
        return
    
    await update.message.reply_text(
        "📸 *Screenshot ricevuto!*\nAnalisi in corso con Claude Vision...",
        parse_mode="Markdown"
    )
    
    try:
        # Scarica la foto (qualità migliore)
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        
        # Analizza con Claude Vision
        dati = await analizza_screenshot(bytes(image_bytes))
        partite = dati.get("partite", [])
        
        if not partite:
            await update.message.reply_text(
                "⚠️ *Nessuna partita trovata nell'immagine.*\n"
                "Assicurati che lo screenshot mostri la tabella Suggerimento Partite.",
                parse_mode="Markdown"
            )
            return
        
        # Salva in ai_db
        aggiunte = 0
        for p in partite:
            if not p.get("verdi") and not p.get("gialli"):
                continue
            if not db_exists_ai(p["match"]):
                db_add_ai({
                    "match": p["match"],
                    "lega": p.get("lega", ""),
                    "ora": p.get("ora", ""),
                    "data": "",
                    "partite_raw": "",
                    "1x2": "",
                    "stelle": p.get("stelle", 0),
                    "segnali": p.get("verdi", []) + [f"🟡{s}" for s in p.get("gialli", [])],
                })
                aggiunte += 1
        
        # Genera bollettino
        bollettino_msg = genera_bollettino_vision(dati)
        
        # Messaggio di conferma
        verdi_count = sum(1 for p in partite if p.get("verdi"))
        gialli_count = sum(1 for p in partite if p.get("gialli") and not p.get("verdi"))
        
        conferma = (
            f"✅ *Analisi completata!*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 Segnali verdi: *{verdi_count}* partite\n"
            f"🟡 Solo gialli: *{gialli_count}* partite\n"
            f"💾 Salvate in lista AI: *{aggiunte}*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📢 Ecco il messaggio per il canale:"
        )
        await update.message.reply_text(conferma, parse_mode="Markdown")
        
        # Invia direttamente il bollettino pronto
        await update.message.reply_text(bollettino_msg, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Errore Vision: {e}")
        await update.message.reply_text(
            f"❌ *Errore nell'analisi.*\n`{str(e)}`",
            parse_mode="Markdown"
        )



async def addai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Formato:
    /addai Real Madrid vs Oviedo - Primera Division - 21:30 - 1X2 1 (94%), Over 1.5 O (88%) - 4
    """
    if not auth(update): return
    try:
        testo = " ".join(context.args).strip()
        parti = [p.strip() for p in testo.split("-")]

        if len(parti) < 4:
            raise ValueError("Formato non valido")

        match        = parti[0].strip()
        lega         = parti[1].strip()
        ora          = parti[2].strip()
        segnali_raw  = parti[3].strip()
        stelle       = int(parti[4].strip()) if len(parti) >= 5 else 3

        # Parsing segnali separati da virgola
        segnali = [s.strip() for s in segnali_raw.split(",") if s.strip()]

        # Controlla duplicati
        if db_exists_ai(match):
            await update.message.reply_text(
                f"⚠️ *{match}* è già nella lista AI.",
                parse_mode="Markdown"
            )
            return

        db_add_ai({
            "match": match,
            "lega": lega,
            "ora": ora,
            "data": "",
            "partite_raw": "",
            "stelle": stelle,
            "segnali": segnali,
        })

        stelle_str = "⭐" * stelle
        msg = f"✅ *Aggiunta alla lista AI!*\n"
        msg += f"━━━━━━━━━━━━━━━━━━━━\n\n"
        msg += f"🕐 {ora} *{match}*\n"
        msg += f"🏆 {lega} · {stelle_str}\n\n"
        for s in segnali:
            msg += f"  ✅ {s}\n"
        msg += f"\n━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"📋 Totale AI: *{len(db_get_ai())}* {plu(len(db_get_ai()), 'partita', 'partite')}\n"
        msg += f"📢 Usa /bollettino per generare il messaggio canale"

        await update.message.reply_text(msg, parse_mode="Markdown")

    except ValueError:
        await update.message.reply_text(
            "❌ *Formato errato!*\n\n"
            "Usa:\n"
            "`/addai Casa vs Trasferta - Lega - Ora - Segnale1, Segnale2 - Stelle`\n\n"
            "Esempio:\n"
            "`/addai Real Madrid vs Oviedo - Primera Division - 21:30 - 1X2 1 (94%), Over 1.5 O (88%) - 4`",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Errore addai: {e}")
        await update.message.reply_text(f"❌ Errore: `{e}`", parse_mode="Markdown")


async def giornata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/giornata — mostra tutte le partite del giorno in un colpo solo"""
    if not auth(update): return

    from datetime import datetime
    oggi = datetime.now().strftime("%d/%m/%Y")
    msg = f"📋 *PARTITE DEL GIORNO — {oggi}*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n"

    # ── STRATEGIE ──────────────────────────
    candidate = [p for p in partite_db if p["esito"] is None]
    if candidate:
        strategie = {}
        for p in candidate:
            strategie.setdefault(p["mercato"], []).append(p)
        msg += f"\n🎯 *STRATEGIE*\n"
        for strat, ps in strategie.items():
            msg += f"_({strat})_\n"
            for p in ps:
                ora = f"🕐 {p['data_ora'].split()[-1]} " if p.get('data_ora') else ""
                prob_text = f" · {p['prob']}%" if p.get('prob') else ""
                quota_text = f" · 💰 {p['quota']}" if p.get('quota') else ""
                msg += f"  *#{p['id']}* {ora}{p['match']}{quota_text}{prob_text}\n"
    else:
        msg += f"\n🎯 *STRATEGIE*\n  _Nessuna partita — invia un CSV_\n"

    # ── AI ─────────────────────────────────
    msg += f"\n━━━━━━━━━━━━━━━━━━━━\n"
    if ai_db:
        msg += f"\n🤖 *SUGGERIMENTI AI* — {len(ai_db)} {plu(len(ai_db), 'partita', 'partite')}\n"
        leghe = {}
        for p in ai_db:
            leghe.setdefault(p["lega"] or "Altro", []).append(p)
        for lega, ps in leghe.items():
            msg += f"\n🏆 {lega}\n"
            for p in ps:
                ora = f"🕐 {p['ora']} " if p.get('ora') else ""
                msg += f"  {ora}*{p['match']}*\n"
                for s in p.get('segnali', []):
                    # distingui verdi da gialli
                    if str(s).startswith('🟡'):
                        msg += f"    🟡 {s[1:]}\n"
                    else:
                        msg += f"    ✅ {s}\n"
    else:
        msg += f"\n🤖 *SUGGERIMENTI AI*\n  _Nessuna partita — usa /addai o invia CSV_\n"

    # ── LIVE ───────────────────────────────
    live_db = [p for p in partite_db if p["mercato"] == "Over 0.5 Live" and p["esito"] is None]
    msg += f"\n━━━━━━━━━━━━━━━━━━━━\n"
    if live_db:
        msg += f"\n⚡ *LIVE Over 0.5* — {len(live_db)} {plu(len(live_db), 'partita', 'partite')}\n"
        for p in live_db:
            ora = f"🕐 {p['data_ora'].split()[-1]} " if p.get('data_ora') else ""
            prob_text = f" · 📊 {p['prob']}%" if p.get('prob') else ""
            msg += f"  {ora}*{p['match']}*{prob_text}\n"
            msg += f"  ➡️ `/live {p['match']}`\n"
    else:
        msg += f"\n⚡ *LIVE Over 0.5*\n  _Nessuna partita — invia CSV live_\n"

    # ── FOOTER ─────────────────────────────
    msg += f"\n━━━━━━━━━━━━━━━━━━━━\n"
    tot = len(candidate) + len(ai_db) + len(live_db)
    msg += f"📊 Totale: *{tot}* {plu(tot, 'partita', 'partite')} oggi"

    await update.message.reply_text(msg, parse_mode="Markdown")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("aggiungi", aggiungi))
    app.add_handler(CommandHandler("lista", lista))
    app.add_handler(CommandHandler("ai", ai_lista))
    app.add_handler(CommandHandler("bollettino", bollettino))
    app.add_handler(CommandHandler("combina", combina))
    app.add_handler(CommandHandler("doppia", doppia))
    app.add_handler(CommandHandler("live", live))
    app.add_handler(CommandHandler("vinta", vinta))
    app.add_handler(CommandHandler("persa", persa))
    app.add_handler(CommandHandler("riepilogo", riepilogo))
    app.add_handler(CommandHandler("cancella", cancella))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("resetai", reset_ai))
    app.add_handler(MessageHandler(filters.Document.FileExtension("csv"), handle_csv))
    app.add_handler(CommandHandler("addai", addai))
    app.add_handler(CommandHandler("giornata", giornata))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    init_db()
    logger.info("🚀 KICKORA BOT v2 avviato!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
