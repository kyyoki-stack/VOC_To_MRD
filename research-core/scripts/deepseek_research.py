"""Analyze collected comments with DeepSeek; never ask the model to invent sources."""
import csv
import json
import os
import re
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import render as renderer
from deepseek_client import DeepSeekClient, ResearchError, post_json
from settings import model_name

SKILL = Path(__file__).resolve().parents[1]
LABEL_FIELDS = ('relevance sentiment theme usage_scene pain_point task_impact evidence_strength '
                'evidence_basis relevance_reason desired_outcome_inferred limitations').split()
MRD_HEADINGS = ['背景与目标', '市场分析', '目标用户', '用户需求与痛点', '竞品分析',
                '产品定位与价值主张', '需求清单与优先级', '商业模式与收益',
                '成功指标', '风险与依赖', '里程碑']
AUDIT_FIELDS = ['source_id', 'url', 'status', 'decision', 'sample_ids']


def collector_url():
    value = os.environ.get('VOC_COLLECTOR_URL', '').strip()
    if not value:
        return ''
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ResearchError('评论采集服务需配置无内嵌凭据、无查询参数的 HTTPS 地址')
    return value


def readiness():
    configured = bool(os.environ.get('DEEPSEEK_API_KEY', '').strip())
    try:
        model = model_name()
        collecting = bool(collector_url())
        message = ('尚未配置 DeepSeek API 密钥' if not configured else
                   'DeepSeek 已配置；真实评论采集服务尚未配置' if not collecting else
                   '研究服务配置已齐全；密钥与渠道可用性将在执行时验证')
    except (ValueError, ResearchError) as exc:
        model, collecting, message = '', False, str(exc)
    return {'backend': 'deepseek', 'model': model, 'analysis_configured': configured,
            'collection_configured': collecting, 'available': configured and collecting and bool(model),
            'message': message, 'collection_ready': '渠道正文获取与密钥有效性以实际执行结果为准'}


