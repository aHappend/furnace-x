"""Strict packed-vector syntax lowering for the installed Yosys Verilog reader.

Only zero-based, descending, constant two-dimensional packed wire/reg
declarations are supported. This does not lower procedural logic or memories.
Each generated input is retained alongside the original source fingerprints.
"""

import re
import hashlib

from run_support import ROOT


TOKEN = re.compile(
    r"//[^\n]*|/\*.*?\*/|\"(?:\\.|[^\"\\])*\"|"
    r"[a-zA-Z_$][a-zA-Z0-9_$]*|\\[^\s]+|"
    r"\d+'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ?]+|'[01xXzZ]|"
    r"\d+|\(\*|\*\)|\+:|-:|<<<|>>>|===|!==|<<|>>|<=|>=|==|!=|&&|\|\||"
    r"\*\*|[^\s]", re.DOTALL
)


def lower_packed(text):
    tokens = [m.group() for m in TOKEN.finditer(text)
              if not m.group().startswith(("//", "/*"))]
    widths = {}
    declarations = {}
    for i, token in enumerate(tokens):
        if token not in ("wire", "reg", "logic"):
            continue
        start = i + 1
        if tokens[start] == "signed":
            start += 1
        if tokens[start] != "[":
            continue
        dimensions = tokens[start:start + 10]
        if not (len(dimensions) == 10 and dimensions[0] == "[" and
                dimensions[2:5] == [":", "0", "]"] and dimensions[5] == "[" and
                dimensions[7:10] == [":", "0", "]"] and
                dimensions[1].isdigit() and dimensions[6].isdigit()):
            continue
        outer, inner = int(dimensions[1]) + 1, int(dimensions[6]) + 1
        declarations[start] = (start + 10, outer * inner)
        name_pos = start + 10
        while True:
            name = tokens[name_pos]
            if not re.fullmatch(r"[a-zA-Z_$][a-zA-Z0-9_$]*", name):
                raise ValueError(f"unsupported packed declaration near {name}")
            if name in widths and widths[name] != inner:
                raise ValueError(f"scope-dependent packed width for {name}")
            widths[name] = inner
            name_pos += 1
            if (tokens[name_pos] != "," or
                tokens[name_pos + 1] in ("input", "output", "inout", "wire", "reg")):
                break
            name_pos += 1

    def bracket(position):
        if tokens[position] != "[":
            raise ValueError("expected bracket")
        level, end = 1, position + 1
        while level and end < len(tokens):
            level += (tokens[end] == "[") - (tokens[end] == "]")
            end += 1
        if level:
            raise ValueError("unbalanced packed select")
        return position + 1, end - 1, end

    def emit(start, end):
        result = []
        i = start
        while i < end:
            if i in declarations:
                after, width = declarations[i]
                result.append(f"[{width-1}:0]")
                i = after
                continue
            name = tokens[i]
            if name not in widths or i + 1 >= end or tokens[i + 1] != "[":
                result.append(name)
                i += 1
                continue
            lo, hi, after = bracket(i + 1)
            index = emit(lo, hi)
            if any(t in (":", "+:", "-:") for t in tokens[lo:hi]):
                raise ValueError(f"unsupported outer packed range on {name}")
            width = widths[name]
            offset, length = "0", str(width)
            if after < end and tokens[after] == "[":
                lo, hi, after = bracket(after)
                separators = [j for j in range(lo, hi)
                              if tokens[j] in (":", "+:", "-:")]
                if not separators:
                    offset, length = emit(lo, hi), "1"
                elif len(separators) == 1:
                    split = separators[0]
                    left, right = emit(lo, split), emit(split + 1, hi)
                    if tokens[split] == ":":
                        offset, length = right, f"(({left})-({right})+1)"
                    elif tokens[split] == "+:":
                        offset, length = left, right
                    else:
                        offset, length = f"(({left})-({right})+1)", right
                else:
                    raise ValueError(f"unsupported nested packed range on {name}")
            result.append(f"{name}[(({index})*{width})+({offset}) +: {length}]")
            i = after
        return " ".join(result)

    lowered = emit(0, len(tokens))
    # Fail closed on any unlowered multidimensional packed declaration.
    if re.search(r"\b(?:wire|reg|logic)\s+(?:signed\s+)?\[[^]]+\]\s*\[", lowered):
        raise ValueError("unsupported multidimensional packed declaration remains")
    return lowered + "\n"


def prepare_sources(run):
    sources = []
    for source in sorted(ROOT.glob("rtl/*.sv")):
        target = run.path / source.name
        (ROOT / target).write_text(lower_packed(source.read_text()))
        sources.append(str(target))
        run.receipt.setdefault("lowered_sha256", {})[str(target)] = hashlib.sha256(
            (ROOT / target).read_bytes()).hexdigest()
    if not sources:
        raise AssertionError("no deliverable RTL sources")
    run.save()
    return sources
