#!/usr/bin/env python3
"""Build a generic homepage and a separate anonymous research example."""
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
    return page.replace('<body>', '<body data-page="example" data-execution="local">', 1).replace(
        '<!-- PAGE_LINKS -->', '<a class="hero-link" href="../index.html">返回通用首页 ↗</a>', 1
    ).replace('<!-- PAGE_CONTEXT -->', '<p class="example-note">研究示例 · 既有匿名座舱数据，包含多个品牌与渠道，非本次新采集。</p>', 1)


def build_homepage():
    page = (BASE / 'research-core/assets/template.html').read_text(encoding='utf-8')
    replacements = {
        '__REVIEW_DATA__': '[]', '__NEED_DATA__': '[]', '__AUDIT_DATA__': '[]',
        '__REPORT_DATA__': renderer.encode({'report': '', 'mrd': ''}),
        '__SUMMARY_DATA__': renderer.encode({'heading': '', 'text': ''}),
        '__RESEARCH_TITLE__': 'VOC_To_MRD · 用户原声',
    }
    page = re.sub('|'.join(map(re.escape, replacements)), lambda m: replacements[m.group()], page)
    return page.replace('<body>', '<body data-page="home" data-execution="local">', 1).replace(
        '<!-- PAGE_LINKS -->', '<a class="hero-link" href="examples/cockpit.html#voices">查看座舱研究示例 ↗</a>', 1
    ).replace('<!-- PAGE_CONTEXT -->', '', 1)


def build_pages(static=False):
    pages = {'index.html': build_homepage(), 'examples/cockpit.html': build_page()}
    if static:
        pages = {path: page.replace('data-execution="local"', 'data-execution="static"', 1)
                 for path, page in pages.items()}
    return pages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--static', action='store_true', help='Build public pages without the local research executor')
    parser.add_argument('--output', type=Path, default=BASE / 'web')
    args = parser.parse_args()
    for path, page in build_pages(args.static).items():
        output = args.output / path
        if args.check:
            if not output.exists() or output.read_text(encoding='utf-8') != page:
                parser.exit(1, '页面快照需更新，请执行 python3 build.py\n')
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(page, encoding='utf-8')
    print('通用首页与研究示例快照一致。' if args.check else '已生成通用首页与独立研究示例。')


if __name__ == '__main__':
    main()
