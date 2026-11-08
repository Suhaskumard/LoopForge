"""Secret redaction (spec §13.2: "secret redaction in logs and prompts").

Applied wherever text that may contain credentials is stored or sent on: untrusted text placed in
prompts, agent-run summaries and errors, execution logs, audit events. It is a safety net, not a
guarantee: the primary control is that secrets are never mounted into the sandbox or given to
agents.
"""

import re

REDACTED = "[REDACTED]"

# Order matters: PEM blocks first (multi-line), then token shapes, then generic assignments.
_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S
    ),
    re.compile(r"\bsk-(?:proj-|live-|test-)?[A-Za-z0-9_-]{16,}"),  # OpenAI-style keys
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),  # GitHub tokens
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),  # Slack tokens
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}"),  # JWTs
    re.compile(r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/=-]{16,}"),
]
# key = value style assignments; keeps the key so logs stay readable.
_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Za-z0-9_.-]*(?:password|passwd|secret|api[_-]?key|access[_-]?key|token|"
    r"private[_-]?key|credential)[A-Za-z0-9_.-]*)(\s*[:=]\s*)(?:\"[^\"\n]{1,}\"|'[^'\n]{1,}'|[^\s\"',;]{3,})"
)


def redact(text: str) -> str:
    """Return `text` with credential-shaped substrings replaced by a marker."""
    if not text:
        return text
    for pattern in _PATTERNS:
        if pattern.groups:  # Bearer: keep the scheme word
            text = pattern.sub(lambda m: f"{m.group(1)} {REDACTED}", text)
        else:
            text = pattern.sub(REDACTED, text)
    return _ASSIGNMENT.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)


def contains_secret(text: str) -> bool:
    return redact(text) != text
