#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import os
import secrets
import ssl
import sqlite3
import threading
import time
from datetime import datetime
import re
from typing import Optional
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
EXTRA_CHAT_IDS = os.getenv("EXTRA_CHAT_IDS", "")
TELEGRAM_MAX_LEN = int(os.getenv("TELEGRAM_MAX_LEN", "3500"))
PORT = int(os.getenv("PORT", "9009"))

GIGACHAT_AUTH_B64 = os.getenv("GIGACHAT_AUTH_B64", "")
GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
GIGACHAT_MODELS = os.getenv(
    "GIGACHAT_MODELS",
    "GigaChat-Max,GigaChat-Pro,GigaChat",
)
GIGACHAT_INSECURE = os.getenv("GIGACHAT_INSECURE", "1") == "1"
STATE_PATH = os.getenv("STATE_PATH", "/var/lib/s-analystexe/state.json")
STATS_PATH = os.getenv("STATS_PATH", "/var/lib/s-analystexe/stats.json")
VISIT_TTL_SEC = 6 * 60 * 60
TG_BOT_USERNAME = os.getenv("TG_BOT_USERNAME", "").lstrip("@")
SITE_URL = os.getenv("SITE_URL", "https://s.analystexe.ru")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
LOGIN_TTL_SEC = int(os.getenv("LOGIN_TTL_SEC", "600"))
SESSION_TTL_SEC = int(os.getenv("SESSION_TTL_SEC", "86400"))
REQUEST_LOG_PATH = os.getenv("REQUEST_LOG_PATH", "/var/log/s-analystexe/requests.jsonl")
REQUEST_LOG_FULL_PATH = os.getenv("REQUEST_LOG_FULL_PATH", "/var/log/s-analystexe/requests_full.jsonl")
DB_PATH = os.getenv("DB_PATH", "/var/lib/s-analystexe/matcher.db")
ADMIN_TG_IDS = {
    item.strip()
    for item in os.getenv("ADMIN_TG_IDS", "").replace(";", ",").split(",")
    if item.strip()
}
HISTORY_LIMIT_DEFAULT = int(os.getenv("HISTORY_LIMIT_DEFAULT", "20"))
HISTORY_LIMIT_MAX = int(os.getenv("HISTORY_LIMIT_MAX", "100"))
STATE_LOCK = threading.Lock()


def _load_json(path: str, default: dict) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default.copy()


def _save_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def _ensure_log_dir(path: str) -> None:
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)


def _write_jsonl(path: str, payload: dict) -> None:
    try:
        _ensure_log_dir(path)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _db_connect():
    _ensure_log_dir(DB_PATH)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _init_db() -> None:
    conn = _db_connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS matcher_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT UNIQUE,
            user_id TEXT,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            vacancy_text TEXT,
            resume_text TEXT,
            result_json TEXT,
            status TEXT,
            error TEXT,
            created_at TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_matcher_requests_user_id ON matcher_requests(user_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_matcher_requests_created_at ON matcher_requests(created_at)"
    )
    conn.commit()
    conn.close()


