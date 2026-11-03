#!/usr/bin/env python3
"""Read-only scheduler witnesses for the logical backend comparator.

These are not functional RTL oracles. Opaque deferred-deletion queues remain
unresolved: neither a name match nor Verilated::quiesce() proves them empty.
"""

import re


RULE = "settled-scheduler-capture-v1"


def inventory(model):
    return {
        f"{cls}.{name}": {"kind": kind, "type": spec}
        for cls, row in model["classes"].items()
        if cls in model.get("active_classes", model["classes"])
        for kind in ("unserialized_data", "unserialized_scheduler")
        for name, spec in row[kind].items()
    }


def capture_fields(model):
    """Every inspectable member has its own tagged, extent-checked witness."""
    fields = {}
    for identity, row in inventory(model).items():
        spec = row["type"]
        trigger = re.fullmatch(r"VlTriggerVec<(\d+)>", spec) if isinstance(spec, str) else None
        if trigger:
            bits = int(trigger[1])
            if bits < 1:
                raise ValueError("invalid scheduler trigger extent: " + identity)
            fields[identity] = {"bytes": 8 * ((bits + 63) // 64), "capture": "trigger"}
        elif spec == "VlMTaskVertex":
            fields[identity] = {"bytes": 1, "capture": "vertex"}
        elif identity.endswith(".__Vm_modelp") and spec == "Vfurnace_x4_top* const":
            fields[identity] = {"bytes": 1, "capture": "model_pointer"}
        elif identity.endswith(".vlSymsp") and spec == "Vfurnace_x4_top__Syms* const":
            fields[identity] = {"bytes": 1, "capture": "symbol_pointer"}
        elif identity.endswith(".__Vm_threadPoolp") and spec == "VlThreadPool*":
            fields[identity] = {"bytes": 1, "capture": "pool_pointer"}
        elif re.fullmatch(r"\w+__Syms\.__Vm_even_cycle__(?:ico|act|nba)", identity) and spec == {
                "bits": 1, "shape": [], "element_bytes": 1, "words": 1}:
            fields[identity] = {"bytes": 1, "capture": "parity"}
    return fields


def accounting(model, directory):
    from boot_lifetime import Lifetime
    from boot_logical_state import clean_cpp, closing

    members = inventory(model)
    captures = capture_fields(model)
    native = any(row["capture"] in ("vertex", "pool_pointer", "parity")
                 for row in captures.values())
    graph, graph_error = None, None
    if native:
        analysis = Lifetime(directory, clean_cpp, closing)
        graph, graph_error = analysis.graph, analysis.graph_error
        if graph is not None:
            # quiesce() in the installed runtime is a no-op. The emitted final
            # join, not that API's name, must cover every asynchronous dispatch.
            additions = sum(len(re.findall(r"\baddTask\s*\(", clean_cpp(path.read_text())))
                            for path in directory.glob("*.cpp"))
            if additions != 1:
                graph, graph_error = None, "additional or missing asynchronous dispatch"
    result = {}
    for identity, member in members.items():
        row = {**member, "disposition": "unresolved"}
        capture = captures.get(identity)
        if capture is None:
            row["failure"] = "no read-only witness or complete lifetime proof for this member"
        elif capture["capture"] in ("vertex", "pool_pointer") and graph is None:
            row["failure"] = graph_error or "missing complete native task graph"
        elif capture["capture"] == "parity":
            field = identity.split(".", 1)[1]
            if field.endswith("__nba"):
                if graph is None:
                    row["failure"] = graph_error or "missing parity/final-join proof"
                else:
                    row["disposition"] = "settled_capture"
            else:
                uses = sum(len(re.findall(r"\b" + re.escape(field) + r"\b",
                                          clean_cpp(path.read_text())))
                           for path in directory.glob("*.cpp"))
                header = directory / (identity.split(".", 1)[0] + ".h")
                initialized = re.search(
                    r"\bbool\s+" + re.escape(field) + r"\s*=\s*false\s*;", header.read_text())
                if uses or not initialized:
                    row["failure"] = "unused scheduler phase is accessed or not initialized false"
                else:
                    row["disposition"] = "settled_capture"
        elif capture["capture"] == "vertex" and identity.split(".__Vm_mtaskstate_", 1)[-1] not in (
                graph["proof"]["vertices"]):
            row["failure"] = "vertex absent from joined task graph"
        else:
            row["disposition"] = "settled_capture"
        if row["disposition"] == "settled_capture":
            row["proof"] = {
                "rule": RULE, "identity": identity, "capture": capture,
                "generated_sha256": model["generated_sha256"],
                **({"native_task_graph": graph["proof"]}
                   if native and capture["capture"] in ("vertex", "pool_pointer", "parity")
                   and graph is not None else {}),
            }
        result[identity] = row
    return result


def validate_accounting(plan):
    expected = {f"{owner}:{name}": row
                for owner in ("baseline", "candidate")
                for name, row in inventory(plan[owner]).items()}
    if plan["unserialized"].keys() != expected.keys():
        raise ValueError("logical accounting omitted or introduced unserialized state")
    unresolved = []
    for key, member in expected.items():
        row = plan["unserialized"][key]
        if any(row.get(name) != value for name, value in member.items()):
            raise ValueError("unserialized scheduler identity/type changed: " + key)
        owner, identity = key.split(":", 1)
        capture = capture_fields(plan[owner]).get(identity)
        proof = row.get("proof", {})
        if row.get("disposition") == "unresolved":
            unresolved.append(key)
            continue
        if row.get("disposition") != "settled_capture" or not capture or (
                proof.get("rule") != RULE or proof.get("identity") != identity or
                proof.get("capture") != capture or not proof.get("generated_sha256") or
                proof["generated_sha256"] != plan[owner]["generated_sha256"]):
            raise ValueError("unproved settled-boundary scheduler accounting: " + key)
        if capture["capture"] in ("vertex", "pool_pointer") or (
                capture["capture"] == "parity" and identity.endswith("__nba")):
            graph = proof.get("native_task_graph", {})
            if not graph.get("final_join_covers_all_tasks") or not graph.get("vertices") or (
                    graph.get("rule") !=
                    "emitted-task-order-and-exact-fan-in-with-parity-final-join-v1"):
                raise ValueError("missing settled-boundary native final join: " + key)
            if capture["capture"] == "vertex" and identity.split(
                    ".__Vm_mtaskstate_", 1)[-1] not in graph["vertices"]:
                raise ValueError("unaccounted scheduler vertex: " + key)
    if unresolved:
        raise ValueError(f"{len(unresolved)} unserialized generated fields lack a "
                         "settled-boundary proof: " + ", ".join(unresolved))


def validate_capture(model, values):
    expected = capture_fields(model)
    if values.keys() != expected.keys():
        raise ValueError("scheduler capture omitted or introduced fields")
    syms = next((name for name in model["classes"] if name.endswith("__Syms")), None)
    parity_name = (syms + ".__Vm_even_cycle__nba") if syms else None
    for identity, spec in expected.items():
        value = values[identity]
        if len(value) != spec["bytes"]:
            raise ValueError("scheduler capture extent mismatch: " + identity)
        kind = spec["capture"]
        if kind == "parity":
            if value not in (b"\x00", b"\x01") or (
                    not identity.endswith("__nba") and value != b"\x00"):
                raise ValueError("scheduler parity mismatch: " + identity)
        elif kind == "vertex":
            parity = values.get(parity_name)
            if parity not in (b"\x00", b"\x01") or value != (
                    b"\x02" if parity == b"\x01" else b"\x01"):
                raise ValueError("pending task or scheduler parity mismatch: " + identity)
        elif kind.endswith("_pointer") and value != b"\x01":
            raise ValueError("scheduler pointer topology mismatch: " + identity)


def compare(plan, baseline, candidate):
    validate_capture(plan["baseline"], baseline)
    validate_capture(plan["candidate"], candidate)
    a, b = capture_fields(plan["baseline"]), capture_fields(plan["candidate"])
    exact = 0
    for identity in a.keys() | b.keys():
        left, right = a.get(identity), b.get(identity)
        if (left and left["capture"] == "trigger") or (right and right["capture"] == "trigger"):
            if left != right or baseline.get(identity) != candidate.get(identity):
                raise ValueError("scheduler trigger mismatch: " + identity)
            exact += left["bytes"]
    return {"scheduler_exact_trigger_bytes": exact,
            "scheduler_witness_fields": {"baseline": len(a), "candidate": len(b)}}


def exporter_lines(model):
    root = next(name for name in model["classes"] if name.endswith("___024root"))
    lines = []
    for index, (identity, spec) in enumerate(capture_fields(model).items()):
        cls, member = identity.split(".", 1)
        if cls == root:
            expression = "dut.rootp->" + member
        elif cls == root.removesuffix("___024root") + "__Syms":
            expression = "dut.rootp->vlSymsp->" + member
        else:
            raise ValueError("unrecognized scheduler owner: " + cls)
        kind = spec["capture"]
        if kind == "trigger":
            lines += [
                f"    uint64_t scheduler_value_{index}[{spec['bytes'] // 8}];",
                f"    for (unsigned i = 0; i < {spec['bytes'] // 8}; ++i) {{",
                f"        uint64_t value = {expression}.word(i);",
                f"        scheduler_value_{index}[i] = value;",
                "    }",
                f'    field("{identity}", scheduler_value_{index}, {spec["bytes"]});',
            ]
            continue
        if kind == "vertex":
            value = (f"unsigned({expression}.areUpstreamDepsDone(false)) | "
                     f"(unsigned({expression}.areUpstreamDepsDone(true)) << 1)")
        elif kind == "model_pointer":
            value = expression + " == &dut"
        elif kind == "symbol_pointer":
            value = expression + " != nullptr && &" + expression + "->TOP == dut.rootp"
        elif kind == "pool_pointer":
            value = (expression + " != nullptr && " + expression +
                     " == dut.contextp()->threadPoolp()")
        else:
            value = expression
        lines += [f"    const uint8_t scheduler_value_{index} = {value};",
                  f'    field("{identity}", &scheduler_value_{index}, 1);']
    return lines
