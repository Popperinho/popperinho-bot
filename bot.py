import logging
import random
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    CallbackQueryHandler, filters, ContextTypes
)

TOKEN = "8345193135:AAGYYoN60Nmri3-SwOlvi_vauYEJHkFK7nw"

OPERATORI = {
    461088008: "Attila",
}

NOME_NEGOZIO = "Popperinho Shop"
DB_PATH = "richieste.db"
PREZZO_UNITARIO = 20  # € per Popperinho

logging.basicConfig(level=logging.INFO)


# ── DATABASE ──────────────────────────────────────────────────────────────────

def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS richieste (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id_cliente INTEGER NOT NULL,
            nome_cliente    TEXT,
            username        TEXT,
            testo           TEXT NOT NULL,
            ricevuta_il     TEXT NOT NULL,
            presa_da        TEXT,
            presa_il        TEXT,
            ordine_completato INTEGER DEFAULT 0,
            completato_il   TEXT,
            completato_da   TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messaggi_operatori (
            richiesta_id  INTEGER NOT NULL,
            op_chat_id    INTEGER NOT NULL,
            msg_id        INTEGER NOT NULL,
            PRIMARY KEY (richiesta_id, op_chat_id),
            FOREIGN KEY (richiesta_id) REFERENCES richieste(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clienti (
            chat_id         INTEGER PRIMARY KEY,
            nome            TEXT,
            username        TEXT,
            primo_contatto  TEXT,
            ultimo_contatto TEXT
        )
    """)
    for col, tipo in [
        ("ordine_completato", "INTEGER DEFAULT 0"),
        ("completato_il", "TEXT"),
        ("completato_da", "TEXT"),
    ]:
        try:
            cur.execute(f"ALTER TABLE richieste ADD COLUMN {col} {tipo}")
        except:
            pass
    con.commit()
    con.close()

def registra_cliente(chat_id, nome, username):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    ora = datetime.now().strftime("%d/%m/%Y %H:%M")
    cur.execute("""
        INSERT INTO clienti (chat_id, nome, username, primo_contatto, ultimo_contatto)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            nome = excluded.nome,
            username = excluded.username,
            ultimo_contatto = excluded.ultimo_contatto
    """, (chat_id, nome, username, ora, ora))
    con.commit()
    con.close()

def salva_richiesta(chat_id_cliente, nome_cliente, username, testo):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO richieste (chat_id_cliente, nome_cliente, username, testo, ricevuta_il)
        VALUES (?, ?, ?, ?, ?)
    """, (chat_id_cliente, nome_cliente, username, testo, datetime.now().strftime("%d/%m/%Y %H:%M")))
    richiesta_id = cur.lastrowid
    con.commit()
    con.close()
    return richiesta_id

def salva_msg_operatore(richiesta_id, op_chat_id, msg_id):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO messaggi_operatori (richiesta_id, op_chat_id, msg_id)
        VALUES (?, ?, ?)
    """, (richiesta_id, op_chat_id, msg_id))
    con.commit()
    con.close()

def prendi_in_carico(richiesta_id, nome_operatore):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT presa_da FROM richieste WHERE id = ?", (richiesta_id,))
    row = cur.fetchone()
    if not row or row[0] is not None:
        con.close()
        return False, row[0] if row else "?"
    cur.execute("""
        UPDATE richieste SET presa_da = ?, presa_il = ? WHERE id = ?
    """, (nome_operatore, datetime.now().strftime("%d/%m/%Y %H:%M"), richiesta_id))
    con.commit()
    con.close()
    return True, nome_operatore

def completa_ordine(richiesta_id, nome_operatore):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT ordine_completato FROM richieste WHERE id = ?", (richiesta_id,))
    row = cur.fetchone()
    if not row or row[0] == 1:
        con.close()
        return False
    cur.execute("""
        UPDATE richieste SET ordine_completato = 1, completato_il = ?, completato_da = ? WHERE id = ?
    """, (datetime.now().strftime("%d/%m/%Y %H:%M"), nome_operatore, richiesta_id))
    con.commit()
    con.close()
    return True

def get_messaggi_operatori(richiesta_id):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT op_chat_id, msg_id FROM messaggi_operatori WHERE richiesta_id = ?", (richiesta_id,))
    rows = cur.fetchall()
    con.close()
    return rows

def get_richiesta(richiesta_id):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT * FROM richieste WHERE id = ?", (richiesta_id,))
    row = cur.fetchone()
    con.close()
    return row

def get_storico(limit=20, solo_aperte=False):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    if solo_aperte:
        cur.execute("""
            SELECT id, nome_cliente, username, testo, ricevuta_il, presa_da, ordine_completato
            FROM richieste WHERE presa_da IS NULL
            ORDER BY id DESC LIMIT ?
        """, (limit,))
    else:
        cur.execute("""
            SELECT id, nome_cliente, username, testo, ricevuta_il, presa_da, ordine_completato
            FROM richieste ORDER BY id DESC LIMIT ?
        """, (limit,))
    rows = cur.fetchall()
    con.close()
    return rows

def get_stats_clienti():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        SELECT c.nome, c.username, c.chat_id, c.primo_contatto, c.ultimo_contatto,
               COUNT(r.id) as tot_richieste,
               SUM(CASE WHEN r.ordine_completato = 1 THEN 1 ELSE 0 END) as tot_ordini
        FROM clienti c
        LEFT JOIN richieste r ON r.chat_id_cliente = c.chat_id
        GROUP BY c.chat_id
        ORDER BY tot_ordini DESC, tot_richieste DESC
    """)
    rows = cur.fetchall()
    con.close()
    return rows

def get_inattivi(giorni=30):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT chat_id, nome, username, ultimo_contatto FROM clienti")
    tutti = cur.fetchall()
    con.close()
    inattivi = []
    ora = datetime.now()
    for chat_id, nome, username, ultimo in tutti:
        try:
            dt = datetime.strptime(ultimo, "%d/%m/%Y %H:%M")
            diff = (ora - dt).days
            if diff >= giorni:
                inattivi.append((chat_id, nome, username, ultimo, diff))
        except:
            pass
    inattivi.sort(key=lambda x: x[4], reverse=True)
    return inattivi

def conta_clienti_totali():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM clienti")
    n = cur.fetchone()[0]
    con.close()
    return n

def conta_ordini_totali():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM richieste WHERE ordine_completato = 1")
    n = cur.fetchone()[0]
    con.close()
    return n


# ── TESTO E TASTIERA RICHIESTA ────────────────────────────────────────────────

def build_testo(req):
    rid, chat_id_cliente, nome_cliente, username, testo, ricevuta_il, presa_da, presa_il, ordine_completato, completato_il, completato_da = req
    if presa_da is None:
        stato = "⏳ *In attesa di essere presa in carico*"
    elif ordine_completato:
        stato = f"✅ Presa da: {presa_da} alle {presa_il}\n📦 *Ordine completato da: {completato_da}* alle {completato_il}"
    else:
        stato = f"✅ Presa da: {presa_da} alle {presa_il}\n🔄 *In lavorazione*"

    return (
        f"📩 *Richiesta #{rid}*\n\n"
        f"👤 {nome_cliente}  |  {username}\n"
        f"🕐 {ricevuta_il}\n\n"
        f"💬 _{testo}_\n\n"
        f"➡️ [Apri chat diretta](tg://user?id={chat_id_cliente})\n\n"
        f"{stato}"
    )

def build_tastiera(req):
    rid, _, _, _, _, _, presa_da, _, ordine_completato, _, _ = req
    tasti = []
    if presa_da is None:
        tasti.append(InlineKeyboardButton("✅ Prendo in carico", callback_data=f"preso:{rid}"))
    if presa_da is not None and not ordine_completato:
        tasti.append(InlineKeyboardButton("📦 Ordine completato", callback_data=f"completato:{rid}"))
    return InlineKeyboardMarkup([tasti]) if tasti else None

def tastiera_quantita():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"1️⃣  →  {PREZZO_UNITARIO}€", callback_data="qty:1"),
            InlineKeyboardButton(f"2️⃣  →  {PREZZO_UNITARIO*2}€", callback_data="qty:2"),
        ],
        [
            InlineKeyboardButton(f"3️⃣  →  {PREZZO_UNITARIO*3}€", callback_data="qty:3"),
            InlineKeyboardButton(f"4️⃣  →  {PREZZO_UNITARIO*4}€", callback_data="qty:4"),
        ],
        [
            InlineKeyboardButton("✏️ Altre quantità o domande", callback_data="qty:altro"),
        ],
    ])


