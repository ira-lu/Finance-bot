from state import registered_users

STRINGS = {
    # Registration
    'welcome_ask_name':    {'en': "Welcome! What's your name?",
                            'ru': 'Добро пожаловать! Как вас зовут?'},
    'welcome_registered':  {'en': 'Welcome, {name}!',
                            'ru': 'Добро пожаловать, {name}!'},
    'invalid_name':        {'en': 'Please enter a valid name (1–32 characters).',
                            'ru': 'Введите корректное имя (1–32 символа).'},
    # Category / amount
    'choose_category':     {'en': 'Choose the category:',
                            'ru': 'Выберите категорию:'},
    'enter_amount':        {'en': 'Category "{cat}" selected.\n'
                                  'Enter amount (RM), optionally followed by a comment.\n'
                                  'Example: "50 coffee"',
                            'ru': 'Категория "{cat}" выбрана.\n'
                                  'Введите сумму (RM), можно добавить комментарий.\n'
                                  'Пример: "50 кофе"'},
    'invalid_amount':      {'en': 'Please enter a valid number for the amount.',
                            'ru': 'Введите корректное число для суммы.'},
    # Split flow
    'split_question':      {'en': 'Amount: {amount} RM. Split with others?',
                            'ru': 'Сумма: {amount} RM. Разделить с другими?'},
    'split_yes_label':     {'en': 'Yes, split',       'ru': 'Да, разделить'},
    'split_no_label':      {'en': 'No, just me',       'ru': 'Нет, только я'},
    'split_select':        {'en': 'Select who to split with:',
                            'ru': 'Выберите, с кем разделить:'},
    'split_confirm_label': {'en': 'Confirm split',     'ru': 'Подтвердить'},
    'split_cancel_label':  {'en': 'Cancel',            'ru': 'Отмена'},
    'no_other_users':      {'en': 'No other registered users to split with.',
                            'ru': 'Нет других зарегистрированных пользователей.'},
    'split_result':        {'en': 'Split {total} RM among {names}. Each share: {share} RM.',
                            'ru': 'Разделено {total} RM между {names}. Доля каждого: {share} RM.'},
    # Saving
    'data_saved':          {'en': 'Saved!', 'ru': 'Сохранено!'},
    'add_another_prompt':  {'en': 'Add another expense?', 'ru': 'Добавить ещё расход?'},
    'add_another_yes':     {'en': 'Yes', 'ru': 'Да'},
    'add_another_no':      {'en': 'No',  'ru': 'Нет'},
    # Admin
    'not_authorized':      {'en': 'Not authorized.',    'ru': 'Нет доступа.'},
    'users_reloaded':      {'en': 'Users reloaded. {count} registered.',
                            'ru': 'Пользователи перезагружены. Зарегистрировано: {count}.'},
    'please_register':     {'en': 'Please use /start to register.',
                            'ru': 'Используйте /start для регистрации.'},
    # Main menu buttons
    'btn_add_expense':     {'en': 'Add expenses',    'ru': 'Добавить расход'},
    'btn_my_expenses':     {'en': 'My expenses',     'ru': 'Мои расходы'},
    # btn_lang_toggle shows the OPPOSITE language (what you will switch TO)
    'btn_lang_toggle':     {'en': '🇷🇺 RU',           'ru': '🇬🇧 EN'},
    # My expenses summary
    'my_expenses_header':  {'en': 'Your expenses:\nTotal: {total_rm} RM (~{total_rub} RUB)\n\nLast 5 entries:',
                            'ru': 'Ваши расходы:\nИтого: {total_rm} RM (~{total_rub} RUB)\n\nПоследние 5 записей:'},
    'no_expenses_yet':     {'en': 'No expenses yet.',  'ru': 'Расходов пока нет.'},
    # Language switch confirmations (always shown in the new language)
    'lang_switched_en':    {'en': 'Language set to English.',   'ru': 'Language set to English.'},
    'lang_switched_ru':    {'en': 'Язык изменён на русский.',   'ru': 'Язык изменён на русский.'},
}

# Pre-computed label sets for fast matching in dispatch_message
ADD_EXPENSE_LABELS = {STRINGS['btn_add_expense']['en'], STRINGS['btn_add_expense']['ru']}
MY_EXPENSES_LABELS = {STRINGS['btn_my_expenses']['en'], STRINGS['btn_my_expenses']['ru']}
LANG_TOGGLE_LABELS = {STRINGS['btn_lang_toggle']['en'], STRINGS['btn_lang_toggle']['ru']}


def t(key, chat_id):
    """Return the localised string for key based on chat_id's language preference."""
    user = registered_users.get(chat_id)
    lang = user.get('language', 'en') if user else 'en'
    entry = STRINGS.get(key, {})
    return entry.get(lang) or entry.get('en', f'[{key}]')
