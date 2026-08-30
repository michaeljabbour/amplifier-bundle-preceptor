"""Three-way split discipline, enforced in code rather than by convention.

    harvest  -- form-analyst reads observations and corrections HERE ONLY.
                Cues are born here. Burned by construction.
    climb    -- the calibration loop evaluates candidates here. Repeatedly.
                Also burned: anything you select on, you overfit to.
    confirm  -- SEALED. Unsealed exactly once, at the end, to report a number.

Why three and not two: a cue proposed from a failure observed on task T, then
validated on task T, is unfalsifiable. `cue-lifecycle.md` already requires gate
and grade probes to be disjoint. This makes that structural instead of stated --
`.confirm` raises until someone calls `unseal_for_gate()`, so there is no
convention left to violate.

The evidence that this matters, and it is not subtle. RSEA (arXiv:2606.28374)
ablated exactly this gate:

    variant                        in-sample    test
    ReAct baseline (no evolution)      --       63.6
    RSEA, NO held-out gate           100.0      66.7      <- 33-point gap
    RSEA, strict held-out gate         --       67.3

Selecting on the evolution set drives in-sample to a perfect 100% and leaves a
33-point train/test gap. And an ungated competitor (Dynamic Cheatsheet) did not
merely fail to help on transfer -- it collapsed below baseline, 0.136 vs 0.429.

Adapted from `amplifier-optimizer-runpod/evals/splits.py` (same author), whose
design brief is the sentence worth keeping: "Climbing on the set you bless from
produces confident nonsense."
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Generic, TypeVar

T = TypeVar("T")


class SealedSplitError(RuntimeError):
    """Raised on any read of `.confirm` before an explicit unseal.

    This is the "enforce it in code" requirement. There is no convention to
    violate because the attribute itself refuses to yield data.
    """


@dataclass
class Splits(Generic[T]):
    """harvest / climb / confirm, with `confirm` sealed until deliberately opened."""

    harvest: list[T]
    climb: list[T]
    _confirm: list[T]
    seed: int
    unsealed: bool = False
    unseal_reason: str | None = None
    unsealed_at: str | None = None
    access_log: list[str] = field(default_factory=list)

    @property
    def confirm(self) -> list[T]:
        if not self.unsealed:
            raise SealedSplitError(
                "confirm split accessed while still sealed. It is read exactly "
                "once, after climbing has stopped, to report a number nobody "
                "selected on. If you are climbing, use `.climb`. If you are "
                "proposing cues, use `.harvest`."
            )
        return list(self._confirm)

    def unseal_for_gate(self, reason: str) -> list[T]:
        """The one sanctioned read. Every call is recorded.

        Idempotent -- a second call does not re-leak anything already unsealed --
        but each is logged, because a run that unsealed three times during
        climbing is a run whose final number means nothing, and the report should
        be able to say so.
        """
        stamp = datetime.now(UTC).isoformat()
        self.access_log.append(f"{stamp} :: {reason}")
        if not self.unsealed:
            self.unsealed = True
            self.unseal_reason = reason
            self.unsealed_at = stamp
        return list(self._confirm)

    def to_report_dict(self) -> dict:
        return {
            "seed": self.seed,
            "harvest_n": len(self.harvest),
            "climb_n": len(self.climb),
            "confirm_n": len(self._confirm),
            "confirm_unsealed": self.unsealed,
            "confirm_unseal_reason": self.unseal_reason,
            "confirm_unsealed_at": self.unsealed_at,
            "confirm_access_count": len(self.access_log),
        }


def split_tasks(
    tasks: list[T],
    *,
    seed: int = 0,
    harvest_frac: float = 0.4,
    climb_frac: float = 0.3,
) -> Splits[T]:
    """Deterministic three-way partition. `confirm` gets the remainder.

    Defaults give 40/30/30. Note that `confirm` is the smallest split and that is
    a real cost: it bounds the precision of the only number you are allowed to
    report. Widen it if the final estimate matters more than search speed.

    Raises rather than silently producing an empty split -- an empty `confirm` is
    a run with no reportable result, and discovering that at the end is worse
    than refusing at the start.
    """
    if len(tasks) < 3:
        raise ValueError(f"need at least 3 tasks to make 3 splits, got {len(tasks)}")
    if not (
        0 < harvest_frac < 1 and 0 < climb_frac < 1 and harvest_frac + climb_frac < 1
    ):
        raise ValueError(f"bad fractions: harvest={harvest_frac} climb={climb_frac}")

    shuffled = list(tasks)
    random.Random(seed).shuffle(shuffled)

    n = len(shuffled)
    h_end = max(1, int(n * harvest_frac))
    c_end = max(h_end + 1, h_end + int(n * climb_frac))
    c_end = min(c_end, n - 1)  # always leave at least one for confirm

    return Splits(
        harvest=shuffled[:h_end],
        climb=shuffled[h_end:c_end],
        _confirm=shuffled[c_end:],
        seed=seed,
    )
