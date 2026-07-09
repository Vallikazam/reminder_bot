# Telegram reminder bot

Бот позволяет создавать текстовые напоминания в Telegram и отправляет их в нужное время.
Создание, список, редактирование и удаление работают через внутренние кнопки Telegram.

## Можно ли ограничить доступ?

Да. Укажите в переменной `ALLOWED_USER_IDS` список разрешенных Telegram ID через запятую. Если список пустой, бот будет доступен всем, кто напишет ему.

Чтобы узнать свой ID, запустите бота и напишите `/start`: бот покажет ваш Telegram ID. Затем добавьте его в `ALLOWED_USER_IDS`.

## Запуск

1. Создайте бота через Telegram `@BotFather` и получите токен.
2. Создайте файл `.env` по примеру `.env.example`.
3. В PowerShell задайте переменные и запустите:

```powershell
$env:TELEGRAM_BOT_TOKEN="123456789:token"
$env:ALLOWED_USER_IDS="111111111,222222222"
$env:BOT_TIMEZONE="Asia/Qyzylorda"
$env:BOT_UTC_OFFSET="+05:00"
python bot.py
```

## Деплой на Vercel

На Vercel бот работает через webhook, а не через бесконечный `python bot.py`.
В проект добавлены:

- `api/webhook.py` - принимает обновления от Telegram
- `api/cron.py` - проверяет и отправляет наступившие напоминания
- `vercel.json` - настройки Vercel Functions
- KV/Upstash Redis storage - хранит напоминания и шаги создания/редактирования

На Vercel Hobby встроенный Vercel Cron доступен только для ежедневных запусков. Для напоминаний нужен запуск чаще, поэтому на Hobby используйте внешний cron-сервис, например cron-job.org, EasyCron, UptimeRobot или GitHub Actions, который будет дергать `/api/cron` каждые 5 минут.

### Что нужно от вас

1. `TELEGRAM_BOT_TOKEN` - токен из `@BotFather`.
2. `ALLOWED_USER_IDS` - Telegram ID разрешенных пользователей через запятую.
3. `TELEGRAM_WEBHOOK_SECRET` - любая случайная строка, например `my_secret_2026`.
4. `CRON_SECRET` - любая другая случайная строка для защиты `/api/cron`.
5. `KV_REST_API_URL` и `KV_REST_API_TOKEN` - из Vercel KV или Upstash Redis.

Без KV/Upstash на Vercel напоминания не будут надежно сохраняться, потому что файловая система serverless-функций не подходит для постоянной базы.

### Как подключить KV в Vercel

1. Откройте проект в Vercel.
2. Перейдите в `Storage`.
3. Создайте `KV` database или подключите Upstash Redis.
4. Скопируйте переменные:
   - `KV_REST_API_URL`
   - `KV_REST_API_TOKEN`
5. Добавьте их в `Settings` -> `Environment Variables`.

### Environment Variables в Vercel

Добавьте в `Settings` -> `Environment Variables`:

```env
TELEGRAM_BOT_TOKEN=ваш_токен_бота
TELEGRAM_WEBHOOK_SECRET=случайный_секрет
CRON_SECRET=случайный_секрет_для_cron
VERCEL_APP_URL=https://your-project.vercel.app
ALLOWED_USER_IDS=111111111,222222222
BOT_TIMEZONE=Asia/Qyzylorda
BOT_UTC_OFFSET=+05:00
KV_REST_API_URL=ваш_kv_rest_url
KV_REST_API_TOKEN=ваш_kv_rest_token
REMINDERS_KEY=otbasy:reminders
SESSIONS_KEY=otbasy:sessions
```

### Деплой

1. Загрузите проект в GitHub.
2. В Vercel нажмите `Add New` -> `Project`.
3. Выберите репозиторий.
4. Добавьте переменные окружения.
5. Нажмите `Deploy`.
6. После деплоя получите URL проекта, например:

```text
https://your-project.vercel.app
```

### Подключить Telegram webhook

После деплоя выполните в PowerShell, заменив значения:

```powershell
$token="TELEGRAM_BOT_TOKEN"
$secret="TELEGRAM_WEBHOOK_SECRET"
$url="https://your-project.vercel.app/api/webhook"

Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/setWebhook" `
  -Method Post `
  -Body @{
    url=$url
    secret_token=$secret
    allowed_updates='["message","callback_query"]'
    drop_pending_updates=$true
  }
```

Проверка webhook:

```powershell
Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/getWebhookInfo"
```

Если в ответе `url` равен вашему `/api/webhook`, бот подключен.

### Запуск проверки напоминаний на Vercel Hobby

Так как Hobby не позволяет Vercel Cron чаще одного раза в день, настройте внешний HTTP cron:

```text
GET https://your-project.vercel.app/api/cron
```

Добавьте один из заголовков:

```text
Authorization: Bearer ваш_CRON_SECRET
```

или:

```text
X-Cron-Secret: ваш_CRON_SECRET
```

Интервал поставьте `5 minutes`. Если сервис не умеет добавлять headers, можно временно убрать `CRON_SECRET` из Vercel env, но это хуже: endpoint `/api/cron` станет публичным.

Если хотите использовать именно Vercel Cron, нужен платный план Vercel Pro или расписание не чаще одного раза в день, что для напоминаний обычно не подходит.

## Кнопки

- `Создать напоминание` - запустить создание напоминания
- `Все напоминания` - открыть общий список активных и повторяющихся напоминаний
- `Редактировать #ID` - изменить текст, дату, время или повтор
- `Удалить #ID` - удалить напоминание после подтверждения

## Создание напоминания

1. Нажмите `Создать напоминание`.
2. Напишите текст напоминания.
3. Выберите дату в календаре под сообщением.
4. Выберите время кнопкой или нажмите `Ввести время текстом`.
5. Выберите повтор: `Без повтора`, `Каждый час`, `Каждый день`, `Каждую неделю`, `Каждый месяц`.

После отправки повторяющееся напоминание автоматически переносится на следующий период.

## Редактирование и удаление

1. Нажмите `Все напоминания`.
2. Под списком выберите `Редактировать #ID` или `Удалить #ID`.
3. При редактировании выберите поле: текст, дата, время или повтор.
4. При удалении подтвердите действие кнопкой `Да, удалить`.

## Форматы времени

Поддерживаются:

- `2026-07-10 18:30`
- `10.07.2026 18:30`
- `10.07 18:30`
- `18:30`
- `через 15 минут`
- `2h`
- `3d`

Напоминания сохраняются в `reminders.json`. Список напоминаний общий: все разрешенные пользователи видят одни и те же активные напоминания и могут редактировать или удалять их через кнопки.
