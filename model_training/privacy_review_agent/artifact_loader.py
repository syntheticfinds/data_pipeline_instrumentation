import json
import os

def load_bundle(run_dir: str) -> dict:
    p = os.path.join(run_dir, "governance_context_bundle.json")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def load_events(run_dir: str) -> list[dict]:
    p = os.path.join(run_dir, "events.jsonl")
    events = []
    if not os.path.exists(p):
        return events
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events
