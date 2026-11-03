#!/usr/bin/env python3
"""Sample disposable generated evaluation functions without changing model state."""

import re
from pathlib import Path


FUNCTION = re.compile(
    r"((?:VL_INLINE_OPT )?void (\w+___(?:ico|nba|act)_(?:sequent|comb)__TOP__\d+)"
    r"\(Vfurnace_x4_top___024root\* vlSelf\) \{)")


def instrument(directory, digest):
    (directory / "generated_schedule.h").write_bytes(
        Path(__file__).with_name("generated_schedule.h").read_bytes())
    records = []
    for path in sorted(directory.glob("Vfurnace_x4_top*DepSet*.cpp")):
        if "Slow" in path.name:
            continue
        text = path.read_text()
        names = []

        def replace(match):
            names.append(match[2])
            return (match[1] + "\n    static thread_local furnace_schedule::Counter "
                    f'counter("{match[2]}");\n'
                    "    furnace_schedule::Sample sample(counter);\n")

        changed = FUNCTION.sub(replace, text)
        if names:
            before = digest(path)
            path.write_text('#include "generated_schedule.h"\n' + changed)
            records.append({"file": path.name, "before_sha256": before,
                            "after_sha256": digest(path), "functions": names})
    if not records:
        raise ValueError("no generated evaluation functions found for profiling")
    return records
