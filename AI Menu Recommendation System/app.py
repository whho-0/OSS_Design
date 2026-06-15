#!/usr/bin/env python3
import os, json, hashlib, sqlite3, subprocess, sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

try:
    from flask import Flask, render_template, request, jsonify, session
    from groq import Groq
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask", "groq", "-q"])
    from flask import Flask, render_template, request, jsonify, session
    from groq import Groq

app = Flask(__name__)
app.secret_key = "menu_advisor_secret_2026"

GROQ_API_KEY = os.getenv("GROQ_API_KEY")  # 환경변수에서 API 키 읽기


# ══════════════════════════════════════════
# Class 1: DatabaseManager
# ══════════════════════════════════════════
class DatabaseManager:
    def __init__(self, db_path="menu_bot.db"):
        self.db_path = db_path
        self._init_db()

    def conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self):
        with self.conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now','localtime'))
                );
                CREATE TABLE IF NOT EXISTS user_preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL UNIQUE,
                    health_info TEXT DEFAULT '',
                    is_setup_done INTEGER DEFAULT 0,
                    updated_at TEXT DEFAULT (datetime('now','localtime')),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    title TEXT DEFAULT '새 추천',
                    filter_data TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now','localtime')),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now','localtime')),
                    FOREIGN KEY(session_id) REFERENCES chat_sessions(id)
                );
            """)


# ══════════════════════════════════════════
# Class 2: User
# ══════════════════════════════════════════
class User:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def _hash(self, pw):
        return hashlib.sha256(pw.encode()).hexdigest()

    def register(self, username, password):
        try:
            with self.db.conn() as c:
                c.execute("INSERT INTO users (username, password) VALUES (?,?)",
                          (username, self._hash(password)))
            return True, None
        except sqlite3.IntegrityError:
            return False, "이미 존재하는 아이디입니다"

    def login(self, username, password):
        with self.db.conn() as c:
            row = c.execute(
                "SELECT id, username FROM users WHERE username=? AND password=?",
                (username, self._hash(password))
            ).fetchone()
        if row:
            return True, dict(row)
        return False, None


# ══════════════════════════════════════════
# Class 3: AuthManager
# ══════════════════════════════════════════
class AuthManager:
    def __init__(self, user: User):
        self.user = user

    def register(self, username, password, confirm):
        if len(username.strip()) < 2:
            return False, "아이디는 2자 이상이어야 합니다"
        if len(password) < 4:
            return False, "비밀번호는 4자 이상이어야 합니다"
        if password != confirm:
            return False, "비밀번호가 일치하지 않습니다"
        return self.user.register(username.strip(), password)

    def login(self, username, password):
        if not username or not password:
            return False, "아이디와 비밀번호를 입력해주세요"
        ok, user = self.user.login(username.strip(), password)
        if not ok:
            return False, "아이디 또는 비밀번호가 올바르지 않습니다"
        return True, user


# ══════════════════════════════════════════
# Class 4: UserPreference
# ══════════════════════════════════════════
class UserPreference:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def get(self, user_id):
        with self.db.conn() as c:
            row = c.execute("SELECT * FROM user_preferences WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def is_setup_done(self, user_id):
        pref = self.get(user_id)
        return bool(pref and pref["is_setup_done"])

    def save_health(self, user_id, health_info):
        with self.db.conn() as c:
            exists = c.execute("SELECT id FROM user_preferences WHERE user_id=?", (user_id,)).fetchone()
            if exists:
                c.execute(
                    "UPDATE user_preferences SET health_info=?, is_setup_done=1, updated_at=datetime('now','localtime') WHERE user_id=?",
                    (health_info, user_id)
                )
            else:
                c.execute(
                    "INSERT INTO user_preferences (user_id, health_info, is_setup_done) VALUES (?,?,1)",
                    (user_id, health_info)
                )


# ══════════════════════════════════════════
# Class 5: MenuFilter
# ══════════════════════════════════════════
class MenuFilter:
    CATEGORIES = ["한식", "중식", "일식", "양식", "분식", "아시안", "패스트푸드"]

    def build_prompt(self, disliked, soup, food_type, temp, health_info):
        parts = []
        if disliked:
            parts.append(f"제외할 음식 카테고리: {', '.join(disliked)}")
        parts.append(f"국물 여부: {soup}")
        parts.append(f"면/밥 선호: {food_type}")
        parts.append(f"온도: {temp}")
        if health_info:
            parts.append(f"건강/식이 제한: {health_info}")
        return " | ".join(parts)


# ══════════════════════════════════════════
# Class 6: ConversationHistory
# ══════════════════════════════════════════
class ConversationHistory:
    def __init__(self, messages=None):
        self.messages = messages or []

    def add(self, role, content):
        self.messages.append({"role": role, "content": content})

    def to_list(self):
        return self.messages.copy()


# ══════════════════════════════════════════
# Class 7: GroqClientWrapper
# ══════════════════════════════════════════
class GroqClientWrapper:
    def __init__(self, api_key):
        self.client = Groq(api_key=api_key)
        self.model = "llama-3.3-70b-versatile"

    def chat(self, messages):
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,
            max_tokens=1024
        )
        return resp.choices[0].message.content


# ══════════════════════════════════════════
# Class 8: MenuRecommender
# ══════════════════════════════════════════
class MenuRecommender:
    SYSTEM = """
