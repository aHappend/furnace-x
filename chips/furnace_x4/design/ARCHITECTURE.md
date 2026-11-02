# FURNACE-X4 implementation architecture

## Integration boundary

The application processor is the literal HAMMER-V4 hierarchy, not the embedded
task processor. `application_processor.g_legal.u_v3` retains core, MMU, fetch/data
paths, router, cache arbiters, I/D caches, fabric, AXI master, CLINT, PLIC, UART and
legacy accelerator. `heterogeneous_fabric` retains the full X3 hierarchy and
independent RV64IM task processor. Neither CPU memory nor MMIO is tied off.

Application MMIO flows through the full-width router, its original AXI-Lite
master, the X4 lane bridge and X3 MMIO arbiter. The X3 address base is removed
only in that bridge. Fabric IRQ occupies PLIC source2, with UART source1.

Application memory flows from I/D caches and PTW through the existing arbiter,
backing fabric and 64-bit AXI master, then the X4 64-to-512 bridge. X3 DMA/engine
AXI joins separately at coherent memory. The public DDR bus has 512-bit data,
64 strobes and five-bit IDs; the high ID bit identifies the application client.
Both clients refer to the same physical bytes, without host staging.

`boot_control` emits the only external application start. A top-level
`boot_launch_seen` interlock holds a buffered early fabric coherence request
until that launch has been presented to HAMMER. This prevents an exclusion from
consuming the one-shot boot pulse before the application has ever started.
Subsequent resumes remain exclusively internal to HAMMER's coherence controller.

## Ownership and buffering

MMIO and CPU lane bridges each retain independent AW/W and read ownership.
No downstream response has a combinational upstream bypass. Errors and selected
lanes are captured along with the transaction, so backpressure cannot change
address, mask, association or response shape.

Fabric transfers are store-and-forward across exclusion. A full write burst
uses 256*64=16384 data bytes plus 2048 strobe bytes. A full read response uses
16384 data bytes plus per-beat response state. Use synchronous independently
enabled byte-lane memories, not asynchronously indexed 512-bit register banks.
One fabric read header and one fabric write header can be resident independently.
Headers and response validity prevent overwrite. The write producer finishes
before halt; the read consumer starts only after release.

The endpoint dispatcher serializes transactions, not individual client beats.
Application transactions are single aligned 64-byte endpoint beats carrying
one selected 64-bit CPU lane. Fabric supports naturally aligned sizes 0..6,
INCR bursts of 1..256 beats, FIXED bursts of 1..16 beats and WRAP lengths
2/4/8/16. Exclusive LOCK requests are rejected; the supplied parent clients
drive LOCK low. INCR segmentation computes the remaining bytes to the next
4 KiB boundary using a shift by SIZE and a comparison with remaining beats.
WRAP bounds are checked over the entire wrap region. No address arithmetic
uses division or modulo. Complete write-buffer validation checks every beat's
LAST and legal byte-strobe lanes before requesting exclusion.

Whole-cache exclusion is conservative hardware coherence, not an AXI cache
sideband claim. The running application drains using its real halt-clean,
then D/I command3 invalidate actual caches. CPU memory remains serviced during
drain. A successful grant invalidates reservations even for an already-halted
core. Fabric ownership spans all split endpoint bursts and final response capture,
not upstream response-consumer stalls. Reuse the parent committed-next restart
path and require actual architectural progress before another exclusion.

## Failure classes

Initial halt-clean error is not successful halt. Its dedicated core diagnostic
identifies the real failed response. The owned DRAIN fault settles immediately;
its architectural trap remains recorded while new core admissions are
quarantined. Accepted transactions retain their path owners and drain normally.
Command3 response errors use the same reset-only containment but a distinct
classification; ordinary endpoint errors after a successful grant do not.
Time and interrupt controllers keep running on all paths.

Fabric coherence errors are translated into buffered, shape-correct SLVERR
responses. No fabric endpoint request or release follows a failed grant.
Other already-buffered requests settle without being overwritten. Reset cancels
validity consistently at the endpoint and SoC before the real boot sequence.

## Implementation and evidence boundaries

