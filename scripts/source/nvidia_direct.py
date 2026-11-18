"""Direct NVIDIA route for roster models listed in config/direct_route.json (owner 2026-11-16): same OpenRouter-shaped request in, same reply shape out,
but the call goes to integrate.api.nvidia.com with the key pool (one key file per key in the folder NVIDIA_KEYS_DIR names, default the secrets folder
next to the repo) and a model whose entry says thinking=false runs with thinking OFF.
Switched on only by the environment variable SAP_DIRECT_ROUTE=nvidia_direct (see openrouter_call.default_transport). Keys are never printed, logged or stored here.
Replies carry the header x-served-by: nvidia-direct, so evidence can tell this route from OpenRouter."""
from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_PER_KEY = 1                                  # ponytail: one request per key per 60 s window across ALL loop processes; raise if throughput is too low
CONFIG = Path(__file__).resolve().parents[2] / "config" / "direct_route.json"


def _models():
    """{roster id: (served id, thinking)} from config/direct_route.json: thinking False sends enable_thinking=false; None leaves the model's default."""
    data = json.loads(CONFIG.read_text(encoding="utf-8"))["models"]
    return {rid: (spec["id"], spec["thinking"]) for rid, spec in data.items()}


RETRY_STATUS = (401, 402, 403, 429, 500, 502, 503, 504)   # try the next key


def _keys():
    folder = Path(os.environ.get("NVIDIA_KEYS_DIR") or Path(__file__).resolve().parents[3] / "secrets" / "nvidia")
    out = []
    for f in sorted(folder.glob("nvidia_api_key*.txt")):
        k = f.read_text(encoding="utf-8").strip()
        if k.startswith("nvapi-"):
            out.append(k)
    return out


def _post(key, body, timeout, opener):
    req = urllib.request.Request(URL, data=body, method="POST", headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with opener(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _p1claims():
    """pieces/p1_claims.py, imported on first use (its import puts scripts/source on sys.path)."""
    pieces = str(Path(__file__).resolve().parents[2] / "pieces")
    if pieces not in sys.path:
        sys.path.insert(0, pieces)
    import p1_claims
    return p1_claims


def _pool(keys):
    """LedgerKeyPool over the loop home: every process of the loop shares one ledger under OS locks, so no key gets more than NVIDIA_PER_KEY
    requests per window, and a rejected or rate-limited key is cooled. None when no loop home can be used (SATVIK_HOME unset inside a git
    worktree): the caller then starts at a random key."""
    p1 = _p1claims()
    try:
        home = p1.loop_home.home(fallback=Path(__file__).resolve().parents[2] / "_loop")
    except p1.loop_home.LoopHomeError:
        return None
    return p1.LedgerKeyPool(keys, str(home), per_key=NVIDIA_PER_KEY, sleep=lambda s: time.sleep(s))


def maybe_send(method, url, body, timeout, opener=urllib.request.urlopen, keys=None):
    """(status, headers, raw) for a roster Nemotron chat call, or None when this request is not one (the caller then uses OpenRouter as before)."""
    if method != "POST" or not url.endswith("/chat/completions") or not body:
        return None
    req = json.loads(body)
    models = _models()
    if req.get("model") not in models:
        return None
    nv_id, thinking = models[req["model"]]
    out = {k: req[k] for k in ("messages", "max_tokens", "temperature", "top_p", "seed", "stop") if k in req}
    out["model"] = nv_id
    if thinking is False:
        out["chat_template_kwargs"] = {"enable_thinking": False}
    keys = keys or _keys()
    if not keys:
        return 401, {"x-served-by": "nvidia-direct"}, b'{"error":{"message":"no NVIDIA key found in secrets/nvidia"}}'
    pool = _pool(keys)
    start = random.randrange(len(keys))             # fallback start only, when there is no shared ledger
    payload = json.dumps(out).encode("utf-8")
    status, raw = 0, b""
    for i in range(len(keys)):                       # one pass over the pool: a rejected or rate-limited key moves to the next
        if pool is not None:
            try:
                idx, key = pool.acquire()            # waits for a free key in the shared window
            except _p1claims().AllKeysUnavailable:
                return 401, {"x-served-by": "nvidia-direct"}, b'{"error":{"message":"every NVIDIA key is retired or cooling"}}'
        else:
            idx = (start + i) % len(keys)
            key = keys[idx]
        status, raw = _post(key, payload, timeout, opener)
        if pool is not None:
            pool.report(idx, status)
        if status not in RETRY_STATUS:
            break
        time.sleep(1)
    headers = {"x-served-by": "nvidia-direct"}
    if status == 200:                                # same shape the loop reads from OpenRouter: roster model id, reasoning under "reasoning"
        data = json.loads(raw)
        data["model"] = req["model"]
        for choice in data.get("choices", []):
            msg = choice.get("message") or {}
            if msg.get("reasoning_content") and not msg.get("reasoning"):
                msg["reasoning"] = msg["reasoning_content"]
        raw = json.dumps(data).encode("utf-8")
    return status, headers, raw