# ── HANDLERS ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome = update.effective_user.first_name or "Cliente"
    await update.message.reply_text(
        f"👋 Ciao {nome}! Benvenuto da {NOME_NEGOZIO}.\n\n"
        f"Scrivi la tua richiesta d'ordine e verrai contattato in privato il prima possibile! 🫵\n\n"
        f"Seleziona la quantità:",
        reply_markup=tastiera_quantita()
    )

async def ricevi_messaggio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in OPERATORI:
        return

    cliente = update.effective_user
    chat_id_cliente = update.effective_chat.id
    testo = update.message.text

    nome_cliente = (cliente.first_name or "") + (" " + cliente.last_name if cliente.last_name else "")
    username = f"@{cliente.username}" if cliente.username else "(senza username)"
    nome_cliente = nome_cliente.strip()

    registra_cliente(chat_id_cliente, nome_cliente, username)
    richiesta_id = salva_richiesta(chat_id_cliente, nome_cliente, username, testo)

    req = get_richiesta(richiesta_id)
    testo_op = build_testo(req)
    tastiera = build_tastiera(req)

    for op_chat_id in OPERATORI:
        try:
            msg = await context.bot.send_message(
                chat_id=op_chat_id,
                text=testo_op,
                parse_mode="Markdown",
                reply_markup=tastiera
            )
            salva_msg_operatore(richiesta_id, op_chat_id, msg.message_id)
        except Exception as e:
            logging.warning(f"Errore invio a operatore {op_chat_id}: {e}")

    await update.message.reply_text(
        "✅ Messaggio ricevuto! Ti risponderemo il prima possibile.\n"
        "⏱️ Siamo di solito disponibili entro poche ore."
    )

