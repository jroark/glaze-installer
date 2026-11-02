"""Explicit hardware test: CE staging and RAM restarts, never programs raw NAND."""
import argparse
import json
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cycles', type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.cycles <= 10:
        parser.error('--cycles must be between 1 and 10')
    bundle = args.bundle.resolve()
    sys.path.insert(0, str(bundle / 'app'))
    from engine import Installer
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / 'ram-session.jsonl').open('w', encoding='utf-8') as log:
        def emit(event):
            event = dict(event, timestamp=time.time())
            text = json.dumps(event)
            log.write(text + '\n')
            log.flush()
            print(text, flush=True)
        installer = Installer(bundle / 'resources', emit, state_dir=args.output / 'state')
        installer.verify()
        device = installer.probe()
        if device['runtime'] != 'CE' and not device['capabilities'] & 32768:
            raise RuntimeError('Start this test in CE or a matching temporary installer session.')
        for cycle in range(args.cycles):
            emit({'event': 'hardware-cycle', 'current': cycle+1, 'total': args.cycles})
            installer.ram_boot('ro')
            device = installer.probe()
            if device['capabilities'] & (4096 | 32768) != (4096 | 32768) or device['capabilities'] & 16384:
                raise RuntimeError('RAM validation requires the read-only installer session.')
        result = {'build': installer.build, 'device': installer.device,
                  'ram_cycles': args.cycles, 'raw_nand_programming': False}
        (args.output / 'ram-validation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        emit(dict(result, event='hardware-ram-success'))


if __name__ == '__main__':
    main()
