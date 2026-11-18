"""Run one automatic bench with the Claude-only roster: python scripts/run_claude_only.py <series> <manifest.json>
Needs SAP_ROSTER=roster_sap_claude.json and SAP_ALLOW_DUPLICATE_MODELS=1. The result is never counted as solved, because writer and reviewers share a model.
The preflight is the normal one: this roster has no OpenRouter role, so preflight reads no key (2026-11-18, defect 23)."""
import json
import sys

sys.path.insert(0, "scripts/source")
import sap_solve as ss

result = ss.solve(sys.argv[2], series=sys.argv[1])
print(json.dumps(result, indent=2, default=str))
