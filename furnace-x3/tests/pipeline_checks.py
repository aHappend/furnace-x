"""Exact pre/post-edge pipeline depths, elastic stalls, CE stalls and reset flush."""

import argparse
import json
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cpu_reference import signed
from numerical_reference import fp32_add, fp32_multiply
from record import Experiment, ROOT


def pack(fields):
    value = 0
    for data, width in fields:
        if not 0 <= data < 1 << width:
            raise ValueError((data, width))
        value = value << width | data
    return value


class Elastic:
    def __init__(self, depth):
        self.depth = depth
        self.clear()

    def clear(self):
        self.enabled = False
        self.stages = [None] * self.depth
        self.history = [0, 0, 0]

    def ready(self, output_ready):
        return int(self.enabled and (self.stages[-1] is None or output_ready))

    def outputs(self, output_ready):
        return [(self.ready(output_ready), 1), (int(self.stages[-1] is not None), 1),
                (self.stages[-1] if self.stages[-1] is not None else 0, 64)]

    def advance(self, valid, output_ready, answer):
        if self.ready(output_ready):
            self.stages = [answer if valid else None] + self.stages[:-1]
        self.enabled = True


def trace(seed):
    rng = random.Random(seed)
    pipes = [Elastic(depth) for depth in (6, 4, 4)]
    fp = [[0]*depth for depth in (4, 5, 4)]
    pending = [None] * 3
    rows = []
    counts = {"accepted": [0]*3, "consumed": [0]*3, "stalled": [0]*3,
              "ce_disabled": 0, "resets": 0}
    specials = [0, 0x80000000, 1, 0x7fffff, 0x800000, 0x3f800000,
                0xbf800000, 0x7f7fffff, 0xff7fffff, 0x7f800000,
                0xff800000, 0x7fc00000, 0x7f800001, 0x33800000]
    for cycle in range(2400):
        reset = int(cycle not in (0, 1, 297, 298, 1199, 1200))
        ce = int(rng.randrange(4) != 0)
        a = specials[cycle % len(specials)] if cycle % 3 else rng.getrandbits(32)
        b = specials[(cycle // len(specials)) % len(specials)] if cycle % 3 else rng.getrandbits(32)
        ready = [int(rng.randrange(4) != 0) for _ in pipes]
        if cycle >= 2336:
            ready, ce = [1]*3, 1
        if not reset:
            for pipe in pipes:
                pipe.clear()
            fp = [[0]*len(stages) for stages in fp]
            pending = [None]*3
            counts["resets"] += 1
        for index in range(3):
            if pending[index] is None:
                valid = int(cycle < 2336 and rng.randrange(5) != 0)
                pending[index] = (valid, (rng.getrandbits(32), rng.randrange(256), rng.randrange(256))
                    if index == 0 else (rng.getrandbits(72),) if index == 1
                    else (rng.getrandbits(16), int(rng.randrange(9) == 0)))
        fields = [(reset, 1), (ce, 1), (a, 32), (b, 32)]
        for index, (valid, data) in enumerate(pending):
            fields += [(valid, 1), (ready[index], 1)]
            fields += list(zip(data, (32, 8, 8) if index == 0 else (72,) if index == 1 else (16, 1)))

        def snapshot():
            return pack([item for index, pipe in enumerate(pipes)
                         for item in pipe.outputs(ready[index])] +
                        [(stages[-1], 32) for stages in fp])

        before = snapshot()
        if reset:
            for index, (valid, data) in enumerate(pending):
                pipe = pipes[index]
                accepting = pipe.ready(ready[index])
                counts["stalled"][index] += int(valid and not accepting)
                counts["consumed"][index] += int(pipe.stages[-1] is not None and ready[index])
                answer = 0
                if valid and accepting:
                    counts["accepted"][index] += 1
                    if index == 0:
                        samples, xf, yf = data
                        p = [(samples >> (8*i)) & 255 for i in range(4)]
                        answer = ((p[0]*(256-xf)+p[1]*xf)*(256-yf) +
                                  (p[2]*(256-xf)+p[3]*xf)*yf+32768) >> 16
                    elif index == 1:
                        p = [(data[0] >> (8*i)) & 255 for i in range(9)]
                        lanes = (p[4], p[2]-p[0]+2*(p[5]-p[3])+p[8]-p[6],
                                 p[6]+2*p[7]+p[8]-p[0]-2*p[1]-p[2],
                                 p[1]+p[3]+p[5]+p[7]-4*p[4])
                        answer = sum((lane & 65535) << (16*i) for i, lane in enumerate(lanes))
                    else:
                        sample, first = data
                        history = [0, 0, 0] if first else pipe.history
                        answer = ((signed(sample, 16) + 3*history[0]+3*history[1]+history[2]) // 8) & 65535
                        pipe.history = [signed(sample, 16), *history[:2]]
                pipe.advance(valid, ready[index], answer)
                if not valid or accepting:
                    pending[index] = None
            if ce:
                values = (fp32_multiply(a, b), fp32_add(a, b), fp32_add(a, b))
                fp = [[value] + stages[:-1] for value, stages in zip(values, fp)]
            else:
                counts["ce_disabled"] += 1
        rows.append(f"{pack(fields):x} {before:x} {snapshot():x}\n")
    if any(value == 0 for key in ("accepted", "consumed", "stalled") for value in counts[key]):
        raise AssertionError("pipeline coverage absent")
    return "".join(rows), len(rows), counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--repair-of")
    args = parser.parse_args()
    experiment = Experiment("pipeline-edge-depths", args.repair_of)
    try:
        text, rows, counts = trace(args.seed)
        path = experiment.path / "pipeline.trace"
        path.write_text(text)
        binary = experiment.path / "pipeline.vvp"
        experiment.command(["iverilog", "-g2012", "-Wall", "-s", "pipeline_tb",
            "-o", str(binary.relative_to(ROOT)), "rtl/furnace_bilinear_pipe.sv",
            "rtl/furnace_spatial3x3_pipe.sv", "rtl/furnace_fir4_pipe.sv",
            "rtl/furnace_fp32_mul4.sv", "rtl/furnace_fp32_add5.sv",
            "rtl/furnace_fp32_round.sv", "tests/pipeline_tb.sv"], "compile")
        output = experiment.command(["vvp", str(binary.relative_to(ROOT)),
            f"+trace={path.relative_to(ROOT)}", f"+rows={rows}"], "simulate")
        if "PIPELINE_EDGE_PASS" not in output:
            raise AssertionError("edge comparisons absent")
        (experiment.path / "coverage.json").write_text(json.dumps(counts, indent=2) + "\n")
        print(output.strip())
    except Exception as error:
        experiment.finish(error)
        raise
    experiment.finish()


if __name__ == "__main__":
    main()
