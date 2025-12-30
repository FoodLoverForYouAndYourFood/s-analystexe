#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import os
import secrets
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
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


def _load_state() -> dict:
    state = _load_json(STATE_PATH, {"last_seen": {}, "offset": 0})
    login = state.setdefault("login", {})
    login.setdefault("states", {})
    return state


def _cleanup_login_states(state: dict) -> None:
    now = int(time.time())
    states = state.setdefault("login", {}).setdefault("states", {})
    for key in list(states.keys()):
        exp = int(states.get(key, {}).get("exp", 0))
        if exp and exp < now:
            states.pop(key, None)


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


def send_telegram(text: str) -> bool:
    if not CHAT_ID:
        return False
    return send_telegram_to(CHAT_ID, text)


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

        try:
            return json.loads(content)
        except Exception:
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
                            _cleanup_login_states(state)
                            entry = state.setdefault("login", {}).setdefault("states", {}).get(payload)
                            if entry and int(entry.get("exp", 0)) >= int(time.time()):
                                user = msg.get("from") or msg.get("chat") or {}
                                entry["status"] = "approved"
                                entry["approved_at"] = int(time.time())
                                entry["user"] = {
                                    "id": user.get("id"),
                                    "username": user.get("username") or "",
                                    "first_name": user.get("first_name") or "",
                                    "last_name": user.get("last_name") or "",
                                }
                                _save_json(STATE_PATH, state)
                                send_telegram_to(chat_id, f"? ??????! ????????? ?? ????: {SITE_URL}")
                    if CHAT_ID and chat_id == str(CHAT_ID) and text in {"/stats", "stats", "?????", "/?????"}:
                        send_telegram(format_stats(get_stats()))
                    state["offset"] = update_id + 1
                _save_json(STATE_PATH, state)
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
            state = _load_state()
            _cleanup_login_states(state)
            states = state.setdefault("login", {}).setdefault("states", {})
            entry = states.get(state_id)
            if not entry:
                self._send_json(404, {"ok": False, "error": "state_not_found"})
                return
            if entry.get("status") != "approved":
                self._send_json(200, {"ok": False, "status": "pending"})
                return
            try:
                token = _make_session(entry.get("user") or {})
            except RuntimeError as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
                return
            user = entry.get("user") or {}
            states.pop(state_id, None)
            _save_json(STATE_PATH, state)
            self._send_json(200, {"ok": True, "token": token, "user": user})
            return

        if path == "/api/me":
            token = self._get_auth_token()
            user = _verify_session(token)
            if not user:
                self._send_json(401, {"ok": False, "error": "unauthorized"})
                return
            self._send_json(200, {"ok": True, "user": user})
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
            state = _load_state()
            _cleanup_login_states(state)
            states = state.setdefault("login", {}).setdefault("states", {})
            token = secrets.token_urlsafe(16)
            states[token] = {"status": "pending", "exp": int(time.time()) + LOGIN_TTL_SEC}
            _save_json(STATE_PATH, state)
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
            data = self._read_json()
            vacancy = str(data.get("vacancy", "")).strip()
            resume = str(data.get("resume", "")).strip()
            if len(vacancy) < 100 or len(resume) < 100:
                self._send_json(400, {"ok": False, "error": "text_too_short"})
                return
            bump_stat("analyze")
            send_telegram("🔎 Matcher used\nhttps://s.analystexe.ru/matcher.html")
            try:
                result = call_gigachat(vacancy, resume)
            except RuntimeError as exc:
                self._send_json(502, {"ok": False, "error": str(exc)})
                return
            except Exception:
                self._send_json(502, {"ok": False, "error": "gigachat_unavailable"})
                return
            self._send_json(200, result)
            return

        self._send_json(404, {"ok": False, "error": "not_found"})

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    t = threading.Thread(target=poll_telegram, daemon=True)
    t.start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.serve_forever()
