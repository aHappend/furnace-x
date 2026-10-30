"""Ten isolated behavioral RTL mutants with original-source controls.

Production RTL is read-only. Compilation failures, timeouts and wrong
diagnostics fail this check rather than counting as defect detection.
"""

import difflib
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cpu_checks import arithmetic_trace
from crypto_checks import traces as crypto_traces
from dma_checks import cases as dma_cases
from record import Experiment, ROOT


MUTANTS = (
    ("rv64w-sign-extension", "cpu", "furnace_rv64im_core.sv",
     "result={{32{word_result[31]}},word_result};", "result={32'b0,word_result};",
     "CPU_BUS_MISMATCH"),
    ("division-zero-corner", "cpu", "furnace_rv64im_core.sv",
     "m_zero_divisor ? 64'hffffffffffffffff", "m_zero_divisor ? 64'h0000000000000000",
     "CPU_BUS_MISMATCH"),
    ("semaphore-double-take", "sync", "furnace_hw_semaphores.sv",
     "next_tokens[index_q] = next_tokens[index_q] - 16'd1;",
     "next_tokens[index_q] = next_tokens[index_q];", "SYNC_RESPONSE unit=0 address=00"),
    ("mailbox-wrap", "sync", "furnace_mailbox_fifo.sv",
     "if (read_pointer == LAST_SLOT) read_pointer <= 0;",
     "if (read_pointer == LAST_SLOT) read_pointer <= LAST_SLOT;",
     "SYNC_RESPONSE unit=2"),
    ("irq-clear-dominates-set", "sync", "furnace_interrupt_aggregator.sv",
     "(pending_q & ~ack_bits) | sources", "(pending_q | sources) & ~ack_bits",
     "SYNC_RESPONSE unit=1 address=00"),
    ("dma-page-split", "dma", "furnace_dma512.sv",
     "if (destination_page_beats < planned_beats)", "if (1'b0)",
     "DMA_PAGE_SPLIT_OR_READ_PLAN"),
    ("dma-tail-strobe", "dma", "furnace_dma512.sv",
     "remaining[5:0] > b", "remaining[5:0] >= b",
     "DMA_TAIL_STROBE"),
    ("dma-premature-completion", "dma", "furnace_dma512.sv",
     "WRITE_RESPONSE: if (m_axi_bvalid && m_axi_bready)",
     "WRITE_RESPONSE: if (1'b1)", "DMA_PREMATURE_COMPLETION"),
    ("authentication-quarantine", "crypto", "furnace_aes128_gcm.sv",
     "FENCE: if (frame_seen)", "FENCE: if (frame_seen || length!=0)", "AUTH_QUARANTINE"),
    ("fusion-lane-order", "fusion", "furnace_fusion_buffer.sv",
     "output_data<={ah[63:0],vh[63:0]}", "output_data<={vh[63:0],ah[63:0]}",
     "FUSION_DATA_OR_ERROR_ORDER"),
)
SOURCES = {
    "cpu": ("furnace_rv64im_core.sv",),
    "sync": ("furnace_hw_semaphores.sv", "furnace_interrupt_aggregator.sv",
             "furnace_mailboxes.sv", "furnace_mailbox_fifo.sv"),
    "dma": ("furnace_dma512.sv",),
    "crypto": ("furnace_aes128_gcm.sv", "furnace_aes128_block.sv", "furnace_ghash_mul.sv"),
    "fusion": ("furnace_fusion_buffer.sv",),
}
TOPS = {"cpu": "cpu_bus_tb", "sync": "synchronization_tb",
        "dma": "dma_tb", "crypto": "crypto_tb", "fusion": "fusion_tb"}
PASS = {"cpu": "CPU_ARITHMETIC_PASS", "sync": "SYNC_PASS", "dma": "DMA_PASS",
        "crypto": "CRYPTO_PASS", "fusion": "FUSION_PASS"}


