"""Cloud isolation, restart and quota tests; never call a paid provider."""
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from cloud_app import JobStore, create_app, run_job

ORIGIN = 'https://voc.example'
CODE_A, CODE_B = 'synthetic-access-a-123456', 'synthetic-access-b-123456'


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = dict(TESTING=True, SECRET_KEY='synthetic-session-secret-'*3,
                           ACCESS_CODES=CODE_A+','+CODE_B, PUBLIC_ORIGIN=ORIGIN,
                           RUNS_DIR=self.temp.name, USER_DAILY_LIMIT=2, GLOBAL_DAILY_LIMIT=3)
        self.app = create_app(self.config, start_worker=False)
        self.client = self.app.test_client()
        self.store = self.app.extensions['jobs']
        self.ready = patch('cloud_app.deepseek_research.readiness', return_value={'available': True, 'message': 'test'})
        self.ready.start()
        self.addCleanup(self.ready.stop)

    def get(self, path, client=None):
        return (client or self.client).get(path, base_url=ORIGIN)

    def post(self, path, payload, client=None, token=None, origin=ORIGIN):
        client = client or self.client
        if token is None:
            token = self.get('/api/health', client).json['token']
        return client.post(path, json=payload, base_url=ORIGIN,
                           headers={'Origin': origin, 'X-Research-Token': token})

    def login(self, client=None, code=CODE_A):
        response = self.post('/api/session', {'code': code}, client)
        self.assertEqual(response.status_code, 200)
        return response

    def test_anonymous_cannot_submit_or_see_jobs(self):
        health = self.get('/api/health').json
        self.assertTrue(health['requires_auth'])
        self.assertFalse(health['authenticated'])
        self.assertEqual(health['token'], '')
        self.assertEqual(self.post('/api/research', {'topic': 'test'}).status_code, 401)
        self.assertEqual(self.get('/api/research').status_code, 401)

    def test_origin_csrf_and_secure_cookie(self):
        response = self.login()
        cookie = response.headers['Set-Cookie']
        for attribute in ['Secure', 'HttpOnly', 'SameSite=Lax']:
            self.assertIn(attribute, cookie)
        self.assertEqual(self.post('/api/research', {'topic': 'test'}, origin='https://evil.example').status_code, 403)
        self.assertEqual(self.post('/api/research', {'topic': 'test'}, token='wrong').status_code, 401)
        self.assertEqual(self.post('/api/research', {'topic': 'test'}, token='中文').status_code, 401)
        self.assertEqual(self.client.get('/api/health', base_url='https://evil.example').status_code, 400)
        self.assertEqual(self.client.delete('/api/session', base_url=ORIGIN, headers={'Origin': ORIGIN}).status_code, 401)

    def test_owner_isolation_for_results_and_history(self):
        self.login()
        ident = self.post('/api/research', {'topic': 'synthetic topic'}).json['id']
        project = Path(self.temp.name)/ident
        project.mkdir()
        (project/'research.html').write_text('<p>synthetic private result</p>')
        self.store.update(ident, status='completed', url=f'/runs/{ident}/research.html')
        other = self.app.test_client()
        self.login(other, CODE_B)
        self.assertEqual(self.get('/api/research', other).json['jobs'], [])
        for path in [f'/api/research/{ident}', f'/runs/{ident}/research.html']:
            self.assertEqual(self.get(path, other).status_code, 404)
            response = self.get(path)
            self.assertEqual(response.status_code, 200)
            response.close()
        self.assertNotIn('owner', self.get(f'/api/research/{ident}').json)

    def test_revoking_code_removes_old_session_access(self):
        self.login()
        with self.client.session_transaction(base_url=ORIGIN) as s:
            signed_state = dict(s)
        new_app = create_app({**self.config, 'ACCESS_CODES': CODE_B}, start_worker=False)
        other = new_app.test_client()
        with other.session_transaction(base_url=ORIGIN) as s:
            s.update(signed_state)
        self.assertFalse(self.get('/api/health', other).json['authenticated'])

    def test_login_invalid_and_throttled(self):
        for code in ['错误访问码', {}, 'bad']:
            self.assertEqual(self.post('/api/session', {'code': code}).status_code, 401)
        for _ in range(9):
            self.post('/api/session', {'code': 'bad'})
        self.assertEqual(self.post('/api/session', {'code': CODE_A}).status_code, 429)

    def test_input_limits_and_private_paths(self):
        self.login()
        for topic in ['', 'a', [], 'a'*201]:
            self.assertEqual(self.post('/api/research', {'topic': topic}).status_code, 400)
        self.assertEqual(self.post('/api/research', {'topic': 'a'*5000}).status_code, 413)
        for path in ['/.env', '/jobs.sqlite3', '/research-runs/', '/runs/../research.html']:
            self.assertEqual(self.get(path).status_code, 404)

    def test_persistent_quotas_and_atomic_double_submit(self):
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.store.enqueue('one', 'synthetic', 2, 3), range(2)))
        self.assertEqual(sorted(r[2] for r in results), [202, 409])
        for record in self.store.history('one'):
            self.store.update(record['id'], status='completed')
        ident, _, _ = self.store.enqueue('one', 'second', 2, 3)
        self.store.update(ident, status='failed')
        fresh = JobStore(self.temp.name)
        self.assertEqual(fresh.enqueue('one', 'third', 2, 3)[2], 429)
        ident, _, code = fresh.enqueue('two', 'third', 2, 3)
        self.assertEqual(code, 202)
        self.assertEqual(fresh.enqueue('three', 'fourth', 2, 3)[2], 429)

    def test_restart_does_not_repeat_running_billed_work(self):
        first, _, _ = self.store.enqueue('a', 'first', 2, 3)
        self.store.claim()
        second, _, _ = self.store.enqueue('b', 'second', 2, 3)
        fresh = JobStore(self.temp.name)
        fresh.recover()
        self.assertEqual(fresh.get(first, 'a')['status'], 'failed')
        self.assertEqual(fresh.claim()['id'], second)
        self.assertIsNone(fresh.claim())

    def test_missing_provider_config_does_not_enqueue(self):
        self.login()
        with patch('cloud_app.deepseek_research.readiness', return_value={'available': False, 'message': 'not ready'}):
            self.assertEqual(self.post('/api/research', {'topic': 'synthetic'}).status_code, 503)
        self.assertEqual(self.get('/api/research').json['jobs'], [])

    def test_unexpected_errors_do_not_leak_provider_data(self):
        ident, _, _ = self.store.enqueue('a', 'synthetic', 2, 3)
        job = self.store.claim()
        with patch('cloud_app.deepseek_research.run', side_effect=RuntimeError('SYNTHETIC_SECRET')):
            run_job(self.store, job)
        record = self.store.get(ident, 'a')
        self.assertEqual(record['status'], 'failed')
        self.assertNotIn('SYNTHETIC_SECRET', str(record))

    def test_cloud_requires_private_credentials_and_https(self):
        for change in [{'SECRET_KEY': 'short'}, {'ACCESS_CODES': 'short'}, {'PUBLIC_ORIGIN': 'http://voc.example'},
                       {'PUBLIC_ORIGIN': 'https://voc.example/path'}]:
            with self.assertRaises(ValueError):
                create_app({**self.config, **change}, start_worker=False)


if __name__ == '__main__':
    unittest.main()
