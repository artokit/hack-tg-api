# Telegram-агент БАРС

Flue принимает Telegram webhook, вызывает OpenAI-совместимую модель и хранит диалоги в PostgreSQL. FastAPI обслуживает авторизацию и управление сотрудниками. Простой текст в личном чате идёт агенту. Команды `/start` и `/reset` работают без модели. `/reset` открывает новый диалог, предыдущий сохраняется в PostgreSQL.

## Запуск

1. Скопируйте `.env.example` в `.env`. Укажите токен бота в `BOT_TOKEN`, произвольный независимый `TELEGRAM_WEBHOOK_SECRET_TOKEN` и настройки модели. `CHAT_BASE_URL` — базовый URL совместимого API, например `https://provider.example/v1`. При работе без авторизации оставьте `CHAT_API_KEY` пустым.
2. Выполните `docker compose up -d --build --wait`. FastAPI применит миграции, Flue создаст таблицы агента и обработки Telegram. Новый volume называется `bars-hackathon_postgres_flue_data`. Volume прежнего Python-бота можно сохранить для отката.
3. Проверьте `http://127.0.0.1:3000/health` с хоста. FastAPI доступен внутри Compose по адресу `http://api:8000`. Для второго экземпляра используйте другое имя проекта Compose, другие хостовые порты и отдельный тестовый токен.

## Документация API

Swagger UI доступен на `http://127.0.0.1:8000/docs`, схема OpenAPI — на `http://127.0.0.1:8000/openapi.json`. В Swagger можно посмотреть и вызвать ручки входа, сотрудников, приглашений и проверки состояния API. Порт API в Docker Compose можно изменить через `API_PORT` в `.env`; доступ с хоста открыт только на `127.0.0.1`.

## Авторизация администратора

Задайте случайный `JWT_SECRET` длиной не менее 32 символов в `.env`. Секрет должен оставаться одинаковым между перезапусками и экземплярами API. Срок действия JWT задаётся через `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` и по умолчанию составляет 60 минут.

Миграция `0004` создаёт администратора `admin@example.com` с временным паролем `admin`. Миграция `0005` удаляет старых Telegram-пользователей, тикеты и сообщения тикетов, а таблицу `admins` переименовывает в `users`, сохраняя аккаунты для входа. Удалённые данные при откате не восстанавливаются. В БД хранится только bcrypt-хеш пароля. Эти реквизиты предназначены только для разработки.

`POST /auth/login` принимает JSON с полями `email` и `password` и возвращает `access_token` и `token_type: "bearer"`. Регистрации и обновления токена нет. Для всех ручек `/employees` передавайте заголовок `Authorization: Bearer <access_token>`. Без действующего токена API возвращает `401`. В Swagger нажмите **Authorize** и вставьте полученный токен без префикса `Bearer`.

## Приглашения сотрудников

Укажите `TELEGRAM_BOT_USERNAME` без `@` и задайте независимый случайный `BOT_API_TOKEN` длиной не менее 32 символов в `.env`. API и Flue должны использовать одинаковый `BOT_API_TOKEN`. Для локального запуска Flue также задайте `API_URL`, например `http://127.0.0.1:8000`; в Docker Compose адрес уже настроен.

Все ручки `/invites` требуют JWT:

- `POST /invites` — создать приглашение и получить `link` вида `https://t.me/<bot_username>?start=invite_<id>`. Тело: `count_of_use` (по умолчанию 1), необязательные `first_name` и `last_name`. ФИ разрешено только для одноразового приглашения. Без `TELEGRAM_BOT_USERNAME` ручка возвращает `503` и не создаёт запись.
- `GET /invites?page=1&page_size=20` — список действующих приглашений, размер страницы до 100.
- `GET /invites/{id}` — получить приглашение и оставшееся число использований.
- `DELETE /invites/{id}` — отозвать приглашение, ответ `204`.

Бот обрабатывает `/start invite_<id>` и вызывает `POST /private/invites/{id}/accept` с заголовком `X-Bot-Token` и данными Telegram-пользователя: `telegram_id`, `username`, `first_name`, `last_name`. Успех — `201` с данными сотрудника. Неизвестное или использованное приглашение — `404`, уже существующий сотрудник — `409` без списания использования, неверный токен бота — `401`.

ФИ из персонального приглашения имеет приоритет над данными Telegram. После создания сотрудника число использований уменьшается; последнее использование удаляет приглашение. Создание сотрудника и списание выполняются отдельными сохранениями без общей транзакции и блокировок: при параллельных запросах или сбое между сохранениями возможна рассинхронизация.

## Публичный webhook

