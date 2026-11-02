# FURNACE-X4 v4.0.0-soc-linux-unified

## Status and provenance

This is the design contract, not a verification result. The admitted work order
remains authoritative. The parent specifications and acceptance packages were
not supplied. `GENERATIONAL_HANDOFF.md` reports no measured Quartus timing or
resource result; its hardware result is bridge connectivity only.
`PARENT_SOURCES.sha256` records every immutable supplied RTL file. Working copies
live in `rtl/`; reference trees must not be modified. The source-list digests are
HAMMER `7719d524aa7f014f6836b14eb62686940926cdb521eea37ac3df94765b3b7706`
and FURNACE `a2d28dcb483d7cbfc808999d11c77cc4f92f3d68fa9d0263e385d913c0e767b2`.
These establish identity, not a passing baseline.

## Clock, reset, top and parameters

Top is `furnace_x4_top`, with one 100 MHz clock `clk`, asynchronous active-low
`rst_n` and two-flop synchronous reset release. There is one application hart.
Reset also resets the external DDR endpoint; pre-reset responses must not
reappear afterward. Valid, ready, LAST and stream-control outputs are zero during
reset; UART TX is one. Memories need not clear behind invalid state. No active
transaction may contain X/Z. New control state uses nonblocking assignments.

Public ports, all scalar unless a width is shown:

| Port | Direction | Width/meaning |
|---|---|---|
| clk, rst_n, uart_rx | input | 1 each |
| uart_tx, irq | output | 1 each; irq is fabric IRQ |
| v_valid, v_last | input | 1 each |
| v_pixel, v_id | input | 8, 16 |
| v_ready | output | 1 |
| a_valid, a_last | input | 1 each |
| a_sample, a_id | input | signed 16, unsigned 16 |
| a_ready | output | 1 |
| mm_ready | input | 1 |
| mm_valid, mm_id, mm_result, mm_error | output | 1, 16, 64, 8 |
| m_axi_* | master | AXI4(32,512,5), including REGION |

Expose only the parent fabric parameters:

| Parameter | Default | Legal values |
|---|---:|---|
| MAX_TILE_BYTES | 4096 | 1..65536 |
| RING_DEPTH | 8 | 1..16 |
| IN_WIDTH, IN_HEIGHT, OUT_WIDTH, OUT_HEIGHT | 8 each | 1..64 each |
| FFT_N | 16 | 8,16,32,64 |
| FUSION_DEPTH, MAILBOX_DEPTH | 4 each | 1..16 each |
| MAX_DMA_BYTES | 1048576 | 1..1048576 |

Illegal values must elaborate to an explicit `PARAMETER ERROR` diagnostic, not
malformed selects. Application parameters are fixed: IMEM_WORDS=16384,
DMEM_WORDS=8192, PRED_MODE=1, BTB_ENTRIES=16, ICACHE_LINES=DCACHE_LINES=64,
LEGACY_TRAPS=0, ITLB_ENTRIES=DTLB_ENTRIES=8, BOOT_ENABLE=1.

## Expanded adapter interfaces

Every adapter has scalar input `clk,rst_n`. The following tables define actual
signal suffixes, widths and directions, not an optional subset. S means slave;
M means master. Response directions reverse request directions.

| AXI4 suffix | CPU bridge S width | CPU bridge M / coherent S width | coherent M width | S direction |
|---|---:|---:|---:|---|
| awid, arid | 4 | 4 | 5 | input |
| awaddr, araddr | 64 | 32 | 32 | input |
| awlen, arlen | 8 | 8 | 8 | input |
| awsize, arsize | 3 | 3 | 3 | input |
| awburst, arburst | 2 | 2 | 2 | input |
| awlock, arlock | 1 | 1 | 1 | input |
| awcache, arcache | 4 | 4 | 4 | input |
| awprot, arprot | 3 | 3 | 3 | input |
| awqos, arqos | 4 | 4 | 4 | input |
| awregion, arregion | absent | 4 | 4 | input |
| awvalid, arvalid | 1 | 1 | 1 | input |
| awready, arready | 1 | 1 | 1 | output |
| wdata | 64 | 512 | 512 | input |
| wstrb | 8 | 64 | 64 | input |
| wlast, wvalid | 1 | 1 | 1 | input |
| wready | 1 | 1 | 1 | output |
| bid, rid | 4 | 4 | 5 | output |
| bresp, rresp | 2 | 2 | 2 | output |
| bvalid, rvalid, rlast | 1 | 1 | 1 | output |
| bready, rready | 1 | 1 | 1 | input |
| rdata | 64 | 512 | 512 | output |

