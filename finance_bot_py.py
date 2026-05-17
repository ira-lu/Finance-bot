import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import threading
from flask import Flask
import os
import requests
import time

import state
import sheets
from state import registered_users
from strings import t, ADD_EXPENSE_LABELS, MY_EXPENSES_LABELS, LANG_TOGGLE_LABELS

# ── Google Sheets connection ──────────────────────────────────────────────────
TABLE_NAME = 'LuOv_finance'

scope = ['https://spreadsheets.google.com/feeds',
         'https://www.googleapis.com/auth/drive']

credentials = ServiceAccountCredentials.from_json_keyfile_name(
    'luov-finance-project-b33b78877788.json', scope)

gs = gspread.authorize(credentials)
work_sheet = gs.open(TABLE_NAME)
sheets.init(work_sheet)

# ── Categories ────────────────────────────────────────────────────────────────
categories_sheet = work_sheet.worksheet('Categories')
title_categories = categories_sheet.col_values(1)
title_categories = [c for c in title_categories if c]

# ── Bot ───────────────────────────────────────────────────────────────────────
bot_token = os.getenv('BOT_TOKEN')
bot = telebot.TeleBot(bot_token)


# ── Keyboard builders ─────────────────────────────────────────────────────────
def create_category_keyboard():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    buttons = [telebot.types.InlineKeyboardButton(text=c, callback_data=c)
               for c in title_categories]
    kb.add(*buttons)
    return kb


def create_question_keyboard(chat_id):
    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(
        telebot.types.InlineKeyboardButton(text=t('add_another_yes', chat_id), callback_data='add_another'),
        telebot.types.InlineKeyboardButton(text=t('add_another_no', chat_id), callback_data='finish'),
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
        text=t('split_confirm_label', chat_id), callback_data='split_confirm'))
    kb.add(telebot.types.InlineKeyboardButton(
        text=t('split_cancel_label', chat_id), callback_data='split_cancel'))
    return kb


def create_main_menu_keyboard(chat_id):
    kb = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True)
    kb.row(
        telebot.types.KeyboardButton(t('btn_add_expense', chat_id)),
        telebot.types.KeyboardButton(t('btn_my_expenses', chat_id)),
    )
    kb.row(telebot.types.KeyboardButton(t('btn_lang_toggle', chat_id)))
    return kb


def show_main_menu(chat_id, text=None):
    bot.send_message(chat_id, text or t('choose_category', chat_id),
                     reply_markup=create_main_menu_keyboard(chat_id))


# ── Commands ──────────────────────────────────────────────────────────────────
@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    s = sheets.ensure_state(chat_id)
    user = sheets.get_user(chat_id)
    if user:
        s['phase'] = state.PHASE_IDLE
        show_main_menu(chat_id)
    else:
        s['phase'] = state.PHASE_AWAITING_NAME
        bot.send_message(chat_id, t('welcome_ask_name', chat_id))


@bot.message_handler(commands=['reloadusers'])
def reloadusers(message):
    chat_id = message.chat.id
    user = sheets.get_user(chat_id)
    if not user or user['role'] != 'owner':
        bot.send_message(chat_id, t('not_authorized', chat_id))
        return
    sheets.load_registered_users()
    bot.send_message(chat_id, t('users_reloaded', chat_id).format(count=len(registered_users)))


# ── Category callback ─────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda call: call.data in title_categories)
def handle_category_callback(call):
    chat_id = call.message.chat.id
    s = sheets.ensure_state(chat_id)
    user = sheets.get_user(chat_id)
    if not user:
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, t('please_register', chat_id))
        return
    s['category'] = call.data
    s['phase'] = state.PHASE_CAT_SELECTED
    bot.answer_callback_query(call.id)
    bot.send_message(chat_id, t('enter_amount', chat_id).format(cat=call.data))


# ── Split-flow callbacks ──────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda call: call.data == 'split_no')
def split_no(call):
    chat_id = call.message.chat.id
    s = sheets.ensure_state(chat_id)
    bot.answer_callback_query(call.id)
    sheets.commit_expense(chat_id, s)
    bot.send_message(chat_id, t('add_another_prompt', chat_id),
                     reply_markup=create_question_keyboard(chat_id))


