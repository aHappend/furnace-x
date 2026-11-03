#!/usr/bin/env python3
"""Conservative generated-C++ entry-value analysis, not an RTL oracle.

The analysis follows actual calls and structured branches. Native worker entries
are independent: lexical order never establishes an inter-worker happens-before
edge. Unsupported syntax, aliases, recursion and path explosion fail closed.
"""

from dataclasses import dataclass
import math
import re


FUNCTION = re.compile(
    r"(?m)^(?:(?:VL_INLINE_OPT|VL_ATTR_COLD) )*(?:void|bool) (\w+)"
    r"\([^;{}]*\) \{")
REF = re.compile(r"\bvlSelf->(\w+)")
TOKEN = re.compile(r"\b[A-Za-z_]\w*\b")
CALL = re.compile(r"\b(\w+)\s*\(")
RULE = "structured-interprocedural-entry-value-deadness-v1"
CASTS = {"CData", "SData", "IData", "QData"}
SCALAR_PURE = CASTS | {"VL_EXTENDS_QI", "VL_MULS_QQQ", "VL_SHIFTRS_QQI", "VL_SHIFTL_III"}


def pure_calls(text):
    remaining = re.sub(
        r"\bvlSelf->__V(?:stl|ico|act|nba)Triggered\.(?:word|any)\([^()]*\)", "", text)
    return all(call[1] in SCALAR_PURE for call in CALL.finditer(remaining))


def balanced(text, start):
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack = [pairs[text[start]]]
    for pos in range(start + 1, len(text)):
        if text[pos] in pairs:
            stack.append(pairs[text[pos]])
        elif text[pos] in ")]}":
            if text[pos] != stack.pop():
                raise ValueError("mismatched generated delimiter")
            if not stack:
                return pos + 1
    raise ValueError("unclosed generated delimiter")


@dataclass(frozen=True)
class Node:
    kind: str
    text: str
    offset: int
    children: tuple = ()


class Statements:
    def __init__(self, text):
        self.text = text
        self.pos = 0

    def space(self):
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def keyword(self, word):
        return re.match(r"\b" + word + r"\b", self.text[self.pos:])

    def condition(self):
        self.space()
        if self.pos >= len(self.text) or self.text[self.pos] != "(":
            raise ValueError("missing generated control condition")
        end = balanced(self.text, self.pos)
        value = self.text[self.pos + 1:end - 1]
        self.pos = end
        return value

    def statement(self):
        self.space()
        start = self.pos
        if self.pos == len(self.text):
            raise ValueError("missing generated statement")
        if self.text[self.pos] == "{":
            self.pos += 1
            children = []
            self.space()
            while self.pos < len(self.text) and self.text[self.pos] != "}":
                children.append(self.statement())
                self.space()
            if self.pos == len(self.text):
                raise ValueError("unclosed generated statement block")
            self.pos += 1
            return Node("block", "", start, tuple(children))
        if self.keyword("if"):
            self.pos += 2
            condition = self.condition()
            yes = self.statement()
            self.space()
            no = Node("block", "", self.pos)
            if self.keyword("else"):
                self.pos += 4
                no = self.statement()
            return Node("if", condition, start, (yes, no))
        for word in ("while", "for"):
            if self.keyword(word):
                self.pos += len(word)
                condition = self.condition()
                return Node("loop", condition, start, (self.statement(),))
        if re.match(r"\b(?:switch|do|try|catch|goto|break|continue)\b", self.text[self.pos:]):
            raise ValueError("unsupported generated control transfer")
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char in "([":
                self.pos = balanced(self.text, self.pos)
            elif char == ";":
                self.pos += 1
                return Node("simple", self.text[start:self.pos], start)
            elif char in "{}":
                raise ValueError("unsupported generated statement")
            else:
                self.pos += 1
        raise ValueError("unterminated generated statement")

    def parse(self):
        rows = []
        self.space()
        while self.pos < len(self.text):
            rows.append(self.statement())
            self.space()
        return Node("block", "", 0, tuple(rows))


def blank(match):
    return "".join("\n" if c == "\n" else " " for c in match[0])


