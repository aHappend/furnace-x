"""Strict public-pin oracle: numerical, conservation, cycle, reset and coverage.

Every expected row is checked against real simulator observations before its
events enter coverage. Active and post-NBA observations are separate; the
negedge observation must agree with the post-NBA observation. Unknowns on any
public output are errors, even when its valid is deasserted.
Stalled-edge stability includes CRC fields on protocol-error results, whose
numerical values are otherwise unspecified.
"""

import json
from collections import Counter, defaultdict, deque

from scenarios import DIRECTED_LENGTHS


class FunctionalMismatch(AssertionError):
    pass


def require(condition, message):
    if not condition:
        raise FunctionalMismatch(message)


def parse_observation(line, cycle, phase):
    fields = line.split()
    require(len(fields) == 22, f"trace shape cycle={cycle} phase={phase}: {line!r}")
    require(fields[0] == phase and int(fields[1]) == cycle,
            f"trace order expected={phase}/{cycle} got={fields[:2]}")
    values = fields[2:]
    require(all(not any(x in value.lower() for x in "xz") for value in values),
            f"X/Z on public outputs cycle={cycle} phase={phase}: {values}")
    try:
        parsed = tuple(int(x, 16) for x in values)
        return parsed[:10], parsed[10:]
    except ValueError as error:
        raise FunctionalMismatch(f"non-hex public outputs {values}") from error


def compare(observed, expected, cycle, phase):
    ready, pv, data, keep, last, cv, c32, c64, mismatch, protocol = observed
    location = f"cycle={cycle} phase={phase}"
    if expected["reset"]:
        require(not any(observed), f"reset outputs nonzero {location}: {observed}")
        return
    payload, result = expected["payload"], expected["result"]
    require(ready == expected["ready"], f"ready mismatch {location}")
    require(pv == int(payload is not None), f"payload valid/latency mismatch {location}")
    require(cv == int(result is not None), f"result valid/cardinality/latency mismatch {location}")
    if payload is not None:
        require((data, keep, last) == (payload["data"], payload["keep"], payload["last"]),
                f"payload/keep/last/order mismatch {location} packet={payload['packet']}")
    if result is not None:
        require(protocol == result["protocol"],
                f"protocol status mismatch {location} packet={result['id']}")
        require(mismatch == result["mismatch"],
                f"check association/mismatch failure {location} packet={result['id']} "
                f"expected={result['mismatch']} actual={mismatch}")
        if not result["protocol"]:
            require((c32, c64) == (result["crc32"], result["crc64"]),
                    f"CRC functional mismatch {location} packet={result['id']} "
                    f"expected={result['crc32']:08x}/{result['crc64']:016x} "
                    f"actual={c32:08x}/{c64:016x}")


def check_stalled_outputs(before, after, payload_ready, result_ready, cycle):
    if before[1] and not payload_ready:
        require(after[1:5] == before[1:5],
                f"stalled payload changed across edge cycle={cycle}")
    if before[5] and not result_ready:
        require(after[5:10] == before[5:10],
                f"stalled result changed across edge cycle={cycle}")