def _store_request(
    request_id: str,
    user: dict,
    vacancy: str,
    resume: str,
    result: Optional[dict],
    status: str,
    error: Optional[str],
) -> None:
    try:
        conn = _db_connect()
        conn.execute(
            """
            INSERT INTO matcher_requests (
                request_id, user_id, username, first_name, last_name,
                vacancy_text, resume_text, result_json, status, error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                str(user.get("id", "")),
                user.get("username", ""),
                user.get("first_name", ""),
                user.get("last_name", ""),
                vacancy,
                resume,
                json.dumps(result, ensure_ascii=False) if result is not None else None,
                status,
                error,
                datetime.utcnow().isoformat() + "Z",
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        return


def _row_to_item(row):
    result = None
    if row["result_json"]:
        try:
            result = json.loads(row["result_json"])
        except Exception:
            result = None
    return {
        "id": row["id"],
        "request_id": row["request_id"],
        "user_id": row["user_id"],
        "username": row["username"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "vacancy_text": row["vacancy_text"],
        "resume_text": row["resume_text"],
        "result": result,
        "status": row["status"],
        "error": row["error"],
        "created_at": row["created_at"],
    }


def _fetch_history(user_id: str, limit: int, offset: int):
    conn = _db_connect()
    rows = conn.execute(
        """
        SELECT * FROM matcher_requests
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        """,
        (user_id, limit, offset),
    ).fetchall()
    conn.close()
    return [_row_to_item(row) for row in rows]


def _fetch_history_all(limit: int, offset: int, user_id: Optional[str] = None):
    conn = _db_connect()
    if user_id:
        rows = conn.execute(
            """
            SELECT * FROM matcher_requests
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM matcher_requests
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    conn.close()
    return [_row_to_item(row) for row in rows]


def _load_state() -> dict:
    state = _load_json(STATE_PATH, {"last_seen": {}, "offset": 0})
    login = state.setdefault("login", {})
    login.setdefault("states", {})
    return state


def _update_state(updater):
    with STATE_LOCK:
        state = _load_json(STATE_PATH, {"last_seen": {}, "offset": 0})
        login = state.setdefault("login", {})
        login.setdefault("states", {})
        result = updater(state)
        _save_json(STATE_PATH, state)
        return result


def _cleanup_login_states(state: dict) -> None:
    now = int(time.time())
    states = state.setdefault("login", {}).setdefault("states", {})
    for key in list(states.keys()):
        exp = int(states.get(key, {}).get("exp", 0))
        if exp and exp < now:
            states.pop(key, None)


def _approve_login_state(payload: str, user: dict) -> bool:
    def updater(state):
        _cleanup_login_states(state)
        entry = state.setdefault("login", {}).setdefault("states", {}).get(payload)
        if entry and int(entry.get("exp", 0)) >= int(time.time()):
            entry["status"] = "approved"
            entry["approved_at"] = int(time.time())
            entry["user"] = {
                "id": user.get("id"),
                "username": user.get("username") or "",
                "first_name": user.get("first_name") or "",
                "last_name": user.get("last_name") or "",
            }
            return True
        return False
    return bool(_update_state(updater))


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64url(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign(value: str) -> str:
    return hmac.new(
        SESSION_SECRET.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _make_session(user: dict) -> str:
    if not SESSION_SECRET:
        raise RuntimeError("missing_session_secret")
    payload = {
        "id": user.get("id"),
        "username": user.get("username") or "",
        "first_name": user.get("first_name") or "",
        "last_name": user.get("last_name") or "",
        "exp": int(time.time()) + SESSION_TTL_SEC,
    }
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _sign(body)
    return f"{body}.{sig}"


def _verify_session(token: str):
    if not token or not SESSION_SECRET:
        return None
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(_sign(body), sig):
        return None
    try:
        payload = json.loads(_unb64url(body).decode("utf-8"))
    except Exception:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


def _is_admin(user: dict) -> bool:
    user_id = str(user.get("id", ""))
    return bool(user_id and user_id in ADMIN_TG_IDS)


def _clamp_limit(raw: Optional[str]) -> int:
    try:
        value = int(raw or 0)
    except Exception:
        value = 0
    if value <= 0:
        value = HISTORY_LIMIT_DEFAULT
    return min(value, HISTORY_LIMIT_MAX)


def _clamp_offset(raw: Optional[str]) -> int:
    try:
        value = int(raw or 0)
    except Exception:
        value = 0
    return max(value, 0)


def _urlopen(req: urllib.request.Request, timeout: int = 20):
    if GIGACHAT_INSECURE:
        ctx = ssl._create_unverified_context()
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)
    return urllib.request.urlopen(req, timeout=timeout)


def send_telegram_to(chat_id: str, text: str) -> bool:
    if not BOT_TOKEN or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def _send_telegram_long(chat_id: str, text: str) -> bool:
    if not text:
        return True
    ok = True
    for idx in range(0, len(text), TELEGRAM_MAX_LEN):
        chunk = text[idx:idx + TELEGRAM_MAX_LEN]
        ok = send_telegram_to(chat_id, chunk) and ok
    return ok


def send_telegram(text: str) -> bool:
    ids = []
    for raw in (CHAT_ID, EXTRA_CHAT_IDS):
        if raw:
            for part in raw.replace(";", ",").split(","):
                val = part.strip()
                if val:
                    ids.append(val)
    if not ids:
        return False
    ok = True
    for chat_id in ids:
        ok = _send_telegram_long(chat_id, text) and ok
    return ok


def _notify_error(error: str, vacancy: str, resume: str, request_id: str) -> None:
    msg = (
        "⚠️ Matcher error\n"
        f"{error}\n"
        f"request_id: {request_id}\n"
        f"vacancy_len: {len(vacancy)}\n"
        f"resume_len: {len(resume)}\n"
        f"link: https://s.analystexe.ru/matcher.html"
    )
    send_telegram(msg)
    send_telegram(f"Vacancy:\n{vacancy}")
    send_telegram(f"Resume:\n{resume}")


def _notify_success(vacancy: str, resume: str, request_id: str, duration_ms: int) -> None:
    msg = (
        "✅ Matcher ok\n"
        f"request_id: {request_id}\n"
        f"duration_ms: {duration_ms}\n"
        f"vacancy_len: {len(vacancy)}\n"
        f"resume_len: {len(resume)}\n"
        f"link: https://s.analystexe.ru/matcher.html"
    )
    send_telegram(msg)
    send_telegram(f"Vacancy:\n{vacancy}")
    send_telegram(f"Resume:\n{resume}")


def _get_gigachat_token() -> str:
    if not GIGACHAT_AUTH_B64:
        raise RuntimeError("missing_gigachat_auth")

    state = _load_json(STATE_PATH, {"last_seen": {}, "offset": 0})
    token = state.get("gigachat_token")
    exp = int(state.get("gigachat_exp", 0))
    now = int(time.time())
    if token and now < exp - 60:
        return token

    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    data = urllib.parse.urlencode({"scope": GIGACHAT_SCOPE}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Basic {GIGACHAT_AUTH_B64}",
            "Content-Type": "application/x-www-form-urlencoded",
            "RqUID": str(uuid.uuid4()),
        },
        method="POST",
    )
    try:
        with _urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8")
            msg = json.loads(body).get("error_description", "")
        except Exception:
            msg = ""
        msg = msg.replace("\n", " ").strip()
        code = f"gigachat_auth_{exc.code}"
        raise RuntimeError(f"{code}:{msg}" if msg else code) from exc
    except Exception as exc:
        raise RuntimeError("gigachat_auth_unavailable") from exc

    token = payload.get("access_token")
    expires_at = int(payload.get("expires_at", 0) / 1000) if payload.get("expires_at") else 0
    if not token:
        raise RuntimeError("gigachat_auth_invalid")

    state["gigachat_token"] = token
    state["gigachat_exp"] = expires_at or (now + 1800)
    _save_json(STATE_PATH, state)
    return token


def _try_parse_json(content: str):
    try:
        return json.loads(content)
    except Exception:
        pass
    match = re.search(r"\{[\\s\\S]*\\}", content)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def call_gigachat(vacancy: str, resume: str) -> dict:
    prompt = (
        "Ты — карьерный консультант с опытом найма аналитиков.\n"
        "Проведи GAP-анализ резюме относительно вакансии.\n\n"
        "Ответь СТРОГО в формате JSON:\n"
        "{\n"
        "  \"requirements\": [\n"
        "    {\n"
        "      \"requirement\": \"Название требования\",\n"
        "      \"status\": \"match|partial|gap\",\n"
        "      \"found_in_resume\": \"Где найдено или null\",\n"
        "      \"recommendation\": \"Что сделать\"\n"
        "    }\n"
        "  ],\n"
        "  \"quick_wins\": [\"...\", \"...\", \"...\"],\n"
        "  \"summary\": \"Краткий вывод\"\n"
        "}\n\n"
        "status:\n"
        "- \"match\" = полное совпадение\n"
        "- \"partial\" = есть опыт, но сформулировано иначе\n"
        "- \"gap\" = не найдено\n\n"
        f"ВАКАНСИЯ:\n{vacancy}\n\n"
        f"РЕЗЮМЕ:\n{resume}"
    )

    token = _get_gigachat_token()
    models = [m.strip() for m in GIGACHAT_MODELS.split(",") if m.strip()]
    last_error = ""

    for model in models:
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )

        try:
            with _urlopen(req, timeout=40) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8")
                msg = json.loads(body).get("error", {}).get("message", "")
            except Exception:
                msg = ""
            msg = msg.replace("\n", " ").strip()
            last_error = f"gigachat_http_{exc.code}:{msg}" if msg else f"gigachat_http_{exc.code}"
            continue
        except Exception:
            last_error = "gigachat_unavailable"
            continue

        content = ""
        try:
            content = data["choices"][0]["message"]["content"]
        except Exception:
            last_error = "gigachat_bad_response"
            continue

        content = content.strip()
        if content.startswith("```"):
            content = content.strip("`")
            content = content.replace("json", "", 1).strip()

        parsed = _try_parse_json(content)
        if parsed is not None:
            return parsed
        last_error = "gigachat_invalid_json"
        continue

    raise RuntimeError(last_error or "gigachat_failed")