Для примера используем `bars-bot.cheremha.ru`. Создайте A-запись `bars-bot` на публичный IPv4 хоста с Compose. Настройте сертификат Let's Encrypt в существующем HTTPS-сервере. Пример маршрута для Nginx внутри HTTPS-блока этого поддомена.

```nginx
location = /channels/telegram/webhook {
    limit_except POST { deny all; }
    proxy_pass http://127.0.0.1:3000;
}

location / {
    return 404;
}
```

На тестовом токене проверьте доступность TLS и зарегистрируйте webhook. Следующий пример PowerShell предполагает, что `BOT_TOKEN` и `TELEGRAM_WEBHOOK_SECRET_TOKEN` уже загружены из приватной конфигурации в окружение.

```powershell
$telegramApi = "https://api.telegram.org/bot$env:BOT_TOKEN"
$body = @{
    url = "https://bars-bot.cheremha.ru/channels/telegram/webhook"
    secret_token = $env:TELEGRAM_WEBHOOK_SECRET_TOKEN
    max_connections = 1
    allowed_updates = @("message")
    drop_pending_updates = $false
} | ConvertTo-Json -Compress
Invoke-RestMethod "$telegramApi/setWebhook" -Method Post -ContentType "application/json" -Body $body
Invoke-RestMethod "$telegramApi/getWebhookInfo"
```

Напишите тестовому боту `/start`, задайте вопрос и отправьте уточнение до готового ответа. После перезапуска Flue убедитесь, что контекст сохраняется. `/reset` открывает диалог с чистым контекстом.

После проверки остановите прежний polling основного бота и зарегистрируйте webhook для его токена. Для отката остановите Flue, вызовите `deleteWebhook` с `drop_pending_updates=false` и запустите предыдущую версию с её БД. Telegram позволяет использовать один способ получения апдейтов на токен.

## База документации

Задайте `RAG_ENABLED=true`, отдельный `RAG_SERVICE_TOKEN` длиной от 32 символов и базовые URL
совместимых API в `RAG_EMBEDDING_BASE_URL` и `RAG_LUNA_BASE_URL`. Указывайте URL
без `/embeddings` или `/chat/completions`, например `https://provider.example/v1`.
Первый сервис должен обслуживать Qwen3 Embedding 8B и возвращать 4096 чисел на вход.
Второй должен обслуживать Luna с поддержкой изображений.
Для локального Qdrant используйте `docker compose --profile rag up -d --build --wait`,
для внешнего укажите `RAG_QDRANT_URL` и запустите Compose без профиля `rag`.
До добавления списка Telegram ID загружайте только материалы, разрешённые для демо.

- `POST /internal/rag/documents` принимает multipart поля `file`, `source_id`, `title` и
  необязательный `source_url`. Поддерживаются PDF, DOCX и Markdown в UTF-8. Повторная загрузка
  с тем же `source_id` создаёт новую версию. Ручка возвращает `202` и `job_id`.
  Из PDF и DOCX извлекаются встроенные изображения, из Markdown — встроенные изображения
  в формате data URI. Обычные ссылки на изображения остаются частью текста.
- `GET /internal/rag/jobs/{job_id}` возвращает статус задания, ошибку или число опубликованных
  фрагментов. Задание и временные байты файла переживают перезапуск API. При ошибке остаётся
  доступна ранее опубликованная версия. Загрузка и статус также доступны из `/docs` FastAPI.
  Для ссылки на конкретную версию документа передавайте постоянный URL этой версии.
- `POST /internal/rag/answer` принимает JSON с `question` и необязательным `standalone_question`.
  Возвращает ответ по частям и источники. Все три ручки требуют
  `Authorization: Bearer <RAG_SERVICE_TOKEN>`.

## Проверки разработки

После `npm ci` в `flue/` выполните `npm run typecheck`, `npm run build` и `npm test`. Для теста реального Flue с подменой Telegram и модели задайте `TEST_FLUE_DATABASE_URL` с URL отдельной PostgreSQL БД. Для тестов API примените миграции в тестовую БД, задайте `TEST_DATABASE_URL` с префиксом `postgresql+asyncpg://` и запустите `python -m pytest` из `api/`. Интеграционный тест RAG использует отдельный Qdrant из `TEST_RAG_QDRANT_URL`; путь к «БП Командировка.pdf» передаётся в `TEST_RAG_TRIP_PDF`. Для Python-тестов нужен `pytest`.

Процесс Flue рассчитан на одну реплику. Сбой между отправкой в Telegram и подтверждением результата в БД переводит отправку в состояние `unknown`. Запись доступна в `bars_telegram_deliveries`. Такие отправки требуют проверки по журналу и чату, поскольку автоматический повтор может отправить сообщение второй раз.
