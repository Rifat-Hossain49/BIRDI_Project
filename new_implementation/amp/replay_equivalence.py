#!/usr/bin/env python3
"""Replay-equivalence gate for the frontend adapter.

The adapter is only usable if it reproduces the ORIGINAL checker's verdict
exactly. This module renders an event sequence back into the TBout.txt text
format the driver emits, executes the frozen checker file end to end (its own
SignalTxt_to_dictlist and check_dut, unmodified), and compares that verdict
against the adapter's.

Any mismatch means the adapter changed benchmark semantics, which disqualifies
it. Unsupported cases are reported, never patched.
"""
from __future__ import annotations

import contextlib
import io
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from frontend_adapter import CheckerAdapter, DriverParse, Event


def render_tbout(events: List[Event], observed: List[Dict[str, int]],
                 parse: DriverParse) -> str:
    """Reproduce the driver's $fdisplay output format line for line.

    Format, from the generated drivers:
        scenario: %d, clk = %d, reset = %d, q = %d
    with a "[check]" prefix on observation lines. SignalTxt_to_dictlist splits
    on ", " then " = ", and on ": " for the scenario field.
    """
    lines = []
    for ev, obs in zip(events, observed):
        parts = [f"scenario: {ev.scenario}", "clk = 0"]
        for sig in parse.input_signals:
            parts.append(f"{sig} = {ev.inputs.get(sig, 0)}")
        for sig in parse.output_signals:
            parts.append(f"{sig} = {obs.get(sig, 0)}")
        prefix = "[check]" if ev.check_en else ""
        lines.append(prefix + ", ".join(parts))
    return "\n".join(lines) + "\n"


def run_original_checker(source: str, tbout: str) -> Tuple[Optional[list], str]:
    """Execute the frozen checker file verbatim against a supplied TBout.txt."""
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory(prefix="amp_replay_") as td:
        Path(td, "TBout.txt").write_text(tbout, encoding="utf-8")
        os.chdir(td)
        ns: Dict[str, object] = {"__name__": "__frozen_checker__"}
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                exec(compile(source, "<frozen_checker_full>", "exec"), ns)
            # check_dut was invoked by the file's own trailer; re-run it to
            # capture the returned failing-scenario list.
            vectors = ns["SignalTxt_to_dictlist"](tbout)
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                failed = ns["check_dut"](vectors)
            return failed, ""
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"
        finally:
            os.chdir(cwd)


def check_equivalence(source: str, parse: DriverParse,
                      observed: List[Dict[str, int]]) -> Dict[str, object]:
    """Compare adapter verdict against the original checker's verdict."""
    adapter = CheckerAdapter(source)
    if not adapter.supported:
        return {"supported": False, "reason": adapter.reason, "equivalent": None}
    tbout = render_tbout(parse.events, observed, parse)
    original, err = run_original_checker(source, tbout)
    if original is None:
        return {"supported": False, "reason": f"original checker failed: {err}",
                "equivalent": None}
    try:
        mine = adapter.run_original(parse.events, observed)
    except Exception as exc:
        return {"supported": False, "reason": f"adapter raised: {exc}",
                "equivalent": None}
    return {"supported": True, "reason": "",
            "equivalent": list(original) == list(mine),
            "original_failed_scenarios": list(original),
            "adapter_failed_scenarios": list(mine)}
