from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
from dotenv import load_dotenv
import uuid
import time
import logging
import json
import re
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('matcher.log')
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
CORS(
    app,
    resources={r"/api/*": {"origins": "*"}},
    allow_headers=["Content-Type", "Authorization", "X-API-Key"]
)

# GigaChat credentials
GIGACHAT_AUTH_KEY = os.getenv('GIGACHAT_AUTH_KEY')
MATCHER_API_KEY = os.getenv('MATCHER_API_KEY')
GIGACHAT_OAUTH_URL = 'https://ngw.devices.sberbank.ru:9443/api/v2/oauth'
GIGACHAT_API_URL = 'https://gigachat.devices.sberbank.ru/api/v1/chat/completions'

# Token cache
token_cache = {
    'access_token': None,
    'expires_at': 0
}

REQUEST_LOG_PATH = os.getenv('REQUEST_LOG_PATH', '/var/log/matcher-main/requests.jsonl')
REQUEST_LOG_FULL_PATH = os.getenv('REQUEST_LOG_FULL_PATH', '/var/log/matcher-main/requests_full.jsonl')

DEFAULT_WEIGHTS = {
    'education_match': 25,
    'experience_match': 25,
    'hard_skills_match': 40,
    'soft_skills_match': 10
}

def is_authorized(req):
    """Check API key auth for protected endpoints."""
    if not MATCHER_API_KEY:
        logger.error('MATCHER_API_KEY not set in .env')
        return False

    auth_header = req.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header.split(' ', 1)[1].strip()
        return token == MATCHER_API_KEY

    api_key = req.headers.get('X-API-Key', '').strip()
    return api_key == MATCHER_API_KEY

def _ensure_log_dir(path):
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

def _write_jsonl(path, payload):
    try:
        _ensure_log_dir(path)
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + '\n')
    except Exception as exc:
        logger.error(f'Failed to write log: {exc}')

def _client_meta(req):
    return {
        'ip': req.headers.get('X-Real-IP') or req.headers.get('X-Forwarded-For') or req.remote_addr,
        'user_agent': req.headers.get('User-Agent'),
        'referer': req.headers.get('Referer'),
        'origin': req.headers.get('Origin')
    }

def get_gigachat_token():
    """Получить токен GigaChat (с кэшированием)"""
    # Если токен валиден - вернуть из кэша
    if token_cache['access_token'] and time.time() < token_cache['expires_at'] - 60:
        logger.info('Using cached GigaChat token')
        return token_cache['access_token']

    # Путь к сертификату
    cert_path = os.path.join(os.path.dirname(__file__), 'russian_trusted_root_ca.cer')
    logger.info(f'Getting new GigaChat token, cert_path exists: {os.path.exists(cert_path)}')

    # Иначе - получить новый
    response = requests.post(
        GIGACHAT_OAUTH_URL,
        headers={
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'RqUID': str(uuid.uuid4()),
            'Authorization': f'Basic {GIGACHAT_AUTH_KEY}'
        },
        data='scope=GIGACHAT_API_PERS',
        verify=cert_path if os.path.exists(cert_path) else False
    )

    if response.status_code != 200:
        logger.error(f'GigaChat OAuth error: {response.status_code} {response.text}')
        raise Exception(f'GigaChat OAuth error: {response.text}')

    data = response.json()
    token_cache['access_token'] = data['access_token']
    token_cache['expires_at'] = data['expires_at']
    logger.info('GigaChat token obtained successfully')

    return token_cache['access_token']

def call_gigachat(messages):
    """Вызвать GigaChat API"""
    token = get_gigachat_token()

    # Путь к сертификату
    cert_path = os.path.join(os.path.dirname(__file__), 'russian_trusted_root_ca.cer')

    logger.info(f'Calling GigaChat API with {len(messages)} messages')
    logger.info(f'Prompt length: {len(messages[0]["content"]) if messages else 0} chars')

    response = requests.post(
        GIGACHAT_API_URL,
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {token}'
        },
        json={
            'model': 'GigaChat',
            'messages': messages,
            'temperature': 0.3,
            'max_tokens': 2000
        },
        verify=cert_path if os.path.exists(cert_path) else False
    )

    logger.info(f'GigaChat API response status: {response.status_code}')

    if response.status_code != 200:
        logger.error(f'GigaChat API error: {response.text}')
        raise Exception(f'GigaChat API error: {response.text}')

    data = response.json()
    content = data['choices'][0]['message']['content']

    logger.info(f'GigaChat response length: {len(content)} chars')
    logger.info(f'GigaChat raw response:\n{content}')

    return content

