import logging
import sqlite3
import random
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
PREZZO_UNITARIO = 20

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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS impostazioni (
            chiave TEXT PRIMARY KEY,
            valore TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS blacklist (
            chat_id INTEGER PRIMARY KEY,
            nome    TEXT,
            aggiunto_il TEXT
        )
    """)
    for col, tipo in [
        ("ordine_completato", "INTEGER DEFAULT 0"),
        ("completato_il", "TEXT"),
        ("completato_da", "TEXT"),
    ]:
        try:
            cur.execute("ALTER TABLE richieste ADD COLUMN " + col + " " + tipo)
        except:
            pass
    con.commit()
    con.close()

def get_impostazione(chiave):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT valore FROM impostazioni WHERE chiave = ?", (chiave,))
    row = cur.fetchone()
    con.close()
    return row[0] if row else None

def set_impostazione(chiave, valore):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO impostazioni (chiave, valore) VALUES (?, ?)", (chiave, valore))
    con.commit()
    con.close()

def is_blacklisted(chat_id):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT 1 FROM blacklist WHERE chat_id = ?", (chat_id,))
    row = cur.fetchone()
    con.close()
    return row is not None

def aggiungi_blacklist(chat_id, nome):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO blacklist (chat_id, nome, aggiunto_il) VALUES (?, ?, ?)",
                (chat_id, nome, datetime.now().strftime("%d/%m/%Y %H:%M")))
    con.commit()
    con.close()

def rimuovi_blacklist(chat_id):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("DELETE FROM blacklist WHERE chat_id = ?", (chat_id,))
    con.commit()
    con.close()

def get_blacklist():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT chat_id, nome, aggiunto_il FROM blacklist")
    rows = cur.fetchall()
    con.close()
    return rows

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

def get_inattivi(giorni=28):
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


# ── TASTIERE ──────────────────────────────────────────────────────────────────

def build_testo(req):
    rid, chat_id_cliente, nome_cliente, username, testo, ricevuta_il, presa_da, presa_il, ordine_completato, completato_il, completato_da = req
    if presa_da is None:
        stato = "Stato: In attesa"
    elif ordine_completato:
        stato = "Presa da: " + presa_da + " alle " + presa_il + "\nOrdine completato da: " + completato_da + " alle " + completato_il
    else:
        stato = "Presa da: " + presa_da + " alle " + presa_il + "\nIn lavorazione"
    return (
        "Richiesta #" + str(rid) + "\n\n"
        + "Cliente: " + nome_cliente + "  |  " + username + "\n"
        + "Ora: " + ricevuta_il + "\n\n"
        + "Messaggio: " + testo + "\n\n"
        + "Apri chat: tg://user?id=" + str(chat_id_cliente) + "\n\n"
        + stato
    )

def build_tastiera(req):
    rid, _, _, _, _, _, presa_da, _, ordine_completato, _, _ = req
    tasti = []
    if presa_da is None:
        tasti.append(InlineKeyboardButton("Prendo in carico", callback_data="preso:" + str(rid)))
    if presa_da is not None and not ordine_completato:
        tasti.append(InlineKeyboardButton("Ordine completato", callback_data="completato:" + str(rid)))
    return InlineKeyboardMarkup([tasti]) if tasti else None

def tastiera_quantita():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1  ->  " + str(PREZZO_UNITARIO) + "euro", callback_data="qty:1"),
            InlineKeyboardButton("2  ->  " + str(PREZZO_UNITARIO*2) + "euro", callback_data="qty:2"),
        ],
        [
            InlineKeyboardButton("3  ->  " + str(PREZZO_UNITARIO*3) + "euro", callback_data="qty:3"),
            InlineKeyboardButton("4  ->  " + str(PREZZO_UNITARIO*4) + "euro", callback_data="qty:4"),
        ],
        [
            InlineKeyboardButton("Altre quantita o domande", callback_data="qty:altro"),
        ],
    ])


# ── PROMEMORIA 28 GIORNI ──────────────────────────────────────────────────────

async def invia_promemoria_inattivi(context: ContextTypes.DEFAULT_TYPE):
    inattivi = get_inattivi(28)
    inviati = 0
    for chat_id, nome, username, ultimo, giorni in inattivi:
        medie = random.randint(5, 20)
        pulsante = InlineKeyboardMarkup([[
            InlineKeyboardButton("Ordina ora", callback_data="qty:nuovo")
        ]])
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Ciao " + nome + ", dobbiamo parlare.\n\nUltimamente ci sentiamo poco... forse e arrivato il momento di spopperare e calarsi " + str(medie) + " medie",
                reply_markup=pulsante
            )
            inviati += 1
        except Exception as e:
            logging.warning("Impossibile inviare promemoria a " + str(chat_id) + ": " + str(e))
    logging.info("Promemoria inattivi: inviati " + str(inviati) + " messaggi.")


# ── HANDLERS ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome = update.effective_user.first_name or "Cliente"
    video_id = get_impostazione("video_benvenuto")
    if video_id:
        try:
            await update.message.reply_video(video=video_id)
        except Exception as e:
            logging.warning("Errore invio video benvenuto: " + str(e))
    await update.message.reply_text(
        "Ciao " + nome + "! Benvenuto dal King del Popper\n\nScrivi la tua richiesta d'ordine e verrai contattato in privato il prima possibile!\n\nSeleziona la quantita:",
        reply_markup=tastiera_quantita()
    )

async def cmd_setvideo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OPERATORI:
        return
    video = update.message.video or update.message.document
    if not video:
        await update.message.reply_text("Manda il video e scrivi /setvideo nella didascalia per impostarlo come video di benvenuto.")
        return
    set_impostazione("video_benvenuto", video.file_id)
    await update.message.reply_text("Video di benvenuto impostato! Ogni nuovo cliente lo ricevera all'avvio.")

async def ricevi_messaggio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in OPERATORI:
        return
    if is_blacklisted(update.effective_user.id):
        return

    cliente = update.effective_user
    chat_id_cliente = update.effective_chat.id
    testo = update.message.text

    nome_cliente = (cliente.first_name or "") + (" " + cliente.last_name if cliente.last_name else "")
    username = "@" + cliente.username if cliente.username else "(senza username)"
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
                reply_markup=tastiera
            )
            salva_msg_operatore(richiesta_id, op_chat_id, msg.message_id)
        except Exception as e:
            logging.warning("Errore invio a operatore " + str(op_chat_id) + ": " + str(e))

    await update.message.reply_text("Messaggio ricevuto! Ti risponderemo il prima possibile.")

async def gestisci_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("qty:"):
        if is_blacklisted(query.from_user.id):
            return
        cliente = query.from_user
        chat_id_cliente = query.message.chat_id
        nome_cliente = (cliente.first_name or "") + (" " + cliente.last_name if cliente.last_name else "")
        nome_cliente = nome_cliente.strip()
        username = "@" + cliente.username if cliente.username else "(senza username)"
        valore = query.data.split(":")[1]

        if valore == "nuovo":
            await query.edit_message_text("Seleziona la quantita per il nuovo ordine:", reply_markup=tastiera_quantita())
            return

        if valore == "altro":
            await query.edit_message_text("Scrivi pure la tua richiesta o domanda, ti risponderemo il prima possibile!")
            return

        quantita = int(valore)
        totale = quantita * PREZZO_UNITARIO
        testo_richiesta = "Ordine: " + str(quantita) + " Popperinho - Totale: " + str(totale) + " euro"

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
                    reply_markup=tastiera_op
                )
                salva_msg_operatore(richiesta_id, op_chat_id, msg.message_id)
            except Exception as e:
                logging.warning("Errore invio a operatore " + str(op_chat_id) + ": " + str(e))

        pulsante_nuovo = InlineKeyboardMarkup([[
            InlineKeyboardButton("Piazza nuovo ordine", callback_data="qty:nuovo")
        ]])
        await query.edit_message_text(
            "Grazie! La tua richiesta e stata presa in carico.\n\n"
            "Quantita: " + str(quantita) + " Popperinho\n"
            "Totale: " + str(totale) + " euro\n\n"
            "Verrai contattato in privato al piu presto!\n\n"
            "Il pulsante qui sotto ti servira la prossima volta che vuoi fare un nuovo ordine - il tuo ordine attuale e gia partito!",
            reply_markup=pulsante_nuovo
        )
        return

    operatore_id = query.from_user.id
    nome_operatore = OPERATORI.get(operatore_id, query.from_user.first_name)

    if query.data.startswith("preso:"):
        richiesta_id = int(query.data.split(":")[1])
        ok, chi = prendi_in_carico(richiesta_id, nome_operatore)
        if not ok:
            await query.answer("Gia presa in carico da " + chi, show_alert=True)
            return

    elif query.data.startswith("completato:"):
        richiesta_id = int(query.data.split(":")[1])
        ok = completa_ordine(richiesta_id, nome_operatore)
        if not ok:
            await query.answer("Ordine gia segnato come completato", show_alert=True)
            return
        req_temp = get_richiesta(richiesta_id)
        if req_temp:
            chat_id_cliente = req_temp[1]
            bot_info = await context.bot.get_me()
            link_bot = "https://t.me/" + bot_info.username
            try:
                await context.bot.send_message(
                    chat_id=chat_id_cliente,
                    text="Chi non spoppera in compagnia e un ladro o una spia, manda il link a un amico!\n\n" + link_bot
                )
            except Exception as e:
                logging.warning("Errore invio messaggio referral: " + str(e))
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
                reply_markup=tastiera
            )
        except Exception as e:
            logging.warning("Errore aggiornamento " + str(op_chat_id) + ": " + str(e))

async def cmd_storico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OPERATORI:
        return
    args = context.args
    solo_aperte = args and args[0].lower() == "aperte"
    richieste = get_storico(20, solo_aperte)

    if not richieste:
        await update.message.reply_text("Nessuna richiesta trovata.")
        return

    titolo = "Richieste aperte:\n\n" if solo_aperte else "Ultime 20 richieste:\n\n"
    righe = []
    for r in richieste:
        rid, nome, uname, testo, ricevuta_il, presa_da, ordine_completato = r
        if ordine_completato:
            stato = "Completato"
        elif presa_da:
            stato = "In lavorazione - " + presa_da
        else:
            stato = "In attesa"
        anteprima = testo[:50] + ("..." if len(testo) > 50 else "")
        righe.append("#" + str(rid) + " - " + (nome or "?") + " | " + stato + "\n" + ricevuta_il + " - " + anteprima)

    # Manda a pezzi se troppo lungo
    testo_completo = titolo
    blocco = ""
    for riga in righe:
        if len(testo_completo) + len(blocco) + len(riga) > 3800:
            await update.message.reply_text(testo_completo + blocco)
            testo_completo = ""
            blocco = ""
        blocco += riga + "\n\n"
    await update.message.reply_text(testo_completo + blocco)

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
            str(i) + ". " + (nome or "?") + " (" + (username or "?") + ")\n"
            "   Richieste: " + str(tot_r) + "  |  Ordini: " + str(tot_o or 0) + "\n"
            "   Ultimo contatto: " + (ultimo or "?")
        )

    testo = "Clienti totali: " + str(tot_clienti) + "\nOrdini completati: " + str(tot_ordini) + "\n\n" + "\n\n".join(righe)
    await update.message.reply_text(testo)

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OPERATORI:
        return
    stats = get_stats_clienti()
    top = [s for s in stats if (s[6] or 0) > 0][:10]

    if not top:
        await update.message.reply_text("Nessun ordine completato ancora.")
        return

    righe = []
    medaglie = ["1.", "2.", "3."]
    for i, (nome, username, chat_id, primo, ultimo, tot_r, tot_o) in enumerate(top):
        medaglia = medaglie[i] if i < 3 else str(i+1) + "."
        righe.append(medaglia + " " + (nome or "?") + " - " + str(tot_o) + " ordini | " + str(tot_r) + " richieste")

    await update.message.reply_text("Top clienti per ordini:\n\n" + "\n".join(righe))

async def cmd_inattivi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OPERATORI:
        return
    inattivi = get_inattivi(28)

    if not inattivi:
        await update.message.reply_text("Nessun cliente inattivo da piu di 28 giorni.")
        return

    righe = []
    for chat_id, nome, username, ultimo, giorni in inattivi[:15]:
        righe.append(
            (nome or "?") + " (" + (username or "?") + ")\n"
            "Inattivo da " + str(giorni) + " giorni (ultimo: " + (ultimo or "?") + ")\n"
            "tg://user?id=" + str(chat_id)
        )

    await update.message.reply_text("Clienti inattivi da 28+ giorni:\n\n" + "\n\n".join(righe))

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OPERATORI:
        return
    testo = update.message.text.replace("/broadcast", "").strip()
    if not testo:
        await update.message.reply_text("Scrivi il messaggio dopo il comando.\nEsempio:\n/broadcast Ciao a tutti, novita in arrivo!")
        return
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT chat_id FROM clienti")
    clienti = cur.fetchall()
    con.close()
    if not clienti:
        await update.message.reply_text("Nessun cliente registrato.")
        return
    inviati = 0
    falliti = 0
    pulsante = InlineKeyboardMarkup([[
        InlineKeyboardButton("Ordina ora", callback_data="qty:nuovo")
    ]])
    for (chat_id,) in clienti:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="King del Popper\n\n" + testo,
                reply_markup=pulsante
            )
            inviati += 1
        except Exception as e:
            logging.warning("Broadcast fallito per " + str(chat_id) + ": " + str(e))
            falliti += 1
    await update.message.reply_text("Broadcast completato!\n\nInviati: " + str(inviati) + "\nFalliti: " + str(falliti))

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OPERATORI:
        return
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    mese_corrente = datetime.now().strftime("%m/%Y")
    cur.execute("SELECT COUNT(*) FROM richieste WHERE ordine_completato = 1")
    tot_ordini = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM richieste WHERE ordine_completato = 1 AND ricevuta_il LIKE ?", ("%" + mese_corrente,))
    ordini_mese = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM richieste")
    tot_richieste = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM clienti")
    tot_clienti = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM richieste WHERE presa_da IS NULL")
    in_attesa = cur.fetchone()[0]
    con.close()
    fatturato_totale = tot_ordini * PREZZO_UNITARIO
    fatturato_mese = ordini_mese * PREZZO_UNITARIO
    mese_nome = datetime.now().strftime("%B %Y")
    testo_stats = (
        "Statistiche Popperinho Shop\n\n"
        "Clienti registrati: " + str(tot_clienti) + "\n"
        "Richieste totali: " + str(tot_richieste) + "\n"
        "In attesa di risposta: " + str(in_attesa) + "\n\n"
        "Ordini completati totali: " + str(tot_ordini) + "\n"
        "Fatturato totale: " + str(fatturato_totale) + " euro\n\n"
        "Ordini questo mese (" + mese_nome + "): " + str(ordini_mese) + "\n"
        "Fatturato questo mese: " + str(fatturato_mese) + " euro"
    )
    await update.message.reply_text(testo_stats)

async def cmd_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OPERATORI:
        return
    args = context.args
    if not args:
        lista = get_blacklist()
        if not lista:
            await update.message.reply_text("Blacklist vuota.")
            return
        righe = []
        for chat_id, nome, aggiunto_il in lista:
            righe.append(str(chat_id) + " - " + (nome or "?") + " (aggiunto il " + aggiunto_il + ")")
        await update.message.reply_text("Blacklist:\n\n" + "\n".join(righe))
        return
    if args[0].lower() == "aggiungi" and len(args) >= 2:
        try:
            chat_id = int(args[1])
            nome = " ".join(args[2:]) if len(args) > 2 else "Sconosciuto"
            aggiungi_blacklist(chat_id, nome)
            await update.message.reply_text("Utente " + str(chat_id) + " aggiunto alla blacklist.")
        except ValueError:
            await update.message.reply_text("ID non valido. Usa: /blacklist aggiungi 123456789 Nome")
    elif args[0].lower() == "rimuovi" and len(args) >= 2:
        try:
            chat_id = int(args[1])
            rimuovi_blacklist(chat_id)
            await update.message.reply_text("Utente " + str(chat_id) + " rimosso dalla blacklist.")
        except ValueError:
            await update.message.reply_text("ID non valido. Usa: /blacklist rimuovi 123456789")
    else:
        await update.message.reply_text("Comandi:\n/blacklist - mostra la lista\n/blacklist aggiungi 123456789 Nome\n/blacklist rimuovi 123456789")

async def cmd_aiuto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OPERATORI:
        return
    await update.message.reply_text(
        "Comandi disponibili:\n\n"
        "/storico - ultime 20 richieste\n"
        "/storico aperte - solo quelle in attesa\n"
        "/clienti - tutti i clienti con richieste e ordini\n"
        "/top - classifica clienti per ordini\n"
        "/inattivi - chi non scrive da 28+ giorni\n"
        "/broadcast <testo> - manda un messaggio a tutti i clienti\n"
        "/setvideo - imposta il video di benvenuto (allega il video al comando)\n"
        "/aiuto - mostra questo messaggio"
    )


# ── AVVIO ─────────────────────────────────────────────────────────────────────

def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("storico", cmd_storico))
    app.add_handler(CommandHandler("clienti", cmd_clienti))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("inattivi", cmd_inattivi))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("blacklist", cmd_blacklist))
    app.add_handler(CommandHandler("aiuto", cmd_aiuto))
    app.add_handler(CallbackQueryHandler(gestisci_callback))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, cmd_setvideo))
    app.add_handler(CommandHandler("setvideo", cmd_setvideo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ricevi_messaggio))
    app.job_queue.run_repeating(
        invia_promemoria_inattivi,
        interval=28 * 24 * 3600,
        first=datetime.strptime("21:00", "%H:%M").time()
    )
    print("Bot avviato - " + NOME_NEGOZIO)
    app.run_polling()

if __name__ == "__main__":
    main()