def operational_body(text):
    # Include debug branches conservatively rather than assuming a compiler flag.
    # No #else or arbitrary preprocessor rewriting is admitted.
    text = re.sub(r"(?m)^\s*#(?:ifdef VL_DEBUG|endif)\s*$", blank, text)
    if "#" in text:
        raise ValueError("unclassified generated preprocessing")
    text = re.sub(r"if\s*\(false\s*&&\s*vlSelf\)\s*\{\s*\}", blank, text)
    text = re.sub(
        r"\bV\w+\*\s+const\s+__restrict\s+vlSelf\s+VL_ATTR_UNUSED\s*=\s*"
        r"static_cast<V\w+\*>\(voidSelf\);", blank, text)
    # An elided diagnostic macro may not contain model references or addresses.
    for match in reversed(list(re.finditer(r"\bVL_DEBUG_IF\s*\(", text))):
        end = balanced(text, text.index("(", match.start()))
        if REF.search(text[match.start():end]) or re.search(
                r"\b(?:vlSelf|voidSelf)\b", text[match.start():end]):
            raise ValueError("model access in diagnostic macro")
        text = text[:match.start()] + blank(re.match(r"[\s\S]+", text[match.start():end])) + text[end:]
    return text


def writes(text):
    result = set()
    for match in REF.finditer(text):
        tail = text[match.end():]
        prefix = text[:match.start()].rstrip()
        if re.match(r"\s*(?:\[[^\]]*\]\s*)*(?:=(?!=)|[+\-*/%&|^]=|<<=|>>=|\+\+|--)", tail) or (
                prefix.endswith(("++", "--"))):
            result.add("member:" + match[1])
        elif re.match(r"\s*\.\s*\w+\s*\(", tail) and not (
                re.fullmatch(r"__V(?:stl|ico|act|nba)Triggered", match[1]) and
                re.match(r"\s*\.\s*(?:word|any)\s*\(", tail)):
            # Treat even a read-only method as potentially modifying its receiver.
            result.add("member:" + match[1])
    local = re.match(r"\s*(\w+)\s*(?:=(?!=)|[+\-*/&|^]=|\+\+|--)", text)
    if local:
        result.add("local:" + local[1])
    for match in re.finditer(r"\b(\w+)\s*(?:=(?!=)|[+\-*/%&|^]=|<<=|>>=|\+\+|--)", text):
        result.add("local:" + match[1])
    for match in re.finditer(r"(?:\+\+|--)\s*(\w+)\b", text):
        result.add("local:" + match[1])
    declaration = re.match(
        r"\s*(?:CData|SData|IData|QData|bool|int|size_t|unsigned(?:\s+int)?)\s+(\w+)\b", text)
    if declaration:
        result.add("local:" + declaration[1])
    return result


def dependencies(text):
    members = {"member:" + match[1] for match in REF.finditer(text)}
    remaining = REF.sub("", text)
    return members | {"local:" + match[0] for match in TOKEN.finditer(remaining)}


def atom(text):
    return re.sub(r"\s+", "", text)


def addressed(text, start):
    pos = start - 1
    while pos >= 0 and text[pos].isspace():
        pos -= 1
    if pos < 0 or text[pos] != "&":
        return False
    pos -= 1
    while pos >= 0 and text[pos].isspace():
        pos -= 1
    return pos < 0 or text[pos] in "=,(?:{;!~" or text[max(0, pos - 5):pos + 1] == "return"


@dataclass(frozen=True)
class State:
    defined: int = 0
    flag: int | None = None
    predicates: frozenset = frozenset()


