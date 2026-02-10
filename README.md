# Матчер резюме - коммерческий продукт (ветка d-analyst)

Матчер резюме помогает быстро понять, насколько вакансия подходит под ваше резюме, и что именно нужно поправить, чтобы увеличить шанс на отклик. Это сервис для тех, кто хочет принимать решения по вакансиям быстро и уверенно.

## Возможности и преимущества

- Быстрое сравнение вакансии и резюме за 1-2 минуты.
- Понятная оценка совпадения и объяснение, за счет чего она получилась.
- Выделение пробелов и слабых зон - что именно подтянуть.
- Рекомендации по следующему шагу: откликаться, подумать или не тратить время.
- Веб-интерфейс и расширение для браузера.

## Как это работает (простыми словами)

1. Вы вставляете текст вакансии и резюме.
2. Система выделяет ключевые требования, опыт и навыки.
3. Алгоритм рассчитывает совпадение.
4. ИИ объясняет результат и предлагает улучшения.

## Для кого

- Аналитики и специалисты, которые подают много откликов.
- Кандидаты, которые хотят видеть свои пробелы до собеседования.
- Те, кто хочет принимать решения по вакансиям быстро и осознанно.

## Кейсы и результаты

- Экономит время на первичном отборе вакансий.
- Показывает, какие пункты резюме мешают попасть в нужный грейд.
- Дает понятное объяснение, почему вакансия подходит или нет.

## FAQ

**Насколько точна оценка?**
Оценку считает алгоритм по выделенным требованиям. ИИ только объясняет результат.

**Можно ли использовать для разных профессий?**
Да, но лучше всего работает для ролей с четким описанием навыков и опыта.

**Нужно ли хранить резюме в системе?**
В s‑analyst запросы сохраняются для истории в личном кабинете (полный текст + результат). В d‑analyst можно работать без сохранения.

---

# Техническая часть

## Компоненты

- `frontend/` - веб-страница матчера в стиле `s.analystexe.ru`.
- `backend/` - s‑analyst API: Telegram-логин, хранение запросов, история и админ-доступ.
- `server/` - Flask API с GigaChat и алгоритмом скоринга.
- `extension-chrome/` - Chrome-расширение для быстрого анализа.
- `deploy/` - шаблон Nginx-конфига под `d.analystexe.ru`.
- `mockups/` - дизайн-макеты.

## API

POST `/api/analyze`

Headers:
```
Authorization: Bearer <MATCHER_API_KEY>
```

Request:
```json
{
  "vacancy_text": "текст вакансии",
  "profile": {
    "resume_text": "текст резюме",
    "salary_min": "200000",
    "work_format": ["remote"],
    "red_flags": ["переработки"],
    "must_have": ["ДМС"]
  }
}
```

Response (ключевые поля):
```json
{
  "score": 7,
  "score_raw": 73,
  "verdict": "краткий вывод",
  "matches": [
    { "item": "Hard skills", "status": "match", "comment": "..." }
  ],
  "company": { "name": "...", "info": "..." },
  "details": { "career": "...", "stack": "...", "team": "..." },
  "pros_cons": { "pros": ["..."], "cons": ["..."] },
  "recommendation": { "decision": "...", "actions": ["..."] }
}
```

## Развертывание (d.analystexe.ru)

- Веб: `/srv/d-analystexe/frontend/index.html`
- API: `/srv/d-analystexe/server/app.py` (gunicorn + systemd)
- Env: `/etc/matcher-main.env`
- Nginx: `/etc/nginx/sites-available/d.analystexe.ru.conf`
- SSL: certbot

В Nginx подставляется `X-API-Key`, чтобы веб работал без ручного ввода ключа.

---

# s-analyst: авторизация, история, мониторинг

## Что сделано

- Вход через Telegram (TG-бот подтверждает логин).
- Личный кабинет с историей запросов (полный текст вакансии/резюме + результат).
- Админ-доступ: просмотр всех запросов, фильтр по `user_id`.
- Мониторинг: JSONL-логи запросов + телеграм-уведомления (успехи и ошибки).

## Эндпоинты s‑analyst

- `POST /api/tg/login/start` — получить ссылку на Telegram.
- `GET /api/tg/login/status?state=...` — статус логина и выдача токена.
- `GET /api/me` — текущий пользователь и флаг `is_admin`.
- `GET /api/history?limit=&offset=` — история текущего пользователя.
- `GET /api/admin/history?limit=&offset=&user_id=` — история для админа.
- `POST /api/analyze` — анализ (требуется Telegram‑сессия).

Поддерживаются оба формата запроса:
```json
{
  "vacancy": "текст вакансии",
  "resume": "текст резюме"
}
```
и
```json
{
  "vacancy_text": "текст вакансии",
  "profile": { "resume_text": "текст резюме" }
}
```

## Хранилище запросов

- SQLite: `/var/lib/s-analystexe/matcher.db`
- Таблица: `matcher_requests` (user_id, vacancy_text, resume_text, result_json, status, error, created_at).

## Логи и мониторинг

- JSONL мета: `/var/log/s-analystexe/requests.jsonl`
- JSONL полные: `/var/log/s-analystexe/requests_full.jsonl`
- Телеграм-уведомления о каждом запросе (успех/ошибка) + полный текст, с разбиением на части.

## Переменные окружения (s‑analyst)

```
BOT_TOKEN=...
CHAT_ID=...               # основной чат логов
EXTRA_CHAT_IDS=...        # дополнительные чаты через запятую
ADMIN_TG_IDS=...          # id админов через запятую
DB_PATH=/var/lib/s-analystexe/matcher.db
REQUEST_LOG_PATH=/var/log/s-analystexe/requests.jsonl
REQUEST_LOG_FULL_PATH=/var/log/s-analystexe/requests_full.jsonl
TELEGRAM_MAX_LEN=3500
```

## Быстрый старт (локально)

### Сервер

```bash
cd server
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Создай `.env`:
```bash
cp .env.example .env
# Добавь:
# GIGACHAT_AUTH_KEY=...
# MATCHER_API_KEY=...
```

Запуск:
```bash
python app.py
```

Сервер доступен на `http://localhost:5000`.

### Веб-страница

Открой `frontend/index.html` через локальный сервер или статику.
API ожидается на `/api/` (через прокси или локально).

### Расширение

1. Открой `chrome://extensions/`.
2. Включи Developer mode.
3. Load unpacked -> `extension-chrome`.
4. В профиле укажи `MATCHER_API_KEY` и вставь резюме.

---

Ветка `d-analyst` не участвует в автодеплое основного сайта.