def text(value, label, limit=12000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ResearchError(label + '缺失或格式无效')
    return value


def normalize_comments(payload):
    if not isinstance(payload, dict):
        raise ResearchError('采集服务需返回 JSON 对象')
    comments = payload.get('comments')
    if not isinstance(comments, list) or len(comments) > 60:
        raise ResearchError('采集服务需返回 comments 数组，首轮最多60条')
    if not isinstance(payload.get('sources'), list) or not 1 <= len(payload['sources']) <= 60:
        raise ResearchError('采集服务必须记录来源及访问结果，包括空结果和失败渠道')
    rows, seen = [], set()
    for comment in comments:
        if not isinstance(comment, dict):
            raise ResearchError('采集记录格式无效')
        quote = text(comment.get('quote'), '原声')
        url = text(comment.get('source_url'), '原文链接', 2000)
        renderer.safe_url(url)
        if re.search(r'\b1[3-9]\d{9}\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', quote):
            raise ResearchError('采集原声含联系方式，请在采集服务中匿名化后再分析')
        fingerprint = re.sub(r'\s+', '', quote)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        published = comment.get('published_at', '')
        if not isinstance(published, str):
            raise ResearchError('原声发布日期格式无效；未知日期应留空')
        if published:
            if not isinstance(published, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', published):
                raise ResearchError('原声发布日期格式无效；未知日期应留空')
            date.fromisoformat(published)
        row = {k: '' for k in renderer.OPTIONAL}
        row.update(sample_id=f'R{len(rows)+1:04}', quote=quote, source_url=url,
                   platform=text(comment.get('platform'), '渠道', 100), published_at=published,
                   relevance='待审核', sentiment='未标注', identity_status='匿名公开评论；身份未独立核实',
                   scope='探索性研究', batch='本次独立研究')
        for key in ['brand', 'model', 'software_version', 'source_title']:
            value = comment.get(key, '')
            if not isinstance(value, str) or len(value) > 500:
                raise ResearchError('来源元数据格式无效')
            row[key] = value
        rows.append(row)
    audit = []
    source_urls = set()
    for source in payload['sources']:
        if not isinstance(source, dict):
            raise ResearchError('来源审核记录格式无效')
        url = source.get('url', '')
        if not isinstance(url, str) or len(url) > 2000:
            raise ResearchError('来源链接格式无效')
        if url:
            renderer.safe_url(url)
            source_urls.add(url)
        audit.append({'source_id': f'S{len(audit)+1:03}', 'url': url,
                      'status': text(source.get('status'), '来源访问结果', 500),
                      'decision': text(source.get('decision'), '来源审核说明', 1000),
                      'sample_ids': ','.join(r['sample_id'] for r in rows if r['source_url'] == url)})
    if any(row['source_url'] not in source_urls for row in rows):
        raise ResearchError('有原声缺少对应的来源获取记录')
    return rows, audit


def apply_labels(rows, result):
    labels = result.get('labels')
    expected = {r['sample_id']: r for r in rows}
    if not isinstance(labels, list) or len(labels) != len(rows):
        raise ResearchError('DeepSeek 未逐条完成评论审核')
    seen, updates = set(), []
    for label in labels:
        if not isinstance(label, dict) or label.get('sample_id') not in expected or label['sample_id'] in seen:
            raise ResearchError('DeepSeek 返回了重复或不存在的评论编号')
        ident = label['sample_id']
        seen.add(ident)
        for key in LABEL_FIELDS:
            text(label.get(key), '评论标注 ' + key, 3000)
        if label['relevance'] not in {'相关', '不相关', '待审核'} or label['sentiment'] not in {'正面', '负面', '混合', '中性', '未标注'}:
            raise ResearchError('DeepSeek 返回了无效的审核分类')
        if label['evidence_strength'] not in {'中', '低'}:
            raise ResearchError('未经独立复验的评论不能标为高证据')
        # Only allow analysis fields; ignore any attempted alteration of quotes or provenance.
        updates.append((ident, {key: label[key] for key in LABEL_FIELDS}))
    for ident, values in updates:
        expected[ident].update(values)


def validate_insights(result, rows):
    needs = result.get('needs')
    if not isinstance(needs, list) or len(needs) > 10:
        raise ResearchError('需求聚类结果格式无效')
    eligible = {r['sample_id'] for r in rows if r['relevance'] == '相关'}
    clean = []
    for index, item in enumerate(needs, 1):
        if not isinstance(item, dict):
            raise ResearchError('需求数据格式无效')
        for field in renderer.NEED_FIELDS - {'need_id'}:
            text(item.get(field), '需求字段 ' + field, 4000)
        ids = [v.strip() for v in item['evidence_ids'].split(',') if v.strip()]
        if not ids or set(ids) - eligible or item['priority'] not in {'P0', 'P1', 'P2'}:
            raise ResearchError('需求引用了未纳入的原声，或优先级无效')
        row = {key: item.get(key, '') for key in renderer.NEED_FIELDS}
        row.update(need_id=f'N{index}', evidence_ids=','.join(dict.fromkeys(ids)))
        clean.append(row)
    summary = result.get('summary', {})
    if not isinstance(summary, dict):
        raise ResearchError('洞察总结格式无效')
    text(summary.get('heading'), '洞察标题', 200)
    text(summary.get('text'), '洞察总结', 6000)
    return clean, summary


def write_csv(path, fields, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def write_report(topic, rows, audit, needs, summary, collection_note, model):
    eligible = [r for r in rows if r['relevance'] == '相关']
    sentiments = Counter(r['sentiment'] for r in eligible)
    lines = ['# 用户之声数据分析报告', '', f'研究主题：{topic}', '',
             f'生成时间：{datetime.now(timezone.utc).isoformat()}；分析模型：{model}', '',
             '## 数据与方法', collection_note,
             f'本批去重后 {len(rows)} 条反馈，相关 {len(eligible)} 条，未纳入 {len(rows)-len(eligible)} 条。',
             '情绪分布（分母为相关反馈记录）：' + '、'.join(f'{k} {v} 条' for k, v in sentiments.items()),
             '完全重复原声按去除空白后的文本去重；语义近似可能仍存在。记录数不等于独立人数，不代表总体满意度、故障率或市场规模。',
             '保留渠道提供的日期与版本；未知项留空。评论归类与需求判断为 AI 分析，尚未人工复核或实车验证。', '',
             '## 主要发现', summary['heading'], summary['text'], '', '## 候选需求与证据']
    for need in needs:
        lines += [f"### {need['need_id']} · {need['priority']} · {need['need']}",
                  f"AI 判断：{need['insight']}", f"依据：{need['reason']}",
                  f"支撑原声：{need['evidence_ids']}", f"建议行动：{need['suggested_action']}",
                  f"待验证：{need['validation']}", '']
    if not needs:
        lines.append('当前没有形成有原声支持的需求；不能据此编写确定的产品结论。')
    lines += ['', '## 纳入的原声与来源']
    for row in eligible:
        lines += [f"### {row['sample_id']} · {row['platform']}", row['quote'], row['source_url'], '']
    lines += ['## 渠道覆盖与失败记录']
    for source in audit:
        lines.append(f"- {source['source_id']}：{source['status']}；{source['decision']}；{source['url']}")
    return '\n\n'.join(lines)


def run(project, topic, progress=lambda message: None, *, collected=None):
    deadline = time.monotonic() + 1800
    client = DeepSeekClient(deadline=deadline)
    if collected is None:
        endpoint = collector_url()
        if not endpoint:
            raise ResearchError('真实评论采集服务尚未配置')
        progress('正在获取真实评论与来源记录')
        collected = post_json(endpoint, {'topic': topic, 'max_comments': 60},
                              os.environ.get('VOC_COLLECTOR_TOKEN', ''), deadline=deadline, label='评论采集服务')
        collection_note = '本轮调用已配置的评论采集服务。正文与来源由采集服务返回，模型不生成原声；未独立验证车主身份。'
    else:
        collection_note = '分析用户显式提供的匿名评论文件；本轮未联网重新采集或核验原文。'
    rows, audit = normalize_comments(collected)
    (project / 'data').mkdir(parents=True, exist_ok=True)
    (project / 'docs').mkdir(parents=True, exist_ok=True)
    # Persist only the validated, anonymous source text, never arbitrary connector fields.
    (project / 'data/collected_comments.json').write_text(json.dumps({'comments': rows, 'sources': audit}, ensure_ascii=False, indent=2), encoding='utf-8')
    schema = (SKILL / 'references/schema.md').read_text(encoding='utf-8')
    for offset in range(0, len(rows), 10):
        batch = rows[offset:offset+10]
        progress(f'DeepSeek 正在审核评论 {offset+1}–{offset+len(batch)} / {len(rows)}')
        result = client.json('依据提供的逐条原声，审核与主题的相关性并标注。严格遵循字段契约。'
                             '禁止改写原声、来源、日期、版本或补充外部事实；期望结果标为推断。'
                             '单纯个人自述证据只能中或低。无内容的标注写未知或信息不足。返回 JSON：'
                             '{"labels":[{"sample_id":"R0001",' + ','.join('"'+k+'":"..."' for k in LABEL_FIELDS) + '}]}.',
                             {'topic': topic, 'schema': schema, 'comments': batch}, thinking=False, max_tokens=8192)
        apply_labels(batch, result)
    related = [r for r in rows if r['relevance'] == '相关']
    needs, summary = [], {'heading': '尚无足够的相关评论形成研究结论', 'text': '请查看渠道覆盖与失败记录，补充相关原声后再分析。'}
    if related:
        progress('DeepSeek 正在归类需求并形成洞察')
        result = client.json('仅从这些已审核的原声形成最多10项候选需求和洞察。无需凑数量。'
                             '禁止新增评论、来源、统计值、行业事实或已验证的商业结论。'
                             '每项需求引用真实相关 sample_id，区分推断与待验证行动。返回 JSON：'
                             '{"needs":[{'+','.join('"'+k+'":"..."' for k in sorted(renderer.NEED_FIELDS))+'}],'
                             '"summary":{"heading":"一句话结论","text":"简短分析及局限"}}。',
                             {'topic': topic, 'schema': schema, 'comments': related})
        needs, summary = validate_insights(result, rows)
    write_csv(project / 'data/feedback.csv', sorted(renderer.REQUIRED) + renderer.OPTIONAL, rows)
    write_csv(project / 'data/needs.csv', sorted(renderer.NEED_FIELDS), needs)
    write_csv(project / 'data/source_audit.csv', AUDIT_FIELDS, audit)
    report = write_report(topic, rows, audit, needs, summary, collection_note, client.model)
    (project / 'docs/01-数据分析报告.md').write_text(report, encoding='utf-8')
    (project / 'docs/03-洞察总结.md').write_text('# '+summary['heading']+'\n\n'+summary['text'], encoding='utf-8')
    bodies = ['当前证据不足，待补充相关原声后验证。'] * len(MRD_HEADINGS)
    if needs:
        progress('数据报告已生成；DeepSeek 正在基于报告撰写 MRD')
        result = client.json('严格继承给定数据报告编写探索性MRD。不得新增用户引文、外部事实、市场规模、'
                             '竞品能力、基线指标或已验证收益。缺少证据的章节明确写待验证。'
                             '成功指标和里程碑写定义与建议阶段，不承诺已实现数字或日期。'
                             '按指定的11个章节顺序返回 JSON：{"sections":[{"content":"章节正文"},...]}。',
                             {'topic': topic, 'data_report': report, 'headings': MRD_HEADINGS,
                              'rules': (SKILL / 'references/mrd.md').read_text(encoding='utf-8')})
        sections = result.get('sections')
        if not isinstance(sections, list) or len(sections) != len(MRD_HEADINGS):
            raise ResearchError('MRD未覆盖11个必需章节')
        bodies = [text(s.get('content') if isinstance(s, dict) else None, 'MRD章节', 20000) for s in sections]
        cited = set(re.findall(r'\bR\d{4}\b', '\n'.join(bodies)))
        if cited - {r['sample_id'] for r in related}:
            raise ResearchError('MRD引用了不存在或未纳入的原声')
    mrd = '# MRD · '+topic+'\n\n本文件继承本次数据分析报告；AI生成，待评审。\n\n'
    mrd += '\n\n'.join(f'## {i}. {heading}\n\n{body}' for i, (heading, body) in enumerate(zip(MRD_HEADINGS, bodies), 1))
    (project / 'docs/02-MRD.md').write_text(mrd, encoding='utf-8')
    progress('正在校验证据并生成结果页面')
