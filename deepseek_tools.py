#!/usr/bin/env python3
"""Check private DeepSeek configuration or analyze explicitly supplied comments."""
import argparse
import json
import sys
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / 'research-core/scripts'))
from settings import load_env
from deepseek_client import DeepSeekClient, ResearchError
import deepseek_research
import render as renderer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('check', help='Check configuration without revealing credentials')
    check.add_argument('--live', action='store_true', help='Make one small, billed API call to verify the model')
    analyze = commands.add_parser('analyze', help='Analyze an explicitly supplied anonymous comments JSON')
    analyze.add_argument('--input', type=Path, required=True)
    analyze.add_argument('--topic', required=True)
    args = parser.parse_args()
    load_env(BASE / '.env')
    try:
        if args.command == 'check':
            state = deepseek_research.readiness()
            print(json.dumps(state, ensure_ascii=False, indent=2))
            if args.live:
                result = DeepSeekClient().json('仅返回 JSON {"ok":true}。', {'check': True}, thinking=False, max_tokens=32)
                if result.get('ok') is not True:
                    raise ResearchError('模型未返回预期校验结果')
                print('DeepSeek API 调用通过；尚未验证真实评论采集。')
            return 0
        topic = args.topic.strip()
        if not 2 <= len(topic) <= 200:
            raise ResearchError('请输入2–200个字符的研究主题')
        if args.input.stat().st_size > 5_000_000:
            raise ResearchError('评论文件超过5MB，请缩小范围')
        payload = json.loads(args.input.read_text(encoding='utf-8-sig'))
        deepseek_research.normalize_comments(payload)
        project = BASE / 'research-runs' / uuid.uuid4().hex
        deepseek_research.run(project, topic, print, collected=payload)
        renderer.render(project, topic, project / 'research.html')
        print('结果文件：' + str(project / 'research.html'))
        return 0
    except ResearchError as exc:
        print(str(exc), file=sys.stderr)
    except (ValueError, OSError):
        print('配置、输入文件或证据校验失败；请检查字段和文件路径。', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