def extract_json_from_text(text):
    """Extract the first JSON object from a string."""
    json_match = re.search(r'\{[\s\S]*\}', text)
    if not json_match:
        raise ValueError('No JSON found in response')
    return json.loads(json_match.group(0))

def extract_structured_data(text, doc_type):
    """Extract structured data from job or resume text using GigaChat."""
    prompt = f"""Ты — HR-аналитик. Извлеки структуру из текста.

Тип документа: {doc_type}

Ответь СТРОГО JSON:
{{
  "education": "кратко или пустая строка",
  "experience_years": число,
  "hard_skills": ["...", "..."],
  "soft_skills": ["...", "..."]
}}

Правила:
- experience_years: число лет опыта (0, если не указано)
- hard_skills: технологии, инструменты, языки, платформы
- soft_skills: качества и поведенческие навыки
- если данных нет, верни пустые значения

ТЕКСТ:
{text}
"""

    response = call_gigachat([{'role': 'user', 'content': prompt}])
    try:
        parsed = extract_json_from_text(response)
    except Exception as exc:
        logger.error(f'Failed to parse structured data JSON: {exc}')
        return {
            'education': '',
            'experience_years': 0,
            'hard_skills': [],
            'soft_skills': []
        }

    parsed.setdefault('education', '')
    parsed.setdefault('experience_years', 0)
    parsed.setdefault('hard_skills', [])
    parsed.setdefault('soft_skills', [])
    return parsed

def calculate_score(job_data, resume_data, weights):
    """Calculate score based on extracted data."""
    report = {
        'missing_required': [],
        'partial_match': [],
        'strengths': [],
        'score_details': {}
    }
    total_score = 0.0

    # Education
    edu_score = weights['education_match'] if job_data['education'] and resume_data['education'] else 0
    report['score_details']['education'] = edu_score
    if edu_score > 0:
        report['strengths'].append('Есть соответствие по образованию')
    else:
        if job_data['education']:
            report['missing_required'].append('Образование не указано в резюме')
    total_score += edu_score

    # Experience
    job_exp = float(job_data.get('experience_years') or 0)
    resume_exp = float(resume_data.get('experience_years') or 0)
    exp_score = 0.0
    if job_exp > 0:
        if resume_exp >= job_exp:
            exp_score = weights['experience_match']
            report['strengths'].append(f'Опыт: {resume_exp:.1f} лет (требуется {job_exp:.1f})')
        elif resume_exp > 0:
            exp_score = (resume_exp / job_exp) * weights['experience_match']
            report['partial_match'].append(f'Опыт: {resume_exp:.1f} лет (требуется {job_exp:.1f})')
        else:
            report['missing_required'].append(f'Опыт {job_exp:.1f} лет')
    report['score_details']['experience'] = round(exp_score, 2)
    total_score += exp_score

    # Hard skills
    job_skills = set(s.lower().strip() for s in job_data.get('hard_skills', []))
    resume_skills = set(s.lower().strip() for s in resume_data.get('hard_skills', []))
    if job_skills:
        matched = job_skills & resume_skills
        missing = job_skills - resume_skills
        points_per = weights['hard_skills_match'] / max(1, len(job_skills))
        hs_score = len(matched) * points_per
        report['score_details']['hard_skills'] = round(hs_score, 2)
        total_score += hs_score
        if matched:
            report['strengths'].extend(f'Навык: {s}' for s in sorted(matched))
        if missing:
            report['missing_required'].extend(f'Навык: {s}' for s in sorted(missing))
    else:
        report['score_details']['hard_skills'] = 0

    # Soft skills
    job_soft = set(s.lower().strip() for s in job_data.get('soft_skills', []))
    resume_soft = set(s.lower().strip() for s in resume_data.get('soft_skills', []))
    matched_soft = job_soft & resume_soft
    if job_soft:
        ss_score = len(matched_soft) * (weights['soft_skills_match'] / max(1, len(job_soft)))
    else:
        ss_score = 0
    report['score_details']['soft_skills'] = round(ss_score, 2)
    total_score += ss_score
    if matched_soft:
        report['strengths'].extend(f'Soft skill: {s}' for s in sorted(matched_soft))

    final_score = min(100, round(total_score))
    return {
        'score': final_score,
        'report': report
    }

