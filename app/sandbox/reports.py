"""Fixed container wrapper and a bounded report envelope, never model commands."""
import base64

MAX_REPORT_BYTES = 2000000
TAIL_BYTES = 2800000


def report_wrapper(command: list[str], marker: bytes, seconds: float) -> str:
    return f"""import base64,os,pathlib,subprocess,sys
try:
    result = subprocess.run({command!r}, timeout={seconds!r})
    code = result.returncode
except subprocess.TimeoutExpired:
    code = 124
path = pathlib.Path('/results/junit.xml')
raw = b''
if path.is_file():
    with path.open('rb') as stream:
        raw = stream.read({MAX_REPORT_BYTES + 1})
if len(raw) > {MAX_REPORT_BYTES}:
    raw = b''
sys.stdout.buffer.write(b'\\n' + {marker!r} + base64.b64encode(raw) + b'\\n')
sys.stdout.buffer.flush()
sys.exit(code)
"""


def decode_report(tail: bytes, marker: bytes) -> bytes:
    if marker not in tail:
        raise ValueError('Bounded sandbox report missing')
    lines = tail.rsplit(marker, 1)[1].splitlines()
    raw = base64.b64decode(lines[0] if lines else b'', validate=True)
    if not raw or len(raw) > MAX_REPORT_BYTES:
        raise ValueError('Bounded sandbox report missing or oversized')
    return raw