`furnace_x4_cpu_axi512_bridge` prefixes are `s_axi_` and `m_axi_`.
`furnace_x4_coherent_memory` prefixes are `s_cpu_axi_`, `s_fabric_axi_`,
and `m_axi_`; each slave has the middle-column widths.
Master directions are the inverse of the table's S directions.
All sidebands, independent AW/W acceptance and response IDs are retained.

| AXI4-Lite suffix | MMIO S width | MMIO M width | S direction |
|---|---:|---:|---|
| awaddr, araddr | 32 | 16 | input |
| awprot, arprot | 3 | 3 | input |
| awvalid, arvalid | 1 | 1 | input |
| awready, arready | 1 | 1 | output |
| wdata | 64 | 32 | input |
| wstrb | 8 | 4 | input |
| wvalid | 1 | 1 | input |
| wready | 1 | 1 | output |
| bresp, rresp | 2 | 2 | output |
| bvalid, rvalid | 1 | 1 | output |
| bready, rready | 1 | 1 | input |
| rdata | 64 | 32 | output |

`furnace_x4_mmio_bridge` uses `s_axil_` and `m_axil_`.

| Coherence suffix | coherent-memory direction | HAMMER direction | Width |
|---|---|---|---:|
| coh_req_valid | output | input | 1 |
| coh_req_ready | input | output | 1 |
| coh_rsp_valid | input | output | 1 |
| coh_rsp_ready | output | input | 1 |
| coh_rsp_error | input | output | 1 |
| coh_release_valid | output | input | 1 |
| coh_release_ready | input | output | 1 |

These are scalar ports on both working HAMMER tops. The working core adds only
output `halt_clean_error`, equal to `rst_n && halt_clean_fault && d_rsp_ready`.
It is a response-handshake diagnostic, not a generic trap decoder.

`furnace_x4_boot_control` has scalar inputs `clk,rst_n,app_boot_ready,
app_boot_error,app_halted` and outputs `app_start,startup_error`. It samples
ready, no error and halted, pulses start for the next cycle exactly once, and
never restarts after a runtime halt/trap. A boot error latches startup_error
and prevents launching until reset. It does not replace the parent ROM/loader.

## Address and software contract

All comparisons precede narrowing; full transaction extent is checked with
overflow width. Unmapped or absent RAM returns DECERR, malformed supported-bus
operations return SLVERR. Neither high aliases nor range overflow may cause
side effects. SLVERR/DECERR reach architectural access faults.

| Physical byte range | Function |
|---|---|
| 0x00000000..0x0000ffff | local application IMEM, parent restrictions |
| 0x02000000..0x0200ffff | CLINT, parent register decode |
| 0x0c000000..0x0fffffff | PLIC, parent register decode |
| 0x10000000..0x1000ffff | local application DMEM |
| 0x10010000..0x100100ff | 16550A UART, source 1 |
| 0x20000000..0x2000ffff | complete X3 MMIO, source 2 |
| 0x80000000..0x87ffffff | shared 128 MiB DDR RAM |

The legacy HAMMER external window at 0x40000000..0x4000ffff remains routed
externally; the X4 bridge rejects it. CLINT increments mtime each clock;
DT timebase-frequency is 100000000. PLIC M/S contexts are 0/1 and claim/complete
ownership plus level re-pending are unchanged.

Boot load slots: OpenSBI v0.2 at 0x80000000..<0x80200000; Linux v5.4 Image at
0x80200000..<0x84000000; initramfs at 0x84000000..<0x86000000; DMA reservation
0x86000000..0x86ffffff; DTB at 0x87e00000..<0x88000000. Validate actual file
lengths/non-overlap; never truncate. Reserve firmware and occupied boot regions.
Load real images into the endpoint before reset release. The accepted 32-word
ROM loader receives a real response for each word, sets a0=0, a1=0x87e00000 and
jumps from reset PC 0 to 0x80000000.

Firmware, kernel, libraries and user applications must use RV64IMA/lp64 without
C/F/D instructions. DTS declares `hammer,v4-cpu`, rv64ima, sv39, RAM,
reservations, CLINT, PLIC M/S contexts, UART IRQ 1 and
`furnace,x4-hetero-fabric` at 0x20000000/0x10000 IRQ 2. DMA coherence requires
implemented and independently verified cache maintenance. The kernel driver
uses actual MMIO/DMA/mapping/ordering/IRQ APIs and maps only controlled DMA
allocations through real Sv39 PTEs; arbitrary physical mappings are forbidden.
The task-graph processor remains a separate RV64IM co-processor.

### Source-derived X3 register and error ABI