def fixtures(path):
    cpu_rows, _ = arithmetic_trace(17)
    cpu = path / "cpu.trace"
    cpu.write_text("".join(
        f"{w} {i} {s} {a:016x} {d:016x} {st:02x} {r:016x} {delay}\n"
        for w, i, s, a, d, st, r, delay in cpu_rows))
    crypto = path / "crypto.trace"
    crypto_text, crypto_rows = crypto_traces(17)
    crypto.write_text(crypto_text)
    dma = path / "dma.cases"
    dma_rows = dma_cases(4096)
    dma.write_text("".join(
        f"{src:08x} {dst:08x} {length} {code} {fault}\n"
        for src, dst, length, code, fault in dma_rows))
    return {
        "cpu": [f"+trace={cpu.relative_to(ROOT)}", "+seed=17"],
        "crypto": [f"+trace={crypto.relative_to(ROOT)}", f"+rows={crypto_rows}", "+seed=17"],
        "dma": [f"+cases={dma.relative_to(ROOT)}", f"+commands={len(dma_rows)}", "+seed=17"],
        "sync": ["+seed=17"], "fusion": ["+seed=17"],
    }


def compile_and_run(experiment, group, directory, source_directory, arguments,
                    diagnostic=None):
    obj = directory / "compile-obj"
    top = TOPS[group]
    experiment.command([
        "verilator", "--binary", "--timing", "-Wno-fatal",
        "--top-module", top, "--Mdir", str(obj.relative_to(ROOT)), "-o", "sim",
        *(str((source_directory / name).relative_to(ROOT)) for name in SOURCES[group]),
        f"tests/{top}.sv"], f"{directory.name}-compile")
    try:
        try:
            output = experiment.command([str((obj / "sim").relative_to(ROOT)), *arguments],
                                        f"{directory.name}-simulate")
        except RuntimeError:
            row = experiment.data["commands"][-1]
            output = (ROOT / row["stdout"]).read_text() + (ROOT / row["stderr"]).read_text()
            if diagnostic is None or row["timed_out"] or row["exit"] == 0:
                raise
            if diagnostic not in output:
                raise AssertionError(f"wrong mutant rejection for {directory.name}: {output}")
            return {"exit": row["exit"], "diagnostic": diagnostic, "command": row}
        if diagnostic is not None:
            raise AssertionError(f"undetected mutant {directory.name}")
        if PASS[group] not in output:
            raise AssertionError(f"missing original control comparisons {group}")
        return {"exit": 0, "pass": PASS[group], "command": experiment.data["commands"][-1]}
    finally:
        for pattern in ("*.o", "*.a", "*.gch"):
            for path in obj.glob(pattern):
                path.unlink()


def main():
    experiment = Experiment("behavioral-defect-sensitivity")
    try:
        experiment.command(["verilator", "--version"], "verilator-version", version=True)
        arguments = fixtures(experiment.path)
        controls = {}
        for group in SOURCES:
            identity = hashlib.sha256(b"".join(
                (ROOT / "rtl" / name).read_bytes() for name in SOURCES[group])).hexdigest()[:12]
            directory = experiment.path / f"control-{group}-{identity}"
            directory.mkdir()
            controls[group] = compile_and_run(experiment, group, directory, ROOT / "rtl",
                                             arguments[group])
        detections = []
        for name, group, filename, original, replacement, diagnostic in MUTANTS:
            text = (ROOT / "rtl" / filename).read_text()
            if text.count(original) != 1:
                raise AssertionError(f"mutation target must occur exactly once: {name}")
            changed = text.replace(original, replacement)
            source_hash = hashlib.sha256(changed.encode()).hexdigest()
            directory = experiment.path / f"{name}-{source_hash[:12]}"
            source_directory = directory / "rtl"
            source_directory.mkdir(parents=True)
            for source in (ROOT / "rtl").glob("*.sv"):
                shutil.copyfile(source, source_directory / source.name)
            (source_directory / filename).write_text(changed)
            (directory / "mutation.diff").write_text("".join(difflib.unified_diff(
                text.splitlines(True), changed.splitlines(True),
                fromfile=f"a/rtl/{filename}", tofile=f"b/rtl/{filename}")))
            result = compile_and_run(experiment, group, directory, source_directory,
                                     arguments[group], diagnostic)
            detections.append({"mutant": name, "group": group,
                               "original_source_sha256": hashlib.sha256(text.encode()).hexdigest(),
                               "mutated_source_sha256": source_hash,
                               "original_control": controls[group], "rejection": result})
            (experiment.path / "detections.json").write_text(
                json.dumps(detections, indent=2) + "\n")
        if len(detections) != 10:
            raise AssertionError("all ten required mutants must be behaviorally detected")
        print("DEFECT_SENSITIVITY_PASS originals=5 detected=10")
    except Exception as error:
        experiment.finish(error)
        raise
    experiment.finish()


if __name__ == "__main__":
    main()
