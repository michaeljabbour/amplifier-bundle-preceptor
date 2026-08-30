#!/usr/bin/env python3
"""Run an arm comparison across isolated Digital Twin containers.

One container per trial, destroyed after. That is the only way to get genuine
independence: a reused container carries filesystem state, a warmed bundle cache,
and whatever the last trial left in ~/.amplifier.

NO GOLDEN IMAGE, deliberately. `incus publish` would bake ANTHROPIC_API_KEY into
the image -- the profile writes it to /root/.amplifier/settings.yaml and
passthrough writes it to /etc/profile.d/dtu-env.sh, both of which get captured.
Provisioning measured at 19s on the resized VM, which is cheap enough that
avoiding a secret-bearing image is the obviously better trade.

    python3 bench/dtu_run.py --trials 30 --concurrency 8
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from verdict import compare, required_n

REPO = "git+https://github.com/michaeljabbour/amplifier-bundle-preceptor@main"

# Arms. Each differs ONLY in which bundle gets composed -- task, model, image,
# and provisioning are identical, which is what makes the comparison controlled.
ARMS: dict[str, str | None] = {
    "baseline": None,
    "observe-off": f"{REPO}#subdirectory=bundles/observe-only.yaml",
    "observe-on": f"{REPO}#subdirectory=bundles/observe-on.yaml",
}

# Deterministic and regex-checkable. No grader model anywhere in the path:
# arXiv:2608.22960 showed full-trace judges score semantic relevance rather than
# causal contribution, so a judge here would add variance AND bias.
TASKS: list[tuple[str, str, str]] = [
    ("echo", "Reply with exactly this and nothing else: PONG", r"^PONG\.?$"),
    ("arith", "What is 17 * 23? Reply with only the number.", r"^391\.?$"),
    (
        "recall",
        "Reply with exactly the third word of this sentence: alpha beta gamma delta.",
        r"^gamma\.?$",
    ),
]

PROFILE = """name: preceptor-trial
base:
  image: ubuntu:24.04
passthrough:
  allow_external: true
  services:
    - name: anthropic
      key_env: ANTHROPIC_API_KEY
provision:
  setup_cmds:
    - apt-get update && apt-get install -y git curl
    - curl -LsSf https://astral.sh/uv/install.sh | sh
    # cryptography 50.0.1 ships an aarch64 wheel whose Rust binding SIGILLs on
    # this VM (exit 132). It crashes the process during module loading -- and
    # because tools load BEFORE hooks, the crash lands after tools and before
    # any hook mounts. That is the entire reason observe-on recorded nothing:
    # not composition, not consent, a segfaulting dependency two layers down.
    - uv tool install -vv git+https://github.com/microsoft/amplifier --with "cryptography==45.0.7"
    - amplifier bundle add git+https://github.com/microsoft/amplifier-foundation@main --app
{extra}
    - |
      mkdir -p /root/.amplifier
      cat > /root/.amplifier/settings.yaml << 'SETTINGS'
      config:
        providers:
          - module: provider-anthropic
            source: git+https://github.com/microsoft/amplifier-module-provider-anthropic@main
            config:
              api_key: ${{ANTHROPIC_API_KEY}}
      SETTINGS
