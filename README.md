# QuestTodo
QuestTodo — минималистичный трекер привычек на неделю (PySide6 + SQLite): отмечай активности по дням, смотри прогресс недели, серию и статистику за 7/30 дней.




##  Возможности
-  Таблица недели (Пн–Вс) с чекбоксами
-  Поиск активностей
-  Drag & Drop сортировка активностей
-  “Обязательные” активности (влияют на серию)
-  Прогресс недели + статистика 7/30 дней
-  Светлая/тёмная тема
-  Автовосстановление базы при повреждении (backup)

##  Установка и запуск
### 1) Через venv
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
python src/questtodo/app.py
