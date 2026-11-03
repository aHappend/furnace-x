#!/usr/bin/env python3
"""Extract only the supported emitted native NBA scheduler, rejecting gaps."""

import re


def task_graph(analysis, directory, clean_cpp, Node, atom):
    workers = sorted(analysis.workers)
    if not workers:
        return None
    expected = re.fullmatch(r"(\w+___024root)____Vthread__nba__0", workers[0])
    if not expected or workers != [expected[1] + "____Vthread__nba__0",
                                   expected[1] + "____Vthread__nba__1"]:
        raise ValueError("unsupported native worker entry set")
    root = expected[1]
    regions, edges, signals, waits = {}, set(), {}, {}
    final = "final__nba"
    alias = re.compile(
        r"\s*V\w+__Syms\*\s+const\s+__restrict\s+vlSymsp\s+VL_ATTR_UNUSED\s*"
        r"=\s*vlSelf->vlSymsp\s*;\s*")

    def calls_only(node):
        if node.kind == "block":
            return all(calls_only(child) for child in node.children)
        if node.kind == "simple":
            match = re.fullmatch(r"\s*(\w+)\(vlSelf\);\s*", node.text)
            return bool(match and match[1] in analysis.functions and
                        "____Vthread__" not in match[1])
        return False

    for worker in workers:
        tree = analysis.functions[worker]["tree"]
        if tree is None:
            raise ValueError("unparsed native worker")
        previous, current, ended, pending = None, None, False, []
        final_signals = 0
        for node in tree.children:
            text = node.text.strip()
            if node.kind == "simple" and text == ";":
                continue
            if node.kind == "simple" and alias.fullmatch(text):
                if current is not None:
                    raise ValueError("symbol alias after native task start")
                continue
            if final_signals:
                raise ValueError("native worker accesses state after signaling its final join")
            start = re.fullmatch(r"Verilated::mtaskId\((\d+)\);", atom(text))
            stop = re.fullmatch(
                r"Verilated::endOfThreadMTask\(vlSymsp->__Vm_evalMsgQp\);", atom(text))
            signal = re.fullmatch(
                r"vlSelf->__Vm_mtaskstate_(\w+)\.signalUpstreamDone\(even_cycle\);", atom(text))
            wait = re.fullmatch(
                r"vlSelf->__Vm_mtaskstate_(\w+)\.waitUntilUpstreamDone\(even_cycle\);", atom(text))
            if node.kind == "simple" and start:
                if current is not None and not ended:
                    raise ValueError("native task missing completion")
                current = start[1]
                if current == "0" or current in regions:
                    raise ValueError("duplicate or reserved native task ID")
                if previous is not None:
                    edges.add((previous, current))
                if pending:
                    if pending != [current] or current in waits:
                        raise ValueError("native wait does not guard its own task")
                    waits[current] = worker
                    pending = []
                regions[current] = {"worker": worker, "children": []}
                previous, ended = current, False
            elif node.kind == "simple" and stop:
                if current is None or ended:
                    raise ValueError("native completion without an active task")
                ended = True
            elif node.kind == "simple" and signal:
                if current is None or not ended or pending:
                    raise ValueError("native signal not after a completed task")
                signals.setdefault(signal[1], []).append(current)
                if signal[1] == final:
                    final_signals += 1
            elif node.kind == "simple" and wait:
                if current is not None and not ended:
                    raise ValueError("native wait inside an unfinished task")
                pending.append(wait[1])
            elif node.kind == "if" and current is not None and not ended:
                condition = atom(node.text)
                if not re.fullmatch(
                        r"\((?:0x[0-9a-f]+|[0-9]+)ULL&vlSelf->__VnbaTriggered"
                        r"\.word\(0U\)\)", condition):
                    raise ValueError("unsupported native task trigger expression")
                if not calls_only(node.children[0]) or node.children[1].children:
                    raise ValueError("native task contains an unclassified operation")
                regions[current]["children"].append(node)
            else:
                raise ValueError("unaccounted native worker statement: " + text[:100])
        if current is None or not ended or pending or final_signals != 1 or (
                signals[final][-1] != current):
            raise ValueError("native worker does not signal its final completed task exactly once")

    constructor = directory / (root + "__Slow.cpp")
    counts = re.findall(r"__Vm_mtaskstate_(\w+)\((\d+)U\)", clean_cpp(constructor.read_text()))
    if len(dict(counts)) != len(counts):
        raise ValueError("duplicate native vertex initialization")
    counts = {name: int(value) for name, value in counts}
    if set(counts) != signals.keys() or set(waits) != signals.keys() - {final}:
        raise ValueError("native vertex/signal/wait inventories disagree")
    if any(len(producers) != counts[name] or len(set(producers)) != len(producers)
           for name, producers in signals.items()):
        raise ValueError("native vertex fan-in differs from its exact signal count")
    for name, producers in signals.items():
        if name != final and name not in regions:
            raise ValueError("native signal targets no scheduled task")
        edges.update((producer, name) for producer in producers)

    evaluator = root + "___eval_nba"
    tree = analysis.functions[evaluator]["tree"]
    if tree is None or any(node.kind != "simple" for node in tree.children):
        raise ValueError("unparsed native dispatch")
    body = "".join(node.text for node in tree.children
                   if node.text.strip() != ";" and not alias.fullmatch(node.text))
    parity = "vlSymsp->__Vm_even_cycle__nba"
    expected_body = (
        f"{parity}=!{parity};"
        f"vlSymsp->__Vm_threadPoolp->workerp(0)->addTask(&{workers[0]},vlSelf,{parity});"
        f"{workers[1]}(vlSelf,{parity});Verilated::mtaskId(0);"
        f"vlSelf->__Vm_mtaskstate_final__nba.waitUntilUpstreamDone({parity});")
    if atom(body) != expected_body:
        raise ValueError("native dispatch/parity/final join differs from the supported schedule")
    if set(analysis.spawned) != {workers[0]}:
        raise ValueError("unaccounted native asynchronous dispatch")

    predecessors = {name: set() for name in {*regions, final}}
    for before, after in edges:
        predecessors[after].add(before)
    order, remaining = [], dict(predecessors)
    while remaining:
        eligible = sorted(name for name, parents in remaining.items() if not parents & remaining.keys())
        if not eligible:
            raise ValueError("cyclic native task dependencies")
        for name in eligible:
            order.append(name)
            del remaining[name]
    ancestors = {}
    for name in order:
        ancestors[name] = predecessors[name] | set().union(*(
            ancestors[parent] for parent in predecessors[name]))
    if ancestors[final] != regions.keys():
        raise ValueError("native final join does not cover every task")
    return {
        "evaluator": evaluator, "workers": workers,
        "regions": {name: Node("block", "", 0, tuple(row["children"]))
                    for name, row in regions.items()},
        "order": [name for name in order if name != final], "ancestors": ancestors,
        "proof": {
            "rule": "emitted-task-order-and-exact-fan-in-with-parity-final-join-v1",
            "vertices": counts, "edges": sorted([list(edge) for edge in edges]),
            "tasks": len(regions), "final_join_covers_all_tasks": True,
            "limitations": "Scheduler library semantics and unserialized state require separate accounting.",
        },
    }
