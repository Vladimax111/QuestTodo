# QuestTodo
QuestTodo — минималистичный трекер привычек на неделю (PySide6 + SQLite): отмечай активности по дням, смотри прогресс недели, серию и статистику за 7/30 дней.


<img width="1352" height="878" alt="Снимок экрана 2026-01-15 в 01 09 40" src="https://github.com/user-attachments/assets/1adce993-f76e-485e-bfab-32c2f3efe4f3" />

<img width="1352" height="878" alt="Снимок экрана 2026-01-15 в 01 11 10" src="https://github.com/user-attachments/assets/9e98a853-17b5-4ea1-a007-76dd38df5cf1" />

<img width="1352" height="878" alt="Снимок экрана 2026-01-15 в 01 09 57" src="https://github.com/user-attachments/assets/400886b1-6b5b-4633-90ae-9c80cb61c707" />

<img width="1352" height="878" alt="Снимок экрана 2026-01-15 в 01 12 04" src="https://github.com/user-attachments/assets/f9ddbc62-ec0a-4dc7-9014-1dfd9b76feee" />


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