def score_to_ten(score_100):
    """Map 0-100 score to 1-10 scale."""
    if score_100 <= 0:
        return 1
    return max(1, min(10, round(score_100 / 10)))

def build_matches(job_data, resume_data, report):
    """Build matches list for UI."""
    matches = []

    edu_status = 'match' if job_data['education'] and resume_data['education'] else 'gap'
    if not job_data['education']:
        edu_status = 'partial'
    matches.append({
        'item': 'Образование',
        'status': edu_status,
        'comment': job_data['education'] or 'не указано'
    })

    job_exp = float(job_data.get('experience_years') or 0)
    resume_exp = float(resume_data.get('experience_years') or 0)
    if job_exp <= 0:
        exp_status = 'partial'
    elif resume_exp >= job_exp:
        exp_status = 'match'
    elif resume_exp > 0:
        exp_status = 'partial'
    else:
        exp_status = 'gap'
    matches.append({
        'item': 'Опыт',
        'status': exp_status,
        'comment': f'{resume_exp:.1f} лет (требуется {job_exp:.1f})' if job_exp > 0 else 'не указано'
    })

    job_skills = set(s.lower().strip() for s in job_data.get('hard_skills', []))
    resume_skills = set(s.lower().strip() for s in resume_data.get('hard_skills', []))
    if not job_skills:
        hs_status = 'partial'
    else:
        missing = job_skills - resume_skills
        matched = job_skills & resume_skills
        if not missing and matched:
            hs_status = 'match'
        elif matched:
            hs_status = 'partial'
        else:
            hs_status = 'gap'
    matches.append({
        'item': 'Hard skills',
        'status': hs_status,
        'comment': ', '.join(sorted(job_skills)) if job_skills else 'не указано'
    })

    job_soft = set(s.lower().strip() for s in job_data.get('soft_skills', []))
    resume_soft = set(s.lower().strip() for s in resume_data.get('soft_skills', []))
    if not job_soft:
        ss_status = 'partial'
    else:
        missing = job_soft - resume_soft
        matched = job_soft & resume_soft
        if not missing and matched:
            ss_status = 'match'
        elif matched:
            ss_status = 'partial'
        else:
            ss_status = 'gap'
    matches.append({
        'item': 'Soft skills',
        'status': ss_status,
        'comment': ', '.join(sorted(job_soft)) if job_soft else 'не указано'
    })

    return matches

def generate_explanation(profile, vacancy_text, job_data, resume_data, report, score_100, score_10):
    """Generate explanation using GigaChat without calculating score."""
    prompt = f"""Ты — карьерный консультант.
Тебе уже дали оценку кандидата, НЕЛЬЗЯ считать её заново.
Сформируй краткое объяснение и рекомендации на основе отчёта.

ОЦЕНКА: {score_100}/100 (это около {score_10}/10)

ОТЧЁТ:
- Сильные стороны: {report['strengths'][:6]}
- Частичные совпадения: {report['partial_match'][:6]}
- Пробелы: {report['missing_required'][:6]}
- Детали: {report['score_details']}

ВАКАНСИЯ:
{vacancy_text}

ПРОФИЛЬ:
- Минимальная зарплата: {profile.get('salary_min') or 'не указана'}
- Формат: {', '.join(profile.get('work_format', [])) or 'не указан'}
- Red flags: {', '.join(profile.get('red_flags', [])) or 'нет'}
- Must have: {', '.join(profile.get('must_have', [])) or 'нет'}

Ответь СТРОГО JSON:
{{
  "verdict": "1-2 предложения, без чисел",
  "company": {{
    "name": "название компании или 'не указано'",
    "info": "1 предложение или 'не указано'"
  }},
  "details": {{
    "career": "1 предложение или 'не указано'",
    "stack": "1 предложение или 'не указано'",
    "team": "1 предложение или 'не указано'"
  }},
  "pros_cons": {{
    "pros": ["плюс 1", "плюс 2", "плюс 3"],
    "cons": ["минус 1", "минус 2", "минус 3"]
  }},
  "recommendation": {{
    "decision": "Откликайся / Подумай / Не рекомендую",
    "actions": ["совет 1", "совет 2"]
  }}
}}
"""
    response = call_gigachat([{'role': 'user', 'content': prompt}])
    try:
        return extract_json_from_text(response)
    except Exception as exc:
        logger.error(f'Failed to parse explanation JSON: {exc}')
        return {}

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok'})

