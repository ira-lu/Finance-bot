import os

# ── Phase constants ───────────────────────────────────────────────────────────
PHASE_UNREGISTERED    = 'unregistered'
PHASE_AWAITING_NAME   = 'awaiting_name'
PHASE_IDLE            = 'idle'
PHASE_CAT_SELECTED    = 'category_selected'
PHASE_AWAITING_SPLIT  = 'awaiting_split'
PHASE_SELECTING_SPLIT = 'selecting_split'

# ── Shared mutable state ──────────────────────────────────────────────────────
user_states = {}       # {chat_id: {phase, category, amount, comment, split_with, pending_row}}
registered_users = {}  # {chat_id: {name, role, sheet, language}}

# ── Owner IDs ─────────────────────────────────────────────────────────────────
_raw = os.environ.get('OWNER_IDS', '')
OWNER_IDS = set(int(x.strip()) for x in _raw.split(',') if x.strip())