`PARENT_SOURCES.sha256` is the immutable intake ledger. Working-parent changes
must be itemized here as they are made; all other copied modules retain source
identity. No unavailable parent specification or historical approval is used as
a passing implementation baseline.

Current working-parent modifications:

* `hammer_v3_data_router.sv`: full-64-bit X3 aperture decode, word-size restriction.
* `hammer_v3_top.sv`: preserve MMIO address bit2 and connect real cache maintenance
  coherence ownership plus reset-only admission quarantine. Clear the progress
  token throughout exclusion, fault containment and the pending restart, so
  drain retirements cannot authorize another exclusion before resumed progress.
* `hammer_v4_top.sv`: forward scalar coherence interface without replacing ROM.
* `hammer_v3_core.sv`: expose only the real initial halt-clean response diagnostic.
* `furnace_x3_local_memory.sv`: replace each packed 64-bit byte-enabled memory
  with eight explicit 2048x8 synchronous byte lanes. Preserve all address/size/
  running restrictions, old-data read-during-write, E0 capture/E1 memory access
  and registered response, storage retention and reset validity semantics.

The declared 100 MHz target is not a measurement. Parent timing/PPA is N/A.
Numerical pipeline/memory audit, full-top static elaboration, independent
functional/numerical/mutation/synthesis results and shared-runtime physical
results must be recorded from actual subsequent work, never inferred from this
architecture description. The software-only build recorded below establishes
generated image identities, not a fitted board image or Linux boot.

## Current implementation checkpoint

The 81 parent modules have been copied to `rtl/`, with the five changes listed
above. New production modules are `furnace_x4_top`, `furnace_x4_boot_control`,
`furnace_x4_mmio_bridge`, `furnace_x4_cpu_axi512_bridge`,
`furnace_x4_coherent_memory`, `furnace_x4_axi_geometry` and
`furnace_x4_burst_store`. The unified top explicitly terminates all disabled
accelerator ingress and debug/retirement outputs on named internal wires.

One Designer static check ran:
`iverilog -g2012 -t null -s furnace_x4_top rtl/*.sv`, with shell-lexical source
expansion and a 60-second bound. It exited 0 with empty stdout/stderr. Its exact
expanded argv, source identities, Icarus version and execution times are in
`evidence/preparation/x4-static-elaboration-20261102T143216155355Z/receipt.json`.
That check precedes the byte-lane and progress-token changes above: its source
identity must not be used to certify the current files. No further Designer
RTL static check, functional simulation, synthesis, timing or hardware execution
has run. Software-build repair diagnostics were subsequently executed using
the existing source-bound helper; the failed attempts remain linked through
`repair_of` from
`evidence/preparation/software-build-20261102T152458032073Z-00b3bad4/receipt.json`.
That final attempt exited0 and produced the complete software image set.
It is a design handoff, not independent engineering acceptance.

## Source-derived compatibility audit

Direct comparison of each supplied parent with its working copy found exactly
the five modified files listed above. The other 76 parent files remain
byte-identical. Both reference trees remain unchanged. The source-derived
control, ring, key, stream, mailbox, semaphore, local-memory, descriptor/result
and error ABI is now tabulated in `SPEC.md` and named in
`sw/include/furnace_x4_regs.h`.
`WORKING_SOURCES.sha256` records this checkpoint's individual production RTL
and supplied software/FPGA source identities, including both upstream archives.
It is a provenance ledger, not a passing baseline or an acceptance dependency.

The HAMMER backing RAM/cache datapaths already use synchronous explicit 8-bit
lanes. X3 LZ4 history and AES quarantine are already byte-wide. The packed
512-bit copy-DMA buffer is only 1024 bytes and is written as whole beats, not a
>=2 KiB byte-enabled memory. The repaired 16 KiB task IMEM/DMEM are byte-lane
memories without asynchronous array resets. The new burst buffers likewise use
synchronous byte lanes with validity owned by the controller. These are source
inference choices, not measured M20K counts or proven Quartus inference.

