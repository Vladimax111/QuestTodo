import sys
import sqlite3
from datetime import date, timedelta, datetime
import os

from PySide6.QtCore import QEvent, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem,
    QCheckBox, QPushButton, QTabWidget,
    QLabel, QHeaderView, QLineEdit,
    QDialog, QDialogButtonBox, QMessageBox,
    QGroupBox, QListWidget, QListWidgetItem,
    QAbstractItemView, QProgressBar
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor


APP_NAME = "QuestTodo"

def get_user_data_dir() -> str:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_NAME)
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", APP_NAME)
    return os.path.join(os.path.expanduser("~"), ".local", "share", APP_NAME)

DATA_DIR = get_user_data_dir()
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "questodo.db")
DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


# ---------- helpers ----------
def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())

def week_label(ws: date) -> str:
    we = ws + timedelta(days=6)
    return f"{ws.strftime('%d.%m.%Y')} — {we.strftime('%d.%m.%Y')}"

def mask_has_day(mask: int, day_idx_0_mon: int) -> bool:
    return ((mask >> day_idx_0_mon) & 1) == 1

def set_mask_day(mask: int, day_idx_0_mon: int, value: bool) -> int:
    bit = 1 << day_idx_0_mon
    return (mask | bit) if value else (mask & ~bit)

def full_week_mask() -> int:
    return (1 << 7) - 1  # 127

def daterange(d1: date, d2: date):
    d = d1
    while d <= d2:
        yield d
        d += timedelta(days=1)


# ---------- DB ----------
def ensure_db_ok_or_rebuild():
    if not os.path.exists(DB_PATH):
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("PRAGMA integrity_check;").fetchone()
        conn.close()
        if row and row[0] == "ok":
            return
    except Exception:
        pass

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bad_path = os.path.join(DATA_DIR, f"questodo_CORRUPTED_{ts}.db")
    try:
        os.rename(DB_PATH, bad_path)
    except Exception:
        try:
            os.remove(DB_PATH)
        except Exception:
            pass

def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn

