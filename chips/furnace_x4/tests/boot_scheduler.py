#!/usr/bin/env python3
"""Read-only scheduler witnesses for the logical backend comparator.

These are not functional RTL oracles. An unused deleter requires a source-bound
construction/non-escape proof; neither its name nor quiesce() proves it empty.
"""

import hashlib
import re


RULE = "settled-scheduler-capture-v1"
DELETER_RULE = "default-empty-deleter-with-no-enqueue-or-escape-v1"
RUNTIME_RULE = "audited-verilator-5.020-debian-runtime-v1"
# Whole-file identities bind the audited vector construction, deletion, trigger,
# vertex acquire/release and worker FIFO semantics, not just API names.
RUNTIME_SHA256 = {
    "verilated.h": "5dae77881c31423d9e0ed126192eaed0721b3f88dd2d7a709c57152e2a861c35",
    "verilated.cpp": "b784038c3cf821588ff4576653b540355889c0621bc258d1b349c29a63836c35",
    "verilated_types.h": "dd56d87f929e7c2a10879e245ce1a7fe30056e86d42e37f5eca5fedf4c020a48",
    "verilated_threads.h": "2164e6b4aa0f366097d95f9e979ce0f999391e7c46183fd31a869a4f7b662b3d",
    "verilated_threads.cpp": "c1290e944bb50e80ee5bf27ab1efdc032aac023ade148ef74d6a45db8bb6f132",
    "verilated_funcs.h": "db34fde6fae46db0dbfa6ad8858d29a6005d2db97b5817e285233fa4d7c2c9d4",
    "verilated_save.h": "e25098f63bd1866afa751c24846bf1962b8fc37e87fff192ee817ca0a4fe9d29",
    "verilated_save.cpp": "0486fac12c0ffe87f220aa92bb5b4594acf4fdf954f3c409424ba892620ae6da",
}


def runtime_library(includes):
    hashes = {name: hashlib.sha256((includes / name).read_bytes()).hexdigest()
              for name in RUNTIME_SHA256}
    proof = {"rule": RUNTIME_RULE, "source_sha256": hashes}
    validate_runtime(proof)
    return proof


def validate_runtime(proof):
    if proof != {"rule": RUNTIME_RULE, "source_sha256": RUNTIME_SHA256}:
        raise ValueError("scheduler runtime library differs from the audited source")


def deleter_proof(model, directory, identity, runtime):
    from boot_logical_state import clean_cpp

    validate_runtime(runtime)
    paths = {path.name: path for path in directory.iterdir()
             if path.name.startswith("V") and path.suffix in (".h", ".cpp")}
    if not model["generated_sha256"] or paths.keys() != model["generated_sha256"].keys() or any(
            hashlib.sha256(path.read_bytes()).hexdigest() != model["generated_sha256"][name]
            for name, path in paths.items()):
        raise ValueError("deferred-deletion generated source identity changed")
    cls, member = identity.split(".", 1)
    if not cls.endswith("__Syms") or member != "__Vm_deleter":
        raise ValueError("unrecognized deferred-deletion owner")
    uses = []
    for path in sorted(directory.iterdir()):
        if not path.name.startswith("V") or path.suffix not in (".h", ".cpp"):
            continue
        text = clean_cpp(path.read_text())
        # A class reference or another deleter type could enqueue indirectly.
        if re.search(r"\b(?:VlClassRef|VlClass|VlDeletable|VL_NEW)\b", text):
            raise ValueError("generated dynamic class can enqueue deferred deletion")
        for line_number, line in enumerate(text.splitlines(), 1):
            if not re.search(r"\b" + re.escape(member) + r"\b|\bVlDeleter\b", line):
                continue
            declaration = path.name == cls + ".h" and re.fullmatch(
                r"\s*VlDeleter " + re.escape(member) + r";\s*", line)
            drain = path.name == cls.removesuffix("__Syms") + ".cpp" and re.fullmatch(
                r"\s*vlSymsp->" + re.escape(member) + r"\.deleteAll\(\);\s*", line)
            if not (declaration or drain):
                raise ValueError("deferred-deletion queue can be modified or escape: " + path.name)
            uses.append({"file": path.name, "line": line_number,
                         "operation": "default_construct" if declaration else "drain"})
    if sorted(row["operation"] for row in uses) != ["default_construct", "drain"]:
        raise ValueError("incomplete deferred-deletion construction/use inventory")
    return {
        "rule": DELETER_RULE, "identity": identity,
        "generated_sha256": model["generated_sha256"], "runtime": runtime,
        "uses": uses, "queues": {"m_newGarbage": 0, "m_deleteNow": 0},
        "reason": "Default vectors start empty; no enqueue, address escape or class allocation "
                  "exists. Draining an always-empty queue cannot invoke a destructor.",
    }


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


def accounting(model, directory, runtime=None):
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
        if member["type"] == "VlDeleter" and runtime is not None:
            try:
                row["proof"] = deleter_proof(model, directory, identity, runtime)
                row["disposition"] = "empty_by_construction"
            except ValueError as error:
                row["failure"] = str(error)
        elif capture is None:
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
                **({"runtime": runtime} if runtime is not None else {}),
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
        if row.get("disposition") == "empty_by_construction":
            validate_runtime(proof.get("runtime"))
            if member["type"] != "VlDeleter" or proof.get("rule") != DELETER_RULE or (
                    proof.get("identity") != identity or not proof.get("generated_sha256") or
                    proof["generated_sha256"] != plan[owner]["generated_sha256"] or
                    proof.get("queues") != {"m_newGarbage": 0, "m_deleteNow": 0} or
                    sorted(use.get("operation", "") for use in proof.get("uses", [])) !=
                    ["default_construct", "drain"]):
                raise ValueError("unproved deferred-deletion queue accounting: " + key)
            continue
        if row.get("disposition") != "settled_capture" or not capture or (
                proof.get("rule") != RULE or proof.get("identity") != identity or
                proof.get("capture") != capture or not proof.get("generated_sha256") or
                proof["generated_sha256"] != plan[owner]["generated_sha256"]):
            raise ValueError("unproved settled-boundary scheduler accounting: " + key)
        validate_runtime(proof.get("runtime"))
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
