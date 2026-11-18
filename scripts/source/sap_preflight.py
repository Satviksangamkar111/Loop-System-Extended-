"""Paid-run preflight (docs/sap/PASS_RULE.md, void runs): one tiny call per DISTINCT model of the production roster, plus the OpenRouter key's
remaining limit and credits. A run must not start when a role is dead or the money is short.

    python scripts/source/sap_preflight.py        # one line per role, then OK or ABORT; exit 0 / 1

preflight(roster_roles=None, *, ask=None, key_info=None) -> {"ok", "roles": {role: {"ok", "seconds", "error"}}, "key": {...}, "failed": [...]}.
`ask(role, spec)` and `key_info()` are injectable (tests: no network, no model). The key is read by openrouter_call.load_keys, used in the
Authorization header and never printed, logged or stored. Top-level imports are stdlib only."""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
API = "https://openrouter.ai/api/v1"
PROMPT = "Reply with the single word ok."
SYSTEM = "You are a connectivity check. Answer exactly as instructed."
MAX_TOKENS = 20
TIMEOUT_S = 120
DEFAULT_MIN_KEY_USD = 1.0
MIN_CREDITS_USD = 1.0


def min_key_usd():
    try:
        return float(os.environ.get("SAP_MIN_KEY_USD", DEFAULT_MIN_KEY_USD))
    except ValueError:
        return DEFAULT_MIN_KEY_USD


def roster_path():
    return ROOT / "config" / (os.environ.get("SAP_ROSTER") or "roster_sap.json")     # the same file as sap_solve.roster_name()


def production_roles():
    import openrouter_call as oc
    return oc.load_profile("production", roster_path())


def _direct_models():
    try:
        return set(json.loads((ROOT / "config" / "direct_route.json").read_text(encoding="utf-8"))["models"])
    except (OSError, ValueError, KeyError):
        return set()


def _http(transport, method, url, key, body=None):
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    status, _h, raw = transport(method, url, headers, None if body is None else json.dumps(body).encode("utf-8"), TIMEOUT_S)
    try:
        data = json.loads(raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else raw)
    except ValueError:
        data = None
    return status, data


def default_ask(role, spec):
    """One tiny live call for a role: Claude CLI roles through claude_code.ask_role (the loop's own safe command), OpenRouter roles (the NVIDIA
    arbiters through the direct route) through openrouter_call.default_transport. Raises on any failure; returns the reply text."""
    import openrouter_call as oc
    if oc.via_of(spec) == "claude_code":
        import claude_code
        s = dict(spec, settings=dict(spec.get("settings") or {}, timeout_s=TIMEOUT_S))
        return claude_code.ask_role(role, SYSTEM, PROMPT, "text", spec=s)
    if oc.via_of(spec) != "openrouter":
        raise RuntimeError(f"{role}: via {oc.via_of(spec)} is not preflighted")
    keys = oc.load_keys()
    key = keys.get("free") or keys.get("paid")
    if not key:
        raise RuntimeError("no OpenRouter key (OPENROUTER_FREE_KEY or secrets/)")
    body = {"model": spec["model"], "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": PROMPT}],
            "max_tokens": MAX_TOKENS, "temperature": 0, "reasoning": {"effort": "low"} if spec["model"].startswith("google/") else {"enabled": False}}
    # ponytail: Gemini 2.5 Pro cannot switch reasoning off, so it gets effort low; the 20-token cap bounds its cost either way
    prev = os.environ.get("SAP_DIRECT_ROUTE")
    if spec["model"] in _direct_models():
        os.environ["SAP_DIRECT_ROUTE"] = "nvidia_direct"
    try:
        status, data = _http(oc.default_transport, "POST", f"{API}/chat/completions", key, body)
    finally:
        if prev is None:
            os.environ.pop("SAP_DIRECT_ROUTE", None)
        else:
            os.environ["SAP_DIRECT_ROUTE"] = prev
    if status != 200 or not isinstance(data, dict) or data.get("error") or not data.get("choices"):
        err = (data or {}).get("error") if isinstance(data, dict) else None
        msg = err.get("message") if isinstance(err, dict) else err
        raise RuntimeError(f"HTTP {status}: {str(msg or 'no choices in the reply')[:200]}")
    return str((data["choices"][0].get("message") or {}).get("content") or "")    # an empty text from a thinking model still proves the model answers


