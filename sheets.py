import gspread
import state
from state import user_states, registered_users, OWNER_IDS, PHASE_UNREGISTERED, PHASE_IDLE

# Initialised by finance_bot_py.py after the gspread connection is established
_work_sheet = None
_sheet1 = None


def init(ws):
    global _work_sheet, _sheet1
    _work_sheet = ws
    _sheet1 = ws.sheet1


# ── State helpers ─────────────────────────────────────────────────────────────
def _blank_state():
    return {
        'phase': PHASE_UNREGISTERED,
        'category': None,
        'amount': None,
        'comment': '',
        'split_with': set(),
        'pending_row': {},
    }


def ensure_state(chat_id):
    if chat_id not in user_states:
        user_states[chat_id] = _blank_state()
    return user_states[chat_id]


def get_user(chat_id):
    return registered_users.get(chat_id)


def _reset_state(chat_id):
    s = user_states[chat_id]
    s['phase'] = PHASE_IDLE
    s['category'] = None
    s['amount'] = None
    s['comment'] = ''
    s['split_with'] = set()
    s['pending_row'] = {}


# ── Sheet helpers ─────────────────────────────────────────────────────────────
def _is_guest_tag(role):
    return 'guest' if role == 'guest' else ''


def get_or_create_user_sheet(name):
    try:
        return _work_sheet.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        ws = _work_sheet.add_worksheet(title=name, rows=1010, cols=6)
        ws.update('A1:F2', [
            ['date', 'category', 'amount (RM)', 'Total RM', 'Total RUB', 'comment'],
            ['',     '',         '',            '=SUM(C3:C1000)',
             '=D2*GOOGLEFINANCE("CURRENCY:MYRRUB")', ''],
        ], value_input_option='USER_ENTERED')
        return ws


def load_registered_users():
    """Read Users sheet and populate registered_users cache."""
    registered_users.clear()
    try:
        users_sheet = _work_sheet.worksheet('Users')
    except gspread.exceptions.WorksheetNotFound:
        users_sheet = _work_sheet.add_worksheet(title='Users', rows=200, cols=4)
        users_sheet.update('A1:D1', [['telegram_id', 'name', 'role', 'language']])
        return

    rows = users_sheet.get_all_values()
    if len(rows) <= 1:
        return

    for i, row in enumerate(rows[1:], start=2):
        if not row or not row[0].strip():
            continue
        try:
            uid = int(row[0].strip())
        except ValueError:
            continue
        name = row[1].strip() if len(row) > 1 else ''
        role = row[2].strip() if len(row) > 2 else 'guest'
        if uid in OWNER_IDS and role != 'owner':
            role = 'owner'
            users_sheet.update_cell(i, 3, 'owner')
        lang = row[3].strip() if len(row) > 3 else ''
        if lang not in ('en', 'ru'):
            lang = 'en'
        ws = get_or_create_user_sheet(name) if name else None
        registered_users[uid] = {'name': name, 'role': role, 'sheet': ws, 'language': lang}


def register_new_user(chat_id, name, lang='en'):
    """Append user to Users sheet and update in-memory cache."""
    role = 'owner' if chat_id in OWNER_IDS else 'guest'
    try:
        users_sheet = _work_sheet.worksheet('Users')
    except gspread.exceptions.WorksheetNotFound:
        users_sheet = _work_sheet.add_worksheet(title='Users', rows=200, cols=4)
        users_sheet.update('A1:D1', [['telegram_id', 'name', 'role', 'language']])
    users_sheet.append_row([str(chat_id), name, role, lang])
    ws = get_or_create_user_sheet(name)
    registered_users[chat_id] = {'name': name, 'role': role, 'sheet': ws, 'language': lang}


def unique_sheet_name(base_name):
    """Return base_name, or base_name2, base_name3, … if tab already exists."""
    existing = {ws.title for ws in _work_sheet.worksheets()}
    if base_name not in existing:
        return base_name
    i = 2
    while f'{base_name}{i}' in existing:
        i += 1
    return f'{base_name}{i}'


# ── Expense commit helpers ────────────────────────────────────────────────────
def commit_expense(chat_id, s):
    row = s['pending_row']
    user = registered_users[chat_id]
    comment = row.get('comment', '')
    _sheet1.append_row([
        row['date'], row['category'], row['amount'],
        user['name'], _is_guest_tag(user['role']), comment,
    ], value_input_option='USER_ENTERED')
    # Per-user sheet: blanks in cols D & E preserve the SUM/GOOGLEFINANCE formulas in row 2
    user['sheet'].append_row(
        [row['date'], row['category'], row['amount'], '', '', comment],
        value_input_option='USER_ENTERED')
    _reset_state(chat_id)


def commit_split_expense(chat_id, s):
    row = s['pending_row']
    comment = row.get('comment', '')
    all_ids = s['split_with'] | {chat_id}
    share = round(row['amount'] / len(all_ids), 2)
    names = []
    for uid in all_ids:
        target = registered_users[uid]
        _sheet1.append_row([
            row['date'], row['category'], share,
            target['name'], _is_guest_tag(target['role']), comment,
        ], value_input_option='USER_ENTERED')
        target['sheet'].append_row(
            [row['date'], row['category'], share, '', '', comment],
            value_input_option='USER_ENTERED')
        names.append(target['name'])
    _reset_state(chat_id)
    return share, names