def check_trace(directory, manifest, full):
    counts = Counter()
    completed = set()
    payload_beats = Counter()
    result_rows = []
    resets = Counter()
    previous = None
    consecutive = 0
    longest = 0
    expected_cycles = 0
    pending_payload = deque()
    pending_results = deque()
    with (directory / "trace.txt").open() as trace, \
            (directory / "expected.jsonl").open() as expectations:
        for phase in ("T0", "BP", "BN"):
            observed, pins = parse_observation(trace.readline(), -1, phase)
            require(not any(observed), f"startup reset {phase} outputs={observed}")
            require(not any(pins), f"startup reset stimulus {phase} inputs={pins}")
            counts["startup_reset_samples"] += 1
        for line in expectations:
            row = json.loads(line)
            cycle = row["cycle"]
            if row["pulse"]:
                asserted, asserted_pins = parse_observation(trace.readline(), cycle, "Q0")
                released, released_pins = parse_observation(trace.readline(), cycle, "Q1")
                require(not any(asserted), f"asynchronous reset outputs cycle={cycle}")
                require(asserted_pins == (0, *row["inputs"][1:]),
                        f"clock-free reset not asserted at public pins cycle={cycle}")
                require(released_pins == tuple(row["inputs"]),
                        f"clock-free reset not released at public pins cycle={cycle}")
                compare(released, row["pre"], cycle, "async-release")
                require(released[1] == released[5] == 0,
                        f"asynchronous reset failed to abort outputs cycle={cycle}")
                counts["asynchronous_reset_pulses"] += 1
            active, active_pins = parse_observation(trace.readline(), cycle, "A")
            post, post_pins = parse_observation(trace.readline(), cycle, "P")
            negative, negative_pins = parse_observation(trace.readline(), cycle, "N")
            require(active_pins == post_pins == negative_pins == tuple(row["inputs"]),
                    f"driven public input differs from stimulus cycle={cycle}")
            compare(active, row["pre"], cycle, "active")
            compare(post, row["post"], cycle, "post")
            compare(negative, row["post"], cycle, "negedge")
            require(post == negative, f"output changed between edges cycle={cycle}")
            if not row["pre"]["reset"]:
                check_stalled_outputs(active, post, row["mr"], row["cr"], cycle)
            if row["pre"]["reset"] or row["pulse"]:
                counts["aborted_payload_beats"] += len(pending_payload)
                counts["aborted_results"] += len(pending_results)
                pending_payload.clear()
                pending_results.clear()
            if previous and not row["pre"]["reset"] and not row["pulse"] \
                    and not previous["post"]["reset"]:
                old = previous["observed"]
                if previous["pins"][1] and not previous["active"][0]:
                    require(active_pins[1:8] == previous["pins"][1:8],
                            f"source changed while unaccepted cycle={cycle}")
                if old[1] and not previous["mr"]:
                    require(active[1:5] == old[1:5],
                            f"stalled payload changed cycle={cycle}")
                if old[5] and not previous["cr"]:
                    require(active[5:10] == old[5:10],
                            f"stalled result changed cycle={cycle}")
            if row["event"]:
                event = row["event"]
                if event == "async-stalled":
                    require(previous is not None and previous["observed"][1] == 1
                            and previous["observed"][5] == 1,
                            "clock-free stalled reset precondition not observed")
                if event.startswith("stalled-"):
                    require(previous is not None, f"missing reset precondition {event}")
                    old = previous["observed"]
                    if event in ("stalled-payload", "stalled-both"):
                        require(old[1] == 1 and previous["mr"] == 0,
                                f"unobserved payload stall before reset {event}")
                    if event in ("stalled-result", "stalled-both"):
                        require(old[5] == 1 and previous["cr"] == 0,
                                f"unobserved result stall before reset {event}")
                resets[event] += 1
            if not row["pre"]["reset"]:
                if active[1] and not row["mr"]:
                    counts["payload_stalls"] += 1
                if active[5] and not row["cr"]:
                    counts["result_stalls"] += 1
                    if active[9]:
                        counts["protocol_error_result_stalls"] += 1
                if active[1] and row["mr"] and active[5] and not row["cr"]:
                    require(post[1] == 0 and post[5] == 1,
                            f"payload independent retirement cycle={cycle}")
                    counts["payload_only_retirements"] += 1
                if active[5] and row["cr"] and active[1] and not row["mr"]:
                    require(post[5] == 0 and post[1] == 1,
                            f"result independent retirement cycle={cycle}")
                    counts["result_only_retirements"] += 1
                if not active_pins[1]:
                    counts["source_bubble_cycles"] += 1
                if active[1] and row["mr"]:
                    packet = row["pre"]["payload"]["packet"]
                    require(bool(pending_payload), f"unsolicited payload cycle={cycle}")
                    oldest = pending_payload.popleft()
                    require((active[2], active[3], active[4]) ==
                            (oldest["data"], oldest["keep"], oldest["last"]),
                            f"transaction queue payload order cycle={cycle}")
                    payload_beats[packet] += 1
                    counts["payload_transfers"] += 1
                if active[5] and row["cr"]:
                    record = row["pre"]["result"]
                    identifier = record["id"]
                    require(bool(pending_results), f"unsolicited result cycle={cycle}")
                    require(pending_results.popleft()["id"] == identifier,
                            f"transaction queue result order cycle={cycle}")
                    require(identifier not in completed, f"duplicate result packet={identifier}")
                    completed.add(identifier)
                    result_rows.append(record)
                    counts["result_transfers"] += 1
                    if record["group"] == "consecutive" and record["beats"] == 1:
                        consecutive += 1
                        longest = max(longest, consecutive)
                    else:
                        consecutive = 0
                else:
                    consecutive = 0
                if row["accepted"]:
                    require(active[0] == 1, f"unaccepted scheduled beat cycle={cycle}")
                    pending_payload.append(row["accepted"])
                    if row["accepted"]["result"] is not None:
                        pending_results.append(row["accepted"]["result"])
                        counts["accepted_packet_ends"] += 1
                    counts["input_transfers"] += 1
                    counts["max_outstanding_payload_beats"] = max(
                        counts["max_outstanding_payload_beats"], len(pending_payload))
                elif active[0] == 0:
                    counts["source_backpressure_cycles"] += 1
            previous = {"post": row["post"], "observed": post,
                        "mr": row["mr"], "cr": row["cr"],
                        "active": active, "pins": active_pins}
            expected_cycles += 1
        require(trace.readline() == "", "extra trace observations after bounded drain")
    require(expected_cycles == manifest["cycles"], "missing cycle observations")
    require(previous["observed"][1] == previous["observed"][5] == 0,
            "outputs not drained")
    require(not pending_payload and not pending_results, "outstanding work after drain")
    require(counts["input_transfers"] ==
            counts["payload_transfers"] + counts["aborted_payload_beats"],
            "input/payload/reset conservation")
    require(counts["accepted_packet_ends"] ==
            counts["result_transfers"] + counts["aborted_results"],
            "packet/result/reset conservation")
    legal = [r for r in result_rows if not r["protocol"] and r["group"] != "aborted"]
    malformed = [r for r in result_rows if r["protocol"]]
    for record in result_rows:
        if record["group"] != "aborted":
            require(payload_beats[record["id"]] == record["beats"],
                    f"payload conservation packet={record['id']}")
    expected_completed = {r["id"] for r in manifest["packets"] if r["group"] != "aborted"}
    aborted_ids = {r["id"] for r in manifest["packets"] if r["group"] == "aborted"}
    require(expected_completed <= completed and completed <= expected_completed | aborted_ids,
            f"result conservation missing={sorted(expected_completed - completed)} "
            f"extra={sorted(completed - expected_completed)}")
    pairs = defaultdict(dict)
    disabled_pairs = defaultdict(dict)
    for record in legal:
        if record["group"] == "flip":
            pairs[record["pair"]][record["side"]] = record
        elif record["group"] == "disabled-flip":
            disabled_pairs[record["pair"]][record["side"]] = record
    for pair, members in pairs.items():
        require(set(members) == {"base", "changed"}, f"incomplete flip pair {pair}")
        base, changed = members["base"], members["changed"]
        require(base["mismatch"] == 0 and changed["mismatch"] == 3,
                f"bit error not detected by both CRCs pair={pair}")
        require(base["crc32"] != changed["crc32"] and base["crc64"] != changed["crc64"],
                f"bit error CRC collision pair={pair}")
    for pair, members in disabled_pairs.items():
        require(set(members) == {"base", "changed"}, f"incomplete disabled pair {pair}")
        base, changed = members["base"], members["changed"]
        require((base["crc32"], base["crc64"]) == (changed["crc32"], changed["crc64"]),
                f"disabled lane affected reference pair={pair}")
    counts.update(legal_packets=len(legal), malformed_packets=len(malformed),
                  enabled_bit_flip_pairs=len(pairs), disabled_bit_flip_pairs=len(disabled_pairs),
                  zero_packets=sum(r["length"] == 0 for r in legal),
                  consecutive_single_beats=longest, cycles=expected_cycles,
                  public_output_samples=3 * expected_cycles + 3 +
                  2 * counts["asynchronous_reset_pulses"],
                  random_lengths=sum(r["group"] == "random-length" for r in legal))
    lengths = {r["length"] for r in legal}
    final_counts = {r["final_count"] for r in legal}
    require(counts["payload_stalls"] >= 32 and counts["result_stalls"] >= 32,
            f"insufficient observed independent stalls {counts}")
    require(longest >= 8 and counts["zero_packets"] >= 8 and len(malformed) >= 8,
            "missing directed consecutive/empty/malformed completion coverage")
    require(len(disabled_pairs) >= 16, "disabled-bit forwarding coverage")
    require(counts["payload_only_retirements"] and counts["result_only_retirements"],
            "independent output retirement not observed")
    require(counts["max_outstanding_payload_beats"] == 16,
            "full sixteen-beat public pipeline occupancy not observed")
    require(counts["source_bubble_cycles"] > 0, "source bubbles not observed")
    require(all(resets[x] for x in ("idle", "partial", "stalled-payload",
                                   "stalled-result", "stalled-both")),
            f"reset coverage incomplete {resets}")
    require(all(resets[f"occupancy-{i}"] for i in range(16)),
            f"latency occupancy reset coverage incomplete {resets}")
    require(all(resets[f"async-{condition}"] for condition in
                ("idle", "internal", "partial", "stalled")),
            "clock-free reset coverage incomplete")
    require(any(r["group"] == "known" for r in legal), "known-answer not completed")
    require(any(r["group"] == "recovery" for r in legal), "reset/malformed recovery missing")
    if full:
        b = manifest["width"] // 8
        require(len(legal) >= 512, f"legal packet threshold: {len(legal)} < 512")
        require(counts["random_lengths"] >= 100, "additional random length threshold")
        require(len(pairs) >= 128, "128 enabled single-bit flip pairs required")
        require(set(range(2 * b + 2)) <= lengths, "exhaustive boundary byte lengths missing")
        require(set(DIRECTED_LENGTHS) <= lengths, "long packet boundary lengths missing")
        require(set(range(b + 1)) <= final_counts, "final valid-byte count coverage missing")
        require({r["pattern"] for r in legal} >= {"zero", "ones", "walking", "random"},
                "data patterns missing")
        require({r["enable"] for r in legal} == {0, 1, 2, 3}, "enable mask coverage missing")
        for bit in (1, 2):
            require(any(r["enable"] & bit and not r["mismatch"] & bit for r in legal),
                    f"enabled correct checking missing bit={bit}")
            require(any(r["mismatch"] & bit for r in legal),
                    f"enabled incorrect checking missing bit={bit}")
        for length in (b, 2 * b):
            require({r["extra"] for r in legal
                     if r["length"] == length and r["group"] == "exact-multiple"} == {False, True},
                    f"both exact-multiple encodings missing length={length}")
    coverage = {"width": manifest["width"], "seed": manifest["seed"],
                "thresholds": {"legal_packets": 512 if full else 1,
                               "enabled_bit_flip_pairs": 128 if full else 8,
                               "payload_stalls": 32, "result_stalls": 32,
                               "consecutive_single_beats": 8, "zero_packets": 8,
                               "malformed_packets": 8},
                "measured": dict(counts), "lengths": sorted(lengths),
                "final_valid_bytes": sorted(final_counts), "resets": dict(resets),
                "completed_packet_ids": sorted(completed), "status": "passed"}
    (directory / "coverage.json").write_text(json.dumps(coverage, indent=2) + "\n")
    return coverage