The following offsets are relative to 0x20000000 for the application processor
and to zero for the task processor. Every register operation is one aligned
32-bit access, with little-endian byte strobes. RW writes merge enabled bytes;
W1C and command operations use only enabled bytes. RO writes, WO reads and
reserved addresses fault unless an exception is stated below. X3 returns
SLVERR for its errors; the external bridge returns DECERR for addresses outside
the aperture. Neither an MMIO error nor a DMA error is a successful completion.

These tables describe the actual working-parent decodes in `furnace_x2_csr`,
`furnace_x3_control`, `furnace_hw_semaphores`, `furnace_mailboxes` and
`furnace_interrupt_aggregator`. They do not extend the admitted flag contract.

| Offset | Access | Meaning and restrictions |
|---|---|---|
| 0x0000 | RO | Tensor subsystem ID 0x01000000 (retained parent ID) |
| 0x0004 | RW | Tensor ring enable bit0; other bits zero |
| 0x0008 | RO | bit0 busy, bit1 key committed, bit2 ring full, bit3 sticky tensor fault |
| 0x000c | R/W1C | bit0 requested successful tensor completion, bit1 failed tensor completion; set wins clear |
| 0x0010 | RW | Tensor IRQ enable bits1:0, reset zero |
| 0x0014 | RO | Last tensor error code in bits7:0 |
| 0x0018 | RW | Ring base, 128-byte alignment; locked while busy, queued or multimodal busy |
| 0x001c | RO | RING_DEPTH |
| 0x0020 | RO | Monotonic wrapping 32-bit consumer head |
| 0x0024 | RW | Producer tail; unsigned advance must be nonnegative and fit currently free slots |
| 0x0028, 0x002c | RO | Last tensor tile ID, tensor completion count |
| 0x0030..0x003c | W/read-zero | Four key-shadow words in increasing byte order; writing any enabled byte marks that byte initialized; locked |
| 0x0040 | W/read-zero | bit0 commit all 16 initialized shadow bytes, bit1 zeroize shadow/committed key and initialization mask; both set is illegal; locked |
| 0x1000 | RO | Multimodal subsystem ID 0x02000000 |
| 0x1004 | RW/command | bit0 multimodal enable; write bit1 clears multimodal fault; bits31:2 zero; locked; enable requires legal buffers |
| 0x1008 | RO | bit0 authenticated weights valid, bit1 multimodal fault, bit2 vision busy, bit3 audio busy, bit4 fusion/controller busy |
| 0x1010, 0x1014, 0x1018 | RW | Vision, audio and result ring bases; 16-byte aligned, pairwise nonoverlapping allocations of 16*FUSION_DEPTH bytes; locked |
| 0x101c | RO | FUSION_DEPTH |
| 0x1020, 0x1024, 0x1028 | RO | Multimodal completion count, last error, last ID |
| 0x1030 | RW | Five QoS nibbles: tensor, vision, audio, fusion, descriptor; reset 0xf4c8f; bits31:20 zero; locked |
| 0x2000 | RO | Task subsystem ID 0x03000000 |
| 0x2004 | RW/command | bit0 task run (requires firmware mode), bit1 task reset pulse (requires actually halted); other bits zero; reset does not clear unrelated fabric state |
| 0x2008 | RO | bit0 not halted, bit1 halted |
| 0x200c | RO | Last task trap interrupt flag at bit31 and cause bits30:0 |
| 0x2010, 0x2014 | RO | Last task trap PC low/high words |
| 0x2018 | R/W1C | bit0 protocol error, bit1 semaphore overflow, bit2 DMA error, bit3 task bus error; sets win clears |
| 0x2020 | RW | Firmware mode bit0; reset-only return to zero; transition to one requires halted task CPU, no legacy packet/stream activity, empty tensor ring and idle multimodal engines |
| 0x2040, 0x2044, 0x2048 | RW | Copy DMA source, destination and byte count; writes prohibited while DMA busy |
| 0x204c | WO | Write bit0=1 to start copy DMA when ready/not busy; zero is a no-op; other bits zero |
| 0x2050 | RO | bit0 DMA busy, bit1 sticky done, bits15:8 last DMA error |
| 0x2054 | WO | Either bit0 or bit1 clears both sticky DMA done and error; other bits zero; new completion wins clear |
| 0x2100 | RO | Interrupt aggregator pending bits15:0 |
| 0x2104 | RW | Interrupt mask bits15:0, reset zero; bits31:16 zero |
| 0x2108 | WO/W1C | Acknowledge pending bits15:0; current source level/event wins acknowledgement |
| 0x2200 | WO | Firmware vision pixel bits7:0, captured with current vision metadata; requires firmware mode |
| 0x2204 | WO | Firmware audio signed sample bits15:0, captured with current audio metadata; requires firmware mode |
| 0x2210, 0x2214 | RW | Vision/audio metadata: ID bits15:0, LAST bit16; bits31:17 zero |
| 0x2220 | RO | bit0 vision input slot full, bit1 audio input slot full |
| 0x2400+16*n | RO/consume | Semaphore n, n=0..15: atomic try-wait returns 1 and consumes a token, else returns 0 |
| 0x2404+16*n | WO | Semaphore n: strobed value must equal 1; zero strobes no-op; overflow faults without wrapping |
| 0x2408+16*n | RO | Semaphore n token count, bits15:0 |
| 0x2600+16*n | RW/queue | Mailbox n, n=0..3: write pushes strobed data (disabled bytes zero), read pops; full push or empty pop faults; zero-strobe write no-op |
| 0x2604+16*n | RO | Mailbox n: count bits4:0, empty bit8, full bit9 |
| 0x4000..0x7fff | RW | Task IMEM host window, 16 KiB, word accesses only; writes require halted task CPU |
| 0x8000..0xbfff | RW | Task DMEM host window, 16 KiB, word accesses only; writes require halted task CPU |