@bot.callback_query_handler(func=lambda call: call.data == 'split_yes')
def split_yes(call):
    chat_id = call.message.chat.id
    s = sheets.ensure_state(chat_id)
    s['phase'] = state.PHASE_SELECTING_SPLIT
    s['split_with'] = set()
    bot.answer_callback_query(call.id)
    if len(registered_users) <= 1:
        bot.send_message(chat_id, t('no_other_users', chat_id))
        sheets.commit_expense(chat_id, s)
        bot.send_message(chat_id, t('add_another_prompt', chat_id),
                         reply_markup=create_question_keyboard(chat_id))
        return
    bot.send_message(chat_id, t('split_select', chat_id),
                     reply_markup=create_split_keyboard(chat_id, s['split_with']))


@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_'))
def handle_toggle(call):
    chat_id = call.message.chat.id
    s = sheets.ensure_state(chat_id)
    try:
        target_uid = int(call.data.split('_', 1)[1])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id)
        return
    if target_uid in s['split_with']:
        s['split_with'].discard(target_uid)
    else:
        s['split_with'].add(target_uid)
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_reply_markup(
            chat_id, call.message.message_id,
            reply_markup=create_split_keyboard(chat_id, s['split_with']))
    except Exception:
        bot.send_message(chat_id, t('split_select', chat_id),
                         reply_markup=create_split_keyboard(chat_id, s['split_with']))


@bot.callback_query_handler(func=lambda call: call.data == 'split_confirm')
def split_confirm(call):
    chat_id = call.message.chat.id
    s = sheets.ensure_state(chat_id)
    bot.answer_callback_query(call.id)
    if not s['split_with']:
        sheets.commit_expense(chat_id, s)
        bot.send_message(chat_id, t('add_another_prompt', chat_id),
                         reply_markup=create_question_keyboard(chat_id))
        return
    total_amount = s['pending_row']['amount']
    share, names = sheets.commit_split_expense(chat_id, s)
    names_str = ', '.join(names)
    msg = t('split_result', chat_id).format(total=total_amount, names=names_str, share=share)
    bot.send_message(chat_id, f'{msg}\n{t("add_another_prompt", chat_id)}',
                     reply_markup=create_question_keyboard(chat_id))


@bot.callback_query_handler(func=lambda call: call.data == 'split_cancel')
def split_cancel(call):
    chat_id = call.message.chat.id
    s = sheets.ensure_state(chat_id)
    s['phase'] = state.PHASE_AWAITING_SPLIT
    s['split_with'] = set()
    bot.answer_callback_query(call.id)
    row = s['pending_row']
    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(
        telebot.types.InlineKeyboardButton(text=t('split_yes_label', chat_id), callback_data='split_yes'),
        telebot.types.InlineKeyboardButton(text=t('split_no_label', chat_id), callback_data='split_no'),
    )
    bot.send_message(chat_id,
                     t('split_question', chat_id).format(amount=row.get('amount')),
                     reply_markup=kb)


# ── Add-another / finish callbacks ────────────────────────────────────────────
@bot.callback_query_handler(func=lambda call: call.data == 'add_another')
def add_another(call):
    chat_id = call.message.chat.id
    s = sheets.ensure_state(chat_id)
    s['phase'] = state.PHASE_IDLE
    bot.answer_callback_query(call.id)
    # Go straight to category keyboard — user explicitly wants another expense
    bot.send_message(chat_id, t('choose_category', chat_id), reply_markup=create_category_keyboard())


@bot.callback_query_handler(func=lambda call: call.data == 'finish')
def finish(call):
    chat_id = call.message.chat.id
    s = sheets.ensure_state(chat_id)
    s['phase'] = state.PHASE_IDLE
    bot.answer_callback_query(call.id)
    show_main_menu(chat_id, t('data_saved', chat_id))


# ── Catch-all message handler ─────────────────────────────────────────────────
@bot.message_handler(func=lambda m: True)
def dispatch_message(message):
    chat_id = message.chat.id
    s = sheets.ensure_state(chat_id)
    text = message.text or ''

    # Main menu button routing — checked before phase logic
    if text in LANG_TOGGLE_LABELS:
        handle_language_toggle(message)
        return
    if text in ADD_EXPENSE_LABELS:
        handle_add_expense_button(message)
        return
    if text in MY_EXPENSES_LABELS:
        handle_my_expenses(message)
        return

    phase = s['phase']
    if phase == state.PHASE_AWAITING_NAME:
        handle_name_input(message, s)
    elif phase == state.PHASE_CAT_SELECTED:
        handle_amount_input(message, s)
    else:
        bot.send_message(chat_id, t('please_register', chat_id))


