"""Narrow packed-array syntax lowering for Yosys's Verilog frontend.

Descending literal [A:0][B:0] packed objects are bit-identical to one vector.
Only their declarations and element selects change. No logic is substituted.
The portable functional smoke also executes these exact generated sources.
"""

import hashlib
import re


DECLARATION = re.compile(
    r"\[(\d+):0\]\s*\[(\d+):0\]\s+"
    r"([A-Za-z_]\w*(?:[ \t]*,[ \t]*[A-Za-z_]\w*)*)"
)


def lower(text):
    shapes = {}

    def declaration(match):
        major, minor = int(match[1]) + 1, int(match[2]) + 1
        names = match[3]
        for name in re.findall(r"[A-Za-z_]\w*", names):
            if name in shapes:
                raise ValueError(f"duplicate packed declaration: {name}")
            shapes[name] = minor
        return f"[{major * minor - 1}:0] {names}"

    text = DECLARATION.sub(declaration, text)
    if not shapes:
        return text, shapes
    pattern = re.compile(r"\b(" + "|".join(sorted(shapes, key=len, reverse=True)) + r")\s*\[")

    def references(source):
        pieces = []
        cursor = 0
        while True:
            match = pattern.search(source, cursor)
            if match is None:
                pieces.append(source[cursor:])
                return "".join(pieces)
            pieces.append(source[cursor:match.start()])
            end = match.end()
            nesting = 1
            while end < len(source) and nesting:
                nesting += (source[end] == "[") - (source[end] == "]")
                end += 1
            if nesting:
                raise ValueError("unbalanced packed-array select")
            index = source[match.end():end - 1]
            if ":" in index:
                raise ValueError(f"packed major slice unsupported: {match[1]}[{index}]")
            if source[end:].lstrip().startswith("["):
                raise ValueError(f"chained packed select unsupported: {match[1]}")
            width = shapes[match[1]]
            pieces.append(f"{match[1]}[({references(index)})*{width} +: {width}]")
            cursor = end

    return references(text), shapes


def sources(run):
    directory = run.directory / "yosys-rtl"
    directory.mkdir(exist_ok=False)
    paths = []
    records = {}
    for source in sorted((run.root / "rtl").glob("*.sv")):
        translated, shapes = lower(source.read_text())
        destination = directory / source.name
        destination.write_text(translated)
        paths.append(destination)
        records[source.name] = {
            "packed_objects": shapes,
            "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "output_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        }
    run.receipt["yosys_syntax_lowering"] = records
    run.save()
    return paths