Parent ring, fusion and mailbox legal branches use comparison-based pointer
wrap and explicit singleton-safe widths. Vision coordinate divisions are
constant elaboration loops; dynamic vision means use registered restoring
division. Audio spectral normalization is a fixed FFT-size shift. The parent
tensor has explicit multiplier/pair/quartet/vector/accumulator pipeline stages.
No numerical datapath or accepted enabled-stage latency was changed.
Legal/illegal boundary behavior and actual timing still require the admitted
independent tests and native gates.

Two concrete source-review findings are retained:

1. The prior X4 progress-token logic cleared on request acceptance but allowed
   a still-draining CPU retirement/trap to set it again. It was not subsequently
   cleared at release. The working top now holds the token zero throughout
   exclusion and pending restart, as well as fault containment. With coherence
   inactive this changes no parent host/accelerator behavior. No simulation
   failure or passing repair experiment is claimed.
2. The prior descriptor contract incorrectly reserved bit9 despite the
   unmodified parent `furnace_x2_top.sv:492-499` accepting it as weight commit.
   The independently admitted recovery names bit9
   `AUTHENTICATED_MULTIMODAL_WEIGHT_COMMIT`, legal only for mode0,
   vector_count=1 and weight_bytes=4. Lines579-590 retain successful retirement
   as the sole non-reset source of `mm_weights_valid`; key change invalidates
   it. The consumer in `furnace_x2_mm_control.sv:103` still requires validity.
   Software now accepts exactly this geometry, authenticates the flag in the
   unchanged 52-byte AAD and observes successful installation before streaming.
   Failed replacements preserve existing weights. No parent RTL, numerical
   rule, quarantine, allocation or completion behavior is changed.

## Software and FPGA checkpoint

The actual source archives under `sw/dist/` pin OpenSBI v0.2 commit
`a1ffba1ac9b0cde0e9005fa79b36e45216646b9d` and Linux v5.4 commit
`219d54332a09e8d8741c1e1982f5eae56099de85`; their hashes/licenses are in
`sw/sources.json`. Public tag resolution and archive download were performed;
no tool was installed. Source reads of the pinned upstream APIs informed the
platform overlay rather than assuming a current OpenSBI API.

`sw/opensbi/platform/furnace_x4/` supplies the real v0.2 platform, with the
retained UART/CLINT/PLIC map, one hart, no unsupported PMP feature and exact
kernel/DTB jump addresses. `sw/linux/furnace_x4.config` requests an S-mode
Sv39 RV64IMA/lp64 kernel without C/F/D. `sw/build_boot.py` hashes/extracts those
actual archives, builds the two components and checks resolved configuration,
ELF/instruction attributes and actual image/runtime bounds. The first independent
build failed before those audits: upstream v0.2 unconditionally included its
FP-only header from hart initialization and misaligned-access handling.
`sw/opensbi/rv64ima-v0.2.patch` guards the includes and FP-only decoder/register
paths with `__riscv_flen`, preserving integer misaligned emulation and rejecting
unsupported FP encodings through the existing `SBI_EILL` path before data-memory
access or PC advancement. The pinned archive, firmware version and RV64IMA/lp64
flags are unchanged. The builder applies this patch only to fresh extracted
sources and records patch/tool identity and before/after source hashes.
An additional v0.2 patch gives the naturally aligned, all-word scratch structure
its real alignment while asserting the assembly layout, resolving GCC13's
packed-member error without suppressing warnings. The software-owned ISA audit
recognizes M's Zmmul subset and distinguishes objdump headers, ELF-mapped data
and illegal-zero alignment padding from instructions. Nonzero compressed and
floating instructions remain rejected. The successful build audited7131
firmware,584244 kernel,70 task and1704 userland instructions; it separately
counted two zero-padding halfwords in the kernel.
See `sw/README.md` for the retained failure, reproduction and remaining
independent functional coverage.

`sw/dts/furnace_x4.dts` declares the two required compatible strings, actual
100 MHz timebase, RAM, reserved DMA pool, PLIC M/S contexts, source1 UART and
source2 fabric. `sw/package_images.py` accepts real built components/initramfs,
checks hashes/sizes/overlap and produces actual-reservation DTS/DTB plus a
hashed image-loading manifest. The successful software-only build produced
the DTB and initramfs under its fresh `system/images/` directory.
The DTS does not yet advertise `dma-coherent`.