async def gestisci_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # ── Selezione quantità dal cliente ──
    if query.data.startswith("qty:"):
        cliente = query.from_user
        chat_id_cliente = query.message.chat_id
        nome_cliente = (cliente.first_name or "") + (" " + cliente.last_name if cliente.last_name else "")
        nome_cliente = nome_cliente.strip()
        username = f"@{cliente.username}" if cliente.username else "(senza username)"
        valore = query.data.split(":")[1]

        if valore == "nuovo":
            await query.edit_message_text(
                "🛒 Seleziona la quantità per il nuovo ordine:",
                reply_markup=tastiera_quantita()
            )
            return

        if valore == "altro":
            await query.edit_message_text(
                "✏️ Scrivi pure la tua richiesta o domanda, ti risponderemo il prima possibile!"
            )
            return

        quantita = int(valore)
        totale = quantita * PREZZO_UNITARIO
        testo_richiesta = f"Ordine: {quantita} Popperinho — Totale: {totale}€"

        registra_cliente(chat_id_cliente, nome_cliente, username)
        richiesta_id = salva_richiesta(chat_id_cliente, nome_cliente, username, testo_richiesta)

        req = get_richiesta(richiesta_id)
        testo_op = build_testo(req)
        tastiera_op = build_tastiera(req)

        for op_chat_id in OPERATORI:
            try:
                msg = await context.bot.send_message(
                    chat_id=op_chat_id,
                    text=testo_op,
                    parse_mode="Markdown",
                    reply_markup=tastiera_op
                )
                salva_msg_operatore(richiesta_id, op_chat_id, msg.message_id)
            except Exception as e:
                logging.warning(f"Errore invio a operatore {op_chat_id}: {e}")

        pulsante_nuovo = InlineKeyboardMarkup([[
            InlineKeyboardButton("🛒 Piazza nuovo ordine", callback_data="qty:nuovo")
        ]])
        await query.edit_message_text(
            f"🎉 Grazie! La tua richiesta è stata presa in carico.\n\n"
            f"🛒 Quantità: *{quantita} Popperinho*\n"
            f"💰 Totale: *{totale}€*\n\n"
            f"Verrai contattato in privato al più presto! 🫵\n\n"
            f"_Il pulsante qui sotto ti servirà la prossima volta che vuoi fare un nuovo ordine — il tuo ordine attuale è già partito! 👆_",
            parse_mode="Markdown",
            reply_markup=pulsante_nuovo
        )
        return

    # ── Pulsanti operatori (prendo in carico / ordine completato) ──
    operatore_id = query.from_user.id
    nome_operatore = OPERATORI.get(operatore_id, query.from_user.first_name)

    if query.data.startswith("preso:"):
        richiesta_id = int(query.data.split(":")[1])
        ok, chi = prendi_in_carico(richiesta_id, nome_operatore)
        if not ok:
            await query.answer(f"⚠️ Già presa in carico da {chi}", show_alert=True)
            return

    elif query.data.startswith("completato:"):
        richiesta_id = int(query.data.split(":")[1])
        ok = completa_ordine(richiesta_id, nome_operatore)
        if not ok:
            await query.answer("⚠️ Ordine già segnato come completato", show_alert=True)
            return

    else:
        return

    req = get_richiesta(richiesta_id)
    if not req:
        return

    testo_aggiornato = build_testo(req)
    tastiera = build_tastiera(req)

    for op_chat_id, msg_id in get_messaggi_operatori(richiesta_id):
        try:
            await context.bot.edit_message_text(
                chat_id=op_chat_id,
                message_id=msg_id,
                text=testo_aggiornato,
                parse_mode="Markdown",
                reply_markup=tastiera
            )
        except Exception as e:
            logging.warning(f"Errore aggiornamento {op_chat_id}: {e}")

