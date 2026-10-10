"""Load only this application's settings; never evaluate shell expressions."""
import os
import re

KEYS = {'VOC_RESEARCH_BACKEND', 'DEEPSEEK_API_KEY', 'DEEPSEEK_MODEL',
        'VOC_COLLECTOR_URL', 'VOC_COLLECTOR_TOKEN'}


def load_env(path):
    if not path.is_file():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if not separator or key not in KEYS:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def model_name():
    model = os.environ.get('DEEPSEEK_MODEL', 'deepseek-v4-pro').strip()
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}', model):
        raise ValueError('DEEPSEEK_MODEL 格式无效')
    return model
