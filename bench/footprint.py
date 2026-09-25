#!/usr/bin/env python3
"""Measure what the full preceptor behavior adds to EVERY request and EVERY event.

Two numbers matter and they are different in kind:

  1. Per-request prompt tokens -- context files, agent descriptions as the
     delegate tool renders them, and tool-preceptor's schema. Paid on every
     provider call of every session. Estimate: chars / 4.
  2. Per-event hook latency -- the handlers run sequentially and IN-BAND, so
     their time is added to every tool call and every provider request, not
     just start-up. Measured at the code level with a minimal fake
     coordinator (no MagicMock -- its overhead would swamp the handlers) and
     representative payloads shaped like loop-streaming's, including
     worst-case tool_input sizes.

No Amplifier session is started and nothing is installed. Point --repo at any
checkout to compare revisions:

    uv run --no-project --with amplifier-core --with pyyaml \\
        python bench/footprint.py [--repo PATH] [--json]
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# 1. Per-request tokens
# ---------------------------------------------------------------------------


def _tok(chars: int) -> int:
    return round(chars / 4)


def _agent_description(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    front = text.split("---", 2)[1]
    return yaml.safe_load(front)["meta"]["description"]


def _behavior(repo: Path, name: str) -> dict[str, Any]:
    return yaml.safe_load((repo / "behaviors" / f"{name}.yaml").read_text())


def _context_files(repo: Path) -> list[str]:
    files: list[str] = []
    for name in ("preceptor-observer", "preceptor"):
        for ref in _behavior(repo, name).get("context", {}).get("include", []):
            files.append(ref.split(":", 1)[1])
    return files


def token_inventory(repo: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"context": {}, "agents": {}, "tool": {}}

    for rel in _context_files(repo):
        n = len((repo / rel).read_text(encoding="utf-8"))
        out["context"][rel] = {"chars": n, "tokens": _tok(n)}

    for ref in _behavior(repo, "preceptor")["agents"]["include"]:
        name = ref.split(":", 1)[1]
        desc = _agent_description(repo / "agents" / f"{name}.md")
        # tool-delegate renders: "  - {name}: {description}"
        line = f"  - {ref}: {desc}"
        out["agents"][ref] = {"chars": len(line), "tokens": _tok(len(line))}

    tool_cfg = next(
        t["config"]
        for t in _behavior(repo, "preceptor")["tools"]
        if t["module"] == "tool-preceptor"
    )
    mod = _import_module(repo, "tool-preceptor", "amplifier_module_tool_preceptor")
    tool = mod.PreceptorTool(_FakeCoordinator("/tmp/x"), dict(tool_cfg))
    rendered = json.dumps(
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }
    )
    out["tool"]["preceptor"] = {"chars": len(rendered), "tokens": _tok(len(rendered))}

    def total(section: str) -> int:
        return sum(v["tokens"] for v in out[section].values())

    out["totals"] = {s: total(s) for s in ("context", "agents", "tool")}
    out["totals"]["all"] = sum(out["totals"].values())
    return out


# ---------------------------------------------------------------------------
# 2. Per-event latency
# ---------------------------------------------------------------------------


class _FakeHooks:
    def __init__(self) -> None:
        self.handlers: dict[str, list[tuple[int, Any]]] = {}

    def register(self, event: str, handler: Any, priority: int = 0, name: str = ""):
        self.handlers.setdefault(event, []).append((priority, handler))
        self.handlers[event].sort(key=lambda p: p[0])

    async def emit(self, event: str, data: dict[str, Any]) -> None:
        for _p, h in self.handlers.get(event, ()):
            await h(event, data)


class _FakeCoordinator:
    def __init__(self, working_dir: str, session_id: str = "sess-bench") -> None:
        self.hooks = _FakeHooks()
        self.session_id = session_id
        self._wd = working_dir
        self.cleanups: list[Any] = []

    def get_capability(self, name: str) -> Any:
        return self._wd if name == "session.working_dir" else None

    def register_cleanup(self, fn: Any) -> None:
        self.cleanups.append(fn)

    async def mount(self, *_a: Any, **_k: Any) -> None:
        return None

    async def run_cleanups(self) -> None:
        for fn in self.cleanups:
            await fn()


def _import_module(repo: Path, module_dir: str, package: str):
    path = str(repo / "modules" / module_dir)
    for key in [k for k in sys.modules if k == package or k.startswith(package + ".")]:
        del sys.modules[key]
    sys.path.insert(0, path)
    try:
        return importlib.import_module(package)
    finally:
        sys.path.remove(path)


def _import_ms(repo: Path, module_dir: str, package: str, reps: int = 7) -> float:
    """Median wall time of `import <package>` in a fresh interpreter, with
    amplifier_core already imported (the kernel has always loaded it).

    COLD-INTERPRETER ONLY. A real Amplifier host has already imported
    `yaml` and `concurrent.futures` (via amplifier_foundation / asyncio)
    before any bundle module mounts, so savings from deferring those
    imports do not show up in a live session."""
    import subprocess

    code = (
        "import time, amplifier_core\n"
        "t = time.perf_counter()\n"
        f"import {package}\n"
        "print((time.perf_counter() - t) * 1000)"
    )
    env = dict(os.environ, PYTHONPATH=str(repo / "modules" / module_dir))
    samples = []
    for _ in range(reps):
        r = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        samples.append(float(r.stdout.strip()))
    return round(statistics.median(samples), 2)


def _drain_observer(obs: Any) -> None:
    bg = getattr(obs, "_background", None)
    if bg is not None:
        bg().submit(lambda: None).result()


def _payloads(sid: str) -> dict[str, dict[str, Any]]:
    small_input = {"file_path": "/home/u/project/src/app.py"}
    big = "x" * (1024 * 1024)
    huge = "x" * (10 * 1024 * 1024)
    return {
        "tool:pre/small": {
            "tool_name": "read_file",
            "tool_call_id": "c1",
            "tool_input": small_input,
            "parallel_group_id": None,
            "session_id": sid,
            "parent_id": None,
        },
        "tool:post/small": {
            "tool_name": "read_file",
            "tool_call_id": "c1",
            "tool_input": small_input,
            "result": {"success": True, "output": "y" * 20_000},
            "parallel_group_id": None,
            "session_id": sid,
            "parent_id": None,
        },
        "tool:pre/1MB": {
            "tool_name": "write_file",
            "tool_call_id": "c2",
            "tool_input": {"file_path": "/p/big.txt", "content": big},
            "session_id": sid,
            "parent_id": None,
        },
        "tool:post/1MB": {
            "tool_name": "write_file",
            "tool_call_id": "c2",
            "tool_input": {"file_path": "/p/big.txt", "content": big},
            "result": {"success": True, "output": big},
            "session_id": sid,
            "parent_id": None,
        },
        "tool:pre/10MB": {
            "tool_name": "write_file",
            "tool_call_id": "c3",
            "tool_input": {"file_path": "/p/huge.txt", "content": huge},
            "session_id": sid,
            "parent_id": None,
        },
        "provider:request": {
            "provider": "anthropic",
            "model": "claude-x",
            "iteration": 3,
            "session_id": sid,
            "parent_id": None,
        },
        "provider:response": {
            "provider": "anthropic",
            "usage": {"input": 1000, "output": 200},
            "session_id": sid,
            "parent_id": None,
        },
    }


def _bench(fn, n: int) -> dict[str, float]:
    """fn is an async no-arg callable. Returns per-call microseconds."""

    async def run() -> list[float]:
        samples: list[float] = []
        for _ in range(n):
            t0 = time.perf_counter_ns()
            await fn()
            samples.append((time.perf_counter_ns() - t0) / 1000)
        return samples

    s = _LOOP.run_until_complete(run())
    s.sort()
    return {
        "mean_us": round(statistics.fmean(s), 1),
        "p50_us": round(s[len(s) // 2], 1),
        "p99_us": round(s[min(len(s) - 1, int(len(s) * 0.99))], 1),
        "max_us": round(s[-1], 1),
    }


_LOOP = asyncio.new_event_loop()


def latency_inventory(repo: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"import_ms": {}, "observer": {}, "injector": {}}
    tmp = Path(tempfile.mkdtemp(prefix="preceptor-footprint-"))
    wd = str(tmp / "work" / "project")
    Path(wd).mkdir(parents=True)
    root_t = str(tmp / "store" / "{project}" / "preceptor")

    for mod_dir, pkg in (
        ("hooks-trajectory-observer", "amplifier_module_hooks_trajectory_observer"),
        ("hooks-cue-injector", "amplifier_module_hooks_cue_injector"),
        ("tool-preceptor", "amplifier_module_tool_preceptor"),
    ):
        out["import_ms"][mod_dir] = _import_ms(repo, mod_dir, pkg)

    obs = _import_module(
        repo, "hooks-trajectory-observer", "amplifier_module_hooks_trajectory_observer"
    )
    inj = _import_module(
        repo, "hooks-cue-injector", "amplifier_module_hooks_cue_injector"
    )

    # --- observer, disabled (what behaviors/preceptor.yaml ships) ----------
    c = _FakeCoordinator(wd)
    os.environ.pop("PRECEPTOR_ENABLED", None)
    _LOOP.run_until_complete(obs.mount(c, {"enabled": False, "root": root_t}))
    out["observer"]["disabled_handlers_registered"] = sum(
        len(v) for v in c.hooks.handlers.values()
    )

    # --- observer, enabled (observe-on / PRECEPTOR_ENABLED=1) -------------
    c = _FakeCoordinator(wd)
    _LOOP.run_until_complete(
        obs.mount(c, {"enabled": True, "root": root_t, "flush_every": 25})
    )
    out["observer"]["events"] = sorted(c.hooks.handlers)
    handler = c.hooks.handlers["tool:pre"][0][1]
    sid = c.session_id
    payloads = _payloads(sid)
    _LOOP.run_until_complete(
        handler("provider:resolve", {"provider": "anthropic", "model": "claude-x"})
    )
    per_event: dict[str, Any] = {}
    for label, data in payloads.items():
        event = label.split("/")[0]
        n = 30 if "10MB" in label else (200 if "1MB" in label else 5000)

        async def call(event=event, data=data):
            await handler(event, data)

        per_event[label] = _bench(call, n)
    # One "typical step": pre + post + request + response, small payloads,
    # includes the amortized flush every 25 records.
    step = [
        ("tool:pre", payloads["tool:pre/small"]),
        ("tool:post", payloads["tool:post/small"]),
        ("provider:request", payloads["provider:request"]),
        ("provider:response", payloads["provider:response"]),
    ]

    async def one_step():
        for e, d in step:
            await handler(e, d)

    per_event["step(pre+post+req+resp)/small"] = _bench(one_step, 2000)

    # TOTAL work for a 1 MB write, in-band + off-loop: pre + post with the
    # same arguments object (as loop-streaming emits them), then wait for the
    # background writer. This is CPU spent somewhere, not latency on the
    # step; it shows the pre/post de-duplication.
    big_pre = payloads["tool:pre/1MB"]
    big_post = dict(payloads["tool:post/1MB"], tool_input=big_pre["tool_input"])
    _drain_observer(obs)

    async def big_pair_total():
        await handler("tool:pre", big_pre)
        await handler("tool:post", big_post)
        _drain_observer(obs)

    per_event["total_work(pre+post 1MB, drained)"] = _bench(big_pair_total, 100)
    _drain_observer(obs)

    async def exec_end():
        for e, d in step:
            await handler(e, d)
        await handler("execution:end", {"session_id": sid})

    per_event["step+execution:end(flush)"] = _bench(exec_end, 500)
    _LOOP.run_until_complete(c.run_cleanups())
    out["observer"]["per_event"] = per_event

    # --- injector ----------------------------------------------------------
    def fresh_injector(with_ledger: bool):
        c = _FakeCoordinator(wd, session_id="s")
        _LOOP.run_until_complete(inj.mount(c, {"root": root_t}))
        if with_ledger:
            slug = wd.replace("/", "-")
            ledger = (
                Path(root_t.replace("{project}", slug))
                / "ledger"
                / "anthropic"
                / "claude-x"
                / "project.yaml"
            )
            ledger.parent.mkdir(parents=True, exist_ok=True)
            cues = [
                {"id": f"cue-{i:03d}", "status": "active", "text": f"Do thing {i}."}
                for i in range(8)
            ] + [
                {"id": f"cue-{i:03d}", "status": "retired", "text": "old"}
                for i in range(8, 60)
            ]
            ledger.write_text(yaml.safe_dump({"version": 3, "cues": cues}))
        return c

    counter = iter(range(10**9))

    def first_request(with_ledger: bool):
        c = fresh_injector(with_ledger)
        res = c.hooks.handlers["provider:resolve"][0][1]
        req = c.hooks.handlers["provider:request"][0][1]

        async def call():
            s = f"s{next(counter)}"
            await res(
                "provider:resolve",
                {"session_id": s, "provider": "anthropic", "model": "claude-x"},
            )
            r = await req(
                "provider:request", {"session_id": s, "provider": "anthropic"}
            )
            # Guard: never time the fail-open path by accident.
            want = "inject_context" if with_ledger else "continue"
            assert r.action == want, f"injector returned {r.action!r}, wanted {want!r}"

        return call

    out["injector"]["events"] = sorted(fresh_injector(False).hooks.handlers)
    out["injector"]["first_request/no-ledger"] = _bench(first_request(False), 500)
    out["injector"]["first_request/8-active-of-60"] = _bench(first_request(True), 300)
    c = fresh_injector(False)
    req = c.hooks.handlers["provider:request"][0][1]
    _LOOP.run_until_complete(req("provider:request", {"session_id": "s"}))

    async def later():
        await req("provider:request", {"session_id": "s"})

    out["injector"]["later_request(already dosed)"] = _bench(later, 20000)

    async def resolve():
        await c.hooks.handlers["provider:resolve"][0][1](
            "provider:resolve", {"session_id": "s", "provider": "a", "model": "m"}
        )

    out["injector"]["provider:resolve"] = _bench(resolve, 20000)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=HERE.parent)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    repo = args.repo.resolve()
    result = {
        "repo": str(repo),
        "tokens": token_inventory(repo),
        "latency": latency_inventory(repo),
    }
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    t = result["tokens"]
    print(f"repo: {repo}\n\nPER-REQUEST TOKENS (chars/4)")
    for section in ("context", "agents", "tool"):
        for k, v in t[section].items():
            print(f"  {section:8s} {k:40s} {v['chars']:6d} ch  {v['tokens']:5d} tok")
    print(f"  totals: {t['totals']}")
    lat = result["latency"]
    print(f"\nIMPORT ms (cold interpreter only): {lat['import_ms']}")
    print(
        f"\nOBSERVER disabled -> handlers registered: "
        f"{lat['observer']['disabled_handlers_registered']}"
    )
    print(f"OBSERVER enabled events: {', '.join(lat['observer']['events'])}")
    for k, v in lat["observer"]["per_event"].items():
        print(f"  {k:36s} {v}")
    print(f"\nINJECTOR events: {', '.join(lat['injector']['events'])}")
    for k, v in lat["injector"].items():
        if k != "events":
            print(f"  {k:36s} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
