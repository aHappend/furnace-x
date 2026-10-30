# FURNACE-X3 v3.0.0-soc-flagship

## Authority and implementation status

The admitted work order defines the acceptance contract; this document does not
relax it. The required product top is `furnace_x3_top`. Target: Intel Arria 10 GX
`10AX115N2F45E1SG`, synchronous clock period <= 10.0 ns. Static elaboration is not
functional verification, timing closure, hardware acceptance, or delivery approval.

The current source increment preserves all 26 parent modules and adds the
synchronization, interrupt, native burst-DMA and shared DDR-fabric building
blocks. The X3 CPU, integration, firmware and independent verification are
not yet complete. Do not
present this increment as an executable X3 SoC.

## Provenance

`furnace_x2_reference/rtl/*.sv` is immutable parent provenance. Its 26 modules
are copied without changes into `rtl/`; shipped RTL must resolve only project-local
modules. The original hierarchy, public `furnace_x1_top` and `furnace_x2_top`
interfaces, numerical behavior and legal parameter domains remain preserved.
No linked source index was supplied or found in the parent directory.

The requested `design/GENERATIONAL_HANDOFF.md` does not exist in this intake.
Historical parent Quartus timing and PPA are unavailable, not accepted
measurements. Fresh runtime timing and hardware gates remain mandatory.

## Product boundary

The new top retains every parent AXI-Lite, vision, audio and multimodal port,
including names, widths, directions and signedness. Four parent 128-bit AXI
masters are adapted to one scalar 512-bit AXI4 master. Addresses are 32-bit;
IDs are 4-bit; lengths are 8-bit; data strobes are 64-bit. Only INCR bursts,
SIZE=6, LOCK=0 and zero CACHE/PROT/QOS/REGION are emitted externally. DDR4 means
the memory-controller-facing AXI4 interface, not a DDR PHY implementation.

The top directly instantiates:

| Instance | Module |
|---|---|
| `control_cpu` | `furnace_rv64im_core` |
| `control` | `furnace_x3_control` |
| `local_memory` | `furnace_x3_local_memory` |
| `mmio_arbiter` | `furnace_x3_mmio_arb` |
| `legacy_soc` | `furnace_x2_top` |
| `burst_dma` | `furnace_dma512` |
| `semaphores` | `furnace_hw_semaphores` |
| `mailboxes` | `furnace_mailboxes` |
| `interrupts` | `furnace_interrupt_aggregator` |
| `cpu_memory_bridge` | `furnace_x3_cpu_axi_bridge` |
| `memory_arbiter` | `furnace_x3_axi512_arb` |

Generate block `legacy_memory_ports` contains four `furnace_axi128_to512`
adapters. No hierarchical peeks, test-only substitutions or extra top-level
debug interfaces implement these connections. The parent literal engine
hierarchy includes `unified_tensor`, `decompressor`, `decryptor`,
`vision_frontend`, `audio_frontend`, `fusion_buffer` and `multimodal_control`.

## Legal configurations

| Parameter | Default | Legal domain |
|---|---:|---|
| MAX_TILE_BYTES | 4096 | 1..65536 |
| RING_DEPTH | 8 | 1..16 |
| IN_WIDTH, IN_HEIGHT | 8, 8 | each 1..64 |
| OUT_WIDTH, OUT_HEIGHT | 8, 8 | each 1..64 |
| FFT_N | 16 | 8, 16, 32, 64 |
| FUSION_DEPTH | 4 | 1..16 |
| MAILBOX_DEPTH | 4 | 1..16 |
| MAX_DMA_BYTES | 1048576 | 1..1048576 |

IMEM and DMEM are each 16384 bytes. There are 16 unsigned 16-bit
semaphores, four 32-bit mailbox FIFOs and 16 interrupt sources. DMA bursts
contain at most 16 beats. Illegal parameters must elaborate safely and
terminate with `PARAMETER ERROR`; illegal datapaths are generate-guarded.

## Cycle and degenerate-boundary table

All handshakes use **pre-edge** VALID && READY. Updates and new VALID values
are visible **post-edge**, never retroactively consumed.