def get_stats() -> dict:
    return _load_json(
        STATS_PATH,
        {"page_view": 0, "cta_click": 0, "form_view": 0, "lead": 0, "analyze": 0},
    )


def bump_stat(key: str, inc: int = 1) -> None:
    stats = get_stats()
    stats[key] = int(stats.get(key, 0)) + inc
    _save_json(STATS_PATH, stats)


def should_count_visit(ip: str, ua: str) -> bool:
    state = _load_json(STATE_PATH, {"last_seen": {}, "offset": 0})
    now = int(time.time())
    key = f"{ip}|{ua}"
    last_seen = int(state.get("last_seen", {}).get(key, 0))
    if now - last_seen < VISIT_TTL_SEC:
        return False
    state.setdefault("last_seen", {})[key] = now
    _save_json(STATE_PATH, state)
    return True


def format_stats(stats: dict) -> str:
    visits = int(stats.get("page_view", 0))
    clicks = int(stats.get("cta_click", 0))
    views = int(stats.get("form_view", 0))
    leads = int(stats.get("lead", 0))
    analyzes = int(stats.get("analyze", 0))
    ctr = (clicks / visits * 100) if visits else 0.0
    conv_visit = (leads / visits * 100) if visits else 0.0
    conv_click = (leads / clicks * 100) if clicks else 0.0
    return (
        "📊 Screener stats\n"
        f"Visits: {visits}\n"
        f"CTA clicks: {clicks}\n"
        f"Form views: {views}\n"
        f"Leads: {leads}\n"
        f"Matcher uses: {analyzes}\n"
        f"CTR (click/visit): {ctr:.1f}%\n"
        f"Conv (lead/visit): {conv_visit:.1f}%\n"
        f"Conv (lead/click): {conv_click:.1f}%"
    )


