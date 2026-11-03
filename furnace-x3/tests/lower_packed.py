"""Narrow, fail-closed lowering of this project's zero-based packed port arrays.

Only literal descending two-dimensional packed ranges are accepted. Unpacked
RAMs and their selectors are untouched. Every change retains its source line
and is recorded for independent review and behavioral equivalence checks.
"""

import hashlib
import re


DECLARATION = re.compile(
    r"\b(?:wire|reg)\s+\[(\d+):0\]\s*\[(\d+):0\]([^\n;]*)(?=[;\n])")
IDENTIFIER = re.compile(r"[A-Za-z_]\w*")


def split_commas(text):
    start = depth = 0
    for index, character in enumerate(text):
        if character in "({[":
            depth += 1
        elif character in ")}]":
            depth -= 1
        elif character == "," and depth == 0:
            yield text[start:index]
            start = index + 1
    yield text[start:]


def bracket(text, position):
    if text[position] != "[":
        raise ValueError("expected selector")
    depth = 1
    for index in range(position + 1, len(text)):
        if text[index] == "[":
            depth += 1
        elif text[index] == "]":
            depth -= 1
            if not depth:
                return text[position + 1:index], index + 1
    raise ValueError("unterminated selector")


def select(base, selector, width):
    if "+:" in selector or "-:" in selector:
        raise ValueError(f"unsupported packed selector {selector}")
    if ":" in selector:
        hi, lo = selector.split(":")
        return f"[(({hi})+1)*{width}-1:({lo})*{width}]"
    return f"[({selector})*{width}+:{width}]"


def lower(text, filename):
    packed = {}
    changes = []

    def declaration(match):
        outer, inner = int(match[1]) + 1, int(match[2]) + 1
        for item in split_commas(match[3]):
            item = item.strip()
            if not item:
                continue
            name = IDENTIFIER.match(item)
            if not name or (name.end() != len(item) and item[name.end():].lstrip()[:1] != "="):
                raise ValueError(f"{filename}: unsupported packed declaration {item}")
            if name[0] in packed:
                raise ValueError(f"{filename}: ambiguous scoped declaration {name[0]}")
            packed[name[0]] = (outer, inner)
        old = match[0]
        result = re.sub(r"\[\d+:0\]\s*\[\d+:0\]",
                        f"[{outer * inner - 1}:0]", old, count=1)
        changes.append({"line": text.count("\n", 0, match.start()) + 1,
                        "before": old, "after": result})
        return result

    flattened = DECLARATION.sub(declaration, text)
    if re.search(r"\b(?:wire|reg)\s+\[[^\]\n]+\]\s*\[", flattened):
        raise ValueError(f"{filename}: unhandled packed declaration")
    if packed:
        pattern = re.compile(r"\b(" + "|".join(map(re.escape, packed)) + r")\s*(?=\[)")
        position = 0
        pieces = []
        for match in pattern.finditer(flattened):
            if match.start() < position:
                continue
            name = match[1]
            selector, end = bracket(flattened, match.end())
            width = packed[name][1]
            after = end
            while after < len(flattened) and flattened[after].isspace():
                after += 1
            if after < len(flattened) and flattened[after] == "[":
                inner, end = bracket(flattened, after)
                if ":" in selector:
                    raise ValueError(f"{filename}: nested range selection")
                if "+:" in inner:
                    start, length = inner.split("+:")
                    result = f"{name}[({selector})*{width}+({start})+:{length}]"
                elif "-:" in inner:
                    start, length = inner.split("-:")
                    result = f"{name}[({selector})*{width}+({start})-:{length}]"
                elif ":" in inner:
                    hi, lo = inner.split(":")
                    result = f"{name}[({selector})*{width}+({lo})+:(({hi})-({lo})+1)]"
                else:
                    result = f"{name}[({selector})*{width}+({inner})]"
            else:
                result = name + select(name, selector, width)
            old = flattened[match.start():end]
            changes.append({"line": flattened.count("\n", 0, match.start()) + 1,
                            "before": old, "after": result})
            pieces.extend((flattened[position:match.start()], result))
            position = end
        pieces.append(flattened[position:])
        flattened = "".join(pieces)
    return flattened, {
        "source": filename,
        "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "lowered_sha256": hashlib.sha256(flattened.encode()).hexdigest(),
        "packed_objects": packed, "changes": changes,
    }
