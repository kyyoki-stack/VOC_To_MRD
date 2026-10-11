"""Discover V2EX topics via SOV2EX; quotes only come from V2EX's reply API."""
import json
import re
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener

from deepseek_client import ResearchError, NoRedirect

MAX_BYTES = 3 * 1024 * 1024
HOSTS = {'www.sov2ex.com', 'www.v2ex.com'}


def read_json(url, deadline):
    if urlsplit(url).hostname not in HOSTS or not url.startswith('https://'):
        raise ResearchError('采集地址不在允许的公开来源内')
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ResearchError('评论采集超过时间限制')
    try:
        with build_opener(NoRedirect()).open(Request(url, headers={'Accept': 'application/json'}), timeout=min(35, remaining)) as response:
            body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ResearchError('评论来源返回内容过大')
        return json.loads(body)
    except HTTPError as exc:
        # Respect access denials and rate limits; never change identity or retry around them.
        raise ResearchError(f'公开评论接口返回 HTTP {exc.code}，本轮不重试') from None
    except (URLError, TimeoutError, ValueError, OSError):
        raise ResearchError('公开评论接口暂时不可达或响应格式无效') from None


def anonymous_quote(value):
    if not isinstance(value, str) or not 4 <= len(value.strip()) <= 12000:
        return ''
    quote = re.sub(r'(?<!\w)@[\w-]+', '@匿名用户', value.strip())
    quote = re.sub(r'(?<!\d)1[3-9]\d{9}(?!\d)|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[联系方式已隐去]', quote)
    return quote


def collect(topic, queries, progress=lambda message: None, *, deadline=None):
    deadline = deadline or time.monotonic() + 300
    comments, sources, topic_ids = [], [], []
    direct = re.findall(r'https://(?:www\.)?v2ex\.com/t/(\d+)', topic)
    topic_ids.extend(int(value) for value in direct[:4])
    if not topic_ids:
        for query in queries[:2]:
            url = 'https://www.sov2ex.com/api/search?' + urlencode({'q': query, 'size': 4, 'operator': 'and'})
            progress('正在检索 V2EX 公开讨论')
            try:
                payload = read_json(url, deadline)
                if not isinstance(payload, dict) or not isinstance(payload.get('hits'), list) or payload.get('timed_out'):
                    raise ResearchError('公开主题搜索未返回有效结果')
                for hit in payload['hits']:
                    ident = hit.get('_source', {}).get('id') if isinstance(hit, dict) else None
                    if isinstance(ident, int) and ident > 0 and ident not in topic_ids:
                        topic_ids.append(ident)
                sources.append({'url': url, 'status': '已检索主题索引', 'decision': '仅用于发现来源；搜索摘要不纳入原声'})
            except ResearchError as exc:
                sources.append({'url': url, 'status': '检索失败', 'decision': str(exc)})
                break
    for ident in topic_ids[:4]:
        url = f'https://www.v2ex.com/t/{ident}'
        progress(f'正在读取 V2EX 主题的真实评论（已获得 {len(comments)} 条）')
        try:
            detail = read_json(f'https://www.v2ex.com/api/topics/show.json?id={ident}', deadline)
            if not isinstance(detail, list) or not detail or detail[0].get('id') != ident:
                raise ResearchError('主题正文暂不可读取')
            title = detail[0].get('title', '')
            replies = read_json(f'https://www.v2ex.com/api/replies/show.json?topic_id={ident}&page=1&page_size=20', deadline)
            if not isinstance(replies, list):
                raise ResearchError('评论接口未返回有效正文')
            included = 0
            for reply in replies[:20]:
                if not isinstance(reply, dict) or not isinstance(reply.get('id'), int):
                    continue
                quote = anonymous_quote(reply.get('content'))
                if not quote:
                    continue
                created = reply.get('created')
                try:
                    published = datetime.fromtimestamp(created, timezone.utc).date().isoformat() if isinstance(created, (int, float)) else ''
                except (ValueError, OverflowError, OSError):
                    published = ''
                source_url = f'{url}#r_{reply["id"]}'
                comments.append({'quote': quote, 'source_url': source_url, 'platform': 'V2EX',
                                 'source_title': title if isinstance(title, str) else '', 'published_at': published})
                sources.append({'url': source_url, 'status': '已读取官方评论 API 正文',
                                'decision': '保留评论正文；提及用户名与联系方式已匿名化；与研究主题的相关性由后续逐条审核'})
                included += 1
                if included >= 8:
                    break
            sources.append({'url': url, 'status': f'本页读取{len(replies)}条，纳入{included}条候选',
                            'decision': '每主题只采首个评论页，最多纳入8条；未遍历全量或验证独立用户身份，不代表总体分布'})
        except ResearchError as exc:
            sources.append({'url': url, 'status': '正文获取失败', 'decision': str(exc)})
            if 'HTTP 429' in str(exc) or time.monotonic() >= deadline:
                break
    return {'comments': comments, 'sources': sources or [{'url': '', 'status': '无可读取的公开来源',
                                                        'decision': '本轮仅覆盖 V2EX；没有使用示例数据或生成评论'}]}
