import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import threading
from flask import Flask
import os
import requests
import time

# ── Google Sheets connection ──────────────────────────────────────────────────
TABLE_NAME = 'LuOv_finance'

scope = ['https://spreadsheets.google.com/feeds',
         'https://www.googleapis.com/auth/drive']

credentials = ServiceAccountCredentials.from_json_keyfile_name(
    'luov-finance-project-b33b78877788.json', scope)

gs = gspread.authorize(credentials)
work_sheet = gs.open(TABLE_NAME)
sheet1 = work_sheet.sheet1

# ── Categories ────────────────────────────────────────────────────────────────
categories_sheet = work_sheet.worksheet('Categories')
title_categories = categories_sheet.col_values(1)
title_categories = [c for c in title_categories if c]

# ── Owner IDs (env var: comma-separated Telegram IDs) ─────────────────────────
_owner_ids_raw = os.environ.get('OWNER_IDS', '')
OWNER_IDS = set(int(x.strip()) for x in _owner_ids_raw.split(',') if x.strip())

# ── Phase constants ───────────────────────────────────────────────────────────
PHASE_UNREGISTERED    = 'unregistered'
PHASE_AWAITING_NAME   = 'awaiting_name'
PHASE_IDLE            = 'idle'
PHASE_CAT_SELECTED    = 'category_selected'
PHASE_AWAITING_SPLIT  = 'awaiting_split'
PHASE_SELECTING_SPLIT = 'selecting_split'

# ── In-memory state ───────────────────────────────────────────────────────────
user_states = {}       # {chat_id: {phase, category, amount, split_with, pending_row}}
registered_users = {}  # {chat_id: {name, role, sheet}}


def _blank_state():
    return {
        'phase': PHASE_UNREGISTERED,
        'category': None,
        'amount': None,
        'split_with': set(),
        'pending_row': {},
    }


def ensure_state(chat_id):
    if chat_id not in user_states:
        user_states[chat_id] = _blank_state()
    return user_states[chat_id]


def get_user(chat_id):
    return registered_users.get(chat_id)


# ── Sheet helpers ─────────────────────────────────────────────────────────────
def get_or_create_user_sheet(name):
    try:
        return work_sheet.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        ws = work_sheet.add_worksheet(title=name, rows=1010, cols=5)
        ws.update('A1:E1', [['date', 'category', 'amount (RM)',
                              '=SUM(C2:C1000)',
                              '=D1*GOOGLEFINANCE("CURRENCY:MYRUB")']],
                  value_input_option='USER_ENTERED')
        return ws


def load_registered_users():
    """Read Users sheet and populate registered_users cache."""
    registered_users.clear()
    try:
        users_sheet = work_sheet.worksheet('Users')
    except gspread.exceptions.WorksheetNotFound:
        # Create Users sheet if it doesn't exist yet
        users_sheet = work_sheet.add_worksheet(title='Users', rows=200, cols=3)
        users_sheet.update('A1:C1', [['telegram_id', 'name', 'role']])
        return

    rows = users_sheet.get_all_values()
    if len(rows) <= 1:
        return  # only header or empty

    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        try:
            uid = int(row[0].strip())
        except ValueError:
            continue
        name = row[1].strip() if len(row) > 1 else ''
        role = row[2].strip() if len(row) > 2 else 'guest'
        # Env-var owner override
        if uid in OWNER_IDS:
            role = 'owner'
        ws = get_or_create_user_sheet(name) if name else None
        registered_users[uid] = {'name': name, 'role': role, 'sheet': ws}


def register_new_user(chat_id, name):
    """Append user to Users sheet and update in-memory cache."""
    role = 'owner' if chat_id in OWNER_IDS else 'guest'
    try:
        users_sheet = work_sheet.worksheet('Users')
    except gspread.exceptions.WorksheetNotFound:
        users_sheet = work_sheet.add_worksheet(title='Users', rows=200, cols=3)
        users_sheet.update('A1:C1', [['telegram_id', 'name', 'role']])
    users_sheet.append_row([str(chat_id), name, role])
    ws = get_or_create_user_sheet(name)
    registered_users[chat_id] = {'name': name, 'role': role, 'sheet': ws}


def unique_sheet_name(base_name):
    """Return base_name, or base_name2, base_name3, … if tab already exists."""
    existing = {ws.title for ws in work_sheet.worksheets()}
    if base_name not in existing:
        return base_name
    i = 2
    while f'{base_name}{i}' in existing:
        i += 1
    return f'{base_name}{i}'


# ── Keyboard builders ─────────────────────────────────────────────────────────
def create_category_keyboard():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    buttons = [telebot.types.InlineKeyboardButton(text=c, callback_data=c)
               for c in title_categories]
    kb.add(*buttons)
    return kb


def create_question_keyboard():
    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(
        telebot.types.InlineKeyboardButton(text='Yes', callback_data='add_another'),
        telebot.types.InlineKeyboardButton(text='No', callback_data='finish'),
    )
    return kb


