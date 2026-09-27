"""Keep the standalone Bash installer's MikroTik release parser testable."""

import html
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile


source = Path('script.sh').read_text(encoding='utf-8')
match = re.search(r"<<'PY'\n(.*?)\nPY\n", source, re.S)
assert match, 'embedded release parser is missing'
parser = match.group(1)


def release(version, channel, archived=False):
    return [{
        'version': version,
        'archived': archived,
        'channels': [{channel: True}, {'s': 'arr'}],
    }, {'s': 'arr'}]


snapshot = {
    'data': {
        'channel': 'longTerm',
        'releases': [[
            release('7.24.4', 'stable'),
            release('7.23.7', 'longTerm'),
            release('6.49.18', 'longTerm'),
            release('7.25beta5', 'development'),
            release('7.23.3', 'stable', archived=True),
        ], {'s': 'arr'}],
    },
}
page = '<div wire:snapshot="' + html.escape(json.dumps(snapshot), quote=True) + '"></div>'
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory, 'chr.html')
    path.write_text(page, encoding='utf-8')
    output = subprocess.check_output(
        [sys.executable, '-c', parser, str(path)], text=True
    ).splitlines()

assert output == ['stable|7.24.4', 'longTerm|7.23.7', 'longTerm|6.49.18'], output
print('release catalog parser: OK')