Firmware input writes wait for capacity rather than dropping a sample. A
zero-strobe input write queues nothing. Hardware posts semaphore0 for copy DMA
completion and semaphore1 for multimodal completion. Posts precede a concurrent
software operation; overflow set wins W1C. A full ring cannot accept a tail
advance using space that will only become free at the same edge: its free-space
test uses pre-edge head/tail. Non-power-of-two ring slots wrap by comparison,
independently of the 32-bit producer/consumer counter wrap.

IRQ source assignments are bit0 parent tensor/multimodal IRQ, bit1 copy DMA
completion, bit2 firmware-mode multimodal completion, bit3 X3 protocol error,
bits4..7 mailbox0..3 nonempty, bit8 semaphore overflow and bit9 task trap pulse.
Bits15:10 are tied zero in the integrated parent, not six additional external
top ports. All 16 positions remain real public inputs of the interrupt-aggregator
leaf for its independent coverage. Integrated coverage must distinguish this
from the ten connected source positions. The aggregator output drives the
public fabric IRQ and PLIC source2. To clear a level source, service/clear the
leaf before acknowledging the aggregator; Linux's PLIC driver then completes
the actual claimed source. Do not mask a permanently asserted error as success.

The task CPU sees its IMEM at 0x00010000..0x00013fff and DMEM at
0x00020000..0x00023fff. Its instruction fetches are aligned words from IMEM only;
data stores to its IMEM fault. Data requests use naturally aligned byte,
halfword, word or doubleword accesses, with unshifted request data/strobes.
Local memory captures address/data/size/CPU-running at E0, performs its
synchronous byte-lane read/write at E1 and publishes a registered response
after E1, with earliest retirement E2. Read-during-write observes the previous
word; write responses expose zero. Invalid requests touch neither memory.
Memory bits are not reset: software must load task instructions and initialize
read data before running. Storage reset, response validity and access policies
are unchanged by the X4 byte-lane inference repair.

| Tensor/stream completion error | Meaning |
|---|---|
| 0 | Success |
| 1 | Invalid descriptor, key state, address allocation or ring descriptor extent |
| 2 | LZ4 format/checksum/length or crypto input protocol/length error |
| 3 | LZ4 invalid match offset |
| 4 | GCM tag mismatch |
| 5 | DMA/AXI failure, including feature/result write failure |
| 6 | Tensor mode/packet protocol or incomplete tensor sequence |
| 7 | Vision/audio input ID/LAST/packet-length error |
| 8 | Fusion head-ID mismatch (takes priority over either input error) |

Copy DMA has a separate error namespace: 0 success, 1 invalid command and
2 endpoint ID/RESP/LAST/protocol failure. Copy addresses are 64-byte aligned,
in the parent DDR half of the 32-bit address space, with nonoverlapping extents
and no overflow. A zero-byte copy is a successful no-op only if the other
command predicates are legal. X4 additionally enforces installed RAM bounds at
the shared endpoint. Copy lengths need not be multiples of 64; last-beat strobes
preserve bytes beyond the requested length. Bursts are at most 16 beats and
split at both source and destination 4 KiB boundaries.

The descriptor, rounded-up-to-16 frame allocation, rounded-up-to-16 plaintext
allocation, vector_count*16 activation allocation, 16-byte result and 16-byte
completion allocations must all be 16-byte aligned, below 2^32 and mutually
nonoverlapping. The ring base itself has the stronger 128-byte alignment.
An invalid descriptor writes an error completion only when its completion
allocation is itself safe; otherwise the CSR error/count still records retirement.
The result record is LE64 result, LE32 tile ID, LE32 zero. The completion record
is status byte, three zero bytes, LE32 tile ID, LE32 authenticated byte count,
LE32 zero. Authentication failure produces no plaintext/result writes.
Multimodal feature/result records are LE64 value, LE32 zero, LE16 packet ID,
one zero byte and error byte. Slots advance modulo FUSION_DEPTH, not packet ID.
Feature writes complete before enqueueing their token; result writes complete
before reporting the multimodal result.