def create_split_keyboard(chat_id, split_with):
    kb = telebot.types.InlineKeyboardMarkup(row_width=1)
    for uid, udata in registered_users.items():
        if uid == chat_id:
            continue
        checked = uid in split_with
        label = f"{'[x]' if checked else '[ ]'} {udata['name']}"
        kb.add(telebot.types.InlineKeyboardButton(
            text=label, callback_data=f'toggle_{uid}'))
    kb.add(telebot.types.InlineKeyboardButton(
        text='Confirm split', callback_data='split_confirm'))
    kb.add(telebot.types.InlineKeyboardButton(
        text='Cancel', callback_data='split_cancel'))
    return kb


# ── Expense commit helpers ────────────────────────────────────────────────────
def _is_guest_tag(role):
    return 'guest' if role == 'guest' else ''


def commit_expense(chat_id, state):
    row = state['pending_row']
    user = registered_users[chat_id]
    sheet1.append_row([
        row['date'], row['category'], row['amount'],
        user['name'], _is_guest_tag(user['role'])
    ])
    user['sheet'].append_row([row['date'], row['category'], row['amount']])
    _reset_state(chat_id)


def commit_split_expense(chat_id, state):
    row = state['pending_row']
    all_ids = state['split_with'] | {chat_id}
    share = round(row['amount'] / len(all_ids), 2)
    names = []
    for uid in all_ids:
        target = registered_users[uid]
        sheet1.append_row([
            row['date'], row['category'], share,
            target['name'], _is_guest_tag(target['role'])
        ])
        target['sheet'].append_row([row['date'], row['category'], share])
        names.append(target['name'])
    _reset_state(chat_id)
    return share, names


def _reset_state(chat_id):
    state = user_states[chat_id]
    state['phase'] = PHASE_IDLE
    state['category'] = None
    state['amount'] = None
    state['split_with'] = set()
    state['pending_row'] = {}


# ── Bot ───────────────────────────────────────────────────────────────────────
bot_token = os.getenv('BOT_TOKEN')
bot = telebot.TeleBot(bot_token)


@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    state = ensure_state(chat_id)
    user = get_user(chat_id)
    if user:
        state['phase'] = PHASE_IDLE
        bot.send_message(chat_id, 'Choose the category:', reply_markup=create_category_keyboard())
    else:
        state['phase'] = PHASE_AWAITING_NAME
        bot.send_message(chat_id, 'Welcome! What\'s your name?')


@bot.message_handler(commands=['reloadusers'])
def reloadusers(message):
    chat_id = message.chat.id
    user = get_user(chat_id)
    if not user or user['role'] != 'owner':
        bot.send_message(chat_id, 'Not authorized.')
        return
    load_registered_users()
    bot.send_message(chat_id, f'Users reloaded. {len(registered_users)} registered.')


# ── Category callback ─────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda call: call.data in title_categories)
def handle_category_callback(call):
    chat_id = call.message.chat.id
    state = ensure_state(chat_id)
    user = get_user(chat_id)
    if not user:
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, 'Please use /start to register first.')
        return
    state['category'] = call.data
    state['phase'] = PHASE_CAT_SELECTED
    bot.answer_callback_query(call.id)
    bot.send_message(chat_id, f'Category "{call.data}" selected. Enter the amount (RM):')


# ── Split-flow callbacks ──────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda call: call.data == 'split_no')
def split_no(call):
    chat_id = call.message.chat.id
    state = ensure_state(chat_id)
    bot.answer_callback_query(call.id)
    commit_expense(chat_id, state)
    bot.send_message(chat_id,
                     'Data saved. Add another expense?',
                     reply_markup=create_question_keyboard())


@bot.callback_query_handler(func=lambda call: call.data == 'split_yes')
def split_yes(call):
    chat_id = call.message.chat.id
    state = ensure_state(chat_id)
    state['phase'] = PHASE_SELECTING_SPLIT
    state['split_with'] = set()
    bot.answer_callback_query(call.id)
    if len(registered_users) <= 1:
        bot.send_message(chat_id, 'No other registered users to split with.')
        commit_expense(chat_id, state)
        bot.send_message(chat_id, 'Data saved. Add another expense?',
                         reply_markup=create_question_keyboard())
        return
    bot.send_message(chat_id, 'Select who to split with:',
                     reply_markup=create_split_keyboard(chat_id, state['split_with']))


@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_'))
def handle_toggle(call):
    chat_id = call.message.chat.id
    state = ensure_state(chat_id)
    try:
        target_uid = int(call.data.split('_', 1)[1])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id)
        return
    if target_uid in state['split_with']:
        state['split_with'].discard(target_uid)
    else:
        state['split_with'].add(target_uid)
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_reply_markup(
            chat_id, call.message.message_id,
            reply_markup=create_split_keyboard(chat_id, state['split_with']))
    except Exception:
        bot.send_message(chat_id, 'Select who to split with:',
                         reply_markup=create_split_keyboard(chat_id, state['split_with']))


