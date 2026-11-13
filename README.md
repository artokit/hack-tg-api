# Telegram-агент БАРС

Текстовый агент Pydantic AI Harness принимает вопросы из личных чатов Telegram.
FastAPI хранит по одному активному снимку диалога на пользователя в PostgreSQL.
После компакции снимок содержит резюме и свежие реплики. Команда `/reset` удаляет
снимок пользователя.

## Локальный запуск

Заполните корневой `.env` по образцу `.env.example`. Сгенерируйте случайное значение
`AGENT_API_TOKEN`, задайте токен Telegram в `BOT_TOKEN` и параметры модели.
`CHAT_BASE_URL` должен указывать на базовый URL OpenAI-совместимого API,
например `https://provider.example/v1`. В `CHAT_CONTEXT_WINDOW` укажите размер окна
модели в токенах. Для провайдера без авторизации оставьте `CHAT_API_KEY` пустым.

Из корня проекта:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r api/requirements.txt -r telegram-bot/requirements.txt
docker compose -p bars-hackathon up -d --wait postgres
.venv/Scripts/python.exe -m alembic -c api/alembic.ini upgrade head
```

В первом терминале, из каталога `api/`:

```powershell
../.venv/Scripts/python.exe -m uvicorn main:app
```

Во втором терминале, из каталога `telegram-bot/`:

```powershell
../.venv/Scripts/python.exe main.py
```

Проверка в Telegram: сообщите агенту факт, задайте уточняющий вопрос, перезапустите
FastAPI и попросите вспомнить факт. Затем отправьте `/reset` и задайте тот же вопрос.

## Тесты

Установите `pytest` и `httpx` и из каталога `api/` запустите
`../.venv/Scripts/python.exe -m pytest`. Для интеграционного теста задайте
`TEST_DATABASE_URL` и заранее примените миграции к этой тестовой базе через
`DATABASE_URL`. Тесты используют выделенные тестовые ID 10001 и 10002.
