#!/usr/bin/env python3
"""Run the local VOC website without requiring a globally installed Skill."""
import argparse
import runpy
import sys
from pathlib import Path


def main():
    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8780)
    parser.add_argument('--runs', type=Path, default=base / 'research-runs')
    args = parser.parse_args()
    scripts = base / 'research-core/scripts'
    sys.path.insert(0, str(scripts))
    sys.argv = [str(scripts / 'serve.py'), '--root', str(base / 'web'),
                '--runs', str(args.runs.resolve()), '--port', str(args.port)]
    runpy.run_path(str(scripts / 'serve.py'), run_name='__main__')


if __name__ == '__main__':
    main()