| Boundary | Required behavior |
|---|---|
| Active reset | New resettable state uses asynchronous active-low reset. All public ready/valid/irq and response payloads are zero. RAM arrays need not reset; uninitialized entries must not become valid. |
| Reset released before E0 | E0 enables interfaces; no request handshakes at E0. E1 is the first possible request edge. |
| Local/MMIO request at En | Capture at En, execute/read at En+1, response valid post-En+1, earliest response handshake En+2. One response remains stable until consumed. |
| New firmware DATA at En | Capture payload and metadata atomically; parent-facing token visible post-En and first consumable En+1. Full slots hold every field stable. |
| DMA command at En | Capture at En, validate En+1, first address visible no earlier than post-En+2. Invalid/zero commands complete post-En+1 without AXI traffic. |
| FIFO DEPTH=1 | Read/write pointers remain zero; full simultaneous pop/push returns old head and replaces it without changing occupancy. |
| FIFO DEPTH=3 or other non-power-of-two | Explicit compare against DEPTH-1 wraps pointers; no bit-mask wrap. |
| FIFO empty simultaneous pop/push | Pop fails; push stores one word; no empty bypass. |
| Semaphore post + TAKE | Hardware post is linearized before software at the software execution edge; TAKE may consume the new token. |
| Semaphore saturation | A post/GIVE at 65535 preserves 65535 and sets overflow; a same-edge TAKE does not retroactively erase overflow. |
| IRQ set + ACK | Set wins: next pending = (pending & ~ACK) \| sources. |
| Sticky overflow set + clear | Set wins; clearing cannot hide a new overflow. |
| DMA one beat / one byte | LAST accompanies the only beat; exact low-byte tail strobes; no read-modify-write. |
| Singleton frame | FIRST and LAST may coincide. Preserve parent packet semantics and mandatory singleton testing. |

CPU fetch response consumption at F is followed by decode F+1,
execute/setup F+2 and non-memory/non-M retirement F+3. Memory response
consumption at M retires at M+1. M instructions perform 64 registered radix-2
iterations, two normalization/sign stages, then retirement, including W
operations and exceptional divisions. No following instruction issues early.
Interrupts are taken only at boundaries with no outstanding request.

Preserved parent elastic stage counts are bilinear six, FIR/spatial four,
FP32 multiply four CE stages and FP32 add five CE stages (or four with
OUTPUT_REGISTER=0 plus the enclosing register). An L-stage token accepted
En first becomes valid post-En+L-1 and consumable En+L without stalls.
Parent tensor completion is visible post-En+24 and consumable En+25.

## CPU and memory

The control processor implements RV64IM and machine-mode Zicsr, standard LP64,
little-endian memory and no custom scheduler instructions. An unavailable
Hammer-V image is not claimed to have run. Physical addresses must be
zero-extended 32-bit values; unsupported high bits fault, never truncate.
The single-issue multicycle core has one outstanding unified request:
`req_valid/ready`, `req_write`, `req_instr`, `req_addr[63:0]`,
`req_wdata[63:0]`, `req_wstrb[7:0]`, `req_size[1:0]`, and
`rsp_valid/ready`, `rsp_rdata[63:0]`, `rsp_error`. Size 0..3 means
1/2/4/8 bytes. Data/strobes and response bytes are low-justified. Fetch
uses instruction=1, write=0, size=2. Requests and responses hold under stalls.

All RV64I instructions and RV64M operations, including W forms, are required.
x0 is immutable, W results sign-extend, integer arithmetic wraps. JALR clears
bit0 then checks IALIGN=32. Misaligned/faulting accesses have no memory side
effect. Signed division truncates toward zero; remainder follows dividend
sign. Zero divisor produces all-one quotient and unchanged dividend remainder;
signed minimum/-1 produces minimum quotient and zero remainder.

Required CSRs: mstatus, misa (RV64IM), mie, mip, direct-only mtvec, mscratch,
mepc, mcause, mtval, mcycle/cycle and minstret/instret. ECALL, EBREAK, MRET,
WFI and serialized FENCE/FENCE.I are supported. Invalid instructions,
unsupported CSR accesses and unsupported mtvec modes trap. Precise causes
are instruction misalignment/access 0/1, illegal 2, breakpoint 3,
load misalignment/access 4/5, store misalignment/access 6/7 and machine
ECALL 11; machine-external interrupt is interrupt cause11. Trap entry does
not retire the instruction. MIE/MPIE/MPP follow machine semantics.
Reset PC is 0x10000, CPU halted, MPP=M, enables zero. RUN=0 requests
halt after retirement; it cannot cancel accepted bus work.

