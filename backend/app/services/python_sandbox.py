"""Run a model-written analysis script on one tab's query results, isolated from the app.

The child gets only those results (already limited to the provider by the SQL), an empty
environment, a temporary working directory, the standard library and hard resource limits. An
audit hook stops network, processes, native code, file writes and reads outside Python itself.

shortcut: a separate process plus an audit hook, not an OS sandbox (this container can't create
namespaces); move to a no-network container or nsjail before running scripts on shared hosts.
"""

import asyncio
import json
import sys
import tempfile
import time
from decimal import Decimal

from app.llm.schemas import QueryResult

TIMEOUT_S = 10
MAX_OUTPUT = 4000

BOOTSTRAP = r"""
import io, json, os, resource, sys, traceback

job = json.load(sys.stdin)
for limit, value in ((resource.RLIMIT_CPU, 5), (resource.RLIMIT_AS, 512 << 20),
                     (resource.RLIMIT_FSIZE, 0), (resource.RLIMIT_NOFILE, 32)):
    resource.setrlimit(limit, (value, value))

ROOTS = tuple({os.path.realpath(p) + os.sep for p in (sys.prefix, sys.base_prefix)})
BLOCKED = ("socket.", "subprocess.", "os.system", "os.exec", "os.posix_spawn", "os.spawn",
           "os.fork", "os.kill", "os.killpg", "os.putenv", "os.unsetenv", "os.remove",
           "os.rename", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.symlink", "os.link",
           "os.truncate", "os.utime", "ctypes.", "mmap.", "resource.", "signal.", "shutil.")
NO_IMPORT = {"ctypes", "_ctypes", "socket", "_socket", "ssl", "_ssl", "subprocess",
             "_posixsubprocess", "multiprocessing", "_multiprocessing", "select", "selectors",
             "asyncio", "http", "urllib", "mmap", "fcntl", "pty", "termios", "_ctypes_test"}
WRITE = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

def hook(event, args):
    if event.startswith(BLOCKED):
        raise PermissionError(f"{event} is not allowed in the analysis sandbox")
    if event == "import" and args[0].partition(".")[0] in NO_IMPORT:
        raise PermissionError(f"import {args[0]} is not allowed in the analysis sandbox")
    if event in ("open", "os.listdir", "os.scandir") and not isinstance(args[0], int):
        path = os.fsdecode(os.fspath("." if args[0] is None else args[0]))
        if not (os.path.realpath(path) + os.sep).startswith(ROOTS):
            raise PermissionError("only the query results are available in the analysis sandbox")
    if event == "open" and (args[2] or 0) & WRITE:
        raise PermissionError("files can't be written in the analysis sandbox")

class Capped(io.TextIOBase):
    def __init__(self):
        self.text = ""
    def writable(self):
        return True
    def write(self, s):
        if len(self.text) <= LIMIT:
            self.text += s[: LIMIT + 1 - len(self.text)]
        return len(s)

LIMIT = job["limit"]
out = sys.stdout
sys.stdout = sys.stderr = Capped()
sys.addaudithook(hook)
code = 0
try:
    exec(compile(job["code"], "<analysis>", "exec"), {"__name__": "__main__", "results": job["data"]})
except BaseException:
    traceback.print_exc(limit=-3)
    code = 1
out.write(sys.stdout.text)
out.flush()
os._exit(code)
"""


def _json(o):
    return float(o) if isinstance(o, Decimal) else str(o)


async def _read(stream: asyncio.StreamReader, limit: int) -> bytes:
    """Drains the stream so the child never blocks, keeping only the first `limit` bytes."""
    kept = b""
    while chunk := await stream.read(65536):
        kept += chunk[: max(0, limit - len(kept))]
    return kept


async def run_script(code: str, results: dict[str, QueryResult]) -> dict:
    """{status, output, duration_ms}; `results` reaches the script as {name: [{column: value}]}."""
    job = json.dumps(
        {
            "code": code,
            "limit": MAX_OUTPUT,
            "data": {n: [dict(zip(r.columns, row)) for row in r.rows] for n, r in results.items()},
        },
        default=_json,
    ).encode()
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as cwd:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            BOOTSTRAP,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
            env={},
        )
        try:
            async with asyncio.timeout(TIMEOUT_S):
                proc.stdin.write(job)
                try:
                    await proc.stdin.drain()
                    proc.stdin.close()
                except ConnectionError:
                    pass  # the child exited early; its output says why
                out = await _read(proc.stdout, MAX_OUTPUT + 1)
                await proc.wait()
        except TimeoutError:
            proc.kill()
            await proc.wait()
            out = f"Stopped after {TIMEOUT_S} s.".encode()
    text = out.decode(errors="replace")
    if proc.returncode < 0 and not text:
        text = "Stopped by the sandbox's CPU or memory limit."
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + "\n… output truncated"
    return {
        "status": "succeeded" if proc.returncode == 0 else "failed",
        "output": text,
        "duration_ms": round((time.monotonic() - started) * 1000),
    }
