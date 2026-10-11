"""Prompt Injection Defense Guardrail (L4).

Scans untrusted free-text fields (e.g. on_call_note, raw alert strings)
for jailbreak patterns, prompt leaks, command injection, and instruction overrides.
"""

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Heuristic signature patterns for prompt injection, jailbreaks, and system overrides
INJECTION_PATTERNS = [
    r"(?i)\bignore\s+(all\s+)?(previous|prior|above)\s+instructions\b",
    r"(?i)\bsystem\s+override\b",
    r"(?i)\bdisregard\s+(all\s+)?(previous|prior)\s+rules\b",
    r"(?i)\byou\s+are\s+now\s+(an\s+unrestricted|a\s+different)\s+agent\b",
    r"(?i)\bjailbreak\b",
    r"(?i)\bdrop\s+all\s+tables\b",
    r"(?i)\broute\s+to\s+self-serve\s+runbook\s+without\s+verification\b",
    r"(?i)\bdo\s+not\s+verify\b",
    r"(?i)\bsuppress\s+(all\s+)?alerts?\b",
    r"(?i)\bbypass\s+guardrails?\b",
]


class InjectionScanResult(BaseModel):
    """Result of prompt injection analysis on untrusted text."""

    is_injection: bool = Field(..., description="Whether a prompt injection attempt was detected.")
    matched_pattern: str | None = Field(
        default=None, description="Regex pattern that triggered detection."
    )
    sanitized_text: str = Field(..., description="Sanitized version of the input text.")
    quarantine_reason: str | None = Field(
        default=None, description="Diagnostic explanation if flagged."
    )


class PromptInjectionGuardrail:
    """Defensive scanner inspecting untrusted free-text fields."""

    def __init__(self, patterns: list[str] | None = None):
        self.patterns = [re.compile(p) for p in (patterns or INJECTION_PATTERNS)]

    def scan_text(self, text: str) -> InjectionScanResult:
        """Scan free-text field for known adversarial injection signatures."""
        if not text:
            return InjectionScanResult(
                is_injection=False,
                matched_pattern=None,
                sanitized_text="",
                quarantine_reason=None,
            )

        for pattern in self.patterns:
            match = pattern.search(text)
            if match:
                logger.warning("Prompt injection detected: matched '%s'", pattern.pattern)
                return InjectionScanResult(
                    is_injection=True,
                    matched_pattern=pattern.pattern,
                    sanitized_text="[REDACTED: POTENTIAL PROMPT INJECTION]",
                    quarantine_reason=f"Prompt injection detected matching adversarial pattern: {pattern.pattern}",
                )

        return InjectionScanResult(
            is_injection=False,
            matched_pattern=None,
            sanitized_text=text,
            quarantine_reason=None,
        )

    def scan_alert(self, alert: dict[str, Any]) -> InjectionScanResult:
        """Scan all free-text fields within an alert payload."""
        note = str(alert.get("on_call_note", ""))
        tags_combined = " ".join(f"{k}:{v}" for k, v in alert.get("tags", {}).items())
        text_to_scan = f"{note} {tags_combined}"
        return self.scan_text(text_to_scan)


# Global singleton instance
_guardrail_instance: PromptInjectionGuardrail | None = None


def get_injection_guardrail() -> PromptInjectionGuardrail:
    """Get or create singleton PromptInjectionGuardrail."""
    global _guardrail_instance
    if _guardrail_instance is None:
        _guardrail_instance = PromptInjectionGuardrail()
    return _guardrail_instance
