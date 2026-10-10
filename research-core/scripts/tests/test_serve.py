"""Backend contract tests. Fixtures are synthetic and are never research evidence."""
import csv
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.parse import quote
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import serve


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'index.html').write_text('test page')
        serve.JOBS.clear()
        self.server = serve.ThreadingHTTPServer(('127.0.0.1', 0), serve.make_handler(self.root, self.root / 'runs', '/test/codex', 'test-token'))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.temp.cleanup()

    def post(self, data, token='test-token', origin=None):
        headers = {'Content-Type': 'application/json', 'X-Research-Token': token}
        if origin: headers['Origin'] = origin
        return urlopen(Request(self.url + '/api/research', data=json.dumps(data).encode(), headers=headers))

    def test_health_and_reject_invalid_queries(self):
        self.assertTrue(json.load(urlopen(self.url + '/api/health'))['available'])
        for topic in ['', 'x', 'x' * 201]:
            with self.assertRaises(HTTPError) as error: self.post({'topic': topic})
            self.assertEqual(error.exception.code, 400)

    def test_example_route_is_explicit_and_other_files_stay_private(self):
        directory = self.root / 'examples'
        directory.mkdir()
        (directory / 'cockpit.html').write_text('anonymous example')
        (directory / 'private.txt').write_text('private fixture')
        self.assertEqual(urlopen(self.url + '/examples/cockpit.html').read(), b'anonymous example')
        with self.assertRaises(HTTPError) as error:
            urlopen(self.url + '/examples/private.txt')
        self.assertEqual(error.exception.code, 404)

    def test_cross_origin_and_missing_token_rejected(self):
        for kwargs in [{'token': ''}, {'origin': 'https://external.example'}]:
            with self.assertRaises(HTTPError) as error: self.post({'topic': '测试主题'}, **kwargs)
            self.assertEqual(error.exception.code, 403)

    def test_unknown_host_rejected(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.url + '/api/health', headers={'Host': 'external.example'}))
        self.assertEqual(error.exception.code, 403)

    def test_docker_remapped_port_and_origin(self):
        self.server.RequestHandlerClass = serve.make_handler(self.root, self.root / 'runs', None, 'test-token', public_port=8781)
        headers = {'Host': 'localhost:8781', 'Origin': 'http://localhost:8781'}
        health = json.load(urlopen(Request(self.url + '/api/health', headers=headers)))
        self.assertFalse(health['available'])
        for field, value in [('Host', 'localhost:9999'), ('Origin', 'https://external.example')]:
            invalid = dict(headers)
            invalid[field] = value
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(self.url + '/api/health', headers=invalid))
            self.assertEqual(error.exception.code, 403)

    def test_missing_executor_does_not_queue_fake_research(self):
        self.server.RequestHandlerClass = serve.make_handler(self.root, self.root / 'runs', None, 'test-token')
        self.assertFalse(json.load(urlopen(self.url + '/api/health'))['available'])
        with self.assertRaises(HTTPError) as error:
            self.post({'topic': '测试研究主题'})
        self.assertEqual(error.exception.code, 503)
        self.assertFalse(serve.JOBS)

    def test_new_topic_dispatch_and_duplicate_block(self):
        with patch.object(serve, 'run_research') as worker:
            job = json.load(self.post({'topic': '测试主题'}))
            self.assertEqual(job['status'], 'queued')
            self.assertNotIn('/', job['id'])
            self.assertEqual(json.load(urlopen(self.url + '/api/research/' + job['id']))['topic'], '测试主题')
            with self.assertRaises(HTTPError) as error: self.post({'topic': '另一主题'})
            self.assertEqual(error.exception.code, 409)

    def test_worker_arguments_and_failure_status(self):
        ident = 'a' * 32
        serve.JOBS[ident] = {'status': 'queued'}
        with patch.object(serve.subprocess, 'run') as execute:
            execute.return_value.returncode = 1
            serve.run_research(ident, self.root / 'runs' / ident, '测试主题; touch /tmp/never-run', '/test/codex')
            args, kwargs = execute.call_args
            self.assertEqual(args[0][0:2], ['/test/codex', 'exec'])
            self.assertIn('--approve-for-me', args[0])
            self.assertEqual(args[0][args[0].index('--sandbox') + 1], 'workspace-write')
            self.assertNotIn('danger-full-access', args[0])
            self.assertNotIn('测试主题; touch /tmp/never-run', args[0])
            self.assertNotIn('shell', kwargs)
            self.assertIn('测试主题', kwargs['input'])
        self.assertEqual(serve.JOBS[ident]['status'], 'failed')

    def test_empty_real_collection_creates_honest_result_page(self):
        ident = 'b' * 32
        project = self.root / 'runs' / ident
        serve.JOBS[ident] = {'status': 'queued'}
        def execute(command, **kwargs):
            for filename, fields in [('feedback.csv', sorted(serve.renderer.REQUIRED)), ('needs.csv', sorted(serve.renderer.NEED_FIELDS)), ('source_audit.csv', ['source_id', 'url', 'status', 'decision', 'sample_ids'])]:
                with (project / 'data' / filename).open('w', newline='') as file:
                    csv.DictWriter(file, fieldnames=fields).writeheader()
            for filename in ['01-数据分析报告.md', '02-MRD.md', '03-洞察总结.md']:
                (project / 'docs' / filename).write_text('# 合成测试：空采集状态\n没有相关评论，不能推断需求。')
            class Result: returncode = 0
            return Result()
        with patch.object(serve.subprocess, 'run', side_effect=execute):
            serve.run_research(ident, project, '合成测试主题', '/test/codex')
        self.assertEqual(serve.JOBS[ident]['status'], 'empty')
        self.assertEqual(serve.JOBS[ident]['counts']['related'], 0)
        self.assertNotIn('html', serve.JOBS[ident]['counts'])
        self.assertTrue((project / 'research.html').exists())
        self.assertEqual(serve.JOBS[ident]['url'], '/runs/' + ident + '/research.html')

    def test_output_not_exposed_before_exists_and_traversal_rejected(self):
        for path in ['/runs/' + 'a' * 32 + '/research.html', '/runs/' + 'a' * 32 + '/docs/04-执行结果.md', '/scripts/render.py']:
            with self.assertRaises(HTTPError): urlopen(self.url + quote(path))


if __name__ == '__main__': unittest.main()