**Admitted authenticated multimodal initialization:** descriptor flag bit9 is
`AUTHENTICATED_MULTIMODAL_WEIGHT_COMMIT`, retaining the existing parent mechanism.
It is legal only with mode0, vector_count=1 and weight_bytes=4; all other flag
bits except mode[1:0] and IRQ bit8 remain zero. Bit9 must be included before
computing the unchanged 52-byte AAD. The four authenticated plaintext bytes
become multimodal W4 weights only at successful descriptor retirement, after
the normal frame/authentication, tensor and DMA completion path. An unsuccessful
replacement does not install candidate weights or invalidate previously
committed weights. Key change clears weights and validity; software must
successfully authenticate and retire a new commit before streaming again.
STREAM retains the real weights-valid prerequisite. No new register,
authentication bypass or software engine replacement is introduced.

Independent verification must cover successful installation and exact
multimodal numerics, illegal bit9 geometry and reserved-bit rejection,
authentication isolation, preservation after failed replacement, key-change
invalidation and authenticated reinitialization. A disposable disconnected-commit
mutation must fail its intended semantic comparison, not merely compilation or
timeout. These repair cases supplement, rather than replace, every mandatory
suite, three-seed Linux workload threshold, admitted cache-error case and native
timing/hardware gate.

### Source-defined Linux interface

The supplied software targets the default fabric geometry, one hart, Linux
v5.4 and RV64IMA/lp64. It is not a different legal-parameter contract for RTL.
`sw/include/furnace_x4_uapi.h` defines ABI version1. A built-in platform driver
owns one 8 MiB coherent allocation and a separate private control page, both
allocated through the DMA API from the exact declared 16 MiB reservation.
Reject allocation fallback outside that region. Only the user allocation may
be mapped, with bounded shared mappings and normal Sv39 read/write permissions;
executable mappings and later execute permission are prohibited. The private
ring, task instructions, MMIO and arbitrary physical addresses are never
user-mapped. One exclusive capability-checked file owns submissions and remains
owned until its last VMA is gone.

INFO reports geometry, the actual controlled DMA address and IRQ count.
KEY commits 16 bytes only while idle. TENSOR requires legal flags including
IRQ bit8 and permits bit9 only for mode0/vector_count1/weight_bytes4. It
validates all owned extents/alignment/nonoverlap at full arithmetic width,
and snapshots a private descriptor before publishing tail with DMA
ordering. Its supplied tag authenticates the exact source-defined 52-byte AAD;
userspace uses INFO's controlled address to construct it. COPY permits only
owned, nonoverlapping, 64-byte-aligned extents with lengths1..1048576 and an
eight-bit ticket; the trusted task program is the sole copy-engine submitter.
STREAM copies one default-size frame and audio packet into kernel ownership
before real firmware-mode MMIO submission, and returns actual private DMA
feature/result records, never a software-engine result. A successful bit9
completion must also expose real authenticated-weights-valid status; otherwise
the driver reports a fatal association failure and retains the allocations.

Every successful submission waits for its real IRQ-domain/PLIC completion.
The handler temporarily masks the fabric aggregator and wakes the owning
process; that process services the leaf before aggregator ACK. Linux's PLIC
driver retains claim/complete ownership. Completion count, tile/packet/ticket
and semaphore checks prevent an unrelated interrupt from being accepted as
completion. Negative errno denotes rejected API input or driver failure;
`hardware_error` reports the real completed hardware error namespace. Normal
completed errors permit recovery. Unsettled timeouts, fatal interrupts and
association failures poison submission and retain all DMA storage until system
reset. This software path cannot recover or execute through the specified
hardware quarantine; it adds no reset/retry bypass.

The freestanding `/init` generates authenticated LZ4/GCM/W4 tensor jobs and
copy task graphs, compares actual bytes/records/guards and checks actual
interrupt counts. Its default stream inputs use constant-image/zero-audio
invariants for bit-exact feature/fusion expectations. These deliberately
narrow application inputs do not satisfy the independent Verifier's broader
numerical, negative, boundary, mutation or transaction thresholds by
themselves. A real cloned U-mode child stores through a read-only DMA mapping;
the parent requires the actual SIGSEGV status, alongside readable mappings on
both sides of a page boundary. Kernel/PTW/privilege/timer observations remain
mandatory independent evidence.