async def cmd_storico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OPERATORI:
        return
    args = context.args
    solo_aperte = args and args[0].lower() == "aperte"
    richieste = get_storico(20, solo_aperte)

    if not richieste:
        await update.message.reply_text("Nessuna richiesta trovata.")
        return

    titolo = "📋 *Richieste aperte:*\n\n" if solo_aperte else "📋 *Ultime 20 richieste:*\n\n"
    righe = []
    for r in richieste:
        rid, nome, uname, testo, ricevuta_il, presa_da, ordine_completato = r
        if ordine_completato:
            stato = "📦 Completato"
        elif presa_da:
            stato = f"🔄 {presa_da}"
        else:
            stato = "⏳ In attesa"
        anteprima = testo[:60] + ("…" if len(testo) > 60 else "")
        righe.append(f"*#{rid}* — {nome} ({uname})\n🕐 {ricevuta_il} | {stato}\n💬 _{anteprima}_")

    await update.message.reply_text(titolo + "\n\n".join(righe), parse_mode="Markdown")

async def cmd_clienti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OPERATORI:
        return
    stats = get_stats_clienti()
    tot_clienti = conta_clienti_totali()
    tot_ordini = conta_ordini_totali()

    if not stats:
        await update.message.reply_text("Nessun cliente ancora.")
        return

    righe = []
    for i, (nome, username, chat_id, primo, ultimo, tot_r, tot_o) in enumerate(stats[:15], 1):
        righe.append(
            f"{i}. *{nome}* ({username})\n"
            f"   📩 {tot_r} richieste  |  📦 {tot_o or 0} ordini\n"
            f"   🕐 Ultimo contatto: {ultimo}"
        )

    testo = (
        f"👥 *Clienti totali: {tot_clienti}*\n"
        f"📦 *Ordini completati: {tot_ordini}*\n\n"
        + "\n\n".join(righe)
    )
    await update.message.reply_text(testo, parse_mode="Markdown")

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OPERATORI:
        return
    stats = get_stats_clienti()
    top = [s for s in stats if (s[6] or 0) > 0][:10]

    if not top:
        await update.message.reply_text("Nessun ordine completato ancora.")
        return

    righe = []
    medaglie = ["🥇", "🥈", "🥉"]
    for i, (nome, username, chat_id, primo, ultimo, tot_r, tot_o) in enumerate(top):
        medaglia = medaglie[i] if i < 3 else f"{i+1}."
        righe.append(f"{medaglia} *{nome}* — {tot_o} ordini  |  {tot_r} richieste")

    await update.message.reply_text(
        "🏆 *Top clienti per ordini:*\n\n" + "\n".join(righe),
        parse_mode="Markdown"
    )