"""


@dataclass
class Trial:
    arm: str
    task: str
    idx: int
    launched: bool = False
    provision_s: float = 0.0
    run_s: float = 0.0
    exit_code: int = -1
    response: str = ""
    correct: bool = False
    observations: int = 0
    error: str = ""


@dataclass
class Arm:
    name: str
    trials: list[Trial] = field(default_factory=list)

    def series(self, attr: str) -> list[float]:
        return [
            float(getattr(t, attr))
            for t in self.trials
            if t.launched and t.exit_code == 0
        ]


def _sh(cmd: list[str], timeout: int = 900) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def _json_of(s: str) -> dict:
    i = s.find("{")
    if i == -1:
        return {}
    try:
        return json.loads(s[i:])
    except json.JSONDecodeError:
        return {}


def run_trial(arm: str, task: tuple[str, str, str], idx: int) -> Trial:
    name, prompt, pattern = task
    t = Trial(arm=arm, task=name, idx=idx)
    cid = f"pt-{arm}-{name}-{idx}-{uuid.uuid4().hex[:6]}"

    bundle = ARMS[arm]
    # Env consent is independent of composition -- see the module docstring.
    env_prefix = "PRECEPTOR_ENABLED=1 " if arm == "observe-on" else ""
    extra = f"    - amplifier bundle add '{bundle}' --app" if bundle else ""
    prof = Path(tempfile.mkdtemp(prefix="ptrial-")) / "p.yaml"
    prof.write_text(PROFILE.format(extra=extra), encoding="utf-8")

    try:
        t0 = time.monotonic()
        rc, out, err = _sh(
            ["amplifier-digital-twin", "launch", str(prof), "--name", cid], timeout=900
        )
        t.provision_s = time.monotonic() - t0
        if rc != 0:
            t.error = (err or out)[-300:]
            return t
        t.launched = True

        # --timeout none: the exec default is 600s and RAISES, which would kill a
        # slow session mid-trial and silently drop it from the sample.
        t1 = time.monotonic()
        rc, out, err = _sh(
            [
                "amplifier-digital-twin",
                "exec",
                "--timeout",
                "none",
                cid,
                "--",
                "bash",
                "-lc",
                f"{env_prefix}amplifier run --output-format json {json.dumps(prompt)}",
            ],
            timeout=900,
        )
        t.run_s = time.monotonic() - t1

        env = _json_of(out)
        t.exit_code = int(env.get("exit_code", rc))
        inner = _json_of(env.get("stdout", ""))
        t.response = (inner.get("response") or "").strip()
        t.correct = bool(re.match(pattern, t.response, re.IGNORECASE))

        # Did the observer actually record? Function check, separate from timing.
        if arm == "observe-on":
            _, o2, _ = _sh(
                [
                    "amplifier-digital-twin",
                    "exec",
                    "--timeout",
                    "120",
                    cid,
                    "--",
                    "bash",
                    "-lc",
                    "cat /root/.amplifier/projects/*/preceptor/observations/*.jsonl 2>/dev/null | wc -l",
                ],
                timeout=180,
            )
            try:
                t.observations = int((_json_of(o2).get("stdout") or "0").strip() or 0)
            except ValueError:
                pass
    finally:
        # destroy uses force=False and swallows stop errors -> orphans. Always
        # follow with a forced delete.
        _sh(["amplifier-digital-twin", "destroy", cid], timeout=300)
        _sh(
            [
                "colima",
                "ssh",
                "--profile",
                "resolve",
                "--",
                "incus",
                "delete",
                cid,
                "--force",
            ],
            timeout=300,
        )
    return t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=10, help="trials per arm per task")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--tasks", type=int, default=0, help="limit to first N tasks")
    ap.add_argument("--out", default="bench-results/dtu-latest.json")
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY not set; passthrough would silently skip it",
            file=sys.stderr,
        )
        return 2
    os.environ.setdefault("AMPLIFIER_DTU_INCUS_LAUNCH_TIMEOUT_SECONDS", "600")

    tasks = TASKS[: args.tasks] if args.tasks else TASKS
    work = [(a, t, i) for a in ARMS for t in tasks for i in range(args.trials)]
    print(
        f"{len(ARMS)} arms x {len(tasks)} tasks x {args.trials} trials = {len(work)} containers, "
        f"{args.concurrency}-way concurrent\n"
    )

    arms = {a: Arm(a) for a in ARMS}
    done = 0
    t0 = time.monotonic()
    with cf.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {ex.submit(run_trial, a, t, i): (a, t[0]) for a, t, i in work}
        for f in cf.as_completed(futs):
            tr = f.result()
            arms[tr.arm].trials.append(tr)
            done += 1
            flag = (
                "ok " if (tr.launched and tr.exit_code == 0 and tr.correct) else "FAIL"
            )
            extra = f" obs={tr.observations}" if tr.arm == "observe-on" else ""
            print(
                f"  [{done:>3}/{len(work)}] {tr.arm:<12} {tr.task:<7} "
                f"prov={tr.provision_s:5.1f}s run={tr.run_s:6.1f}s {flag}{extra}"
                f"{('  ' + tr.error[:60]) if tr.error else ''}",
                flush=True,
            )
    wall = time.monotonic() - t0

    print(f"\n{'=' * 74}\nRESULTS  ({wall / 60:.1f} min wall)\n{'=' * 74}")
    summary: dict = {"arms": {}, "comparisons": {}, "wall_min": round(wall / 60, 2)}
    for name, a in arms.items():
        launched = [t for t in a.trials if t.launched]
        ok = [t for t in launched if t.exit_code == 0]
        correct = [t for t in ok if t.correct]
        runs = a.series("run_s")
        summary["arms"][name] = {
            "n": len(a.trials),
            "launched": len(launched),
            "exit_ok": len(ok),
            "correct": len(correct),
            "mean_run_s": round(statistics.mean(runs), 3) if runs else None,
            "stdev_run_s": round(statistics.stdev(runs), 3) if len(runs) > 1 else 0.0,
            "mean_provision_s": round(
                statistics.mean([t.provision_s for t in launched]), 2
            )
            if launched
            else None,
            "observations": sum(t.observations for t in a.trials),
        }
        s = summary["arms"][name]
        print(f"\n{name}")
        print(
            f"  launched {s['launched']}/{s['n']}   exit ok {s['exit_ok']}   correct {s['correct']}"
        )
        if runs:
            print(
                f"  run  {s['mean_run_s']:.2f}s +/- {s['stdev_run_s']:.2f}    provision {s['mean_provision_s']:.1f}s"
            )
        if name == "observe-on":
            print(f"  observation records written: {s['observations']}")

    base = arms["baseline"].series("run_s")
    print(f"\n{'-' * 74}\nOVERHEAD vs baseline")
    for name in [a for a in ARMS if a != "baseline"]:
        r = compare(base, arms[name].series("run_s"))
        summary["comparisons"][name] = {
            "verdict": r.verdict,
            "detail": r.detail,
            "cohens_d": r.cohens_d,
        }
        print(f"  {name:<12} {r.verdict:<13} {r.detail}")

    print("\nHARM")
    harmed = [n for n, s in summary["arms"].items() if s["correct"] < s["n"]]
    if harmed:
        for n in harmed:
            s = summary["arms"][n]
            print(
                f"  {n:<12} {s['n'] - s['correct']} of {s['n']} trials wrong or failed"
            )
    else:
        print("  none - every arm completed every trial with the correct answer")
    summary["harm"] = bool(harmed)

    if base:
        print(
            f"\npower: n={len(base)} usable in control. "
            f"Need ~{required_n(base, 0.8)} for d=0.8, ~{required_n(base, 0.5)} for d=0.5."
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    summary["trials"] = [asdict(t) for a in arms.values() for t in a.trials]
    out.write_text(json.dumps(summary, indent=2))
    print(f"\nwrote {out}")
    return 1 if harmed else 0


if __name__ == "__main__":
    sys.exit(main())
