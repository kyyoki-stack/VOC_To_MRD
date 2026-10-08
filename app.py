#!/usr/bin/env python3
"""Run the local VOC website without requiring a globally installed Skill."""
import argparse
import os
import runpy
import sys
from pathlib import Path


def main():
    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8780)
    parser.add_argument('--host', choices=['127.0.0.1', '0.0.0.0'], default='127.0.0.1')
    parser.add_argument('--public-port', type=int, default=os.environ.get('VOC_PUBLIC_PORT'),
                        help='Browser-facing port when Docker maps a different host port')
    parser.add_argument('--runs', type=Path, default=base / 'research-runs')
    args = parser.parse_args()
    scripts = base / 'research-core/scripts'
    sys.path.insert(0, str(scripts))
    sys.argv = [str(scripts / 'serve.py'), '--root', str(base / 'web'),
                '--runs', str(args.runs.resolve()), '--port', str(args.port), '--host', args.host]
    if args.public_port is not None:
        sys.argv.extend(['--public-port', str(args.public_port)])
    runpy.run_path(str(scripts / 'serve.py'), run_name='__main__')


if __name__ == '__main__':
    main()
