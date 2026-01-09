# Матчер резюме (ветка d-analyst)

Ветка d-analyst используется для поддомена d.analystexe.ru и не участвует в автодеплое основного сайта.

## Что делает

- LLM вытаскивает структуру из вакансии и резюме.
- Алгоритм считает скоринг (0-100, затем 1-10).
- LLM объясняет результат и дает рекомендации, не пересчитывая оценку.

## Компоненты

- frontend/ - веб-страница матчера в стиле s.analystexe.ru.
- server/ - Flask API с GigaChat и алгоритмом скоринга.
- extension-chrome/ - Chrome-расширение для быстрого анализа.
- deploy/ - шаблон Nginx-конфига под d.analystexe.ru.
- mockups/ - дизайн-макеты.

## Быстрый старт (локально)

### Сервер

```bash
cd server
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Создай .env:
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

Сервер доступен на http://localhost:5000.

### Веб-страница

Открой frontend/index.html через локальный сервер или статику.
API ожидается на /api/ (через прокси или локально).

### Расширение

1. Открой chrome://extensions/.
2. Включи Developer mode.
3. Load unpacked -> extension-chrome.
4. В профиле укажи MATCHER_API_KEY и вставь резюме.

## API

POST /api/analyze

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

## Деплой (d.analystexe.ru)

- Веб: /srv/d-analystexe/frontend/index.html
- API: /srv/d-analystexe/server/app.py (gunicorn + systemd)
- Env: /etc/matcher-main.env
- Nginx: /etc/nginx/sites-available/d.analystexe.ru.conf
- SSL: certbot

В Nginx подставляется X-API-Key, чтобы веб работал без ручного ввода ключа.

## Примечания

- Ветка d-analyst не затрагивает автодеплой main.
- В проде веб использует прокси /api/ на тот же домен.