| Range | Owner/access |
|---|---|
| 0x0000..0x1fff | Unchanged parent CSRs, CPU and host |
| 0x2000..0x2fff | X3 CSRs |
| Host 0x4000..0x7fff | IMEM aperture |
| Host 0x8000..0xbfff | DMEM aperture |
| CPU 0x10000..0x13fff | IMEM, executable/read-only |
| CPU 0x20000..0x23fff | DMEM, read/write |
| 0x80000000..0xffffffff | DDR, read/write/executable |

Other accesses fault. Local memories are synchronous, little-endian and
byte-write enabled. Host memory writes while CPU runs return SLVERR.
CPU MMIO requires aligned 32-bit non-instruction accesses. Host AW and W
may arrive independently. Host/CPU MMIO use fair round-robin transaction
arbitration, reset tie priority host, toggling on service; parent ownership
lasts through response. Held VALID does not duplicate operations.

## X3 registers

Unsupported offsets, misalignment and reserved-bit writes return SLVERR and
set sticky protocol error. Byte strobes apply before reserved-bit checks.

| Address | Register/semantics |
|---|---|
| 0x2000 | RO version 0x03000000 |
| 0x2004 | CPU_CTRL RUN bit0; core-only reset bit1 only while halted |
| 0x2008 | CPU_STATUS running bit0, halted bit1 |
| 0x200c | Last trap cause, interrupt indicator bit31 |
| 0x2010/0x2014 | Last trap PC low/high |
| 0x2018 | W1C error: protocol0, semaphore overflow1, DMA2, core bus3 |
| 0x2020 | FW_MODE bit0: set only halted and parent quiescent; sticky until global reset; clearing a set mode faults |
| 0x2040/0x2044/0x2048 | DMA_SRC/DST/LEN; writes while busy fault |
| 0x204c | CMD bit0 snapshots configuration; busy start faults without disturbance |
| 0x2050 | STATUS busy0, sticky done1, error15:8 |
| 0x2054 | W1C DMA done/error |
| 0x2100/0x2104/0x2108 | IRQ_PENDING / IRQ_MASK / IRQ_ACK W1C |
| 0x2200/0x2204 | Vision pixel u8 / signed audio sample i16; wait for free slot |
| 0x2210/0x2214 | Metadata ID15:0, LAST16; captured at DATA execution |
| 0x2220 | RO slot-full vision0/audio1 |
| 0x2400+16*i | Semaphore i TAKE read, returns1/decrements iff nonzero |
| 0x2404+16*i | Semaphore GIVE write1, overflow faults/preserves |
| 0x2408+16*i | Semaphore VALUE read |
| 0x2600+16*i | Mailbox i DATA, read pop / write push |
| 0x2604+16*i | Mailbox STATUS count4:0, empty8, full9 |

RUN requires FW_MODE. Mode0 preserves external parent streams. Mode1 zeros
external v_ready/a_ready/mm_valid, uses internal registered firmware slots
and internally consumes parent multimodal output independently of host
mm_ready. Mode switch cannot split a packet.

DMA completion (including error) posts semaphore0 once; internally consumed
multimodal completion posts semaphore1 once. Software graph semaphores
are 2..15. Mailbox empty reads/full writes fault without mutation.
IRQ sources are parent level0, DMA pulse1, internal multimodal pulse2,
sticky protocol3, mailbox-nonempty4..7, sticky overflow8, core trap pulse9,
zero10..15. Pending and mask reset zero. IRQ is the masked registered
pending reduction. Firmware clears originating level conditions as well
as aggregator pending.

## Memory arbitration and burst DMA

Six clients are legacy0..3, CPU4 and DMA5, with these external physical IDs.
Read/write arbitration is independent, burst round-robin, with one global
outstanding read and one write; write ownership extends through B.
Legacy response IDs are restored. 128-bit adapters align down to 64 bytes,
select the addressed read quarter and place original data/strobes in the
write quarter. CPU adapters select bytes and use exact strobes. Extra
read bytes are allowed only in DDR. Partial writes never use read-modify-write.
Check IDs, response errors and LAST; faults must propagate.

