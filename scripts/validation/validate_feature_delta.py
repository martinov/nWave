"""validate_feature_delta — schema validator for lean feature-delta.md (C14).

Dev/CI-only validator (NOT shipped to end users). Enforces D2 schema-typed
section headings: every `## Wave: <NAME> / [<TYPE>] <Section>` heading must
declare a TYPE token in {REF, WHY, HOW}. Non-Wave `##` headings are out of
scope (e.g. `## Expansions requested` is a meta heading).

CLI contract (AC-5.c):
- Exit 0 on a well-formed lean feature-delta.md.
- Exit non-zero with explicit list of malformed headings otherwise.

Architecture:
- Pure functional core (`validate_feature_delta_content`) — no I/O.
- Thin CLI shell (`main`) — reads file, calls pure function, prints, returns
  exit code.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Domain types — pure data carriers
# ---------------------------------------------------------------------------

#: Tokens accepted in the `[<TYPE>]` slot of a Wave heading per D2.
ALLOWED_TYPE_TOKENS: frozenset[str] = frozenset({"REF", "WHY", "HOW"})

#: Match a Wave-prefixed `##` heading. Captures (wave_name, type_token, tail).
#: Anchored on the schema separator ` / ` so non-conforming headings still
#: parse but flag a violation.
_WAVE_HEADING_RE = re.compile(
    r"^##\s+Wave:\s+(?P<wave>[A-Za-z0-9_\- ]+?)\s*/\s*"
    r"\[(?P<type>[^\]]+)\]\s+(?P<section>.+?)\s*$"
)

#: Match any heading that starts with `## Wave:` — used to detect Wave headings
#: that are malformed AND lack the schema separator entirely.
_WAVE_PREFIX_RE = re.compile(r"^##\s+Wave:\s")

#: Match any `##` markdown heading (level-2 only, not `###` or deeper).
_H2_RE = re.compile(r"^##\s+(?!#)(?P<text>.+?)\s*$")


class Offender(NamedTuple):
    """A heading that violates the D2 schema."""

    line: int
    heading: str
    reason: str


class ValidationResult(NamedTuple):
    """Outcome of validating one feature-delta.md."""

    is_valid: bool
    offenders: list[Offender]
    wave_section_count: int


# ---------------------------------------------------------------------------
# Pure core
# ---------------------------------------------------------------------------


def _classify_wave_heading(line_no: int, raw_text: str) -> Offender | None:
    """Validate one Wave heading. Pure.

    Args:
        line_no: 1-based line number for diagnostics.
        raw_text: stripped heading line, including the leading `## `.

    Returns:
        None if the heading conforms to the schema; an Offender otherwise.
    """
    match = _WAVE_HEADING_RE.match(raw_text)
    if match is None:
        return Offender(
            line=line_no,
            heading=raw_text,
            reason=(
                "missing schema prefix; expected "
                "'## Wave: <NAME> / [REF|WHY|HOW] <Section>'"
            ),
        )
    type_token = match.group("type")
    if type_token not in ALLOWED_TYPE_TOKENS:
        return Offender(
            line=line_no,
            heading=raw_text,
            reason=(
                f"invalid type token '[{type_token}]'; "
                f"expected one of {sorted(ALLOWED_TYPE_TOKENS)}"
            ),
        )
    return None


def validate_feature_delta_content(content: str) -> ValidationResult:
    """Validate a feature-delta.md document body. Pure function.

    Walks each line; for every `## Wave:` heading delegates to
    `_classify_wave_heading`. Other H2 headings are ignored (meta sections
    such as `## Expansions requested` are out-of-scope per scope of D2).

    Args:
        content: file body (UTF-8 text).

    Returns:
        ValidationResult with `is_valid` true iff no offenders were found.
    """
    offenders: list[Offender] = []
    wave_count = 0

    for idx, line in enumerate(content.splitlines(), start=1):
        if not _WAVE_PREFIX_RE.match(line):
            continue
        wave_count += 1
        offender = _classify_wave_heading(idx, line.rstrip())
        if offender is not None:
            offenders.append(offender)

    return ValidationResult(
        is_valid=not offenders,
        offenders=offenders,
        wave_section_count=wave_count,
    )


# ---------------------------------------------------------------------------
# Thin CLI shell — only side effect boundary
# ---------------------------------------------------------------------------


def _format_success(result: ValidationResult) -> str:
    return f"Feature delta is valid. {result.wave_section_count} wave sections checked."


def _format_failure(result: ValidationResult) -> str:
    lines = [f"Feature delta has {len(result.offenders)} malformed headings:"]
    for offender in result.offenders:
        lines.append(f"  line {offender.line}: {offender.heading} - {offender.reason}")
    return "\n".join(lines)


def validate_feature_delta(file_path: Path) -> ValidationResult:
    """Read `file_path` and validate its content. Thin I/O wrapper.

    Args:
        file_path: Path to a feature-delta.md file.

    Returns:
        ValidationResult.
    """
    content = file_path.read_text(encoding="utf-8")
    return validate_feature_delta_content(content)


def main(argv: list[str] | None = None) -> int:
    """CLI entry: `python validate_feature_delta.py <path-to-feature-delta.md>`.

    Args:
        argv: optional argument list (defaults to `sys.argv[1:]`).

    Returns:
        0 on success, 1 on any malformed heading or I/O error.
    """
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(
            "usage: validate_feature_delta.py <path-to-feature-delta.md>",
            file=sys.stderr,
        )
        return 1

    target = Path(args[0])
    if not target.is_file():
        print(f"error: {target} is not a file", file=sys.stderr)
        return 1

    result = validate_feature_delta(target)
    if result.is_valid:
        print(_format_success(result))
        return 0
    print(_format_failure(result))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