def db_init():
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        mandatory INTEGER NOT NULL DEFAULT 0 CHECK(mandatory IN (0,1)),
        days_mask INTEGER NOT NULL DEFAULT 127,
        sort_order INTEGER NOT NULL DEFAULT 0
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS completions (
        activity_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        done INTEGER NOT NULL CHECK(done IN (0,1)),
        PRIMARY KEY (activity_id, day),
        FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE
    );
    """)

    cols = [r[1] for r in cur.execute("PRAGMA table_info(activities);").fetchall()]
    if "mandatory" not in cols:
        cur.execute("ALTER TABLE activities ADD COLUMN mandatory INTEGER NOT NULL DEFAULT 0 CHECK(mandatory IN (0,1));")
    if "days_mask" not in cols:
        cur.execute("ALTER TABLE activities ADD COLUMN days_mask INTEGER NOT NULL DEFAULT 127;")
    if "sort_order" not in cols:
        cur.execute("ALTER TABLE activities ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0;")
        cur.execute("UPDATE activities SET sort_order = id WHERE sort_order = 0;")

    conn.commit()
    conn.close()

def db_list_activities():
    conn = db_connect()
    rows = conn.execute(
        "SELECT id, name, mandatory, days_mask FROM activities ORDER BY sort_order ASC, name COLLATE NOCASE"
    ).fetchall()
    conn.close()
    return rows

def db_count_activities() -> int:
    conn = db_connect()
    n = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    conn.close()
    return int(n)

def db_any_mandatory_exists() -> bool:
    conn = db_connect()
    row = conn.execute("SELECT 1 FROM activities WHERE mandatory=1 LIMIT 1").fetchone()
    conn.close()
    return row is not None

def db_add_activity(name: str) -> tuple[bool, str]:
    name = (name or "").strip()
    if not name:
        return False, "empty"

    conn = db_connect()
    try:
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) FROM activities;").fetchone()[0]
        conn.execute(
            "INSERT INTO activities(name, mandatory, days_mask, sort_order) VALUES(?, 0, ?, ?)",
            (name, full_week_mask(), int(max_order) + 1)
        )
        conn.commit()
        return True, ""
    except sqlite3.IntegrityError:
        return False, "exists"
    finally:
        conn.close()

def db_rename_activity(activity_id: int, new_name: str) -> tuple[bool, str]:
    new_name = (new_name or "").strip()
    if not new_name:
        return False, "empty"
    conn = db_connect()
    try:
        conn.execute("UPDATE activities SET name=? WHERE id=?", (new_name, int(activity_id)))
        conn.commit()
        return True, ""
    except sqlite3.IntegrityError:
        return False, "exists"
    finally:
        conn.close()

def db_set_sort_orders(ordered_ids: list[int]):
    conn = db_connect()
    try:
        for i, aid in enumerate(ordered_ids, start=1):
            conn.execute("UPDATE activities SET sort_order=? WHERE id=?", (i, int(aid)))
        conn.commit()
    finally:
        conn.close()

def db_delete_activity(activity_id: int):
    conn = db_connect()
    conn.execute("DELETE FROM activities WHERE id=?", (activity_id,))
    conn.commit()
    conn.close()

def db_clear_all():
    conn = db_connect()
    conn.execute("DELETE FROM completions;")
    conn.execute("DELETE FROM activities;")
    conn.commit()
    conn.close()

def db_update_activity(activity_id: int, *, mandatory=None, days_mask=None):
    sets, vals = [], []
    if mandatory is not None:
        sets.append("mandatory=?")
        vals.append(int(mandatory))
    if days_mask is not None:
        sets.append("days_mask=?")
        vals.append(int(days_mask))
    if not sets:
        return
    vals.append(int(activity_id))

    conn = db_connect()
    conn.execute(f"UPDATE activities SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()

def db_get_done(activity_id: int, day_iso: str) -> int:
    conn = db_connect()
    row = conn.execute(
        "SELECT done FROM completions WHERE activity_id=? AND day=?",
        (activity_id, day_iso)
    ).fetchone()
    conn.close()
    return int(row[0]) if row else 0

def db_set_done(activity_id: int, day_iso: str, done: int):
    conn = db_connect()
    conn.execute("""
    INSERT INTO completions(activity_id, day, done)
    VALUES(?, ?, ?)
    ON CONFLICT(activity_id, day) DO UPDATE SET done=excluded.done
    """, (int(activity_id), day_iso, int(done)))
    conn.commit()
    conn.close()

def db_bulk_done_map(start_iso: str, end_iso: str) -> dict[tuple[int, str], int]:
    conn = db_connect()
    rows = conn.execute("""
        SELECT activity_id, day, done
        FROM completions
        WHERE day >= ? AND day <= ?
    """, (start_iso, end_iso)).fetchall()
    conn.close()
    return {(int(a), str(d)): int(done) for a, d, done in rows}


# ---------- streak ----------
def day_is_success_for_streak(day_: date) -> bool:
    activities = db_list_activities()
    day_idx = day_.weekday()
    required = []
    for a_id, _, mandatory, days_mask in activities:
        if int(mandatory) == 1 and mask_has_day(int(days_mask), day_idx):
            required.append(int(a_id))

    if not required:
        return True

    iso = day_.isoformat()
    return all(db_get_done(a_id, iso) == 1 for a_id in required)

def calc_streak_upto(today: date, allowed_misses_per_week: int = 1) -> int:
    if not db_any_mandatory_exists():
        return 0

    streak = 0
    d = today
    current_week = monday(d)
    misses = 0

    while True:
        w = monday(d)
        if w != current_week:
            current_week = w
            misses = 0

        ok = day_is_success_for_streak(d)
        if ok:
            streak += 1
        else:
            misses += 1
            if misses > allowed_misses_per_week:
                break
            streak += 1

        d -= timedelta(days=1)
        if streak > 3650:
            break

    return streak


# ---------- Theme ----------
LIGHT_QSS = """
QWidget { color: #0F172A; font-size: 14px; }
QMainWindow { background: #F4FBF6; }
QTabWidget::pane { border: 0; }
QTabBar::tab {
    background: #E7F7EC;
    padding: 10px 14px;
    margin: 4px;
    border-radius: 14px;
    color: #14532D;
    font-weight: 700;
}
QTabBar::tab:selected { background: #22C55E; color: white; }
QCheckBox { padding: 0px; }
QPushButton {
    background: #22C55E;
    color: white;
    border: 0;
    padding: 10px 14px;
    border-radius: 18px;
    font-weight: 800;
}
QPushButton:hover { background: #16A34A; }
QPushButton:pressed { background: #15803D; }

QCheckBox { padding: 0px; }

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid #86EFAC;     /* ровная светло-зелёная рамка */
    background: #FFFFFF;
}

QCheckBox::indicator:hover {
    border: 1px solid #22C55E;
}

QCheckBox::indicator:checked {
    background: #22C55E;
    border: 1px solid #22C55E;
}

QCheckBox::indicator:disabled {
    background: #F3F4F6;
    border: 1px solid #E5E7EB;
}

QPushButton#secondary {
    background: #E7F7EC;
    color: #14532D;
    font-weight: 800;
}
QPushButton#secondary:hover { background: #D8F2E0; }

QLineEdit {
    background: white;
    color: #0F172A;
    padding: 10px 12px;
    border-radius: 16px;
    border: 1px solid rgba(0,0,0,0.08);
}

QTableWidget {
    background: white;
    color: #0F172A;
    border-radius: 18px;
    border: 1px solid rgba(0,0,0,0.08);
    gridline-color: rgba(0,0,0,0.05);
    selection-background-color: rgba(34,197,94,0.16);
}
QHeaderView::section {
    background: #E7F7EC;
    padding: 10px;
    border: 0;
    font-weight: 900;
    color: #14532D;
}
QGroupBox {
    border: 1px solid rgba(0,0,0,0.08);
    border-radius: 18px;
    margin-top: 10px;
    padding: 12px;
    background: rgba(255,255,255,0.7);
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 8px;
    font-weight: 900;
    color: #14532D;
}
QListWidget {
    background: white;
    border-radius: 18px;
    border: 1px solid rgba(0,0,0,0.08);
    padding: 6px;
}
QProgressBar {
    border: 1px solid rgba(0,0,0,0.10);
    border-radius: 10px;
    background: #F0FBF3;
    text-align: center;
    font-weight: 800;
}
QProgressBar::chunk {
    border-radius: 10px;
    background: #22C55E;
}
"""

DARK_QSS = """
QWidget { color: #E5E7EB; font-size: 14px; }
QMainWindow { background: #0B1220; }
QTabWidget::pane { border: 0; }
QTabBar::tab {
    background: #0F172A;
    padding: 10px 14px;
    margin: 4px;
    border-radius: 14px;
    color: #BBF7D0;
    font-weight: 700;
}
QTabBar::tab:selected { background: #22C55E; color: #0B1220; }
QCheckBox { padding: 0px; }
QPushButton {
    background: #22C55E;
    color: #0B1220;
    border: 0;
    padding: 10px 14px;
    border-radius: 18px;
    font-weight: 900;
}
QPushButton:hover { background: #16A34A; }
QPushButton:pressed { background: #15803D; }

QCheckBox { padding: 0px; }

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid rgba(187, 247, 208, 0.35);
    background: #0F172A;
}

QCheckBox::indicator:hover {
    border: 1px solid #22C55E;
}

QCheckBox::indicator:checked {
    background: #22C55E;
    border: 1px solid #22C55E;
}

QCheckBox::indicator:disabled {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.10);
}

QPushButton#secondary {
    background: #0F172A;
    color: #BBF7D0;
    font-weight: 800;
}
QPushButton#secondary:hover { background: #111C33; }

QLineEdit {
    background: #0F172A;
    color: #E5E7EB;
    padding: 10px 12px;
    border-radius: 16px;
    border: 1px solid rgba(255,255,255,0.10);
}

QTableWidget {
    background: #0F172A;
    color: #E5E7EB;
    border-radius: 18px;
    border: 1px solid rgba(255,255,255,0.10);
    gridline-color: rgba(255,255,255,0.08);
    selection-background-color: rgba(34,197,94,0.20);
}
QHeaderView::section {
    background: #111C33;
    padding: 10px;
    border: 0;
    font-weight: 900;
    color: #BBF7D0;
}
QGroupBox {
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 18px;
    margin-top: 10px;
    padding: 12px;
    background: rgba(15,23,42,0.7);
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 8px;
    font-weight: 900;
    color: #BBF7D0;
}
QListWidget {
    background: #0F172A;
    border-radius: 18px;
    border: 1px solid rgba(255,255,255,0.10);
    padding: 6px;
}
QProgressBar {
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 10px;
    background: #0F172A;
    text-align: center;
    font-weight: 900;
}
QProgressBar::chunk {
    border-radius: 10px;
    background: #22C55E;
}
"""

def apply_palette(app: QApplication, dark: bool):
    pal = QPalette()
    if not dark:
        pal.setColor(QPalette.Window, QColor("#F4FBF6"))
        pal.setColor(QPalette.WindowText, QColor("#0F172A"))
        pal.setColor(QPalette.Base, QColor("#FFFFFF"))
        pal.setColor(QPalette.Text, QColor("#0F172A"))
        pal.setColor(QPalette.ButtonText, QColor("#0F172A"))
    else:
        pal.setColor(QPalette.Window, QColor("#0B1220"))
        pal.setColor(QPalette.WindowText, QColor("#E5E7EB"))
        pal.setColor(QPalette.Base, QColor("#0F172A"))
        pal.setColor(QPalette.Text, QColor("#E5E7EB"))
        pal.setColor(QPalette.ButtonText, QColor("#E5E7EB"))
    app.setPalette(pal)


# ---------- dialogs ----------
class TaskSettingsDialog(QDialog):
    def __init__(self, task_name: str, mandatory: int, days_mask: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Настройки: {task_name}")
        self.setModal(True)

        self.cb_mand = QCheckBox("Обязательная (влияет на серию)")
        self.cb_mand.setChecked(bool(int(mandatory)))

        lay = QVBoxLayout(self)
        lay.addWidget(self.cb_mand)

        box = QGroupBox("План по дням недели")
        b_lay = QVBoxLayout(box)

        self.day_checks = []
        row = QHBoxLayout()
        for i, d in enumerate(DAYS):
            ch = QCheckBox(d)
            ch.setChecked(mask_has_day(int(days_mask), i))
            self.day_checks.append(ch)
            row.addWidget(ch)
        row.addStretch()
        b_lay.addLayout(row)

        self.btn_full = QPushButton("На всю неделю")
        self.btn_full.setObjectName("secondary")
        self.btn_full.clicked.connect(self.set_full_week)
        b_lay.addWidget(self.btn_full)

        lay.addWidget(box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Сохранить")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def set_full_week(self):
        for ch in self.day_checks:
            ch.setChecked(True)

    def result_values(self):
        mand = 1 if self.cb_mand.isChecked() else 0
        m = 0
        for i, ch in enumerate(self.day_checks):
            m = set_mask_day(m, i, ch.isChecked())
        return mand, m


# ---------- reorderable list ----------
class ActivitiesList(QListWidget):
    def __init__(self, on_reorder, parent=None):
        super().__init__(parent)
        self.on_reorder = on_reorder
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragDropMode(QAbstractItemView.InternalMove)

    def dropEvent(self, event):
        super().dropEvent(event)
        ids = []
        for i in range(self.count()):
            it = self.item(i)
            ids.append(int(it.data(Qt.UserRole)))
        self.on_reorder(ids)


# ---------- UI tabs ----------
class   WeekTab(QWidget):
    def __init__(self, on_db_changed):
        super().__init__()
        self.on_db_changed = on_db_changed
        self.week_start = monday(date.today())
        self._activity_rows: dict[int, int] = {}
        self.selected_day_idx = None

        root = QHBoxLayout(self)
        root.setSpacing(12)



        # ---- LEFT ----
        left = QVBoxLayout()
        left.setSpacing(10)

        box = QGroupBox("Активности")
        box_lay = QVBoxLayout(box)

        self.input_name = QLineEdit()
        self.input_name.setPlaceholderText("Новая активность (например: Спорт)")
        self.btn_add = QPushButton("➕ Добавить")
        self.btn_add.clicked.connect(self.add_activity_inline)

        add_row = QHBoxLayout()
        add_row.addWidget(self.input_name, 1)
        add_row.addWidget(self.btn_add)
        box_lay.addLayout(add_row)

        self.search = QLineEdit()
        self.search.setPlaceholderText("🔎 Поиск активности...")
        self.search.textChanged.connect(self.apply_filter)
        box_lay.addWidget(self.search)

        self.list_acts = ActivitiesList(on_reorder=self.save_reorder)
        self.list_acts.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_acts.itemSelectionChanged.connect(self.on_activity_selected)
        self.list_acts.setEditTriggers(
            QAbstractItemView.DoubleClicked |
            QAbstractItemView.EditKeyPressed |
            QAbstractItemView.SelectedClicked
        )
        self.list_acts.itemChanged.connect(self.on_item_renamed)
        box_lay.addWidget(self.list_acts, 1)

        btns = QHBoxLayout()
        self.btn_settings = QPushButton("⚙️")
        self.btn_settings.setObjectName("secondary")
        self.btn_settings.clicked.connect(self.open_settings)

        self.btn_del = QPushButton("🗑")
        self.btn_del.setObjectName("secondary")
        self.btn_del.clicked.connect(self.delete_selected)

        btns.addWidget(self.btn_settings)
        btns.addWidget(self.btn_del)
        box_lay.addLayout(btns)

        self.btn_reset = QPushButton("⛔ Сбросить всё")
        self.btn_reset.setObjectName("secondary")
        self.btn_reset.clicked.connect(self.reset_all)
        box_lay.addWidget(self.btn_reset)

        left.addWidget(box, 1)

        info = QGroupBox("Инфо")
        info_lay = QVBoxLayout(info)
        self.week_title = QLabel()
        self.week_title.setStyleSheet("font-size: 16px; font-weight: 900;")
        self.streak_label = QLabel("")
        self.streak_label.setStyleSheet("font-weight: 900;")
        self.count_label = QLabel("")
        self.db_path_label = QLabel(f"DB: {DB_PATH}")
        self.db_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.db_path_label.setStyleSheet("opacity: 0.8; font-size: 12px;")

        nav = QHBoxLayout()
        self.btn_prev = QPushButton("←")
        self.btn_prev.setObjectName("secondary")
        self.btn_next = QPushButton("→")
        self.btn_next.setObjectName("secondary")
        self.btn_prev.clicked.connect(self.prev_week)
        self.btn_next.clicked.connect(self.next_week)
        nav.addWidget(self.btn_prev)
        nav.addWidget(self.btn_next)
        nav.addStretch()

        info_lay.addLayout(nav)
        info_lay.addWidget(self.week_title)
        info_lay.addWidget(self.count_label)
        info_lay.addWidget(self.streak_label)
        info_lay.addWidget(self.db_path_label)
        left.addWidget(info)

        left_wrap = QWidget()
        left_wrap.setLayout(left)
        left_wrap.setMaximumWidth(420)
        left_wrap.setMinimumWidth(360)

        # ---- RIGHT ----
        right = QVBoxLayout()
        right.setSpacing(10)

        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setFormat("Прогресс недели: %p%")
        self.progress.setMaximumHeight(18)
        right.addWidget(self.progress)

        daybar = QHBoxLayout()
        self.day_hint = QLabel("Выбери день в таблице (клик по заголовку).")
        self.day_hint.setStyleSheet("opacity: 0.8;")
        self.btn_mark_day = QPushButton("✓ Отметить день")
        self.btn_mark_day.setObjectName("secondary")
        self.btn_unmark_day = QPushButton("✕ Снять день")
        self.btn_unmark_day.setObjectName("secondary")

        self.btn_mark_day.clicked.connect(lambda: self.bulk_set_day(True))
        self.btn_unmark_day.clicked.connect(lambda: self.bulk_set_day(False))
        self.btn_mark_day.setEnabled(False)
        self.btn_unmark_day.setEnabled(False)

        daybar.addWidget(self.day_hint, 1)
        daybar.addWidget(self.btn_mark_day)
        daybar.addWidget(self.btn_unmark_day)
        right.addLayout(daybar)

        self.table = QTableWidget()
        self.table.setMouseTracking(True)
        self.table.viewport().setMouseTracking(True)
        self.table.viewport().installEventFilter(self)
        self._hover_cell = (-1, -1)
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(["Активность"] + DAYS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)
        self.table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)
        self.table.cellClicked.connect(self.on_cell_clicked)

        right.addWidget(self.table, 1)

        root.addWidget(left_wrap)
        right_wrap = QWidget()
        right_wrap.setLayout(right)
        root.addWidget(right_wrap, 1)

        self.load_data()
        self._undo_stack = []  # (activity_id, day_iso, prev_value)

    def toggle_current_cell(self):
        r = self.table.currentRow()
        c = self.table.currentColumn()
        if r < 0 or c < 1:
            return
        self.on_cell_clicked(r, c)

    def undo_last_action(self):
        if not self._undo_stack:
            return
        aid, day_iso, prev = self._undo_stack.pop()
        db_set_done(aid, day_iso, prev)

        self.load_data()
        self.on_db_changed()

    def on_done_toggled(self, activity_id: int, day_iso: str, checked: bool, row: int, col: int):
        db_set_done(activity_id, day_iso, 1 if checked else 0)
        self.refresh_streak()
        self.update_week_progress()
        self.on_db_changed()
        self.animate_cell_pulse(row, col)


    def prev_week(self):
        self.week_start -= timedelta(days=7)
        self.load_data()

    def next_week(self):
        self.week_start += timedelta(days=7)
        self.load_data()

    def refresh_streak(self):
        s = calc_streak_upto(date.today(), allowed_misses_per_week=1)
        if not db_any_mandatory_exists():
            self.streak_label.setText("🔥 Серия: — (нет обязательных)")
        else:
            self.streak_label.setText(f"🔥 Серия: {s} дн.")

    def apply_filter(self):
        q = (self.search.text() or "").strip().lower()
        for i in range(self.list_acts.count()):
            it = self.list_acts.item(i)
            name = it.text().replace("⭐ ", "").lower()
            it.setHidden(bool(q) and q not in name)

    def save_reorder(self, ordered_ids: list[int]):
        db_set_sort_orders(ordered_ids)
        self.load_data()
        self.on_db_changed()

    def on_item_renamed(self, item: QListWidgetItem):
        aid = int(item.data(Qt.UserRole))
        new_text = item.text().replace("⭐ ", "").strip()
        old_name = str(item.data(Qt.UserRole + 10) or "").strip()

        if not old_name:
            item.setData(Qt.UserRole + 10, new_text)
            return
        if new_text == old_name:
            return

        ok, reason = db_rename_activity(aid, new_text)
        if not ok:
            if reason == "exists":
                QMessageBox.information(self, "Имя занято", "Такая активность уже существует.")
            elif reason == "empty":
                QMessageBox.information(self, "Пустое имя", "Название не может быть пустым.")
            self.list_acts.blockSignals(True)
            mand = int(item.data(Qt.UserRole + 1))
            item.setText(f"⭐ {old_name}" if mand == 1 else old_name)
            self.list_acts.blockSignals(False)
            return

        item.setData(Qt.UserRole + 10, new_text)
        self.load_data()
        self.on_db_changed()

    def on_header_clicked(self, section: int):
        if section <= 0:
            self.selected_day_idx = None
            self.day_hint.setText("Выбери день в таблице (клик по заголовку).")
        else:
            self.selected_day_idx = section - 1
            self.day_hint.setText(f"Выбран день: {DAYS[self.selected_day_idx]}")
        self.btn_mark_day.setEnabled(self.selected_day_idx is not None)
        self.btn_unmark_day.setEnabled(self.selected_day_idx is not None)
        self.load_data()

    def bulk_set_day(self, value: bool):
        if self.selected_day_idx is None:
            QMessageBox.information(self, "День не выбран", "Кликни по заголовку дня (Пн..Вс) в таблице.")
            return

        activities = db_list_activities()
        day = self.week_start + timedelta(days=self.selected_day_idx)
        day_iso = day.isoformat()

        for a_id, _, _, days_mask in activities:
            planned = mask_has_day(int(days_mask), self.selected_day_idx)
            if planned:
                db_set_done(int(a_id), day_iso, 1 if value else 0)

        self.load_data()
        self.on_db_changed()

    def load_activities_list(self, activities):
        self.list_acts.blockSignals(True)
        self.list_acts.clear()
        for a_id, name, mandatory, days_mask in activities:
            label = f"⭐ {name}" if int(mandatory) == 1 else name
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, int(a_id))
            it.setData(Qt.UserRole + 1, int(mandatory))
            it.setData(Qt.UserRole + 2, int(days_mask))
            it.setData(Qt.UserRole + 10, name)
            it.setFlags(it.flags() | Qt.ItemIsEditable)
            self.list_acts.addItem(it)
        self.list_acts.blockSignals(False)
        self.apply_filter()

    def update_week_progress(self):
        activities = db_list_activities()
        start_iso = self.week_start.isoformat()
        end_iso = (self.week_start + timedelta(days=6)).isoformat()
        done_map = db_bulk_done_map(start_iso, end_iso)

        planned_total = 0
        done_total = 0
        for a_id, _, _, days_mask in activities:
            for i in range(7):
                if mask_has_day(int(days_mask), i):
                    planned_total += 1
                    d_iso = (self.week_start + timedelta(days=i)).isoformat()
                    if done_map.get((int(a_id), d_iso), 0) == 1:
                        done_total += 1

        if planned_total <= 0:
            self.progress.setValue(0)
            self.progress.setFormat("Прогресс недели: —")
            return

        pct = int(round((done_total / planned_total) * 100))
        self.progress.setValue(pct)
        self.progress.setFormat(f"Прогресс недели: {pct}%  ({done_total}/{planned_total})")

    def load_data(self):
        self.week_title.setText(f"Неделя: {week_label(self.week_start)}")
        self.count_label.setText(f"Активностей: {db_count_activities()}")

        activities = db_list_activities()
        self.load_activities_list(activities)

        start_iso = self.week_start.isoformat()
        end_iso = (self.week_start + timedelta(days=6)).isoformat()
        done_map = db_bulk_done_map(start_iso, end_iso)

        today = date.today()
        today_idx = None
        if self.week_start <= today <= (self.week_start + timedelta(days=6)):
            today_idx = (today - self.week_start).days

        self.table.setHorizontalHeaderItem(0, QTableWidgetItem("Активность"))
        for i, dn in enumerate(DAYS, start=1):
            hi = QTableWidgetItem(dn)
            hi.setTextAlignment(Qt.AlignCenter)
            if today_idx is not None and (i - 1) == today_idx:
                hi.setBackground(QColor(34, 197, 94, 40))
            if self.selected_day_idx is not None and (i - 1) == self.selected_day_idx:
                hi.setBackground(QColor(34, 197, 94, 70))
            self.table.setHorizontalHeaderItem(i, hi)

        self._activity_rows.clear()
        self.table.setRowCount(len(activities))

        for row, (a_id, name, mandatory, days_mask) in enumerate(activities):
            self._activity_rows[int(a_id)] = row

            item = QTableWidgetItem(name)
            item.setData(Qt.UserRole, int(a_id))
            item.setData(Qt.UserRole + 1, int(mandatory))
            item.setData(Qt.UserRole + 2, int(days_mask))
            item.setFlags(item.flags() ^ Qt.ItemIsEditable)
            if int(mandatory) == 1:
                item.setText(f"⭐ {name}")
            self.table.setItem(row, 0, item)

            for i in range(7):
                day = self.week_start + timedelta(days=i)
                day_iso = day.isoformat()
                planned = mask_has_day(int(days_mask), i)

                # --- фон ячейки (нужен для hover/сегодня/выбранный день) ---
                bg_item = QTableWidgetItem("")
                bg_item.setFlags(Qt.ItemIsEnabled)
                if today_idx is not None and i == today_idx:
                    bg_item.setBackground(QColor(34, 197, 94, 18))
                if self.selected_day_idx is not None and i == self.selected_day_idx:
                    bg_item.setBackground(QColor(34, 197, 94, 30))
                self.table.setItem(row, i + 1, bg_item)

                # --- чекбокс ---
                cb = QCheckBox()
                cb.setCursor(Qt.PointingHandCursor)
                cb.setEnabled(planned)
                cb.setChecked(done_map.get((int(a_id), day_iso), 0) == 1)

                cb.toggled.connect(
                    lambda checked, aid=int(a_id), d=day_iso, r=row, c=i + 1:
                    self.on_done_toggled(aid, d, checked, r, c)
                )

                cell = QWidget()
                cell_lay = QHBoxLayout(cell)
                cell_lay.setContentsMargins(0, 0, 0, 0)
                cell_lay.setAlignment(Qt.AlignCenter)
                cell_lay.addWidget(cb)

                self.table.setCellWidget(row, i + 1, cell)

        self.refresh_streak()
        self.update_week_progress()

    def on_cell_clicked(self, row: int, col: int):
        # колонка 0 — название активности
        if col <= 0:
            return

        cell = self.table.cellWidget(row, col)
        if not cell:
            return

        cb = cell.findChild(QCheckBox)
        if not cb or not cb.isEnabled():
            return

        # если кликнули прямо по чекбоксу — он сам переключится
        if cb.underMouse():
            return

        cb.setChecked(not cb.isChecked())

    def eventFilter(self, obj, event):
        if obj is self.table.viewport():
            if event.type() == QEvent.MouseMove:
                idx = self.table.indexAt(event.pos())
                r, c = idx.row(), idx.column()
                if (r, c) != self._hover_cell:
                    old = self._hover_cell
                    self._hover_cell = (r, c)
                    self._update_hover_cell(old)
                    self._update_hover_cell(self._hover_cell)
            elif event.type() == QEvent.Leave:
                old = self._hover_cell
                self._hover_cell = (-1, -1)
                self._update_hover_cell(old)
        return super().eventFilter(obj, event)

    def _update_hover_cell(self, cell):
        r, c = cell
        if r < 0 or c < 1:
            return
        item = self.table.item(r, c)
        if not item:
            return

        # не подсвечиваем если день не запланирован (чекбокс disabled)
        w = self.table.cellWidget(r, c)
        cb = w.findChild(QCheckBox) if w else None
        if not cb or not cb.isEnabled():
            return

        if (r, c) == self._hover_cell:
            item.setBackground(QColor(34, 197, 94, 28))
        else:
            item.setBackground(self._base_cell_bg(c - 1))

    def _base_cell_bg(self, day_idx: int) -> QColor:
        # day_idx: 0..6
        today = date.today()
        col = day_idx + 1

        base = QColor(0, 0, 0, 0)


        if self.week_start <= today <= (self.week_start + timedelta(days=6)):
            today_idx = (today - self.week_start).days
            if day_idx == today_idx:
                base = QColor(34, 197, 94, 18)


        if self.selected_day_idx is not None and day_idx == self.selected_day_idx:
            base = QColor(34, 197, 94, 30)

        return base

    def animate_cell_pulse(self, row: int, col: int):

        if col < 1:
            return
        item = self.table.item(row, col)
        if not item:
            return

        start = QColor(34, 197, 94, 70)
        end = self._base_cell_bg(col - 1)

        anim = QPropertyAnimation(self.table, b"dummy")  # фиктивная привязка
        anim.setDuration(180)


        if not hasattr(self, "_anims"):
            self._anims = []
        self._anims.append(anim)

        def step(value):
            # value 0..1
            a = float(value)
            r = int(start.red() * (1 - a) + end.red() * a)
            g = int(start.green() * (1 - a) + end.green() * a)
            b = int(start.blue() * (1 - a) + end.blue() * a)
            al = int(start.alpha() * (1 - a) + end.alpha() * a)
            item.setBackground(QColor(r, g, b, al))

        anim.valueChanged.connect(step)

        def finished():
            item.setBackground(end)
            try:
                self._anims.remove(anim)
            except Exception:
                pass

        anim.finished.connect(finished)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(260)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        start = QColor(34, 197, 94, 120)
        anim.start()

    def selected_task_from_list(self):
        items = self.list_acts.selectedItems()
        if not items:
            return None
        it = items[0]
        return {
            "id": int(it.data(Qt.UserRole)),
            "name": it.text().replace("⭐ ", ""),
            "mandatory": int(it.data(Qt.UserRole + 1)),
            "days_mask": int(it.data(Qt.UserRole + 2)),
        }

    def on_activity_selected(self):
        t = self.selected_task_from_list()
        if not t:
            return
        row = self._activity_rows.get(t["id"])
        if row is None:
            return
        self.table.setCurrentCell(row, 0)

    def add_activity_inline(self):
        name = (self.input_name.text() or "").strip()
        if not name:
            return
        ok, reason = db_add_activity(name)
        if not ok and reason == "exists":
            QMessageBox.information(self, "Уже существует", "Такая активность уже есть.")
        self.input_name.setText("")
        self.load_data()
        self.on_db_changed()

    def delete_selected(self):
        t = self.selected_task_from_list()
        if not t:
            QMessageBox.information(self, "Выбор", "Выбери активность слева.")
            return
        if QMessageBox.question(self, "Удалить?", f"Удалить активность: «{t['name']}» ?") == QMessageBox.Yes:
            db_delete_activity(t["id"])
            self.load_data()
            self.on_db_changed()

    def reset_all(self):
        if QMessageBox.question(self, "Сбросить всё?", "Удалить ВСЕ активности и отметки?") == QMessageBox.Yes:
            db_clear_all()
            self.load_data()
            self.on_db_changed()

    def open_settings(self):
        t = self.selected_task_from_list()
        if not t:
            QMessageBox.information(self, "Выбор", "Выбери активность слева, затем нажми ⚙️.")
            return

        dlg = TaskSettingsDialog(t["name"], t["mandatory"], t["days_mask"], self)
        if dlg.exec() == QDialog.Accepted:
            mand, mask = dlg.result_values()
            db_update_activity(t["id"], mandatory=mand, days_mask=mask)
            self.load_data()
            self.on_db_changed()


class StatsTab(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setSpacing(10)

        top = QHBoxLayout()
        title = QLabel("📊 Статистика")
        title.setStyleSheet("font-size: 18px; font-weight: 900;")
        self.strong_day = QLabel("")
        self.strong_day.setStyleSheet("font-weight: 900; opacity: 0.9;")

        self.btn_refresh = QPushButton("↻ Обновить")
        self.btn_refresh.setObjectName("secondary")
        self.btn_refresh.clicked.connect(self.load_data)

        top.addWidget(title)
        top.addWidget(self.strong_day)
        top.addStretch()
        top.addWidget(self.btn_refresh)
        root.addLayout(top)

        self.table_acts = QTableWidget()
        self.table_acts.setColumnCount(7)
        self.table_acts.setHorizontalHeaderLabels([
            "Активность", "План 7д", "Сделано 7д", "% 7д",
            "План 30д", "Сделано 30д", "% 30д",
        ])
        self.table_acts.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_acts.verticalHeader().setVisible(False)
        self.table_acts.setEditTriggers(QAbstractItemView.NoEditTriggers)

        self.table_days = QTableWidget()
        self.table_days.setColumnCount(3)
        self.table_days.setHorizontalHeaderLabels(["День", "Сделано (30д)", "Доля"])
        self.table_days.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_days.verticalHeader().setVisible(False)
        self.table_days.setEditTriggers(QAbstractItemView.NoEditTriggers)

        root.addWidget(self.table_acts, 2)
        root.addWidget(self.table_days, 1)

        hint = QLabel("Подсчёт идёт по плану активности (учитываются выбранные дни недели).")
        hint.setStyleSheet("opacity: 0.75;")
        root.addWidget(hint)

        self.load_data()

    def _calc_range_stats(self, start_d: date, end_d: date):
        activities = db_list_activities()
        done_map = db_bulk_done_map(start_d.isoformat(), end_d.isoformat())

        per_act = []
        day_done = [0] * 7

        for a_id, name, mandatory, days_mask in activities:
            planned = 0
            done = 0
            for d in daterange(start_d, end_d):
                idx = d.weekday()
                if mask_has_day(int(days_mask), idx):
                    planned += 1
                    if done_map.get((int(a_id), d.isoformat()), 0) == 1:
                        done += 1
                        day_done[idx] += 1
            per_act.append((name, planned, done))
        return per_act, day_done

    def load_data(self):
        today = date.today()
        start7 = today - timedelta(days=6)
        start30 = today - timedelta(days=29)

        acts7, _ = self._calc_range_stats(start7, today)
        acts30, day_done30 = self._calc_range_stats(start30, today)

        if any(day_done30):
            mx = max(day_done30)
            idx = day_done30.index(mx)
            self.strong_day.setText(f"🏆 Самый сильный день: {DAYS[idx]} ({mx})")
        else:
            self.strong_day.setText("🏆 Самый сильный день: —")

        m7 = {n: (p, d) for n, p, d in acts7}
        m30 = {n: (p, d) for n, p, d in acts30}
        names = sorted(set(m30.keys()) | set(m7.keys()), key=lambda s: s.lower())

        self.table_acts.setRowCount(len(names))
        for r, n in enumerate(names):
            p7, d7 = m7.get(n, (0, 0))
            p30, d30 = m30.get(n, (0, 0))
            pct7 = int(round((d7 / p7) * 100)) if p7 else 0
            pct30 = int(round((d30 / p30) * 100)) if p30 else 0

            self.table_acts.setItem(r, 0, QTableWidgetItem(n))
            self.table_acts.setItem(r, 1, QTableWidgetItem(str(p7)))
            self.table_acts.setItem(r, 2, QTableWidgetItem(str(d7)))
            self.table_acts.setItem(r, 3, QTableWidgetItem(f"{pct7}%"))
            self.table_acts.setItem(r, 4, QTableWidgetItem(str(p30)))
            self.table_acts.setItem(r, 5, QTableWidgetItem(str(d30)))
            self.table_acts.setItem(r, 6, QTableWidgetItem(f"{pct30}%"))

        total_done = sum(day_done30)
        self.table_days.setRowCount(7)
        for i, dn in enumerate(DAYS):
            done = day_done30[i]
            share = int(round((done / total_done) * 100)) if total_done else 0
            self.table_days.setItem(i, 0, QTableWidgetItem(dn))
            self.table_days.setItem(i, 1, QTableWidgetItem(str(done)))
            self.table_days.setItem(i, 2, QTableWidgetItem(f"{share}%"))

        if any(day_done30):
            mx = max(day_done30)
            for i in range(7):
                if day_done30[i] == mx and mx > 0:
                    for c in range(3):
                        item = self.table_days.item(i, c)
                        if item:
                            item.setBackground(QColor(34, 197, 94, 25))


# ---------- main ----------
class MainWindow(QMainWindow):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.dark = False

        self.setWindowTitle("Quests ToDo")
        self.resize(1300, 760)

        tabs = QTabWidget()
        self.stats_tab = StatsTab()
        self.week_tab = WeekTab(on_db_changed=self.stats_tab.load_data)

        tabs.addTab(self.week_tab, "Главная")
        tabs.addTab(self.stats_tab, "Статистика")

        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        topbar = QHBoxLayout()
        self.theme_btn = QPushButton("🌙 Тёмная тема")
        self.theme_btn.setObjectName("secondary")
        self.theme_btn.clicked.connect(self.toggle_theme)
        topbar.addStretch()
        topbar.addWidget(self.theme_btn)

        root.addLayout(topbar)
        root.addWidget(tabs, 1)

        self.setCentralWidget(container)
        self.apply_theme()

    def apply_theme(self):
        apply_palette(self.app, self.dark)
        if self.dark:
            self.app.setStyleSheet(DARK_QSS)
            self.theme_btn.setText("☀️ Светлая тема")
        else:
            self.app.setStyleSheet(LIGHT_QSS)
            self.theme_btn.setText("🌙 Тёмная тема")

    def toggle_theme(self):
        self.dark = not self.dark
        self.apply_theme()


if __name__ == "__main__":
    ensure_db_ok_or_rebuild()
    db_init()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow(app)
    win.show()
    sys.exit(app.exec())
