"""Synthetic fixtures only; no real model requests, research, or credentials."""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deepseek_client as api
import deepseek_research as research
import render as renderer
import settings


def collection():
    return {'comments': [{'quote': '合成测试原声：导航识别错误。', 'source_url': 'https://example.org/comment/1',
                          'platform': '合成测试', 'published_at': '2026-01-01'}],
            'sources': [{'url': 'https://example.org/comment/1', 'status': '合成成功', 'decision': '仅用于测试'}]}


def labels():
    row = {key: '合成测试标注' for key in research.LABEL_FIELDS}
    row.update(sample_id='R0001', relevance='相关', sentiment='负面', evidence_strength='低',
               quote='模型试图改写原声', source_url='https://invalid.example/model')
    return {'labels': [row]}


def insights():
    need = {key: '合成测试需求' for key in renderer.NEED_FIELDS}
    need.update(need_id='ignored', evidence_ids='R0001', priority='P1')
    return {'needs': [need], 'summary': {'heading': '合成测试结论', 'text': '仅有一条合成记录，不能外推。'}}


class DeepSeekTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'synthetic-key', 'DEEPSEEK_MODEL': 'deepseek-v4-pro'}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_configuration_requires_model_and_collector_without_exposing_secrets(self):
        self.assertFalse(research.readiness()['available'])
        os.environ['VOC_COLLECTOR_URL'] = 'https://collector.example/comments'
        self.assertTrue(research.readiness()['available'])
        self.assertNotIn('synthetic-key', json.dumps(research.readiness()))
        os.environ['VOC_COLLECTOR_URL'] = 'https://user:secret@collector.example/'
        self.assertFalse(research.readiness()['available'])
        self.assertNotIn('secret', json.dumps(research.readiness()))
        os.environ['DEEPSEEK_API_KEY'] = ''
        with self.assertRaisesRegex(api.ResearchError, '密钥'):
            api.DeepSeekClient()

    def test_env_is_literal_allowlisted_and_does_not_override_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / '.env'
            file.write_text('DEEPSEEK_API_KEY=wrong\nVOC_COLLECTOR_TOKEN="$(never-run)"\nHOME=not-home\n')
            settings.load_env(file)
        self.assertEqual(os.environ['DEEPSEEK_API_KEY'], 'synthetic-key')
        self.assertEqual(os.environ['VOC_COLLECTOR_TOKEN'], '$(never-run)')
        self.assertNotIn('HOME', os.environ)

    def test_dedup_and_provenance_are_source_controlled(self):
        source = collection()
        source['comments'] *= 2
        rows, audit = research.normalize_comments(source)
        self.assertEqual(len(rows), 1)
        self.assertEqual(audit[0]['sample_ids'], 'R0001')
        research.apply_labels(rows, labels())
        self.assertEqual(rows[0]['quote'], source['comments'][0]['quote'])
        self.assertEqual(rows[0]['source_url'], source['comments'][0]['source_url'])
        self.assertEqual(rows[0]['published_at'], '2026-01-01')

    def test_missing_source_and_contact_information_rejected(self):
        source = collection()
        source['sources'][0]['url'] = 'https://example.org/other'
        with self.assertRaisesRegex(api.ResearchError, '来源获取记录'):
            research.normalize_comments(source)
        source = collection()
        source['comments'][0]['quote'] = '请联系 synthetic@example.org'
        with self.assertRaisesRegex(api.ResearchError, '联系方式'):
            research.normalize_comments(source)
        source = collection()
        source['sources'][0]['url'] = None
        with self.assertRaises(api.ResearchError):
            research.normalize_comments(source)

    def test_unknown_or_duplicate_model_ids_and_unsupported_evidence_rejected(self):
        rows, _ = research.normalize_comments(collection())
        output = labels()
        output['labels'][0]['sample_id'] = 'R9999'
        with self.assertRaises(api.ResearchError):
            research.apply_labels(rows, output)
        two_rows = rows + [{**rows[0], 'sample_id': 'R0002'}]
        output = labels()
        output['labels'] *= 2
        with self.assertRaises(api.ResearchError):
            research.apply_labels(two_rows, output)
        output = labels()
        output['labels'][0]['evidence_strength'] = '高'
        with self.assertRaises(api.ResearchError):
            research.apply_labels(rows, output)
        with self.assertRaisesRegex(api.ResearchError, '未纳入'):
            research.validate_insights(insights(), rows)

    def test_full_pipeline_report_precedes_mrd_and_renders_real_input(self):
        sections = {'sections': [{'content': '合成测试：依据 R0001，仍待验证。'} for _ in research.MRD_HEADINGS]}
        with tempfile.TemporaryDirectory() as directory, patch.object(research, 'DeepSeekClient') as factory:
            project = Path(directory)
            client = factory.return_value
            client.model = 'synthetic-model'
            def reply(instruction, data, **kwargs):
                if 'headings' in data:
                    self.assertEqual(data['data_report'], (project / 'docs/01-数据分析报告.md').read_text())
                    self.assertNotIn('comments', data)
                    return sections
                return labels() if 'labels' in instruction else insights()
            client.json.side_effect = reply
            research.run(project, '合成测试主题', collected=collection())
            result = renderer.render(project, '合成测试', project / 'research.html')
            self.assertEqual((result['collected'], result['related'], result['needs']), (1, 1, 1))
            self.assertEqual(client.json.call_count, 3)
            report = (project / 'docs/01-数据分析报告.md').read_text()
            self.assertIn('本轮未联网重新采集', report)
            self.assertIn(collection()['comments'][0]['quote'], report)
            self.assertNotIn('模型试图改写原声', report)
            self.assertEqual((project / 'docs/02-MRD.md').read_text().count('\n## '), 11)

    def test_empty_collector_result_produces_empty_page_without_model_inference(self):
        payload = collection()
        payload['comments'] = []
        payload['sources'][0].update(status='失败', decision='合成渠道无法访问')
        os.environ['VOC_COLLECTOR_URL'] = 'https://collector.example/comments'
        with tempfile.TemporaryDirectory() as directory, patch.object(research, 'post_json', return_value=payload) as collect, patch.object(research, 'DeepSeekClient') as factory:
            factory.return_value.model = 'synthetic-model'
            project = Path(directory)
            research.run(project, '空结果测试')
            result = renderer.render(project, '空结果测试', project / 'research.html')
            self.assertEqual((result['collected'], result['related'], result['needs']), (0, 0, 0))
            factory.return_value.json.assert_not_called()
            self.assertEqual(collect.call_args.args[1]['topic'], '空结果测试')

    def test_mrd_cannot_cite_uncollected_records(self):
        output = {'sections': [{'content': '伪造引用 R9999'} for _ in research.MRD_HEADINGS]}
        with tempfile.TemporaryDirectory() as directory, patch.object(research, 'DeepSeekClient') as factory:
            factory.return_value.model = 'synthetic-model'
            factory.return_value.json.side_effect = [labels(), insights(), output]
            with self.assertRaisesRegex(api.ResearchError, 'MRD引用'):
                research.run(Path(directory), '合成测试', collected=collection())
            self.assertFalse((Path(directory) / 'docs/02-MRD.md').exists())

    def test_api_contract_and_truncated_or_empty_json_rejected(self):
        response = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}', 'reasoning_content': 'discard'}}]}
        with patch.object(api, 'post_json', return_value=response) as post:
            self.assertEqual(api.DeepSeekClient().json('返回JSON', {}, thinking=False), {'ok': True})
            url, request, key = post.call_args.args
            self.assertEqual(url, 'https://api.deepseek.com/chat/completions')
            self.assertEqual(key, 'synthetic-key')
            self.assertEqual(request['model'], 'deepseek-v4-pro')
            self.assertEqual(request['response_format'], {'type': 'json_object'})
            response['choices'][0]['finish_reason'] = 'length'
            with self.assertRaises(api.ResearchError):
                api.DeepSeekClient().json('返回JSON', {})
            response['choices'][0].update(finish_reason='stop', message={'content': ''})
            with self.assertRaises(api.ResearchError):
                api.DeepSeekClient().json('返回JSON', {})

    def test_upstream_errors_do_not_echo_body_credentials_and_retry_is_bounded(self):
        for status in [401, 402, 429, 500]:
            with self.subTest(status=status), patch.object(api, 'build_opener') as factory, patch.object(api.time, 'sleep'):
                opener = factory.return_value
                opener.open.side_effect = lambda *a, **k: (_ for _ in ()).throw(HTTPError('https://api.deepseek.com/', status, 'synthetic-key', {}, io.BytesIO(b'synthetic-key')))
                with self.assertRaises(api.ResearchError) as error:
                    api.post_json('https://api.deepseek.com/chat/completions', {}, retries=2)
                self.assertIn(str(status), str(error.exception))
                self.assertNotIn('synthetic-key', str(error.exception))
                self.assertEqual(opener.open.call_count, 3 if status in {429, 500} else 1)


if __name__ == '__main__':
    unittest.main()
