# privacy_governance.py
from __future__ import annotations

import os
import re
import json
import time
import uuid
import hashlib
import platform
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Callable


# -------------------------
# Helpers
# -------------------------

def _sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def _now_ts() -> int:
    return int(time.time())

def _safe_json_dump(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)


# -------------------------
# Data Models
# -------------------------

@dataclass
class PrivacyControls:
    dp_training_enabled: bool = False
    dp_noise_multiplier: Optional[float] = None
    dp_clip_norm: Optional[float] = None


@dataclass
class ModelAccessControls:
    artifact_store: str
    public_access: Optional[bool] = None


@dataclass
class PrivacyRiskTests:
    canary_test_ran: bool = False
    canary_exposed: Optional[bool] = None
    canary_hash: Optional[str] = None
    canary_trigger_prompts_tested: int = 0

    memorization_test_ran: bool = False
    memorization_flagged: Optional[bool] = None
    memorization_notes: Optional[str] = None


@dataclass
class GovernanceContextBundle:
    run_id: str
    timestamp: int
    domain: str
    intended_use: str

    environment: Dict[str, Any]
    model_access_controls: ModelAccessControls
    privacy_controls: PrivacyControls
    privacy_risk_tests: PrivacyRiskTests

# -------------------------
# Main Wrapper
# -------------------------

class PrivacyGovernanceLogger:
    """
    A lightweight, self-contained governance logger for PyTorch training runs.

    - Writes a single JSON bundle to disk at end of run
    - Optionally runs canary and memorization checks via a user-provided generator fn
    - Avoids exporting raw canary strings (hashes instead)
    """

    def __init__(
        self,
        *,
        output_dir: str = "./governance_out",
        domain: str,
        intended_use: str,
        model_access_controls: ModelAccessControls,
        privacy_controls: PrivacyControls,
    ):
        self.output_dir = output_dir
        self.domain = domain
        self.intended_use = intended_use
        self.model_access_controls = model_access_controls
        self.privacy_controls = privacy_controls

        self.run_id = f"run_{_now_ts()}_{uuid.uuid4().hex[:8]}"
        self._risk_tests = PrivacyRiskTests()

        self._bundle_path = os.path.join(self.output_dir, self.run_id, "governance_context_bundle.json")

    # ---------
    # Lifecycle
    # ---------

    def start(self) -> None:
        # You can call this at the beginning of training if you want.
        os.makedirs(os.path.join(self.output_dir, self.run_id), exist_ok=True)

    def end(self) -> GovernanceContextBundle:
        bundle = self._build_bundle()
        _safe_json_dump(self._bundle_path, asdict(bundle))
        return bundle

    # -------------------------
    # Risk Tests (Optional)
    # -------------------------

    def run_canary_exposure_test(
        self,
        *,
        canary: str,
        trigger_prompts: List[str],
        generate_fn: Callable[[str], str],
        match_mode: str = "substring",  # "substring" | "regex"
        regex_flags: int = 0,
    ) -> None:
        """
        Canary test: checks if model output reproduces a known canary token.

        - Never stores raw canary
        - Stores hash + boolean exposure result
        """

        self._risk_tests.canary_test_ran = True
        self._risk_tests.canary_hash = _sha256_str(canary)
        self._risk_tests.canary_trigger_prompts_tested = len(trigger_prompts)

        exposed = False
        for p in trigger_prompts:
            out = generate_fn(p) or ""

            if match_mode == "substring":
                if canary in out:
                    exposed = True
                    break
            elif match_mode == "regex":
                if re.search(canary, out, flags=regex_flags):
                    exposed = True
                    break
            else:
                raise ValueError(f"Unknown match_mode: {match_mode}")

        self._risk_tests.canary_exposed = exposed

    def run_memorization_smoke_test(
        self,
        *,
        heldout_prompts: List[str],
        generate_fn: Callable[[str], str],
        suspicious_substrings: Optional[List[str]] = None,
        max_flagged: int = 1,
    ) -> None:
        """
        Very lightweight memorization smoke test.

        Flags if model output contains suspicious patterns (e.g. email-like strings).
        This is NOT a full membership inference test — but it's a practical guardrail.
        """

        self._risk_tests.memorization_test_ran = True

        # Default suspicious patterns (lightweight)
        patterns = suspicious_substrings or [
            "@",                # emails
            "ssn",              # SSN mentions
            "social security",
            "api_key",
            "password",
            "BEGIN PRIVATE KEY",
        ]

        flagged = 0
        notes = []

        for p in heldout_prompts:
            out = (generate_fn(p) or "").lower()
            for s in patterns:
                if s.lower() in out:
                    flagged += 1
                    notes.append(f"Found suspicious substring '{s}' for prompt hash={_sha256_str(p)}")
                    break
            if flagged >= max_flagged:
                break

        self._risk_tests.memorization_flagged = flagged > 0
        self._risk_tests.memorization_notes = "; ".join(notes) if notes else "No obvious leakage patterns detected."

    # -------------------------
    # Export for Agent Context
    # -------------------------

    def as_agent_context_json(self) -> str:
        """
        Returns a compact JSON string meant to be pasted into a code agent prompt/context.
        """
        bundle = self._build_bundle()
        obj = asdict(bundle)

        # Keep it compact-ish
        return json.dumps(obj, indent=2, sort_keys=True)

    def write_agent_context_file(self) -> str:
        """
        Writes the bundle file and returns the path (useful for passing into other tooling).
        """
        self.end()
        return self._bundle_path

    # -------------------------
    # Internal Bundle Builder
    # -------------------------

    def _build_bundle(self) -> GovernanceContextBundle:
        env = {
            "timestamp": _now_ts(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "hostname": platform.node(),
        }

        bundle = GovernanceContextBundle(
            run_id=self.run_id,
            timestamp=_now_ts(),
            domain=self.domain,
            intended_use=self.intended_use,
            environment=env,
            model_access_controls=self.model_access_controls,
            privacy_controls=self.privacy_controls,
            privacy_risk_tests=self._risk_tests,
        )

        # Integrity hash of the bundle (excluding itself)
        tmp = asdict(bundle)
        tmp["bundle_hash"] = None
        bundle.bundle_hash = _sha256_str(json.dumps(tmp, sort_keys=True))
        return bundle