당신은 한국인을 위한 AI 메뉴 추천 시스템이다.

반드시 자연스럽고 완전한 한국어로만 답변해야 한다.
일본어, 중국어, 한자, 영어를 절대 섞지 마라.
모든 메뉴 설명과 추천 이유도 한국어만 사용한다.

사용자의 조건과 건강 상태를 반드시 반영하여 메뉴를 추천한다.

반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 금지):

{
  "menus": [
    {
      "name": "메뉴명",
      "emoji": "이모지",
      "category": "카테고리",
      "description": "한줄설명",
      "reason": "추천이유"
    },
    {
      "name": "메뉴명",
      "emoji": "이모지",
      "category": "카테고리",
      "description": "한줄설명",
      "reason": "추천이유"
    },
    {
      "name": "메뉴명",
      "emoji": "이모지",
      "category": "카테고리",
      "description": "한줄설명",
      "reason": "추천이유"
    }
  ]
}
"""

    def __init__(self, groq: GroqClientWrapper):
        self.groq = groq

    def recommend(self, filter_prompt):
        messages = [
            {"role": "system", "content": self.SYSTEM},
            {"role": "user", "content": f"다음 조건에 맞는 메뉴 3가지를 추천해주세요:\n{filter_prompt}"},
        ]
        raw = self.groq.chat(messages)
        try:
            start, end = raw.find("{"), raw.rfind("}") + 1
            return json.loads(raw[start:end])
        except Exception as e:
            print("===== RAW RESPONSE =====")
            print(raw)

            print("===== ERROR =====")
            print(e)

            return {
                "menus": [
                    {
                        "name": "추천 실패",
                        "emoji": "⚠️",
                        "category": "",
                        "description": raw[:100],
                        "reason": "JSON 파싱 오류"
                    }
                ]
            }

    def chat_refine(self, history, user_msg, health_info):
        system = f"당신은 친절한 메뉴 추천 AI입니다. 건강 정보: {health_info or '없음'}. 이전 추천 맥락을 유지하며 한국어로 답하세요."
        messages = [{"role": "system", "content": system}] + history[-20:] + [{"role": "user", "content": user_msg}]
        return self.groq.chat(messages)


# ══════════════════════════════════════════
# Class 9: ChatSession
# ══════════════════════════════════════════
class ChatSession:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def create(self, user_id, title, filter_data):
        with self.db.conn() as c:
            cur = c.execute(
                "INSERT INTO chat_sessions (user_id, title, filter_data) VALUES (?,?,?)",
                (user_id, title, json.dumps(filter_data))
            )
            return cur.lastrowid

    def get_sessions(self, user_id):
        with self.db.conn() as c:
            rows = c.execute(
                "SELECT * FROM chat_sessions WHERE user_id=? ORDER BY created_at DESC LIMIT 30",
                (user_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def add_message(self, session_id, role, content):
        with self.db.conn() as c:
            c.execute("INSERT INTO messages (session_id, role, content) VALUES (?,?,?)",
                      (session_id, role, content))

    def get_messages(self, session_id):
        with self.db.conn() as c:
            rows = c.execute(
                "SELECT role, content, created_at FROM messages WHERE session_id=? ORDER BY created_at",
                (session_id,)
            ).fetchall()
        return [dict(r) for r in rows]


# ══════════════════════════════════════════
# Class 10: AppController
# ══════════════════════════════════════════
class AppController:
    def __init__(self):
        self.db = DatabaseManager()
        self.user_model = User(self.db)
        self.auth = AuthManager(self.user_model)
        self.preference = UserPreference(self.db)
        self.menu_filter = MenuFilter()
        self.groq = GroqClientWrapper(GROQ_API_KEY)
        self.recommender = MenuRecommender(self.groq)
        self.chat_session = ChatSession(self.db)


ctrl = AppController()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/me")
def me():
    if "user" not in session:
        return jsonify({"ok": False})
    uid = session["user"]["id"]
    return jsonify({"ok": True, "user": session["user"], "setup_done": ctrl.preference.is_setup_done(uid)})


@app.route("/api/register", methods=["POST"])
def register():
    d = request.json
    ok, err = ctrl.auth.register(d["username"], d["password"], d["confirm"])
    if not ok:
        return jsonify({"ok": False, "error": err})
    _, user = ctrl.user_model.login(d["username"], d["password"])
    session["user"] = user
    return jsonify({"ok": True})


@app.route("/api/login", methods=["POST"])
def login():
    d = request.json
    ok, result = ctrl.auth.login(d["username"], d["password"])
    if not ok:
        return jsonify({"ok": False, "error": result})
    session["user"] = result
    return jsonify({"ok": True, "setup_done": ctrl.preference.is_setup_done(result["id"]), "username": result["username"]})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/save_health", methods=["POST"])
def save_health():
    if "user" not in session:
        return jsonify({"ok": False, "error": "로그인 필요"})
    ctrl.preference.save_health(session["user"]["id"], request.json.get("health_info", ""))
    return jsonify({"ok": True})


@app.route("/api/recommend", methods=["POST"])
def recommend():
    if "user" not in session:
        return jsonify({"ok": False, "error": "로그인 필요"})
    d = request.json
    uid = session["user"]["id"]
    pref = ctrl.preference.get(uid)
    health_info = pref["health_info"] if pref else ""

    filter_prompt = ctrl.menu_filter.build_prompt(
        d.get("disliked", []), d.get("soup", "상관없음"),
        d.get("type", "상관없음"), d.get("temp", "상관없음"), health_info
    )
    result = ctrl.recommender.recommend(filter_prompt)
    title = f"추천 {datetime.now().strftime('%m/%d %H:%M')}"
    sid = ctrl.chat_session.create(uid, title, d)
    ctrl.chat_session.add_message(sid, "assistant", json.dumps(result, ensure_ascii=False))
    session["current_session_id"] = sid
    session["health_info"] = health_info
    return jsonify({"ok": True, "result": result, "session_id": sid})


@app.route("/api/chat", methods=["POST"])
def chat():
    if "user" not in session:
        return jsonify({"ok": False, "error": "로그인 필요"})
    d = request.json
    sid = d.get("session_id") or session.get("current_session_id")
    user_msg = d["message"]
    msgs = ctrl.chat_session.get_messages(sid)
    history = [{"role": m["role"], "content": m["content"]} for m in msgs if m["role"] in ("user", "assistant")]
    ctrl.chat_session.add_message(sid, "user", user_msg)
    reply = ctrl.recommender.chat_refine(history, user_msg, session.get("health_info", ""))
    ctrl.chat_session.add_message(sid, "assistant", reply)
    return jsonify({"ok": True, "reply": reply})


@app.route("/api/sessions")
def get_sessions():
    if "user" not in session:
        return jsonify({"ok": False})
    return jsonify({"ok": True, "sessions": ctrl.chat_session.get_sessions(session["user"]["id"])})


@app.route("/api/session/<int:sid>")
def get_session(sid):
    if "user" not in session:
        return jsonify({"ok": False})
    return jsonify({"ok": True, "messages": ctrl.chat_session.get_messages(sid)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
