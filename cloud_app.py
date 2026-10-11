"""Single-instance cloud service: private sessions, durable jobs, bounded research."""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, jsonify, request, send_file, session

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / 'research-core/scripts'))
import deepseek_research
import render as renderer
from deepseek_client import ResearchError


class JobStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'jobs.sqlite3'
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, topic TEXT NOT NULL,
                    status TEXT NOT NULL, message TEXT NOT NULL, created_at REAL NOT NULL,
                    counts TEXT, url TEXT);
                CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner, created_at);
                CREATE TABLE IF NOT EXISTS login_attempts (bucket TEXT PRIMARY KEY, count INTEGER);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def public(self, row):
        if row is None:
            return None
        data = dict(row)
        data.pop('owner', None)
        data['counts'] = json.loads(data['counts']) if data['counts'] else None
        return data

    def get(self, ident, owner):
        with self.connect() as db:
            return self.public(db.execute('SELECT * FROM jobs WHERE id=? AND owner=?', (ident, owner)).fetchone())

    def history(self, owner):
        with self.connect() as db:
            return [self.public(r) for r in db.execute('SELECT * FROM jobs WHERE owner=? ORDER BY created_at DESC LIMIT 20', (owner,))]

    def enqueue(self, owner, topic, user_limit, global_limit):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            active = db.execute("SELECT id FROM jobs WHERE owner=? AND status IN ('queued','running')", (owner,)).fetchone()
            if active:
                return None, '你已有任务正在进行，请先等待完成', 409
            since = time.time() - 86400
            if db.execute('SELECT COUNT(*) FROM jobs WHERE owner=? AND created_at>?', (owner, since)).fetchone()[0] >= user_limit:
                return None, '已达到此访问码最近24小时的研究次数，请稍后再试', 429
            if db.execute('SELECT COUNT(*) FROM jobs WHERE created_at>?', (since,)).fetchone()[0] >= global_limit:
                return None, '今日研究名额已用完，请稍后再试', 429
            if db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] >= 10:
                return None, '研究队列已满，请稍后再试', 429
            ident = uuid.uuid4().hex
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)',
                       (ident, owner, topic, 'queued', '已进入队列，等待开始研究', time.time(), None, None))
            return ident, None, 202

    def recover(self):
        with self.connect() as db:
            # Never repeat partially charged model calls after a deployment/restart.
            db.execute("UPDATE jobs SET status='failed', message=? WHERE status='running'",
                       ('服务重启中断了本次研究；已保留材料，没有自动重复调用模型，请重新提交',))

    def claim(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE jobs SET status='running', message='正在启动研究' WHERE id=?", (row['id'],))
                return dict(row)

    def update(self, ident, *, status=None, message=None, counts=None, url=None):
        fields = {k: v for k, v in {'status': status, 'message': message,
                  'counts': json.dumps(counts) if counts is not None else None, 'url': url}.items() if v is not None}
        with self.connect() as db:
            db.execute('UPDATE jobs SET ' + ','.join(k+'=?' for k in fields) + ' WHERE id=?', (*fields.values(), ident))

    def login_allowed(self, identity):
        minute = int(time.time() // 600)
        bucket = str(minute) + ':' + identity
        with self.connect() as db:
            db.execute('DELETE FROM login_attempts WHERE bucket < ?', (str(minute-1)+':',))
            db.execute('INSERT INTO login_attempts VALUES (?,1) ON CONFLICT(bucket) DO UPDATE SET count=count+1', (bucket,))
            return db.execute('SELECT count FROM login_attempts WHERE bucket=?', (bucket,)).fetchone()[0] <= 12


def run_job(store, job):
    project = store.directory / job['id']
    try:
        deepseek_research.run(project, job['topic'], lambda message: store.update(job['id'], message=message))
        result = renderer.render(project, job['topic'], project / 'research.html')
        counts = {key: value for key, value in result.items() if key != 'html'}
        store.update(job['id'], status='completed' if counts['related'] else 'empty', counts=counts,
                     message='调研结果已生成' if counts['related'] else '本次未获取到相关反馈，请查看覆盖与失败记录',
                     url=f"/runs/{job['id']}/research.html")
    except Exception as exc:
        # Only deliberately sanitized errors may leave the server.
        store.update(job['id'], status='failed', message=str(exc)[:220] if isinstance(exc, ResearchError)
                     else '研究处理或证据校验失败，已保留本次材料，请稍后重试')


def create_app(config=None, *, start_worker=True):
    app = Flask(__name__, static_folder=None)
    origin = os.environ.get('VOC_PUBLIC_ORIGIN', '').rstrip('/')
    if not origin and os.environ.get('RENDER_EXTERNAL_HOSTNAME'):
        origin = 'https://' + os.environ['RENDER_EXTERNAL_HOSTNAME']
    app.config.update(
        SECRET_KEY=os.environ.get('VOC_SESSION_SECRET', ''),
        ACCESS_CODES=os.environ.get('VOC_ACCESS_CODES', ''),
        PUBLIC_ORIGIN=origin,
        RUNS_DIR=os.environ.get('VOC_RUNS_DIR', '/data/research-runs'),
        USER_DAILY_LIMIT=int(os.environ.get('VOC_USER_DAILY_LIMIT', '3')),
        GLOBAL_DAILY_LIMIT=int(os.environ.get('VOC_GLOBAL_DAILY_LIMIT', '10')),
        MAX_CONTENT_LENGTH=4096,
        SESSION_COOKIE_NAME='voc_session', SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=True, SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    )
    if config:
        app.config.update(config)
    codes = [v.strip() for v in app.config['ACCESS_CODES'].split(',') if v.strip()]
    if len(app.config['SECRET_KEY']) < 32 or not codes or any(len(v) < 16 for v in codes):
        raise ValueError('云服务需要至少32字符的会话密钥和至少16字符的访问码')
    parsed = urlsplit(app.config['PUBLIC_ORIGIN'])
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError('VOC_PUBLIC_ORIGIN 必须是本站 HTTPS 源，不带路径和凭据')
    if min(app.config['USER_DAILY_LIMIT'], app.config['GLOBAL_DAILY_LIMIT']) < 1:
        raise ValueError('研究次数上限必须为正整数')
    owner_for = lambda code: hmac.new(app.config['SECRET_KEY'].encode(), code.encode(), hashlib.sha256).hexdigest()
    owners = {owner_for(code) for code in codes}
    store = JobStore(app.config['RUNS_DIR'])
    app.extensions['jobs'] = store
    wake = threading.Event()

    def worker():
        while True:
            job = store.claim()
            if job:
                if job['owner'] in owners:
                    run_job(store, job)
                else:
                    store.update(job['id'], status='failed', message='访问码已撤销，本次排队任务未执行')
            else:
                wake.wait(2)
                wake.clear()

    if start_worker:
        store.recover()
        threading.Thread(target=worker, name='research-worker', daemon=True).start()

    def owner():
        value = session.get('owner', '')
        return value if value in owners else None

    @app.before_request
    def protect():
        # Host checks protect the public service; local health probes use /healthz only.
        if request.path == '/healthz' and request.method == 'GET':
            return None
        if request.host != parsed.netloc:
            return jsonify(error='请求地址不允许'), 400
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            if request.headers.get('Origin') != app.config['PUBLIC_ORIGIN']:
                return jsonify(error='请从本站页面提交'), 403
            if not (request.path == '/api/session' and request.method == 'POST'):
                expected = session.get('csrf', '')
                supplied = request.headers.get('X-Research-Token', '')
                if not owner() or not expected or not hmac.compare_digest(expected.encode(), supplied.encode()):
                    return jsonify(error='登录已失效，请重新输入访问码'), 401

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        return response

    @app.errorhandler(413)
    def too_large(_):
        return jsonify(error='输入内容过长'), 413

    @app.get('/healthz')
    def healthz():
        with store.connect() as db:
            db.execute('SELECT 1')
        return jsonify(status='ok')

    @app.get('/api/health')
    def health():
        return jsonify(**deepseek_research.readiness(), requires_auth=True,
                       authenticated=bool(owner()), token=session.get('csrf', '') if owner() else '',
                       user_daily_limit=app.config['USER_DAILY_LIMIT'])

    @app.post('/api/session')
    def login():
        # Per-IP throttling uses Render's appended proxy hop, never a client-supplied first hop.
        address = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[-1].strip()
        if not store.login_allowed(owner_for(address)):
            return jsonify(error='尝试次数过多，请10分钟后再试'), 429
        data = request.get_json(silent=True)
        code = data.get('code', '') if isinstance(data, dict) else ''
        if not isinstance(code, str) or not any(hmac.compare_digest(code.encode(), allowed.encode()) for allowed in codes):
            return jsonify(error='访问码不正确，请向网站管理员获取'), 401
        session.clear()
        session.permanent = True
        session['owner'], session['csrf'] = owner_for(code), secrets.token_hex(32)
        return jsonify(authenticated=True)

    @app.delete('/api/session')
    def logout():
        session.clear()
        return jsonify(authenticated=False)

    @app.route('/api/research', methods=['GET', 'POST'])
    def research():
        if not owner():
            return jsonify(error='请输入访问码后开始研究'), 401
        if request.method == 'GET':
            return jsonify(jobs=store.history(owner()))
        data = request.get_json(silent=True)
        topic = data.get('topic', '') if isinstance(data, dict) else ''
        if not isinstance(topic, str) or not 2 <= len(topic.strip()) <= 200:
            return jsonify(error='请输入2–200个字符的研究主题'), 400
        ready = deepseek_research.readiness()
        if not ready['available']:
            return jsonify(error=ready['message']), 503
        ident, error, status = store.enqueue(owner(), topic.strip(), app.config['USER_DAILY_LIMIT'], app.config['GLOBAL_DAILY_LIMIT'])
        if error:
            return jsonify(error=error), status
        wake.set()
        return jsonify(id=ident, status='queued'), status

    @app.get('/api/research/<ident>')
    def job(ident):
        item = store.get(ident, owner()) if owner() else None
        return jsonify(item) if item else (jsonify(error='任务不存在或无权访问'), 404)

    @app.get('/runs/<ident>/research.html')
    def result(ident):
        item = store.get(ident, owner()) if owner() and re.fullmatch(r'[a-f0-9]{32}', ident) else None
        if not item or item['status'] not in {'completed', 'empty'}:
            return jsonify(error='研究结果尚不可访问，请登录后从历史记录打开'), 404
        path = store.directory / ident / 'research.html'
        if not path.is_file():
            return jsonify(error='研究结果文件不存在'), 404
        return send_file(path, mimetype='text/html')

    @app.get('/')
    @app.get('/index.html')
    def homepage():
        return send_file(BASE / 'web/index.html')

    @app.get('/examples/cockpit.html')
    def example():
        return send_file(BASE / 'web/examples/cockpit.html')

    return app