DMA copies real DDR bytes. Source/destination must be 64-byte aligned DDR
addresses; positive lengths are <=MAX_DMA_BYTES, exact ranges nonoverlapping
and end-exclusive sums <=2^32. Zero length succeeds only with otherwise
valid aligned DDR addresses. Invalid commands complete code1 without AXI
traffic. Bus/ID/LAST faults complete code2 after draining accepted traffic;
success code0 never precedes final B handshake.

Each burst buffers up to16 512-bit beats before writing. Beats are the
minimum of remaining rounded-up beats,16, source page remainder and
destination page remainder. Neither channel crosses4KiB. LAST matches the
final beat. Partial final WSTRB selects only requested low bytes, preserving
all destination guards. Faulted predecessors never launch dependent nodes.

## Firmware graph and numerical contract

Firmware is freestanding, project-local, deterministically generated using
declared tools. Host initializes images, manifests, keys and data, enables
FW_MODE and writes RUN; after RUN it performs no scheduling, sample
injection, acknowledgements or dependency resolution.

DMEM boot manifest at0x20000 holds graph DDR address+0, node count+4,
parent ring base+8, vision/audio/result bases+12/+16/+20, AES key words+24..39.
Graphs have1..64 64-byte records: opcode+0, ID+4, dependency bitmap u64+8,
six u32 arguments+16..39, wait/post semaphore+40/+44, status address+48,
zero reserved+52..63. Dependencies name record indices. Semaphore
0xffffffff means none; graph indices otherwise2..15. Reject cycles,
invalid dependencies/opcodes/reserved bits/indices explicitly.

Opcode1 copies DMA(src,dst,len); opcode2 submits a supplied128-byte parent
descriptor at arg0 through a legal ring slot; opcode3 streams image/audio
at arg0/1 with frame ID arg2; opcode4 is a zero-argument barrier.
Unused arguments are zero. Scan runnable nodes, overlap independent DMA
and parent work, consume actual completion interrupts/tokens, post graph
tokens only after success, and mark failed dependents explicitly.
Status records are16 bytes: state(0 pending,1 active,2 successful,3 failed,
4 dependency-failed), error, ID, zero. Final mailbox notification follows
commit of every terminal record.

The required graph exercises encrypted compressed weight loading,
LZ4/AES-GCM authenticated INT4 commit, concurrent ISP/DSP, fusion/tensor,
DMA publication, fork/join, semaphore waits/posts and IRQ wait/resume.
Repeated executions must wrap queues without reset. Preserved BF16 and
W4/BF16 standalone descriptor modes remain required.

Preserve the complete parent128-byte descriptor ABI: version1@0;
mode1:0/IRQ8/authenticated-weight-commit9 flags@4; frame address/bytes@8/12;
plain/activations/result@16/20/24; weight bytes/vector count/tile ID@28/32/36;
nonce bytes40..51; tag52..67; completion address68; zero remainder.
AAD is bytes0..51. Preserve alignment, range/nonoverlap checks, allocation,
error priority and suppression of unsafe completion writes. Result record
is u64 result/u32 ID/u32 zero. Completion is status/ID/authenticated bytes/zero.
Errors0..8 mean success, descriptor, frame, LZ4 offset, authentication,
memory, tensor protocol, stream framing, fusion ID mismatch. Failure must
not release quarantined plaintext or replace authenticated weights.

Mode0 is eight signed INT4 weights (LS nibble first) times eight signed
INT16 activations (LS lane first), wrapping64-bit accumulation. Modes1/2
are BF16/BF16 and INT4/BF16. BF16 extends to FP32 bits31:16. Independently
round each multiplication, balanced reduction level and inter-vector sum
to nearest-even, with gradual underflow, signed zero, infinity and canonical
NaN0x7fc00000; result is zero-extended FP32 bits, never tolerance-based.

ISP uses align-corners Q8 floor coordinates (zero for singleton output),
clamped neighbors, bilinear +32768 before shift16, replicated spatial
edges, Sobel and four-neighbor Laplacian. Feature u16 lanes are floor
mean intensity/abs gx/abs gy/abs Laplacian. DSP resets FIR per frame,
uses[1,3,3,1]/8 arithmetic floor, radix2 FFT Q15 twiddles, full products,
shift15 and signed32 butterfly saturation. Audio lanes are mean abs FIR,
DC L1/N, bins1..N/4 L1/N, binsN/4+1..N/2 L1/N (spectral saturation32767).
Vision occupies low64 activation bits, audio high64. FIFO pairing is
arrival ordered; ID mismatch overrides with error8/zero, otherwise vision
error precedes audio error.