@app.route('/api/analyze', methods=['POST'])
def analyze_vacancy():
    """Анализ вакансии"""
    try:
        request_id = str(uuid.uuid4())
        start_time = time.time()
        data = request.json
        logger.info('Received analyze request')

        if not is_authorized(request):
            logger.warning('Unauthorized analyze request')
            return jsonify({'error': 'Unauthorized'}), 401

        # Валидация
        if not data.get('vacancy_text'):
            logger.warning('Missing vacancy_text')
            return jsonify({'error': 'vacancy_text required'}), 400

        if not data.get('profile'):
            logger.warning('Missing profile')
            return jsonify({'error': 'profile required'}), 400

        profile = data['profile']
        vacancy_text = (data.get('vacancy_text') or '').strip()
        resume_text = (profile.get('resume_text') or '').strip()

        logger.info(f'Vacancy text length: {len(vacancy_text)} chars')
        logger.info(f'Resume text length: {len(resume_text)} chars')

        # Step 1: Extract blocks via LLM
        job_data = extract_structured_data(vacancy_text, 'вакансия')
        resume_data = extract_structured_data(resume_text, 'резюме')

        # Step 2: Score via algorithm
        score_result = calculate_score(job_data, resume_data, DEFAULT_WEIGHTS)
        score_100 = score_result['score']
        score_10 = score_to_ten(score_100)

        # Step 3: Explanation via LLM
        explanation = generate_explanation(
            profile,
            vacancy_text,
            job_data,
            resume_data,
            score_result['report'],
            score_100,
            score_10
        )

        matches = build_matches(job_data, resume_data, score_result['report'])

        result = {
            'score': score_10,
            'score_raw': score_100,
            'verdict': explanation.get('verdict', 'Готово. Посмотри совпадения и рекомендации.'),
            'matches': matches
        }

        if explanation.get('company'):
            result['company'] = explanation['company']
        if explanation.get('details'):
            result['details'] = explanation['details']
        if explanation.get('pros_cons'):
            result['pros_cons'] = explanation['pros_cons']
        if explanation.get('recommendation'):
            result['recommendation'] = explanation['recommendation']

        duration_ms = int((time.time() - start_time) * 1000)
        meta_log = {
            'ts': datetime.utcnow().isoformat() + 'Z',
            'request_id': request_id,
            'status': 'ok',
            'duration_ms': duration_ms,
            'score_raw': score_100,
            'score': score_10,
            'meta': _client_meta(request)
        }
        full_log = {
            'ts': meta_log['ts'],
            'request_id': request_id,
            'status': 'ok',
            'duration_ms': duration_ms,
            'meta': meta_log['meta'],
            'vacancy_text': vacancy_text,
            'resume_text': resume_text,
            'profile': profile,
            'job_data': job_data,
            'resume_data': resume_data,
            'report': score_result['report'],
            'result': result
        }
        _write_jsonl(REQUEST_LOG_PATH, meta_log)
        _write_jsonl(REQUEST_LOG_FULL_PATH, full_log)

        logger.info('Analysis completed successfully')
        return jsonify(result)

    except Exception as e:
        logger.exception(f'Unexpected error in analyze_vacancy')
        error_log = {
            'ts': datetime.utcnow().isoformat() + 'Z',
            'request_id': str(uuid.uuid4()),
            'status': 'error',
            'error': str(e),
            'meta': _client_meta(request)
        }
        _write_jsonl(REQUEST_LOG_PATH, error_log)
        _write_jsonl(REQUEST_LOG_FULL_PATH, error_log)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    if not GIGACHAT_AUTH_KEY:
        logger.error('GIGACHAT_AUTH_KEY not set in .env')
        print('ERROR: GIGACHAT_AUTH_KEY not set in .env')
        exit(1)
    if not MATCHER_API_KEY:
        logger.error('MATCHER_API_KEY not set in .env')
        print('ERROR: MATCHER_API_KEY not set in .env')
        exit(1)

    logger.info('Starting Matcher API server on http://0.0.0.0:5000')
    logger.info(f'Certificate file exists: {os.path.exists(os.path.join(os.path.dirname(__file__), "russian_trusted_root_ca.cer"))}')
    print('Starting Matcher API server...')
    app.run(host='0.0.0.0', port=5000, debug=True)
