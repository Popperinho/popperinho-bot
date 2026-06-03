import logging
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

logging.basicConfig(level=logging.INFO)


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
            presa_il        TEXT
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
            SELECT id, nome_cliente, username, testo, ricevuta_il, presa_da
            FROM richieste WHERE presa_da IS NULL
            ORDER BY id DESC LIMIT ?
        """, (limit,))
    else:
        cur.execute("""
            SELECT id, nome_cliente, username, testo, ricevuta_il, presa_da
            FROM richieste ORDER BY id DESC LIMIT ?
        """, (limit,))
    rows = cur.fetchall()
    con.close()
    return rows


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome = update.effective_user.first_name or "Cliente"
    await update.message.reply_text(
        f"👋 Ciao {nome}! Benvenuto da {NOME_NEGOZIO}.\n\n"
        f"Scrivimi la tua domanda e un operatore ti risponderà il prima possibile! 😊"
    )

async def ricevi_messaggio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in OPERATORI:
        return

    cliente = update.effective_user
    chat_id_cliente = update.effective_chat.id
    testo = update.message.text

    nome_cliente = (cliente.first_name or "") + (" " + cliente.last_name if cliente.last_name else "")
    username = f"@{cliente.username}" if cliente.username else "(senza username)"

    richiesta_id = salva_richiesta(chat_id_cliente, nome_cliente.strip(), username, testo)

    tasto = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Prendo in carico", callback_data=f"preso:{richiesta_id}")
    ]])

    testo_operatori = (
        f"📩 *Nuova richiesta #{richiesta_id}*\n\n"
        f"👤 {nome_cliente.strip()}  |  {username}\n"
        f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
        f"💬 _{testo}_\n\n"
        f"➡️ [Apri chat diretta](tg://user?id={chat_id_cliente})\n\n"
        f"⏳ *In attesa di essere presa in carico*"
    )

    for op_chat_id in OPERATORI:
        try:
            msg = await context.bot.send_message(
                chat_id=op_chat_id,
                text=testo_operatori,
                parse_mode="Markdown",
                reply_markup=tasto
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

    if not query.data.startswith("preso:"):
        return

    richiesta_id = int(query.data.split(":")[1])
    operatore_id = query.from_user.id
    nome_operatore = OPERATORI.get(operatore_id, query.from_user.first_name)

    ok, chi = prendi_in_carico(richiesta_id, nome_operatore)

    req = get_richiesta(richiesta_id)
    if not req:
        return
    _, chat_id_cliente, nome_cliente, username, testo, ricevuta_il, presa_da, presa_il = req

    stato = f"✅ *Presa in carico da: {nome_operatore}* alle {presa_il}" if ok else f"⚠️ Già presa in carico da: {chi}"

    testo_aggiornato = (
        f"📩 *Richiesta #{richiesta_id}*\n\n"
        f"👤 {nome_cliente}  |  {username}\n"
        f"🕐 {ricevuta_il}\n\n"
        f"💬 _{testo}_\n\n"
        f"➡️ [Apri chat diretta](tg://user?id={chat_id_cliente})\n\n"
        f"{stato}"
    )

    for op_chat_id, msg_id in get_messaggi_operatori(richiesta_id):
        try:
            await context.bot.edit_message_text(
                chat_id=op_chat_id,
                message_id=msg_id,
                text=testo_aggiornato,
                parse_mode="Markdown",
                reply_markup=None
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
        rid, nome, uname, testo, ricevuta_il, presa_da = r
        stato = f"✅ {presa_da}" if presa_da else "⏳ In attesa"
        anteprima = testo[:60] + ("…" if len(testo) > 60 else "")
        righe.append(f"*#{rid}* — {nome} ({uname})\n🕐 {ricevuta_il} | {stato}\n💬 _{anteprima}_")

    await update.message.reply_text(titolo + "\n\n".join(righe), parse_mode="Markdown")

async def cmd_aiuto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OPERATORI:
        return
    await update.message.reply_text(
        "📖 *Comandi disponibili:*\n\n"
        "/storico — ultime 20 richieste\n"
        "/storico aperte — solo quelle in attesa\n"
        "/aiuto — mostra questo messaggio",
        parse_mode="Markdown"
    )

def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("storico", cmd_storico))
    app.add_handler(CommandHandler("aiuto", cmd_aiuto))
    app.add_handler(CallbackQueryHandler(gestisci_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ricevi_messaggio))
    print(f"✅ Bot avviato — {NOME_NEGOZIO}")
    app.run_polling()

if __name__ == "__main__":
    main()