Preserve LZ4 frame magic04 22 4d 18/version1/BD0x40, optional content size,
block/content XXH32 seed0 checksums, independent/dependent/raw blocks,
overlapping matches and history/decoded limits. Reject invalid flags,
dictionary/reserved fields, offsets, extensions, lengths/LAST/checksums
and final-sequence constraints. AES128/GCM ordering follows its standard
byte strings with explicit conversion at the preserved boundary.

## Independent acceptance and reproduction

Designer owns `rtl/*.sv`, `design/*.md` and `firmware/*`. Independent
Verifier owns all `tests/*`, models, harnesses and execution orchestration.
No Designer functional simulation or synthesis is an acceptance shortcut.

From the delivered root, mandatory portable L1 entry points are:

```
python3 tests/verify.py --suite behavior
python3 tests/verify.py --suite defects
python3 tests/verify.py --suite synthesis
python3 tests/verify.py --suite portability
```

These are required future Verifier-owned entry points, not currently executed
results. Dependencies: Python3, Icarus/vvp, Verilator, make, g++ and Yosys
with a compatible SV path. Icarus Verilog12.0 (stable) performed a static
default-parameter elaboration of the eight new leaf/fabric modules only.
That check did not run vvp, functional simulation or synthesis.
Other dependency versions have not yet been established.
No installation is authorized by this source increment.

Behavior requires real Icarus compact smoke, full compiled-Verilator
C0..C4 cells with seeds17/89/2027, independent CPU/device/graph and
bit-exact numerical/cryptographic models, every admitted coverage threshold,
precise trap/ISA tests and observed queue-wrap/concurrency/AXI error behavior.
Each cell/seed runs >=2 autonomous >=6-node graphs with fork/join;
descriptor retirements >=2*RING_DEPTH+1, multimodal results
>=2*FUSION_DEPTH+1 and mailbox transfers >=2*MAILBOX_DEPTH+1.
Applicable observed coverage counters must be nonzero; only the admitted
singleton legal-geometry distinctions apply.

| Cell | MAX_TILE_BYTES | RING_DEPTH | FUSION_DEPTH | MAILBOX_DEPTH | Input | Output | FFT_N | MAX_DMA_BYTES |
|---|---:|---:|---:|---:|---|---|---:|---:|
| C0 | 4096 | 8 | 4 | 4 | 8x8 | 8x8 | 16 | 1048576 |
| C1 | 64 | 1 | 1 | 1 | 1x1 | 1x1 | 8 | 1 |
| C2 | 256 | 3 | 3 | 3 | 3x2 | 5x3 | 32 | 4096 |
| C3 | 4096 | 8 | 4 | 4 | 8x8 | 3x2 | 64 | 1048576 |
| C4 | 65536 | 16 | 16 | 16 | 64x64 | 64x64 | 64 | 1048576 |

Default/large cells must observe multi-beat DMA, DMA/engine overlap and
competing memory clients. C1 must observe legal one-byte DMA and oversize
rejection. MAX_TILE_BYTES=1 is a separate legal parameter test, not a
fabricated four-byte-weight descriptor workload.

Defect sensitivity requires >=10 isolated valid RTL mutants, passing
original controls and intended behavioral assertion failures, including
W sign extension, division corners, semaphore double-take, mailbox wrap,
IRQ priority, DMA page/tail/premature completion, quarantine and fusion.
Synthesis covers the complete X3 and standalone X1/X2 hierarchies,
singleton/non-power-of-two leaves, zero latches, no black boxes and
substantive connected state. Portability copies only declared sources
and executes fresh firmware/engine smoke without private/generated inputs.
No stale or missing receipt is a passing check.

Icarus is limited to compact <=500000-cycle smoke; full cells and mutations
use compiled Verilator. Evidence directories are unique and end in a
timestamp/hash; failures are retained. The shared runtime alone owns
L1.5 timing lint, L2 Quartus17.1 STA (WNS>=0 at<=10ns) and L3 Arria10
PCIe Gen3x8 HIL (>=3 consecutive deterministic physical passes).
Zero combinational division/modulo and no mixed blocking/nonblocking
sequential assignments are mandatory. No timing waiver is presumed.
The runtime-authored, independently approved product PDF follows engineering
acceptance and is not an earlier verification prerequisite.
