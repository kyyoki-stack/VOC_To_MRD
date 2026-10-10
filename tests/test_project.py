"""Build and evidence-contract checks; altered fixtures stay in temporary directories."""
import csv
import importlib.util
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('voc_build', BASE / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class ProjectTests(unittest.TestCase):
    def test_page_snapshot_and_findings_reference_real_case_records(self):
        page = build.build_page()
        self.assertEqual(page, (BASE / 'web/examples/cockpit.html').read_text(encoding='utf-8'))
        rows = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S)[1])
        reports = json.loads(re.search(r'<script id="report-data" type="application/json">(.*?)</script>', page, re.S)[1])
        ids = {row['sample_id'] for row in rows if row['relevance'] == '相关'}
        self.assertTrue(reports['conclusions'])
        for finding in reports['conclusions']:
            self.assertFalse(set(finding['evidence_ids'].split(',')) - ids)
        self.assertNotIn('阅读 MRD', page)
        self.assertIn('id="report-findings"', page)

    def test_homepage_and_public_mode_do_not_reuse_example_results(self):
        pages = build.build_pages(static=True)
        home, example = pages['index.html'], pages['examples/cockpit.html']
        for key in ['data', 'need-data', 'audit-data']:
            payload = json.loads(re.search(r'<script id="' + key + r'" type="application/json">(.*?)</script>', home, re.S)[1])
            self.assertEqual(payload, [])
        self.assertNotIn('魏牌', home)
        self.assertIn('data-page="home"', home)
        self.assertIn('data-execution="static"', home)
        self.assertIn('href="examples/cockpit.html#voices"', home)
        self.assertIn('既有匿名座舱数据', example)
        self.assertIn('href="../index.html"', example)
        self.assertEqual(build.build_homepage(), (BASE / 'web/index.html').read_text(encoding='utf-8'))

    def test_missing_evidence_is_rejected_before_rendering(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'case'
            shutil.copytree(BASE / 'examples/cockpit', project)
            path = project / 'data/needs.csv'
            with path.open(encoding='utf-8-sig', newline='') as file:
                reader = csv.DictReader(file)
                fields, rows = reader.fieldnames, list(reader)
            rows[0]['evidence_ids'] = 'UNVERIFIED_TEST_RECORD'
            with path.open('w', encoding='utf-8-sig', newline='') as file:
                writer = csv.DictWriter(file, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, '需求引用不存在'):
                build.renderer.render(project, '测试', project / 'output.html')
            self.assertFalse((project / 'output.html').exists())

    def test_document_text_cannot_break_out_of_script_data(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'case'
            shutil.copytree(BASE / 'examples/cockpit', project)
            payload = '</script><script>synthetic_security_test()</script>'
            (project / 'docs/01-数据分析报告.md').write_text(payload, encoding='utf-8')
            output = project / 'output.html'
            build.renderer.render(project, '合成安全测试', output)
            page = output.read_text(encoding='utf-8')
            self.assertNotIn(payload, page)
            data = re.search(r'<script id="report-data" type="application/json">(.*?)</script>', page, re.S)[1]
            self.assertEqual(json.loads(data)['report'], payload)


if __name__ == '__main__':
    unittest.main()
