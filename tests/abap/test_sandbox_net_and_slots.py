"""Network preload guard and cross-process transpile slots.

The preload is defence in depth, NOT a security boundary: it only replaces the
networking entry points inside the node process. The real boundary is an OS
firewall rule or a container (docs/sap/SANDBOX_NETWORK.md).
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "source"))
import abap_transpile_run as t  # noqa: E402

NODE = shutil.which("node")
SRC = Path(__file__).resolve().parents[2] / "scripts" / "source"
GUARD = SRC / "net_guard_preload.js"
MSG = "network is blocked in the ABAP sandbox"
SLOTS_ENV = t.SLOT_ENV


def _unused_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---------------------------------------------------------------- network guard

def test_preload_is_in_the_built_commands_with_a_read_grant():
    cmd = t.build_node_command("node", ["x.mjs"], ["C:/w"], preload=str(GUARD))
    assert cmd[cmd.index("--require") + 1] == str(GUARD)
    assert f"--allow-fs-read={GUARD}" in cmd
    assert cmd.index("--require") < cmd.index("x.mjs")  # loaded before the user script
    assert "--require" not in t.build_node_command("node", ["x.mjs"], ["C:/w"])  # default unchanged


def test_the_runner_points_at_the_guard_file():
    assert Path(t.NET_GUARD_PRELOAD) == GUARD and GUARD.is_file()


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_guard_blocks_outbound_and_keeps_local_work(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    (work / "in.txt").write_text("hello", encoding="utf-8")
    port = _unused_port()
    js = f"""
const net = require('net'), dns = require('dns'), path = require('path'), fs = require('fs');
const out = {{}};
function sync(name, fn) {{ try {{ fn(); out[name] = 'NOERR'; }} catch (e) {{ out[name] = e.message; }} }}
sync('connect', () => net.connect({port}, '127.0.0.1'));
sync('lookup', () => dns.lookup('example.invalid', () => {{}}));
sync('http', () => require('http').get('http://127.0.0.1:{port}/', () => {{}}));
sync('dgram', () => require('dgram').createSocket('udp4'));
Promise.allSettled([
  fetch('http://127.0.0.1:{port}/'),
  require('dns/promises').lookup('example.invalid'),
]).then((r) => {{
  out.fetch = r[0].reason ? r[0].reason.message : 'NOERR';
  out.dnsp = r[1].reason ? r[1].reason.message : 'NOERR';
  out.read = fs.readFileSync(path.join(process.cwd(), 'in.txt'), 'utf8');
  setTimeout(() => console.log(JSON.stringify(out)), 10);
}});
"""
    cmd = t.build_node_command(NODE, ["-e", js], [str(work)], preload=str(GUARD))
    res = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout.strip().splitlines()[-1])
    for key in ("connect", "lookup", "http", "dgram", "fetch", "dnsp"):
        assert out[key].startswith(MSG), (key, out[key])
    assert out["read"] == "hello"  # local read still works under the guard


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_without_the_guard_a_closed_port_is_refused_not_blocked(tmp_path):
    """Control: shows the block above comes from the guard, not from the network being down."""
    port = _unused_port()
    js = (f"const s=require('net').connect({port},'127.0.0.1');"
          "s.on('error',e=>{console.log(e.code);process.exit(0)});")
    res = subprocess.run([NODE, "-e", js], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert res.stdout.strip() == "ECONNREFUSED", res.stdout + res.stderr


# ---------------------------------------------------------------- transpile slots

_HOLDER = """
import sys, time
sys.path.insert(0, sys.argv[1])
import abap_transpile_run as t
home, hold = sys.argv[2], float(sys.argv[3])
with t.transpile_slot(home_dir=home) as slot:
    print('HELD', slot, time.time(), flush=True)
    time.sleep(hold)
print('RELEASED', time.time(), flush=True)
"""


def _holder(home, hold, slots):
    """A separate OS process that takes a slot, so the lock is really cross-process."""
    env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "TEMP", "TMP") if k in os.environ}
    env[SLOTS_ENV] = str(slots)
    return subprocess.Popen([sys.executable, "-c", _HOLDER, str(SRC), str(home), str(hold)],
                            stdout=subprocess.PIPE, text=True, env=env)


def _held_at(proc) -> float:
    line = proc.stdout.readline()  # blocks until this holder has the slot
    assert line.startswith("HELD"), line
    return float(line.split()[-1])


def _released_at(proc) -> float:
    line = proc.stdout.readline()
    assert line.startswith("RELEASED"), line
    return float(line.split()[-1])


def test_default_is_two_slots(monkeypatch):
    monkeypatch.delenv(SLOTS_ENV, raising=False)
    assert t.slot_count() == 2
    monkeypatch.setenv(SLOTS_ENV, "3")
    assert t.slot_count() == 3
    monkeypatch.setenv(SLOTS_ENV, "0")
    with pytest.raises(t.RunnerError):
        t.slot_count()


def test_one_slot_serializes_two_holders(tmp_path):
    a = _holder(tmp_path, hold=2.0, slots=1)
    got_a = _held_at(a)
    b = _holder(tmp_path, hold=0.0, slots=1)
    got_b = _held_at(b)  # blocks until A lets go
    rel_a = _released_at(a)
    assert rel_a >= got_a + 1.5
    assert got_b >= rel_a - 0.05  # B got the slot only after A released it
    a.wait(10)
    b.wait(10)


def test_a_dead_holder_frees_its_slot(tmp_path):
    a = _holder(tmp_path, hold=60.0, slots=1)
    _held_at(a)
    a.kill()  # dies while still holding the slot
    a.wait(10)
    b = _holder(tmp_path, hold=0.0, slots=1)
    start = time.time()
    _held_at(b)
    assert time.time() - start < 10
    b.wait(10)


def test_default_two_holders_run_together_third_waits(tmp_path, monkeypatch):
    monkeypatch.delenv(SLOTS_ENV, raising=False)
    a = _holder(tmp_path, hold=3.0, slots=2)
    b = _holder(tmp_path, hold=3.0, slots=2)
    _held_at(a)
    _held_at(b)  # both slots in use at once
    c = _holder(tmp_path, hold=0.0, slots=2)
    t0 = time.time()
    _held_at(c)
    assert time.time() - t0 >= 1.0  # the third waited for one of the first two
    for p in (a, b, c):
        p.wait(20)


def test_slot_wait_happens_before_the_run_body(tmp_path, monkeypatch):
    """The body (where the per-run timers start) runs only after the slot is held."""
    monkeypatch.setenv(SLOTS_ENV, "1")
    monkeypatch.setattr(t, "_slot_home", lambda: tmp_path)
    order = []

    def holder():
        with t.transpile_slot():
            time.sleep(1.0)
        order.append("released")

    th = threading.Thread(target=holder)
    th.start()
    time.sleep(0.2)
    monkeypatch.setattr(t, "_transpile_and_run", lambda cfg, contents, timeout_s: order.append("body") or {})
    t.run_abap_tests({}, {}, timeout_s=1)
    th.join()
    assert order == ["released", "body"]
