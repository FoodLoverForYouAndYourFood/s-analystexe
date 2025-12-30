#!/usr/bin/env python3
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import ssl
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

STATE_PATH = "/opt/screener-bot/state.json"
STATS_PATH = "/opt/screener-bot/stats.json"
VISIT_TTL_SEC = 6 * 60 * 60


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


def _urlopen(req: urllib.request.Request, timeout: int = 20):
    if GIGACHAT_INSECURE:
        ctx = ssl._create_unverified_context()
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)
    return urllib.request.urlopen(req, timeout=timeout)


def send_telegram(text: str) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": CHAT_ID, "text": text}).encode("utf-8")
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
    if not BOT_TOKEN or not CHAT_ID:
        return
    while True:
        try:
            state = _load_json(STATE_PATH, {"last_seen": {}, "offset": 0})
            offset = int(state.get("offset", 0))
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=0"
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                for item in data.get("result", []):
                    update_id = int(item.get("update_id", 0))
                    msg = item.get("message", {})
                    text = (msg.get("text") or "").strip().lower()
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    if chat_id == str(CHAT_ID) and text in {"/stats", "stats", "стата", "/стата"}:
                        send_telegram(format_stats(get_stats()))
                    state["offset"] = update_id + 1
                _save_json(STATE_PATH, state)
        except Exception:
            pass
        time.sleep(5)


class Handler(BaseHTTPRequestHandler):
    server_version = "screener-bot/1.5"

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

    def do_POST(self):
        if self.path == "/api/event":
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

        if self.path == "/api/lead":
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

        if self.path == "/api/analyze":
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