`sw/taskgraph/task.S` and its linker/Makefile implement a real local-IMEM
RV64IM copy/dependency graph program using all four mailboxes, real copy DMA,
hardware semaphore0 completion and software posts of semaphore2..15. It checks
reservation bounds/alignment/length/overlap and reports actual DMA errors.
It has been assembled and ISA-audited, but not loaded or executed. Its FIFO command and ownership
contract is documented in `sw/README.md`.

`fpga/` supplies a 100 MHz core QSF/SDC and portable reset/image-loading
contract, not board-specific pin/electrical constraints or a fitted image.
The shared-runtime bridge/native gates still own physical integration, actual
external timing and all hardware execution.

## Continued software implementation

`sw/linux/driver/` now contains the built-in platform driver and Kconfig/Kbuild
overlay; `sw/include/furnace_x4_uapi.h` defines its controlled ioctl ABI.
The driver checks the exact resource/pool and real parent IDs/depths, uses
Linux DMA allocation/mapping/ordering APIs, and accepts only allocations inside
the reserved pool. Its private control page holds immutable submitted ring
descriptors and multimodal DMA records. Only the separate 8 MiB owned buffer
can be user-mapped; its PTE permissions remain enforced and execute permission
is prohibited. No arbitrary physical mapping, user-programmable task code or
raw register-write API is exposed.

The driver submits tensor descriptors, mailbox copy task graphs and
firmware-mode streams, waits on actual IRQs and checks completion association.
It services leaf sources before aggregator ACK and leaves PLIC claim/complete
to the kernel's real interrupt-controller driver. Completed hardware errors
are reported explicitly; unsettled/fatal failures retain storage and disable
resubmission until reset. Task trap cause/PC/status are logged. The fixed SoC
driver is built-in with no runtime bind/unbind interface, not a hot-removable
device driver. These are source behavior descriptions, not observed results.

`sw/build_boot.py` now assembles/audits the trusted task and generates a header
containing only its actual binary words; it installs that header, driver and
public ABI into the extracted pinned Linux source and requires the resolved
driver configuration. The source archives themselves remain unchanged.

`sw/user/` supplies freestanding RV64IMA/lp64 startup, syscall/memory runtime,
standard AES/GCM/GHASH and XXH32 encoding, real authenticated LZ4/W4 tensor and
task-graph copy inputs and complete byte/record/guard comparisons. Its stream
inputs use varying constant images and zero audio with independent mathematical
invariants. These narrow production workload choices do not replace the
Verifier's broader numerical/parameter/defect coverage. The application
compares a NIST AES/GCM known answer, clones a child for a real U-mode
write-permission fault, checks both sides of a mapped page boundary and uses a
timer-backed syscall. All observations still require independent execution.

`sw/build_userland.py` builds and audits the actual static `/init`, then emits
deterministic newc initramfs records, including the console device.
`sw/package_images.py` now checks the archive's records and executable RISC-V
`/init`, not just its magic. `sw/build_system.py` wires the three builders in
a fresh tree and records their actual output identities. None has run; there
is still no built firmware, kernel, task binary, application, initramfs or DTB.

The admitted bit9 recovery is implemented in the register header, driver and
application. The first tensor job commits the four authenticated W4 bytes;
the flag is set before AAD construction, and actual IRQ/result/plaintext/
completion comparisons precede the remaining families. The driver additionally
requires real weights-valid status after a successful commit. The corrupt-tag
job requests replacement without bypassing authentication; subsequent streams
depend on the prior valid weights. STREAM still rejects absent weights with
`-EOPNOTSUPP`. Key changes require a fresh successful authenticated commit.
All other reserved bits remain rejected. No synthetic weight state or software
engine fallback has been added.

This design repair is ready for independent Verifier handoff, not engineering
acceptance. Software builds, actual Linux/U-mode
execution, independent functional/numerical/mutation/synthesis verification and
all native gates remain pending. Only direct source inspection and edits
were performed for this recovery: no new static check or preparation probe
ran, and no verification source, reference tree or runtime evidence was edited.