def poll_telegram() -> None:
    if not BOT_TOKEN:
        return
    while True:
        try:
            state = _load_state()
            offset = int(state.get("offset", 0))
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=0"
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                for item in data.get("result", []):
                    update_id = int(item.get("update_id", 0))
                    msg = item.get("message", {})
                    text_raw = (msg.get("text") or "").strip()
                    text = text_raw.lower()
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    if text.startswith("/start"):
                        parts = text_raw.split(maxsplit=1)
                        payload = parts[1] if len(parts) > 1 else ""
                        if payload:
                            user = msg.get("from") or msg.get("chat") or {}
                            if _approve_login_state(payload, user):
                                send_telegram_to(chat_id, f"✅ Готово! Вернитесь на сайт: {SITE_URL}")
                            else:
                                send_telegram_to(chat_id, "Ссылка устарела. Вернитесь на сайт и нажмите «Войти через Telegram» ещё раз.")
                        else:
                            send_telegram_to(chat_id, "Для входа вернитесь на сайт и нажмите «Войти через Telegram».")
                    if CHAT_ID and chat_id == str(CHAT_ID) and text in {"/stats", "stats", "стата", "/стата"}:
                        send_telegram(format_stats(get_stats()))
                    _update_state(lambda s, u=update_id: s.__setitem__("offset", u + 1))
        except Exception:
            pass
        time.sleep(5)