class Lifetime:
    def __init__(self, directory, clean_cpp, closing):
        from boot_fixedpoint import audited_sources

        try:
            projected, self.evaluation_cache = audited_sources(directory)
            cache_error = None
        except ValueError as exc:
            projected, self.evaluation_cache, cache_error = {}, None, str(exc)
        self.functions = {}
        self.errors = [] if cache_error is None else [cache_error]
        self.outside = set()
        self.unclassified_fields = set()
        self.escaped_fields = set()
        self.escape = []
        for path in sorted(directory.glob("*.cpp")):
            text = clean_cpp(projected.get(path.name, path.read_text()))
            covered = []
            for match in re.finditer(r"void \w+::__V(?:serialize|deserialize)\([^;{}]*\) \{", text):
                covered.append((match.start(), closing(text, match.end() - 1) + 1))
            for match in FUNCTION.finditer(text):
                end = closing(text, match.end() - 1)
                covered.append((match.start(), end + 1))
                if "___ctor_var_reset" in match[1]:
                    continue
                if match[1] in self.functions:
                    self.errors.append("duplicate generated function: " + match[1])
                    continue
                body = text[match.end():end]
                try:
                    normalized = operational_body(body)
                    tree = Statements(normalized).parse()
                    error = None
                except ValueError as exc:
                    normalized, tree, error = body, None, str(exc)
                self.functions[match[1]] = {
                    "body": normalized, "tree": tree, "error": error, "file": path.name,
                    "line": text.count("\n", 0, match.end()) + 1,
                    "refs": {ref[1] for ref in REF.finditer(normalized)},
                }
                self.unclassified_fields.update(
                    token[0] for token in TOKEN.finditer(normalized)
                    if normalized[max(0, token.start() - 8):token.start()] != "vlSelf->")
                self.escaped_fields.update(
                    ref[1] for ref in REF.finditer(normalized)
                    if addressed(normalized, ref.start()))
            covered.sort()
            cursor = 0
            for start, end in covered:
                self.outside.update(match[0] for match in TOKEN.finditer(text[cursor:start]))
                cursor = max(cursor, end)
            self.outside.update(match[0] for match in TOKEN.finditer(text[cursor:]))
        self.calls = {
            name: {call[1] for call in CALL.finditer(row["body"]) if call[1] in self.functions}
            for name, row in self.functions.items()
        }
        # addTask's function pointer is not a normal call; it is an independent
        # entry, never an ordering edge from the parent's other worker.
        self.spawned = set()
        for name, row in self.functions.items():
            body = row["body"]
            symbol_alias = re.compile(
                r"\bV\w+__Syms\*\s+const\s+__restrict\s+vlSymsp\s+VL_ATTR_UNUSED\s*"
                r"=\s*vlSelf->vlSymsp\s*;")
            for occurrence in re.finditer(r"\bvlSelf->vlSymsp\b", body):
                if not any(match.start() <= occurrence.start() < match.end()
                           for match in symbol_alias.finditer(body)):
                    self.escape.append({"function": name, "reason": "unclassified symbol-table alias"})
            symbol_body = symbol_alias.sub(blank, body)
            if re.search(r"\bvlSymsp\b(?!->)", symbol_body):
                self.escape.append({"function": name, "reason": "unclassified symbol-pointer escape"})
            allowed = []
            for match in re.finditer(
                    r"vlSymsp->__Vm_threadPoolp->workerp\(0\)->addTask\(&(\w+),\s*"
                    r"vlSelf,\s*vlSymsp->__Vm_even_cycle__\w+\)", body):
                if match[1] not in self.functions or "____Vthread__" not in match[1]:
                    self.escape.append({"function": name, "reason": "unknown worker entry"})
                else:
                    self.spawned.add(match[1])
                    self.calls[name].add(match[1])
                    allowed.append((match.start(), match.end()))
            for match in re.finditer(r"\bvlSelf\b(?!->)", body):
                if any(start <= match.start() < end for start, end in allowed):
                    continue
                prefix = body[:match.start()]
                call = re.search(r"(\w+)\(\s*$", prefix)
                if call is None or call[1] not in self.functions:
                    self.escape.append({"function": name, "file": row["file"],
                                        "reason": "unclassified model-pointer escape"})
            if re.search(r"\bvoidSelf\b", body):
                self.escape.append({"function": name, "reason": "unclassified worker-pointer use"})
        called = set().union(*self.calls.values()) if self.calls else set()
        self.entries = (self.functions.keys() - called) | self.spawned
        self.workers = {name for name in self.functions if "____Vthread__" in name}
        self.entries |= self.workers
        self.transitive = {name: set(row["refs"]) for name, row in self.functions.items()}
        changed = True
        while changed:
            changed = False
            for name, callees in self.calls.items():
                before = len(self.transitive[name])
                for callee in callees:
                    self.transitive[name].update(self.transitive[callee])
                changed |= before != len(self.transitive[name])
        self.modifies = {}
        for name, row in self.functions.items():
            self.modifies[name] = self.tree_writes(row["tree"]) if row["tree"] else {
                "member:" + ref for ref in row["refs"]}
        changed = True
        while changed:
            changed = False
            for name, callees in self.calls.items():
                before = len(self.modifies[name])
                for callee in callees:
                    self.modifies[name].update(self.modifies[callee])
                changed |= before != len(self.modifies[name])
        self.node_cache = {}
        self.graph = None
        self.graph_error = None
        if self.workers:
            from boot_task_graph import task_graph
            try:
                self.graph = task_graph(self, directory, clean_cpp, Node, atom)
                self.entries -= self.workers
            except (OSError, KeyError, ValueError) as exc:
                self.graph_error = str(exc)

    def tree_writes(self, node):
        if node is None:
            return set()
        modified = writes(node.text)
        if not pure_calls(node.text):
            modified |= dependencies(node.text)
        return modified | set().union(*(self.tree_writes(child) for child in node.children))

    def info(self, node):
        if id(node) not in self.node_cache:
            refs = {ref[1] for ref in REF.finditer(node.text)}
            modified = writes(node.text)
            if not pure_calls(node.text):
                modified |= dependencies(node.text)
            for call in CALL.finditer(node.text):
                refs.update(self.transitive.get(call[1], ()))
                modified.update(self.modifies.get(call[1], ()))
            returned = bool(re.match(r"\s*return\b", node.text))
            for child in node.children:
                child_refs, child_modified, child_returned = self.info(child)
                refs.update(child_refs)
                modified.update(child_modified)
                returned |= child_returned
            self.node_cache[id(node)] = refs, modified, returned
        return self.node_cache[id(node)]

    def relevant(self, node, wanted):
        return bool(self.info(node)[0] & wanted)

    def prove(self, identity, spec=None):
        target = identity.split(".", 1)[1]
        shape = [] if spec is None else list(spec["shape"])
        if spec is not None and spec["words"] > 1:
            shape.append(spec["words"])
        units = math.prod(shape)
        guard = None
        if target.startswith(("__Vdlyvval__", "__Vdlyvdim")):
            # Selection is only a hypothesis. The complete caller/branch
            # analysis below must prove every guarded read on every entry.
            suffix = re.sub(r"^__Vdly(?:vval|vdim\d+)__", "", target)
            guard = "__Vdlyvset__" + suffix
            candidates = set()

            def guards(node):
                if node is None:
                    return
                match = re.fullmatch(r"\s*vlSelf->(__Vdlyvset__\w+)\s*", node.text)
                if node.kind == "if" and match and self.relevant(node.children[0], {target}):
                    candidates.add(match[1])
                for child in node.children:
                    guards(child)

            for row in self.functions.values():
                if target in row["refs"]:
                    guards(row["tree"])
            if len(candidates) == 1:
                guard = next(iter(candidates))
        wanted = {target} | ({guard} if guard else set())
        proof = {
            "rule": RULE, "identity": identity, "guard_hypothesis": guard,
            "entries": [], "reads_checked": 0, "definitions_checked": 0,
            "unclassified_pointer_escapes": self.escape, "proven": False,
            "boundary": "Each generated entry, including each native worker, starts independently.",
            "native_schedule_error": self.graph_error,
            "storage_shape": shape, "storage_units": units,
            **({"evaluation_cache": self.evaluation_cache} if self.evaluation_cache else {}),
        }
        failure = None
        if self.errors:
            failure = "; ".join(self.errors)
        if target in self.outside:
            failure = "field identity occurs outside parsed generated functions"
        if target in self.escaped_fields:
            failure = "generated field address escapes the bounded lifetime analysis"
        if target in self.unclassified_fields:
            failure = "field identity has an unclassified alias/local access"
        if self.escape:
            failure = "unclassified generated model-pointer escape"
        relevant_entries = sorted(name for name in self.entries if target in self.transitive[name])
        touching_workers = [name for name in self.workers if self.transitive[name] & wanted]
        if len(touching_workers) > 1 and self.graph is None:
            failure = "field/guard crosses native workers without a happens-before proof"
        if not relevant_entries:
            failure = failure or "no generated execution entry reaches this field"
        if failure is not None:
            proof["failure"] = failure
            return proof
        self.target, self.guard, self.wanted = target, guard, wanted
        self.storage_shape, self.storage_units = shape, units
        self.full_mask = (1 << units) - 1
        self.proof = proof
        self.stack = []
        self.atom_dependencies = {}
        self.concurrent_modifications = set().union(*(
            self.modifies[name] for name in self.workers if name not in touching_workers))
        if self.graph:
            proof["native_task_graph"] = self.graph["proof"]
            proof["boundary"] = (
                "Each external generated entry; native task definitions propagate only through "
                "proven happens-before edges, never an arbitrary topological linearization.")
        try:
            for name in relevant_entries:
                proof["entries"].append(name)
                self.function(name, {State()})
            if not proof["reads_checked"] or not proof["definitions_checked"]:
                raise ValueError("no complete definition/read lifetime was established")
            proof["proven"] = True
        except ValueError as exc:
            proof["failure"] = str(exc)
            proof["failure_stack"] = list(self.stack)
        return proof

    def invalidate(self, states, modified):
        invalid = {key for key, deps in self.atom_dependencies.items() if deps & modified}
        return {State(state.defined,
                      None if self.guard and "member:" + self.guard in modified else state.flag,
                      frozenset((key, value) for key, value in state.predicates if key not in invalid))
                for state in states}

    def bounded(self, states):
        # Once the whole old value is dead, future control-path distinctions
        # cannot resurrect it. Keeping those distinctions causes exponential
        # growth without providing additional lifetime information.
        if any(state.defined == self.full_mask for state in states):
            states = {state for state in states if state.defined != self.full_mask}
            states.add(State(self.full_mask))
        if len(states) > 256:
            raise ValueError("generated branch-state bound exceeded; lifetime unresolved")
        return states

    def function(self, name, states):
        if name in self.stack:
            raise ValueError("recursive generated call")
        row = self.functions[name]
        if row["tree"] is None:
            raise ValueError("unparsed generated function " + name + ": " + row["error"])
        self.stack.append(name)
        if self.graph and name == self.graph["evaluator"]:
            selected = [key for key in self.graph["order"]
                        if self.relevant(self.graph["regions"][key], self.wanted)]
            mutable = {"member:" + field for field in self.wanted}
            writers = {key for key in selected if self.info(
                self.graph["regions"][key])[1] & mutable}
            for index, key in enumerate(selected):
                if any(previous not in self.graph["ancestors"][key] and (
                        previous in writers or key in writers) for previous in selected[:index]):
                    raise ValueError("field/guard accesses have unordered native task lifetimes")
            other_writes = set().union(*(
                self.info(node)[1] for key, node in self.graph["regions"].items()
                if key not in selected))
            # Unordered read-only fanout cannot define the target/guard, but its
            # writes to other condition operands cannot establish correlations
            # for a different reader in an arbitrary topological linearization.
            other_writes |= set().union(*(
                self.info(self.graph["regions"][key])[1] for key in selected if key not in writers))
            old_concurrent = self.concurrent_modifications
            self.concurrent_modifications = other_writes
            states = self.invalidate(states, other_writes)
            for key in selected:
                self.proof.setdefault("ordered_native_regions", []).append(key)
                states, returned = self.visit(self.graph["regions"][key], states)
                if returned:
                    raise ValueError("unclassified native task early return")
            self.concurrent_modifications = old_concurrent
            self.stack.pop()
            return self.invalidate(states, self.modifies[name])
        continuing, returned = self.visit(row["tree"], states)
        self.stack.pop()
        return self.bounded(continuing | returned)

    def reads(self, text, states):
        for ref in REF.finditer(text):
            if ref[1] != self.target:
                continue
            suffix = re.match(r"\s*((?:\[\s*(?:0x[0-9a-fA-F]+|[0-9]+)U?\s*\]\s*)+)",
                              text[ref.end():])
            required = self.index_mask(suffix[1]) if suffix else self.full_mask
            if any(state.defined & required != required for state in states):
                raise ValueError("entry value can reach a read in " + self.stack[-1])
            self.proof["reads_checked"] += 1

    def index_mask(self, indices):
        if not indices:
            return self.full_mask
        constants = re.findall(r"\[\s*(0x[0-9a-fA-F]+|[0-9]+)U?\s*\]", indices)
        if len(constants) != len(self.storage_shape) or (
                re.sub(r"\[\s*(?:0x[0-9a-fA-F]+|[0-9]+)U?\s*\]", "", indices).strip()):
            raise ValueError("unproved dynamic/partial storage index")
        offset = 0
        for constant, extent in zip(constants, self.storage_shape):
            value = int(constant, 16 if constant.startswith("0x") else 10)
            if value >= extent:
                raise ValueError("storage index outside declared extent")
            offset = offset * extent + value
        return 1 << offset

    def expression(self, text, states):
        # A generated call carrying the model pointer is only supported as a
        # complete expression/statement. Unsequenced compound expressions do not
        # establish an order between a call's stores and its other operands.
        calls = [call[1] for call in CALL.finditer(text) if call[1] in self.functions]
        if calls:
            match = re.fullmatch(r"\s*(\w+)\(vlSelf(?:,\s*[^()]+)?\)\s*;?\s*", text)
            if len(calls) != 1 or match is None:
                raise ValueError("unsupported compound generated call expression")
            name = calls[0]
            if "____Vthread__" in name:
                # This entry is checked separately, with no imported definitions.
                return self.invalidate(states, self.modifies[name])
            if self.transitive[name] & self.wanted:
                return self.function(name, states)
            return self.invalidate(states, self.modifies[name])
        self.reads(text, states)
        states = self.invalidate(states, writes(text))
        if not pure_calls(text):
            states = self.invalidate(states, dependencies(text))
        return states

    def visit(self, node, states):
        if not states:
            return set(), set()
        if not self.relevant(node, self.wanted) and not self.info(node)[2]:
            return self.invalidate(states, self.info(node)[1]), set()
        if node.kind == "block":
            returned = set()
            for child in node.children:
                states, exits = self.visit(child, states)
                returned.update(exits)
            return self.bounded(states), self.bounded(returned)
        if node.kind == "if":
            states = self.expression(node.text, states)
            key = atom(node.text)
            self.atom_dependencies[key] = dependencies(node.text)
            stable = pure_calls(node.text) and not re.search(
                r"\+\+|--|(?<![=<>!])=(?!=)", node.text) and not (
                self.atom_dependencies[key] & self.concurrent_modifications)
            if not stable:
                # Such predicates may change asynchronously. Do not retain or
                # consult their truth across distinct condition evaluations.
                states = {State(state.defined, state.flag,
                                frozenset((old, value) for old, value in state.predicates
                                          if old != key)) for state in states}
            outputs, returned = set(), set()
            for truth, child in ((True, node.children[0]), (False, node.children[1])):
                branch = set()
                for state in states:
                    known = dict(state.predicates).get(key)
                    flag_test = re.fullmatch(r"\s*vlSelf->(\w+)\s*", node.text)
                    if flag_test and flag_test[1] == self.guard and state.flag is not None:
                        known = bool(state.flag)
                    if known is None or known == truth:
                        predicates = state.predicates
                        if stable:
                            predicates |= {(key, truth)}
                        branch.add(State(state.defined, state.flag, predicates))
                outgoing, exits = self.visit(child, branch)
                outputs.update(outgoing)
                returned.update(exits)
            return self.bounded(outputs), self.bounded(returned)
        if node.kind == "loop":
            # A zero-iteration and an arbitrary iteration are both possible.
            # No loop-carried definitions or branch correlations are assumed.
            incoming = {State(state.defined) for state in states}
            self.expression(node.text, incoming)
            _, returned = self.visit(node.children[0], incoming)
            modified = self.info(node)[1]
            return self.invalidate(states, modified), returned
        text = node.text
        if re.match(r"\s*return\b", text):
            expression = re.sub(r"^\s*return\b", "", text).strip().removesuffix(";").strip()
            if expression:
                states = self.expression(expression, states)
            return set(), states
        assignment = re.fullmatch(
            r"\s*vlSelf->(\w+)\s*((?:\[[^\]]+\]\s*)*)=(?!=)(.*);\s*", text, re.S)
        if assignment:
            field, indices, rhs = assignment[1], assignment[2], assignment[3]
            states = self.expression(indices, states)
            states = self.expression(rhs, states)
            states = self.invalidate(states, {"member:" + field})
            if field == self.target:
                # C++ casts are pure. Do not infer a definition from an unknown
                # helper that might access an escaped pointer or not return.
                if any(call[1] not in SCALAR_PURE
                       for call in CALL.finditer(rhs)):
                    helpers = sorted({call[1] for call in CALL.finditer(rhs) if call[1] not in SCALAR_PURE})
                    raise ValueError("unsupported helper in storage definition: " + ",".join(helpers))
                self.proof["definitions_checked"] += 1
                mask = self.index_mask(indices)
                states = {State(state.defined | mask, state.flag, state.predicates) for state in states}
            if field == self.guard:
                value = re.fullmatch(r"\s*([01])U?\s*", rhs)
                states = {State(state.defined, int(value[1]) if value else None,
                                state.predicates) for state in states}
            return states, set()
        states = self.expression(text, states)
        return self.invalidate(states, writes(text)), set()


def entry_proofs(directory, names, clean_cpp, closing, specs=None):
    analysis = Lifetime(directory, clean_cpp, closing)
    return {name: analysis.prove(name, None if specs is None else specs[name]) for name in names}