def handle_name_input(message, s):
    chat_id = message.chat.id
    name = message.text.strip()
    if not name or len(name) > 32:
        bot.send_message(chat_id, t('invalid_name', chat_id))
        return
    lang = 'ru' if (message.from_user.language_code or '').startswith('ru') else 'en'
    safe_name = sheets.unique_sheet_name(name)
    sheets.register_new_user(chat_id, safe_name, lang)
    s['phase'] = state.PHASE_IDLE
    show_main_menu(chat_id, t('welcome_registered', chat_id).format(name=safe_name))


def handle_amount_input(message, s):
    chat_id = message.chat.id
    if message.text == '/start':
        start(message)
        return
    parts = message.text.strip().split(None, 1)
    amount_str = parts[0]
    comment = parts[1].strip() if len(parts) > 1 else ''
    try:
        amount = float(amount_str)
    except ValueError:
        bot.send_message(chat_id, t('invalid_amount', chat_id))
        return
    if amount <= 0:
        bot.send_message(chat_id, t('invalid_amount', chat_id))
        return

    formatted_date = datetime.fromtimestamp(message.date).strftime('%d/%m/%Y')
    s['amount'] = amount
    s['comment'] = comment
    s['pending_row'] = {
        'date': formatted_date,
        'category': s['category'],
        'amount': amount,
        'comment': comment,
    }
    s['phase'] = state.PHASE_AWAITING_SPLIT

    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(
        telebot.types.InlineKeyboardButton(text=t('split_yes_label', chat_id), callback_data='split_yes'),
        telebot.types.InlineKeyboardButton(text=t('split_no_label', chat_id), callback_data='split_no'),
    )
    bot.send_message(chat_id, t('split_question', chat_id).format(amount=amount), reply_markup=kb)


def handle_add_expense_button(message):
    chat_id = message.chat.id
    if not sheets.get_user(chat_id):
        bot.send_message(chat_id, t('please_register', chat_id))
        return
    bot.send_message(chat_id, t('choose_category', chat_id), reply_markup=create_category_keyboard())


def handle_my_expenses(message):
    chat_id = message.chat.id
    user = registered_users.get(chat_id)
    if not user or not user.get('sheet'):
        bot.send_message(chat_id, t('please_register', chat_id))
        return
    ws = user['sheet']
    try:
        all_data = ws.get_all_values()   # single API call
    except Exception as e:
        bot.send_message(chat_id, f'Error reading data: {e}')
        return
    # Row index 1 (0-based) = row 2 in sheet = formula row
    formula_row = all_data[1] if len(all_data) > 1 else []
    total_rm  = formula_row[3] if len(formula_row) > 3 else '0'   # D2 = Total RM
    total_rub = formula_row[4] if len(formula_row) > 4 else '0'   # E2 = Total RUB
    # Data rows start at index 2 (row 3 in sheet)
    data_rows = [r for r in all_data[2:] if any(r)]
    last_5 = data_rows[-5:]
    lines = []
    for row in last_5:
        date   = row[0] if len(row) > 0 else ''
        cat    = row[1] if len(row) > 1 else ''
        amount = row[2] if len(row) > 2 else ''
        comment_val = row[5] if len(row) > 5 else ''
        suffix = f' — {comment_val}' if comment_val else ''
        lines.append(f'{date} | {cat} | {amount} RM{suffix}')
    header = t('my_expenses_header', chat_id).format(total_rm=total_rm, total_rub=total_rub)
    body = '\n'.join(lines) if lines else t('no_expenses_yet', chat_id)
    bot.send_message(chat_id, f'{header}\n{body}')


def handle_language_toggle(message):
    chat_id = message.chat.id
    user = registered_users.get(chat_id)
    if not user:
        return
    new_lang = 'ru' if user.get('language', 'en') == 'en' else 'en'
    user['language'] = new_lang
    try:
        users_ws = work_sheet.worksheet('Users')
        cell = users_ws.find(str(chat_id), in_column=1)
        if cell:
            users_ws.update_cell(cell.row, 4, new_lang)
    except Exception:
        pass
    key = 'lang_switched_ru' if new_lang == 'ru' else 'lang_switched_en'
    bot.send_message(chat_id, t(key, chat_id),
                     reply_markup=create_main_menu_keyboard(chat_id))


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
    sheets.load_registered_users()

    threading.Thread(target=run_bot, daemon=True).start()
    threading.Thread(target=self_ping, daemon=True).start()

    port = int(os.environ.get('PORT', 5000))
    flask_app.run(host='0.0.0.0', port=port)