class Handler(BaseHTTPRequestHandler):
    server_version = "screener-bot/1.6"

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _client_meta(self):
        ip = self.headers.get("X-Real-IP") or self.client_address[0]
        ua = self.headers.get("User-Agent", "-")
        ref = self.headers.get("Referer", "-")
        return ip, ua, ref

    def _parse_path(self):
        parsed = urllib.parse.urlparse(self.path)
        return parsed.path, urllib.parse.parse_qs(parsed.query)

    def _get_auth_token(self) -> str:
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth.split(" ", 1)[1].strip()
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "screener_session":
                return value
        return ""

    def do_GET(self):
        path, query = self._parse_path()

        if path == "/api/tg/login/status":
            state_id = (query.get("state") or [""])[0]
            if not state_id:
                self._send_json(400, {"ok": False, "error": "state_required"})
                return

            def updater(state):
                _cleanup_login_states(state)
                states = state.setdefault("login", {}).setdefault("states", {})
                entry = states.get(state_id)
                if not entry:
                    return ("not_found", None, None)
                if entry.get("status") != "approved":
                    return ("pending", None, None)
                user = entry.get("user") or {}
                states.pop(state_id, None)
                return ("ok", user, _make_session(user))

            status, user, token = _update_state(updater)
            if status == "not_found":
                self._send_json(404, {"ok": False, "error": "state_not_found"})
                return
            if status == "pending":
                self._send_json(200, {"ok": False, "status": "pending"})
                return
            if status == "ok":
                self._send_json(200, {"ok": True, "token": token, "user": user})
                return
            self._send_json(500, {"ok": False, "error": "login_failed"})
            return

        if path == "/api/me":
            token = self._get_auth_token()
            user = _verify_session(token)
            if not user:
                self._send_json(401, {"ok": False, "error": "unauthorized"})
                return
            self._send_json(200, {"ok": True, "user": user, "is_admin": _is_admin(user)})
            return

        if path == "/api/history":
            token = self._get_auth_token()
            user = _verify_session(token)
            if not user:
                self._send_json(401, {"ok": False, "error": "unauthorized"})
                return
            limit = _clamp_limit((query.get("limit") or [None])[0])
            offset = _clamp_offset((query.get("offset") or [None])[0])
            items = _fetch_history(str(user.get("id", "")), limit, offset)
            self._send_json(200, {"ok": True, "items": items, "limit": limit, "offset": offset})
            return

        if path == "/api/admin/history":
            token = self._get_auth_token()
            user = _verify_session(token)
            if not user or not _is_admin(user):
                self._send_json(403, {"ok": False, "error": "forbidden"})
                return
            limit = _clamp_limit((query.get("limit") or [None])[0])
            offset = _clamp_offset((query.get("offset") or [None])[0])
            user_id = (query.get("user_id") or [""])[0].strip() or None
            items = _fetch_history_all(limit, offset, user_id)
            self._send_json(200, {"ok": True, "items": items, "limit": limit, "offset": offset})
            return

        self._send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        path, _ = self._parse_path()

        if path == "/api/tg/login/start":
            if not BOT_TOKEN:
                self._send_json(500, {"ok": False, "error": "missing_bot_token"})
                return
            if not TG_BOT_USERNAME:
                self._send_json(500, {"ok": False, "error": "missing_bot_username"})
                return
            if not SESSION_SECRET:
                self._send_json(500, {"ok": False, "error": "missing_session_secret"})
                return

            def updater(state):
                _cleanup_login_states(state)
                states = state.setdefault("login", {}).setdefault("states", {})
                token = secrets.token_urlsafe(16)
                states[token] = {"status": "pending", "exp": int(time.time()) + LOGIN_TTL_SEC}
                return token

            token = _update_state(updater)
            self._send_json(200, {
                "ok": True,
                "state": token,
                "expires_in": LOGIN_TTL_SEC,
                "tg_url": f"https://t.me/{TG_BOT_USERNAME}?start={token}",
            })
            return

        if path == "/api/event":
            data = self._read_json()
            event = str(data.get("event", "")).strip()
            ip, ua, _ = self._client_meta()
            if event == "page_view":
                if should_count_visit(ip, ua):
                    bump_stat("page_view")
            elif event in {"cta_click", "form_view"}:
                bump_stat(event)
            else:
                self._send_json(400, {"ok": False, "error": "invalid_event"})
                return
            self._send_json(200, {"ok": True})
            return

        if path == "/api/lead":
            data = self._read_json()
            email = str(data.get("email", "")).strip()
            if not email:
                self._send_json(400, {"ok": False, "error": "email_required"})
                return
            bump_stat("lead")
            msg = f"🎯 New lead\nEmail: {email}"
            ok = send_telegram(msg)
            self._send_json(200, {"ok": ok})
            return

        if path == "/api/analyze":
            started = time.time()
            request_id = str(uuid.uuid4())
            user = _verify_session(self._get_auth_token())
            if not user:
                self._send_json(401, {"ok": False, "error": "unauthorized"})
                return
            data = self._read_json()
            vacancy = str(data.get("vacancy") or data.get("vacancy_text") or "").strip()
            profile = data.get("profile") or {}
            resume = str(data.get("resume") or profile.get("resume_text") or "").strip()
            ip, ua, ref = self._client_meta()
            meta = {"ip": ip, "user_agent": ua, "referer": ref}
            if len(vacancy) < 100 or len(resume) < 100:
                duration_ms = int((time.time() - started) * 1000)
                ts = datetime.utcnow().isoformat() + "Z"
                error = "text_too_short"
                meta_log = {
                    "ts": ts,
                    "request_id": request_id,
                    "status": "error",
                    "duration_ms": duration_ms,
                    "meta": meta,
                    "error": error,
                }
                full_log = {
                    **meta_log,
                    "vacancy_text": vacancy,
                    "resume_text": resume,
                }
                _write_jsonl(REQUEST_LOG_PATH, meta_log)
                _write_jsonl(REQUEST_LOG_FULL_PATH, full_log)
                _store_request(request_id, user, vacancy, resume, None, "error", error)
                _notify_error(error, vacancy, resume, request_id)
                self._send_json(400, {"ok": False, "error": "text_too_short"})
                return
            bump_stat("analyze")
            try:
                result = call_gigachat(vacancy, resume)
            except RuntimeError as exc:
                duration_ms = int((time.time() - started) * 1000)
                ts = datetime.utcnow().isoformat() + "Z"
                error = str(exc)
                meta_log = {
                    "ts": ts,
                    "request_id": request_id,
                    "status": "error",
                    "duration_ms": duration_ms,
                    "meta": meta,
                    "error": error,
                }
                full_log = {
                    **meta_log,
                    "vacancy_text": vacancy,
                    "resume_text": resume,
                }
                _write_jsonl(REQUEST_LOG_PATH, meta_log)
                _write_jsonl(REQUEST_LOG_FULL_PATH, full_log)
                _store_request(request_id, user, vacancy, resume, None, "error", error)
                _notify_error(error, vacancy, resume, request_id)
                self._send_json(502, {"ok": False, "error": str(exc)})
                return
            except Exception:
                duration_ms = int((time.time() - started) * 1000)
                ts = datetime.utcnow().isoformat() + "Z"
                error = "gigachat_unavailable"
                meta_log = {
                    "ts": ts,
                    "request_id": request_id,
                    "status": "error",
                    "duration_ms": duration_ms,
                    "meta": meta,
                    "error": error,
                }
                full_log = {
                    **meta_log,
                    "vacancy_text": vacancy,
                    "resume_text": resume,
                }
                _write_jsonl(REQUEST_LOG_PATH, meta_log)
                _write_jsonl(REQUEST_LOG_FULL_PATH, full_log)
                _store_request(request_id, user, vacancy, resume, None, "error", error)
                _notify_error(error, vacancy, resume, request_id)
                self._send_json(502, {"ok": False, "error": "gigachat_unavailable"})
                return
            duration_ms = int((time.time() - started) * 1000)
            ts = datetime.utcnow().isoformat() + "Z"
            meta_log = {
                "ts": ts,
                "request_id": request_id,
                "status": "ok",
                "duration_ms": duration_ms,
                "meta": meta,
            }
            full_log = {
                **meta_log,
                "vacancy_text": vacancy,
                "resume_text": resume,
                "result": result,
            }
            _write_jsonl(REQUEST_LOG_PATH, meta_log)
            _write_jsonl(REQUEST_LOG_FULL_PATH, full_log)
            _store_request(request_id, user, vacancy, resume, result, "ok", None)
            _notify_success(vacancy, resume, request_id, duration_ms)
            self._send_json(200, result)
            return

        self._send_json(404, {"ok": False, "error": "not_found"})

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    _init_db()
    t = threading.Thread(target=poll_telegram, daemon=True)
    t.start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.serve_forever()