The first of the application's sixteen tensor jobs sets the admitted bit9
before constructing AAD and authenticates the four W4 bytes. Its actual IRQ,
result, plaintext, completion and driver-observed weights-valid status must
succeed before later workloads. The corrupt-tag job also requests bit9,
exercising a failed replacement before STREAM uses the retained valid weights.
STREAM still returns `-EOPNOTSUPP` while authenticated-weights-valid is zero.
The program prints a three-family completion line only after all real families
compare successfully. Software builders, generated initramfs/DTB packaging and
image manifests do not certify execution. No software build or workload has
yet run.

## MMIO and CPU width adaptation

MMIO accepts independent AW/W slots and one independent AR slot. Only
four-byte-aligned addresses inside the X3 aperture are legal. Subtract the base
once; A[2] selects one half of the 64-bit CPU beat. Out-of-half write strobes
give SLVERR without issuing any target transaction. All selected partial or zero
strobes are retained. Reads place one target 32-bit word in the addressed half,
zeroing the other. Never split one instruction into two side-effecting accesses.
PROT and target responses are preserved. Unsupported sizes are rejected in the
full-width HAMMER router before any external request.

CPU memory accepts only eight-byte-aligned, LEN=0, SIZE=3, INCR, unlocked
transactions with WLAST=1. Check all 64 address bits and the last byte before
narrowing. Target address is A & ~63, LEN=0, SIZE=6, INCR, REGION=0. Lane A[5:3]
selects eight bytes/strobes without read-modify-write. Return exactly that read
lane. Preserve CACHE/PROT/QOS and four-bit IDs; bad return ID/LAST is an explicit
protocol error. One outstanding request per direction is sufficient.

## Shared memory, exclusion and fault containment

External ID[4]=1 means application; ID[4]=0 means fabric. Preserve low four bits.
Registered arbitration holds ownership through the final response and never
interleaves W owners. Legal 4 KiB crossings split into legal endpoint bursts
without changing upstream order or final LAST. Aggregate B errors.
Fabric writes have a complete 256-beat 512-bit data/strobe buffer; reads have a
complete 256-beat response buffer. Both use synchronous byte-lane RAM. Validate
complete writes before exclusion; capture complete reads before release.
No fabric producer/response-consumer stall may span exclusion; occupied headers
are backpressured and pending completions cannot be overwritten.

Normal transaction arbitration is round-robin within each client and between
eligible clients. A continuously eligible client loses at most one competing
normal completion, excluding endpoint stalls and atomic/coherence maintenance.
Processor drain writebacks are not fabric grants. Another exclusion requires
real resumed architectural progress, not an invented progress token.

Coherence uses the actual caches, core halt and maintenance arbiter slots:
IDLE -> DRAIN -> DREQ/DWAIT -> IREQ/IWAIT -> GRANT -> HELD -> RELEASE -> IDLE.
Request admission remembers whether the core was running, halts it, and excludes
new host/accelerator admissions. Continue CPU/MMIO/PTW/AMO traffic needed to
drain; wait for true core_halted and empty path obligations. The core first
cleans D-cache with command 2. Then command 3 cleans/invalidates D-cache through
u_d_arbiter and I-cache through u_i_arbiter, serialized against existing owners.
Grant is registered and only its successful handshake permits fabric DDR.
Keep CPU halted/caches invalid until release. Resume only a core deliberately
paused here, using committed_next and the existing registered start path.
Time/interrupt state and CSRs continue during exclusion.

On owned DRAIN `halt_clean_error`, immediately latch coherence_fault and
maintenance_fault, classify DRAIN_HALT_CLEAN_FAILURE and enter FAULT_RESPONSE.
This outranks normal drain completion and all maintenance/grant/release/resume.
Consume the actual failed clean response normally; preserve its architectural
trap and dirty line. Do not wait for core_halted: this failure leaves it running.
Registered coh_rsp_valid/error remain high until accepted, then FAULT_LOCKED
until reset. No request/release READY, successful grant, command-3 request,
retry clean, start/resume or handler execution is permitted.

Containment keeps halt asserted and quarantines new instruction/data/atomic
translation/SFENCE admissions at their existing boundaries with READY=0.
Already accepted paths and advertised downstream VALID/payload/response
ownership remain live through completion. Do not reset/gate the core, fake
halted, discard accepted work, disable caches or fabricate successful maintenance.
Ordinary halt-clean errors outside an owned DRAIN retain parent behavior.

