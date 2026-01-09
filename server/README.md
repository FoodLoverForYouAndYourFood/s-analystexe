# Matcher API Server

Flask сервер для проксирования запросов к GigaChat API

## Установка

```bash
cd server
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Настройка

1. Скопируй `.env.example` в `.env`:
```bash
cp .env.example .env
```

2. Добавь свой ключ GigaChat в `.env`:
```
GIGACHAT_AUTH_KEY=твой_ключ_тут
```

Получить ключ: https://developers.sber.ru/studio/

3. Добавь API key сервера в `.env`:
```
MATCHER_API_KEY=любой_секретный_ключ
```

4. **Сертификат (уже включен):** Сертификат российского CA (`russian_trusted_root_ca.cer`) уже скачан и будет использоваться автоматически для HTTPS запросов к GigaChat API.

## Запуск

```bash
python app.py
```

Сервер запустится на `http://localhost:5000`

**Логи:** Все запросы, ответы GigaChat и ошибки пишутся в файл `matcher.log` и выводятся в консоль.

## API

### POST /api/analyze

Анализ вакансии

**Headers:**
```
Authorization: Bearer <MATCHER_API_KEY>
```

**Request:**
```json
{
  "vacancy_text": "текст вакансии...",
  "profile": {
    "resume_text": "текст резюме...",
    "salary_min": "200000",
    "work_format": ["remote"],
    "red_flags": ["переработки", "стартап"],
    "must_have": ["ДМС", "удалёнка"]
  }
}
```

**Response:**
```json
{
  "score": 8,
  "verdict": "Отличное совпадение",
  "matches": [
    {
      "item": "Навыки",
      "status": "match",
      "comment": "Python, Flask - полное совпадение"
    }
  ],
  "quick_wins": ["Добавь в резюме опыт с Docker"]
}
```

### GET /health

Health check

## Production

Для продакшена используй gunicorn:

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```
