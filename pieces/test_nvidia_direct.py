"""nvidia_direct: a roster Nemotron call is sent to NVIDIA with thinking off for Super, rotates past a rejected key, and returns the roster model id."""
import io
import json
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "source"))
import nvidia_direct as nd  # noqa: E402


class _Resp(io.BytesIO):
    status = 200
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_super_thinking_off_key_rotation_and_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(nd.time, "sleep", lambda s: None)
    monkeypatch.setenv("SATVIK_HOME", str(tmp_path))           # the shared key ledger lives here, never in the real home
    seen = []

    def opener(req, timeout):
        seen.append((req.get_header("Authorization"), json.loads(req.data)))
        if len(seen) == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "x", {}, io.BytesIO(b"{}"))
        return _Resp(json.dumps({"model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "choices": [{"message": {"content": "ok", "reasoning_content": "r"}}]}).encode())

    body = json.dumps({"model": "nvidia/nemotron-3.5-super-vl:free", "messages": [], "max_tokens": 5, "temperature": 0.1,
                       "reasoning": {"effort": "high"}, "provider": {"x": 1}}).encode()
    status, headers, raw = nd.maybe_send("POST", "https://openrouter.ai/api/v1/chat/completions", body, 5, opener=opener, keys=["nvapi-a", "nvapi-b"])
    assert status == 200 and headers["x-served-by"] == "nvidia-direct" and len(seen) == 2 and seen[0][0] != seen[1][0]
    sent = seen[1][1]
    assert sent["model"] == "nvidia/nemotron-3.5-super-vl-120b-a12b" and sent["chat_template_kwargs"] == {"enable_thinking": False}
    assert "reasoning" not in sent and "provider" not in sent
    data = json.loads(raw)
    assert data["model"] == "nvidia/nemotron-3.5-super-vl:free" and data["choices"][0]["message"]["reasoning"] == "r"
    assert nd.maybe_send("POST", "u/chat/completions", json.dumps({"model": "other/model"}).encode(), 5) is None