DWAIT/IWAIT command-3 errors use the same registered FAULT_RESPONSE/FAULT_LOCKED
contract, classified MAINTENANCE_COMMAND3_FAILURE. DWAIT error forbids IREQ;
IWAIT error forbids GRANT. Successful external ownership invalidates the existing
eight-byte LR/SC reservation through host_data_write, including when already
halted. Retain parent alignment, address/width match, AMO.W/D signedness,
sign-extension and conservative store/trap/CSR/SFENCE invalidations.

Failed coherence admission returns real fabric SLVERR with no fabric DDR access
or release: one B for writes; exactly LEN+1 zero-data R beats with original ID,
SLVERR on every beat and LAST only on the last. Hold responses under stalls.
Latch requester fault; reject new fabric headers until reset. Retain and settle
other accepted transactions through error buffers without DDR. Continue CPU
obligations. Reset consistently cancels remaining validity at both ends.
Ordinary endpoint errors after successful maintenance propagate normally and
allow recovery without reset-only containment.

## Cycle & degenerate-boundary table

All handshakes sample pre-edge VALID && READY; the following states/counters
are post-edge. Payload remains stable throughout any stalled VALID.

| Event | Required behavior |
|---|---|
| Active reset | public ready/valid/LAST/control=0; TX=1; outstanding validity cleared |
| First release edge | reset synchronizer has not yet enabled internal transactions |
| E0 request capture | downstream registered VALID may appear after E0; earliest acceptance E1 |
| ER response capture | upstream response appears after ER; earliest retirement ER+1 |
| Independent MMIO AW/W | assemble after max(EA,EW); issue/hold AW and W independently |
| CPU bridge capture | coherent slave capture earliest E1; endpoint acceptance earliest E2 |
| DH actual drain complete | D command after DH, acceptance no earlier than DH+1 |
| DR D response | I command after DR, acceptance no earlier than DR+1 |
| IR I response | registered grant after IR, acceptance no earlier than IR+1 |
| Successful grant | fabric endpoint VALID only after grant handshake |
| Final fabric response | release next; release before upstream completion-consumer wait |
| Fault edge FE | latch fault/error response; quarantine new admissions; preserve accepted work |
| FE+1 or later | earliest error handshake; then FAULT_LOCKED, never IDLE |
| Depth=1 | one legal slot; simultaneous accepted push/pop retains count and order |
| Depth=3 or other non-power of two | compare pointer to DEPTH-1; no masked wrap |
| LEN=0 / one-word packet | one beat; FIRST && LAST is legal |
| Singleton vision output axis | corresponding coordinate=0, replicated borders |
| Simultaneous events | semaphore post priority; overflow set beats clear; IRQ set beats W1C |
| Simultaneous fusion push/pop | preserve accepted FIFO head pairing, ID order and count |

Cache hit/miss/maintenance and MMU latency remain variable. Preserve cache
LOOK/RESPONSE, four-word refill/writeback and RELOOK; MLOOK/MCHECK/optional
writeback/MNEXT per line. Bilinear has six enabled stages; FIR/spatial four;
tensor acceptance precedes 24 busy advances. No new combinational division/modulo
or mixed blocking/nonblocking sequential assignments is allowed. Target device
is Arria 10 GX 10AX115N2F45E1SG, period <=10 ns, WNS >=0 under real Quartus STA.

## Numerical and descriptor ABI

Preserve the complete parent CSR/control/ring/local-memory/mailbox/semaphore ABI,
reserved/error behavior and numerical error values. Tensor descriptors are 128
little-endian bytes: version u32=1 @0; flags @4 (mode[1:0], IRQ bit8,
AUTHENTICATED_MULTIMODAL_WEIGHT_COMMIT bit9, all others 0);
frame address/bytes @8/12; plaintext/activation/result @16/20/24; weight bytes,
vector count,tile ID @28/32/36; nonce[12] @40; tag[16] @52; completion @68;
72..127 zero. AAD is exactly bytes 0..51 in parent byte convention. Required
weights are vector_count*16 for BF16 mode1 and vector_count*4 for W4 modes0/2.
Preserve alignment, non-overlap, allocation and result/completion layout.
Bit9 additionally requires mode0, vector_count=1 and weight_bytes=4, without
changing descriptor layout, AAD length, quarantine or completion semantics.

LZ4 frame magic=0x184d2204, FLG version01; dictionary/reserved bits0/1 rejected;
BD=0x40. Support accepted block dependence, content size, block/content checksums.
Header checksum is seed-zero XXH32[15:8]. Content size equals requested decoded
bytes. Blocks <=64 KiB, raw/compressed and overlap-safe matches. Reject reserved
formats, bad checksum/offset/length, truncation and decoded-length mismatch.
Frame length bound is 2*MAX_TILE_BYTES+256.

