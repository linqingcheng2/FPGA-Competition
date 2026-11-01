from portable_tools import vivado_bin
"""Execute the real ILA stream endpoint against an independent memory fixture."""
from pathlib import Path
import datetime
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WORK = (ROOT / '../../../work/route_opt_stream_unit').resolve()
WORK.mkdir(exist_ok=True)
B = vivado_bin()
paths = (ROOT / 'rtl/debug_stream.v', ROOT / 'tb/tb_debug_stream.v', Path(__file__))
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
hashes = {str(p.relative_to(ROOT)).replace('\\', '/'): digest(p) for p in paths}
commands = ([str(B / 'xvlog.bat'), str(paths[0]), str(paths[1])],
    [str(B / 'xelab.bat'), 'tb_debug_stream', '-s', 'debug_stream_snapshot'],
    [str(B / 'xsim.bat'), 'debug_stream_snapshot', '-runall'])
for command in commands:
    result = subprocess.run(command, cwd=WORK, capture_output=True, text=True,
        encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    output = result.stdout + result.stderr
    (WORK / (Path(command[0]).stem + '.log')).write_text(output, encoding='utf-8')
    assert result.returncode == 0, output[-4000:]
match = re.search(r'DEBUG_STREAM_ALL_PASS words=(\d+) captures=(\d+) cancel_cases=(\d+)', output)
assert match and 'Fatal:' not in output, output[-4000:]
words, captures, cancels = map(int, match.groups())
assert (words, captures, cancels) == (30720, 15, 6)
assert all(digest(ROOT / name) == value for name, value in hashes.items())
report = dict(passed=True, source='actual_RTL_stream_with_independent_synchronous_memory_fixture',
    board_test=False, exact_words=words, complete_captures=captures, cancellation_boundaries=cancels,
    FFT_sizes=[8192, 16384], scope_exact_words=4096,
    completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), source_sha256=hashes,
    output_sha256={p.name: digest(p) for p in WORK.glob('*.log')})
(ROOT / 'results/stream_verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print('DEBUG_STREAM_EXACT_WORDS_AND_CANCELLATION_PASS', words, captures, cancels)