def default_key_info():
    """{"limit_remaining", "usage", "credits_left"} from GET /key and /credits (None for a field the API does not give). Raises on a failed read."""
    import openrouter_call as oc
    keys = oc.load_keys()
    key = keys.get("free") or keys.get("paid")
    if not key:
        raise RuntimeError("no OpenRouter key (OPENROUTER_FREE_KEY or secrets/)")
    s1, d1 = _http(oc.default_transport, "GET", f"{API}/key", key)
    if s1 != 200 or not isinstance(d1, dict) or not isinstance(d1.get("data"), dict):
        raise RuntimeError(f"GET /key failed: HTTP {s1}")
    d = d1["data"]
    out = {"limit_remaining": d.get("limit_remaining"), "usage": d.get("usage"), "credits_left": None}
    s2, d2 = _http(oc.default_transport, "GET", f"{API}/credits", key)
    c = d2.get("data") if isinstance(d2, dict) else None
    if s2 == 200 and isinstance(c, dict) and c.get("total_credits") is not None:
        out["credits_left"] = float(c["total_credits"]) - float(c.get("total_usage") or 0)
    return out


def key_problems(info, minimum=None):
    """Why this key state stops a run (a list; empty when fine). A None limit_remaining is an unlimited key; unknown credits are not a failure."""
    minimum = min_key_usd() if minimum is None else minimum
    out = []
    lr, cl = info.get("limit_remaining"), info.get("credits_left")
    if isinstance(lr, (int, float)) and lr < minimum:
        out.append(f"key limit_remaining {lr:.4f} USD is below {minimum:.2f}")
    if isinstance(cl, (int, float)) and cl < MIN_CREDITS_USD:
        out.append(f"credits_left {cl:.4f} USD is below {MIN_CREDITS_USD:.2f}")
    return out


def preflight(roster_roles=None, *, ask=None, key_info=None):
    """roster_roles: {role: spec} (default: the production roster). One call per distinct (via, model, effort); every role sharing it gets that result."""
    roles = production_roles() if roster_roles is None else roster_roles
    ask = ask or default_ask
    done, res = {}, {}
    for role, spec in roles.items():
        ident = (spec.get("via", "openrouter"), spec.get("model"), spec.get("effort"))
        if ident not in done:
            t0 = time.time()
            try:
                ask(role, spec)
                done[ident] = {"ok": True, "error": None}
            except Exception as exc:                                  # any failure is a dead role
                done[ident] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
            done[ident]["seconds"] = round(time.time() - t0, 2)
        res[role] = dict(done[ident])
    # 2026-11-18 (defect 23): the OpenRouter key is read only when a role is called through OpenRouter; a Claude-only roster needs no key
    key_checked = any(spec.get("via", "openrouter") == "openrouter" for spec in roles.values())
    key = {"limit_remaining": None, "usage": None, "credits_left": None}
    problems = []
    if key_checked:
        try:
            key.update((key_info or default_key_info)())
            problems = key_problems(key)
        except Exception as exc:
            problems = [f"key state unreadable: {type(exc).__name__}: {exc}"[:200]]
    failed = [r for r, v in res.items() if not v["ok"]]
    return {"ok": not failed and not problems, "roles": res, "key": key, "key_checked": key_checked, "failed": failed, "key_problems": problems}


def main(argv=None):
    r = preflight()
    for role, v in r["roles"].items():
        print(f"{role}: {'ok' if v['ok'] else 'FAIL'} {v['seconds']}s {v['error'] or ''}".rstrip())
    k = r["key"]
    if r["key_checked"]:
        print(f"key: limit_remaining={k['limit_remaining']} usage={k['usage']} credits_left={k['credits_left']}")
    else:
        print("key: not read (no role of this roster is called through OpenRouter)")
    for p in r["key_problems"]:
        print("key problem: " + p)
    print("OK" if r["ok"] else "ABORT")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