AES-128-GCM uses a 96-bit nonce, 128-bit tag and exact 52-byte AAD. Preserve byte
and counter convention; no cleartext/result DMA before authentication and frame
fence success. All errors complete explicitly.

Mode0 tensor: eight signed W4 weights, signed16 activations, exact products,
balanced reduction, signed64 modular accumulation. Mode1 uses BF16 pairs;
mode2 exact W4-to-FP32 and BF16 activation. BF16 appends 16 zeros. Multiply and
each pair/quartet/vector/accumulator addition round separately nearest-even in
accepted order, never fused/reassociated. Preserve subnormals, infinities,
signed zero and canonical invalid/NaN 0x7fc00000. FP result upper32=0.

Vision uses unsigned8 pixels, align-corners Q8 coordinates
floor(256*i*(input_size-1)/(output_size-1)), singleton output coordinate0,
replicated borders, bilinear add32768 then shift16. Preserve Sobel X/Y,
four-neighbor Laplacian and floor spatial means of pixel/absX/absY/absLaplacian
in ascending16-bit lanes. FIR is arithmetic-floor
(x+3*h0+3*h1+h2)>>3 with packet-start zero history. FFT is accepted unnormalized
radix2 with Q15 twiddles, arithmetic multiplication shifts and signed32 butterfly
saturation. Audio lanes: FIR absolute mean, DC magnitude, low-bin sum, high-bin
sum; divide spectral values by FFT_N and saturate32767. Fusion pairs FIFO heads,
preserves ID/order; mismatch error8 precedes vision then audio error; erroneous
data0; successful audio occupies the upper64 bits of the 128-bit fusion packet,
with vision in the lower64. Comparisons are bit-exact.

## Independent acceptance and ownership

Designer owns `rtl/`, this file, `ARCHITECTURE.md`, `sw/`, `fpga/`; Verifier owns
`tests/`, all oracles/transactors/mutations and functional/synthesis execution.
The five admitted commands and thresholds cannot be replaced. Required work
includes real Icarus startup/leaf execution, compiled Verilator seeds17/89/211,
all three workload families >=16 successes/family/seed, independently scored
>=256 MMIO and DDR transactions/client/seed, every mask/lane, legal boundary
lengths, maximum DMA, 4KiB splits, faults, stalls and reset recovery. All16
semaphores, four mailboxes, 16 public IRQ-source positions and legal parameter
boundaries must be exercised. Zero mismatches, active X/Z, latches, unresolved
black boxes or unaccounted transfers are allowed.

Each seed requires actual firmware/Linux/U execution, page-boundary mappings,
permission faults, PTW, timer/PLIC claim-complete and UART-corroborated workload
comparisons, plus dirty CPU/DMA coherence, partial-write preservation,
code/FENCE.I, page-table/SFENCE.VMA, LR/SC and AMO exclusion. Synthetic console
logs, QEMU-only boots and testbench-driven workload execution are not substitutes.

Mandatory distinct fault groups:
`drain_halt_clean_persistent_writeback_error` is the full-top real initial
command-2 endpoint-error witness. It must observe actual error handshakes,
next-edge containment, no handler retirement/retry/fabric DDR/resume and real
reset/boot recovery. `maintenance_command3_persistent_writeback_error` contains
all three separate subcases: `dirty_cache_leaf_endpoint_error`,
`controller_boundary_dwait_error`, `controller_boundary_iwait_error`.
The leaf dirties a real cache via public ports and fails a real command-3 memory
writeback; verify retained dirty/valid/data and later successful reset recovery.
Boundary tests OR only the selected real cache response error in a disposable
Verifier copy before the actual arbiter; preserve VALID/READY/data/timing and
source identity/diff. They follow successful initial cleaning and cannot claim
a later endpoint writeback witness. DWAIT forbids IREQ; IWAIT forbids GRANT.
All error policies persist until consistent endpoint/system reset. Cover
backpressure, write/multibeat read SLVERR, second buffered transaction settlement
and all obligations. Injection OFF preserves normal behavior.
`ordinary_ddr_error_recovery` and ordinary halt-clean failure without coherence
remain independent groups. Fault-classifier-disconnect and all other admitted
mutants must fail intended semantic assertions, not compile failure/timeouts.

The portable suite entry is `python3 tests/verify.py --suite <suite>
--output-root evidence` with suites behavior/linux/defects/synthesis/portability;
behavior/linux also use `--seeds 17,89,211`. Verifier implements these, including
fresh non-overwriting run receipts and real software builds. The shared runtime
alone owns timing lint, Quartus STA and native hardware gates. The final product
PDF is authored/reviewed/rendered after engineering acceptance, never a
verification prerequisite. Source/output selectors exclude runtime metadata.
