#!/usr/bin/env python3
"""Count developer-correction turns from an agent session transcript.

WHY THIS EXISTS
---------------
Every eval run in this ecosystem already produces the data for this metric and
nothing reads it. `amplifier-bundle-evaluation` drives trials with an "AI User"
whose system prompt instructs it, verbatim (ai_user.py:122-129):

    "The agent will often return before completing the scenario. It might ask a
     clarifying question, stop after a single mode-confirmation gate, pause for
     direction, or offer options without picking one. In every such case, send a
     short follow-up that nudges it to keep going ('go ahead', 'yes', 'proceed',
     or a brief direct answer)"

That is a scripted developer issuing corrections. Every follow-up it sends is a
turn the agent should not have needed. An exhaustive search across the
evaluation, ergonomics, feedback, behavioral-plasticity, context-intelligence
and survey bundles found zero implementations counting them.

The metric is cheap precisely because the nudge policy is already written down
as an instruction: a rule the agent is *told* to follow is a rule you can count
against. That system prompt is simultaneously the behavior spec and the
labeling function.

WHY NOT AN LLM JUDGE
--------------------
arXiv:2608.22960 (He et al., Aug 2026) shows full-trace LLM judges exhibit
systematic collider bias -- shown a whole trajectory they score *semantic
relevance*, not *causal contribution*, picking the step that looks decisive in
hindsight rather than the one that changed the outcome. So this module is
deterministic string classification and nothing else. It will misclassify some
turns. It will misclassify them the SAME WAY in both arms of an A/B, which is
the property that actually matters for a paired comparison.

USAGE
-----
    python3 bench/correction_turns.py <transcript.jsonl> [...]
    python3 bench/correction_turns.py --json results/*/extraction/**/transcript.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# Classification
#
# Ordered most-specific first; the first matching class wins. These patterns
# are deliberately narrow. A turn that matches nothing is SUBSTANTIVE, because
# the expensive error here is silently discounting a real correction -- an
# undercount makes an arm look better than it is.
# --------------------------------------------------------------------------

# Pure "keep going" with no new information. The agent stopped when it
# shouldn't have. Cheap for the human, but still a turn they had to spend.
NUDGE = re.compile(
    r"^\W*(?:"
    r"go\s*ahead|proceed|continue|carry\s*on|keep\s*going|"
    r"y|ya|yes|yep|yeah|yup|ok|okay|k|sure|please\s*do|do\s*it|"
    r"go|go\s*for\s*it|sounds?\s*good|lgtm|approved?"
    r")\b[\s.!]*$",
    re.IGNORECASE,
)

# The agent asked something it could have decided or discovered itself.
CLARIFICATION_ANSWER = re.compile(
    r"^\W*(?:"
    r"(?:use|try|pick|choose|option)\s+\S+|"
    r"the\s+(?:first|second|third|latter|former)|"
    r"either|both|neither|"
    r"(?:it'?s|its)\s+\S+"
    r")\b",
    re.IGNORECASE,
)

# The agent did the wrong thing and is being redirected. The expensive class.
REDIRECT = re.compile(
    r"\b(?:"
    r"no,|nope|don'?t|do\s*not|stop|wrong|incorrect|instead|"
    r"actually|rather\s+than|not\s+(?:that|what|quite)|"
    r"revert|undo|roll\s*back|back\s*out|"
    r"you\s+(?:missed|forgot|broke|didn'?t)|"
    r"that'?s\s+not|still\s+(?:broken|failing|wrong)|"
    r"try\s+again|redo"
    r")",
    re.IGNORECASE,
)

CLASSES = ("nudge", "clarification", "redirect", "substantive")


def classify(text: str) -> str:
    """Bucket one follow-up turn. Order matters; first match wins."""
    t = (text or "").strip()
    if not t:
        return "nudge"
    # Redirect is checked first and anywhere in the string: "ok, but no, use X"
    # is a redirect that happens to open with an acknowledgement.
    if REDIRECT.search(t):
        return "redirect"
    if NUDGE.match(t):
        return "nudge"
    if CLARIFICATION_ANSWER.match(t) and len(t) < 120:
        return "clarification"
    return "substantive"


@dataclass
class Turn:
    index: int
    kind: str
    chars: int
    preview: str


@dataclass
class Report:
    """One session's correction profile.

    `correction_turns` is the headline: user turns after the opening request.
    A perfect session is 0 -- the agent did the whole task from one prompt.
    """

    path: str
    user_turns: int = 0
    correction_turns: int = 0
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(CLASSES, 0))
    turns: list[Turn] = field(default_factory=list)
    parse_errors: int = 0

    @property
    def weighted(self) -> float:
        """Cost-weighted corrections.

        A redirect costs the developer far more than a "go ahead" -- it means
        work was done wrong and has to be undone. Weights are a judgment call
        and are stated here rather than buried: report the raw count as the
        primary endpoint and this only as a secondary.
        """
        w = {"nudge": 1.0, "clarification": 1.5, "redirect": 3.0, "substantive": 2.0}
        return round(sum(w[k] * v for k, v in self.counts.items()), 2)


# Platform-injected content that arrives with role=user but is NOT a human
# speaking. Counting these inflates every arm and would have silently corrupted
# the first A/B this tool was pointed at -- a spot-check on real transcripts
# caught `<system-reminder>` and `<turn_aborted>` being scored as "redirect".
_SYSTEM_BLOCK = re.compile(
    r"<system-reminder\b.*?</system-reminder>|<system-reminder\b[^>]*>",
    re.IGNORECASE | re.DOTALL,
)
_NOT_HUMAN_PREFIX = (
    "<system-reminder",
    "<turn_aborted",
    "<tool_result",
    "[tool_result",
    "<function_results",
    "<local-command",
    "<command-name",
    "caveat: the messages below",
)


def _text_of(msg: dict) -> str:
    """Extract plain text from a message whose content may be str or blocks."""
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for b in c:
            if isinstance(b, dict) and b.get("type") in (None, "text"):
                parts.append(b.get("text") or "")
            elif isinstance(b, str):
                parts.append(b)
        return "\n".join(p for p in parts if p)
    return ""


def human_text(msg: dict) -> str:
    """Return only what a human actually typed, or "" if this turn is machinery.

    A real user turn can still CARRY an appended system-reminder, so strip those
    blocks before deciding the turn is empty -- otherwise a genuine correction
    that happens to have a reminder stapled to it gets dropped, which is the
    opposite error and just as bad.
    """
    raw = _text_of(msg).strip()
    if not raw:
        return ""
    if raw.lower().startswith(_NOT_HUMAN_PREFIX):
        return ""
    return _SYSTEM_BLOCK.sub("", raw).strip()


def analyze(path: Path) -> Report:
    """Read one transcript.jsonl and count the user's follow-up turns.

    Tolerates schema drift: transcript formats here are untyped dict literals
    with no schema and no tests behind them, so every field access is a .get()
    and a malformed line is counted, not fatal.
    """
    rep = Report(path=str(path))
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"  ! cannot read {path}: {e}", file=sys.stderr)
        return rep

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            rep.parse_errors += 1
            continue
        if not isinstance(rec, dict):
            rep.parse_errors += 1
            continue

        # Transcripts nest the message differently across versions.
        inner = rec.get("message")
        msg: dict = inner if isinstance(inner, dict) else rec
        if msg.get("role") != "user":
            continue

        text = human_text(msg)
        if not text:
            continue  # platform machinery, not a human correction

        rep.user_turns += 1
        if rep.user_turns == 1:
            continue  # the opening request is not a correction

        kind = classify(text)
        rep.correction_turns += 1
        rep.counts[kind] += 1
        rep.turns.append(
            Turn(
                index=rep.user_turns,
                kind=kind,
                chars=len(text),
                preview=(text[:77] + "...") if len(text) > 80 else text,
            )
        )
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("paths", nargs="+", help="transcript.jsonl files (globs ok)")
    ap.add_argument("--json", action="store_true", help="emit JSON for aggregation")
    ap.add_argument("--detail", action="store_true", help="print every correction turn")
    args = ap.parse_args()

    files: list[Path] = []
    for p in args.paths:
        hits = sorted(Path().glob(p)) if any(c in p for c in "*?[") else [Path(p)]
        files.extend(h for h in hits if h.is_file())

    if not files:
        print("no transcript files matched", file=sys.stderr)
        return 2

    reports = [analyze(f) for f in files]

    if args.json:
        print(
            json.dumps(
                [asdict(r) | {"weighted": r.weighted} for r in reports], indent=2
            )
        )
        return 0

    print(
        f"{'session':<44} {'turns':>6} {'corr':>5} {'nudge':>6} "
        f"{'clar':>5} {'redir':>6} {'subst':>6} {'wt':>6}"
    )
    print("-" * 92)
    for r in reports:
        c = r.counts
        print(
            f"{Path(r.path).parent.name[:43]:<44} {r.user_turns:>6} {r.correction_turns:>5} "
            f"{c['nudge']:>6} {c['clarification']:>5} {c['redirect']:>6} "
            f"{c['substantive']:>6} {r.weighted:>6.1f}"
        )
        if args.detail:
            for t in r.turns:
                print(f"    #{t.index} [{t.kind}] {t.preview}")

    n = len(reports)
    tot = sum(r.correction_turns for r in reports)
    red = sum(r.counts["redirect"] for r in reports)
    print("-" * 92)
    print(
        f"{'TOTAL (' + str(n) + ' sessions)':<44} "
        f"{sum(r.user_turns for r in reports):>6} {tot:>5}"
    )
    print(f"\nmean corrections/session   {tot / n:.2f}")
    print(f"mean redirects/session     {red / n:.2f}   <- the expensive class")
    if any(r.parse_errors for r in reports):
        print(f"\n! {sum(r.parse_errors for r in reports)} unparseable lines skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