async def cmd_inattivi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OPERATORI:
        return
    inattivi = get_inattivi(30)

    if not inattivi:
        await update.message.reply_text("Nessun cliente inattivo da più di 30 giorni. 🎉")
        return

    righe = []
    for chat_id, nome, username, ultimo, giorni in inattivi[:15]:
        righe.append(
            f"👤 *{nome}* ({username})\n"
            f"   Inattivo da *{giorni} giorni* (ultimo: {ultimo})\n"
            f"   ➡️ [Scrivi ora](tg://user?id={chat_id})"
        )

    await update.message.reply_text(
        "😴 *Clienti inattivi da 30+ giorni:*\n\n" + "\n\n".join(righe),
        parse_mode="Markdown"
    )

async def cmd_aiuto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OPERATORI:
        return
    await update.message.reply_text(
        "📖 *Comandi disponibili:*\n\n"
        "/storico — ultime 20 richieste\n"
        "/storico aperte — solo quelle in attesa\n"
        "/clienti — tutti i clienti con richieste e ordini\n"
        "/top — classifica clienti per ordini\n"
        "/inattivi — chi non scrive da 30+ giorni\n"
        "/aiuto — mostra questo messaggio",
        parse_mode="Markdown"
    )

def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("storico", cmd_storico))
    app.add_handler(CommandHandler("clienti", cmd_clienti))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("inattivi", cmd_inattivi))
    app.add_handler(CommandHandler("aiuto", cmd_aiuto))
    app.add_handler(CallbackQueryHandler(gestisci_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ricevi_messaggio))
    # Promemoria automatico ogni 28 giorni alle 21:00
    app.job_queue.run_repeating(
        invia_promemoria_inattivi,
        interval=28 * 24 * 3600,
        first=datetime.strptime("21:00", "%H:%M").time()
    )
    print(f"✅ Bot avviato — {NOME_NEGOZIO}")
    app.run_polling()

if __name__ == "__main__":
    main()

# ── PROMEMORIA AUTOMATICO 30 GIORNI ──────────────────────────────────────────

async def invia_promemoria_inattivi(context: ContextTypes.DEFAULT_TYPE):
    """Ogni giorno controlla chi è inattivo da 30+ giorni e gli manda un messaggio."""
    inattivi = get_inattivi(30)
    inviati = 0
    for chat_id, nome, username, ultimo, giorni in inattivi:
        medie = random.randint(5, 20)
        pulsante = InlineKeyboardMarkup([[
            InlineKeyboardButton("🛒 Ordina ora", callback_data="qty:nuovo")
        ]])
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"👋 Ciao {nome}, dobbiamo parlare.\n\n"
                    f"Ultimamente ci sentiamo poco... forse è arrivato il momento di spopperare "
                    f"e calarsi {medie} medie 🍺"
                ),
                reply_markup=pulsante
            )
            inviati += 1
        except Exception as e:
            logging.warning(f"Impossibile inviare promemoria a {chat_id}: {e}")
    logging.info(f"Promemoria inattivi: inviati {inviati} messaggi.")
