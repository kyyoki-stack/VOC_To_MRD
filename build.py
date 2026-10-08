#!/usr/bin/env python3
"""Build the anonymous cockpit example, or check that its snapshot is current."""
import argparse
import importlib.util
import json
import re
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('voc_renderer', BASE / 'research-core/scripts/render.py')
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


def build_page():
    project = BASE / 'examples/cockpit'
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / 'index.html'
        renderer.render(project, '座舱 AI 语音助手 · 用户之声', output)
        page = output.read_text(encoding='utf-8')
    findings = renderer.csv_read(project / 'data/report_findings.csv', {'title', 'text', 'evidence_ids'})
    related = {r['sample_id'] for r in renderer.csv_read(project / 'data/feedback.csv', renderer.REQUIRED)
               if r['relevance'] == '相关'}
    for finding in findings:
        evidence = {x.strip() for x in finding['evidence_ids'].split(',') if x.strip()}
        if not finding['title'].strip() or not finding['text'].strip() or not evidence or evidence - related:
            raise ValueError('研究结论缺少内容或引用了未纳入的原声')
    pattern = r'(<script id="report-data" type="application/json">)(.*?)(</script>)'
    def replace(match):
        reports = json.loads(match[2])
        reports.update(conclusions=findings, report_filename='用户之声数据分析报告.md', mrd_filename='02-MRD_v2.md')
        return match[1] + renderer.encode(reports) + match[3]
    page, replaced = re.subn(pattern, replace, page, count=1, flags=re.S)
    if replaced != 1:
        raise ValueError('页面缺少报告数据')
    return page


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    output = BASE / 'web/index.html'
    page = build_page()
    if args.check:
        if not output.exists() or output.read_text(encoding='utf-8') != page:
            parser.exit(1, '页面快照需更新，请执行 python3 build.py\n')
        print('页面快照与匿名案例、模板一致。')
    else:
        output.parent.mkdir(exist_ok=True)
        output.write_text(page, encoding='utf-8')
        print('已生成 web/index.html。')


if __name__ == '__main__':
    main()
