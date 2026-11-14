# Telegram-агент БАРС

Flue принимает Telegram webhook, вызывает OpenAI-совместимую модель и хранит диалоги в PostgreSQL. FastAPI обслуживает регистрацию и поиск пользователей. Простой текст в личном чате идёт агенту. Команды `/start`, `/me <id>` и `/reset` работают без модели. `/reset` открывает новый диалог, предыдущий сохраняется в PostgreSQL.

## Запуск

1. Скопируйте `.env.example` в `.env`. Укажите токен бота в `BOT_TOKEN`, произвольный независимый `TELEGRAM_WEBHOOK_SECRET_TOKEN` и настройки модели. `CHAT_BASE_URL` — базовый URL совместимого API, например `https://provider.example/v1`. При работе без авторизации оставьте `CHAT_API_KEY` пустым.
2. Выполните `docker compose up -d --build --wait`. FastAPI применит миграцию пользователей, Flue создаст таблицы агента и обработки Telegram. Новый volume называется `bars-hackathon_postgres_flue_data`. На новом запуске пользователи регистрируются заново. Volume прежнего Python-бота можно сохранить для отката.
3. Проверьте `http://127.0.0.1:3000/health` с хоста. FastAPI доступен внутри Compose по адресу `http://api:8000`. Для второго экземпляра используйте другое имя проекта Compose, другие хостовые порты и отдельный тестовый токен.

## Документация API

Swagger UI доступен на `http://127.0.0.1:8000/docs`, схема OpenAPI — на `http://127.0.0.1:8000/openapi.json`. В Swagger можно посмотреть и вызвать ручки пользователей, сотрудников, тикетов и проверки состояния API. Порт API в Docker Compose можно изменить через `API_PORT` в `.env`; доступ с хоста открыт только на `127.0.0.1`.

## Авторизация администратора

Задайте случайный `JWT_SECRET` длиной не менее 32 символов в `.env`. Секрет должен оставаться одинаковым между перезапусками и экземплярами API. Срок действия JWT задаётся через `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` и по умолчанию составляет 60 минут.

Миграция `0004` создаёт администратора `admin@example.com` с временным паролем `admin`. В БД хранится только bcrypt-хеш пароля. Эти реквизиты предназначены только для разработки.

`POST /auth/login` принимает JSON с полями `email` и `password` и возвращает `access_token` и `token_type: "bearer"`. Регистрации и обновления токена нет. Для `POST /employees` передавайте заголовок `Authorization: Bearer <access_token>`. Без действующего токена API возвращает `401`. В Swagger нажмите **Authorize** и вставьте полученный токен без префикса `Bearer`.

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

Напишите тестовому боту `/start`, проверьте `/me <id>`, задайте вопрос и отправьте уточнение до готового ответа. После перезапуска Flue убедитесь, что контекст сохраняется. `/reset` открывает диалог с чистым контекстом.

После проверки остановите прежний polling основного бота и зарегистрируйте webhook для его токена. Для отката остановите Flue, вызовите `deleteWebhook` с `drop_pending_updates=false` и запустите предыдущую версию с её БД. Telegram позволяет использовать один способ получения апдейтов на токен.

## Проверки разработки

После `npm ci` в `flue/` выполните `npm run typecheck` и `npm run build`.

Процесс Flue рассчитан на одну реплику. Сбой между отправкой в Telegram и подтверждением результата в БД переводит отправку в состояние `unknown`. Запись доступна в `bars_telegram_deliveries`. Такие отправки требуют проверки по журналу и чату, поскольку автоматический повтор может отправить сообщение второй раз.