@bot.callback_query_handler(func=lambda call: call.data == 'split_confirm')
def split_confirm(call):
    chat_id = call.message.chat.id
    state = ensure_state(chat_id)
    bot.answer_callback_query(call.id)
    if not state['split_with']:
        commit_expense(chat_id, state)
        bot.send_message(chat_id, 'Data saved. Add another expense?',
                         reply_markup=create_question_keyboard())
        return
    total_amount = state['pending_row']['amount']
    share, names = commit_split_expense(chat_id, state)
    names_str = ', '.join(names)
    bot.send_message(chat_id,
                     f'Split {total_amount} RM among {names_str}. '
                     f'Each share: {share} RM.\nAdd another expense?',
                     reply_markup=create_question_keyboard())


@bot.callback_query_handler(func=lambda call: call.data == 'split_cancel')
def split_cancel(call):
    chat_id = call.message.chat.id
    state = ensure_state(chat_id)
    state['phase'] = PHASE_AWAITING_SPLIT
    state['split_with'] = set()
    bot.answer_callback_query(call.id)
    row = state['pending_row']
    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(
        telebot.types.InlineKeyboardButton(text='Yes, split', callback_data='split_yes'),
        telebot.types.InlineKeyboardButton(text='No, just me', callback_data='split_no'),
    )
    bot.send_message(chat_id,
                     f'Amount: {row.get("amount")} RM. Split with others?',
                     reply_markup=kb)


# ── Add-another / finish callbacks ───────────────────────────────────────────
@bot.callback_query_handler(func=lambda call: call.data == 'add_another')
def add_another(call):
    chat_id = call.message.chat.id
    state = ensure_state(chat_id)
    state['phase'] = PHASE_IDLE
    bot.answer_callback_query(call.id)
    bot.send_message(chat_id, 'Choose the category:', reply_markup=create_category_keyboard())


@bot.callback_query_handler(func=lambda call: call.data == 'finish')
def finish(call):
    chat_id = call.message.chat.id
    state = ensure_state(chat_id)
    state['phase'] = PHASE_IDLE
    bot.answer_callback_query(call.id)
    bot.send_message(chat_id, 'Thank you! Your data has been saved.')


# ── Catch-all message handler ─────────────────────────────────────────────────
@bot.message_handler(func=lambda m: True)
def dispatch_message(message):
    chat_id = message.chat.id
    state = ensure_state(chat_id)
    phase = state['phase']

    if phase == PHASE_AWAITING_NAME:
        handle_name_input(message, state)
    elif phase == PHASE_CAT_SELECTED:
        handle_amount_input(message, state)
    else:
        bot.send_message(chat_id, 'Please use /start to begin.')


def handle_name_input(message, state):
    chat_id = message.chat.id
    name = message.text.strip()
    if not name or len(name) > 32:
        bot.send_message(chat_id, 'Please enter a valid name (1–32 characters).')
        return
    safe_name = unique_sheet_name(name)
    register_new_user(chat_id, safe_name)
    state['phase'] = PHASE_IDLE
    bot.send_message(chat_id, f'Welcome, {safe_name}! Choose a category:',
                     reply_markup=create_category_keyboard())


def handle_amount_input(message, state):
    chat_id = message.chat.id
    if message.text == '/start':
        start(message)
        return
    try:
        amount = float(message.text.strip())
    except ValueError:
        bot.send_message(chat_id, 'Please enter a valid number for the amount.')
        return

    formatted_date = datetime.fromtimestamp(message.date).strftime('%Y-%m-%d')
    state['amount'] = amount
    state['pending_row'] = {
        'date': formatted_date,
        'category': state['category'],
        'amount': amount,
    }
    state['phase'] = PHASE_AWAITING_SPLIT

    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(
        telebot.types.InlineKeyboardButton(text='Yes, split', callback_data='split_yes'),
        telebot.types.InlineKeyboardButton(text='No, just me', callback_data='split_no'),
    )
    bot.send_message(chat_id, f'Amount: {amount} RM. Split with others?', reply_markup=kb)


# ── Infrastructure ────────────────────────────────────────────────────────────
def run_bot():
    bot.infinity_polling()


def self_ping():
    url = os.environ.get('RENDER_EXTERNAL_URL')
    if not url:
        return
    while True:
        time.sleep(10 * 60)
        try:
            requests.get(url, timeout=10)
        except Exception:
            pass


flask_app = Flask(__name__)


@flask_app.route('/')
def home():
    return "Bot's working!"


if __name__ == '__main__':
    load_registered_users()

    threading.Thread(target=run_bot, daemon=True).start()
    threading.Thread(target=self_ping, daemon=True).start()

    port = int(os.environ.get('PORT', 5000))
    flask_app.run(host='0.0.0.0', port=port)
