# FURNACE-X3 architecture

## Increment and preservation

This is the design description of the connected implementation,
not an engineering acceptance report. All26 original parent modules have
project-local copies in `rtl/`, without numerical or interface changes.
The original source directory is not an arithmetic oracle or a passing
baseline. Missing historical timing/PPA is disclosed in `SPEC.md`.

The integration retains the full parent engine subsystem behind
four width adapters, shares a six-client DDR memory fabric, and adds a
registered single-issue RV64IM control processor. Firmware owns task graph
scheduling; hardware owns accepted transactions, synchronization and events.
There is no host scheduling after RUN and no scripted completion path.

## Boundary dependency table

| Consumer | Relies on producer guarantee |
|---|---|
| CPU | Memory response is low-justified, stable under stalls, and explicit about faults |
| Local memory | Arbiter sends only one outstanding request and protects host writes while running |
| Parent subsystem | Width adapters preserve single-beat quarter/data/strobes/IDs and response errors |
| Memory arbiter | Each requester retains its burst address/data until handshake and drains accepted responses |
| DMA | Memory is ordinary DDR; writes use byte strobes, not read-modify-write |
| Graph scheduler | Completion token/event follows actual retirement/B response, never command issue |
| Firmware slots | Parent backpressure may persist; every queued token is held atomically |
| Synchronization | Serialized MMIO operations are executed once; hardware posts may occur independently |
| Interrupt aggregator | Completion pulses are single-edge events; level sources remain asserted until cleared |

## New leaf interfaces

All new clocked leaves have `clk,rst_n`, an internal post-reset enable,
asynchronous active-low state reset and zero external outputs while reset.
No ready signal is high before the first post-reset edge.

### Register request/response leaves

`furnace_hw_semaphores`, `furnace_mailboxes` and
`furnace_interrupt_aggregator` use the same local transaction convention:

| Port | Meaning |
|---|---|
| req_valid / req_ready | Capture a single local operation |
| req_write | 1 write, 0 read |
| req_addr[7:0] | Byte offset within the selected leaf window |
| req_wdata[31:0], req_wstrb[3:0] | Host/CPU little-endian byte write enables |
| rsp_valid / rsp_ready | One retained response |
| rsp_rdata[31:0], rsp_error | Read result (zero for writes/errors), explicit fault |
| protocol_error | One-cycle pulse when executing a malformed/unsupported operation |

Capture at En is followed by execution at En+1, not at capture. An
accepted operation owns the leaf until its response handshakes. All input
fields are captured; later request changes cannot affect execution.
Response payload remains stable under backpressure. Zero-strobe writes to
an otherwise writable legal register perform no mutation and succeed;
invalid addresses/directions still fault.

Semaphore offset is16*index+{0 TAKE,4 GIVE,8 VALUE}. `hw_post[15:0]`
is one token per asserted semaphore per edge. Software service sees
same-edge posts first. The saturating counters and overflow flag are
reset state, not uninitialized RAM. `clear_overflow` is W1C-derived;
hardware/software overflow wins a simultaneous clear. `overflow` is
sticky and `overflow_event` pulses on each overflowing operation.
The semaphore leaf itself does not assign CPU/host arbitration priority.

Mailbox leaf offsets are16*index+{0 DATA,4 STATUS}, index0..3.
`nonempty[3:0]` drives interrupt levels. Each child
`furnace_mailbox_fifo` additionally exposes `push,pop,push_data`,
`pop_data,pop_ok,push_ok,count,empty,full` for its actual integration,
not as top-level debug ports. These are pre-edge operation qualifiers
and acceptance results, not an empty fall-through stream. The storage
read is the existing head; simultaneous full pop/push returns old head
while storing the replacement. RAM writes occur only on a successful
push; pointers and count reset; empty data is zero. DEPTH invalidity
is safely guarded before declaring arrays.

IRQ offsets are0 PENDING (RO),4 MASK (RW),8 ACK (WO W1C).
`sources[15:0]` are sampled each active edge. `pending` and `mask`
are registered outputs; `irq` is their masked reduction. Source set
wins software clear. Mask writes merge bytes; nonzero reserved
bits31:16 fault. A source sampled at En affects IRQ post-En.
A PENDING read returns the registered pre-execution-edge pending value;
same-edge new sources become visible to subsequent reads.

### Native burst DMA

`furnace_dma512` accepts `cmd_valid/ready`, `cmd_src/dst/bytes[31:0]`.
One accepted command owns the engine through completion handshake.
`busy` covers validation, transfer and retained completion. Outputs
`done_valid/ready` and `done_error[7:0]` are retained; `completion`
is a one-edge publication event, independent of done response stalls.
The control block will consume done unconditionally, retain sticky
software status, and use completion for IRQ and semaphore0.

Its compact AXI-facing boundary includes the five standard channels:
AW/AR address32, ID4, LEN8, SIZE3, BURST2, valid/ready;
W data512/strobe64/LAST/valid/ready; B ID4/RESP2/valid/ready;
R ID4/data512/RESP2/LAST/valid/ready. Fixed AXI attributes are
driven once by the enclosing fabric; this leaf emits only SIZE6,
INCR and ID5. Unused payloads are zero, including reset outputs.

Pipeline states are capture -> validate -> plan -> AR -> buffer R ->
prepare write -> AW -> W -> B -> advance/complete. Address arithmetic
is33-bit for validation, page limits are 7-bit counts of64-byte beats,
and burst size is1..16. Planning separates address-limit arithmetic
from external VALID. The16x512 buffer has a synchronous read port
with a separate read-valid preparation state; W payload remains
registered and stable when stalled.

Accepted reads with malformed LAST drain until an actual LAST before
publishing code2. An early LAST is a fault and cannot cause an AW.
An expected final beat missing LAST enters drain; no partial buffer
is written. Any fault in the burst suppresses that burst's writes.
Accepted writes always finish their W stream and consume B.
Earlier acknowledged bursts remain on an error, as the contract allows.

### DDR bridges and arbitration

`furnace_x3_cpu_axi_bridge` has the core's unified request/response
interface on its input and the same compact five-channel AXI interface
as the DMA on its output. It accepts only zero-extended32-bit DDR
addresses and naturally aligned1/2/4/8-byte accesses. Instruction
requests must be4-byte reads. Strobes outside the addressed access
width fault; legitimate partial strobes remain exact. Captured requests
are validated before any AXI side effect. Writes place bytes directly
in the addressed64-byte line; reads buffer the line, then normalize
low-justified bytes in a separate registered stage. ID4, response
errors and read LAST are checked. Missing LAST enters drain before
an error response. There is only one outstanding unified request.

`furnace_axi128_to512` has the full parent128-bit AXI port as its
slave input. CLIENT_ID is0..3, with executable illegal-parameter
diagnostics. Its master boundary is the compact512-bit AXI interface.
AW and W are captured independently. Only aligned16-byte DDR,
single-beat, SIZE4, INCR, unlocked parent transactions are legal.
Original IDs are retained for the parent response; external IDs
are CLIENT_ID. Legacy QoS/cache/protection attributes do not alter
the frozen zero-attribute external interface. Address quarter selects
the128-bit data/strobe positions without read-modify-write.
Reads/writes have independent outstanding slots. Faulted read responses
contain zero data, and missing LAST drains to actual LAST.

`furnace_x3_axi512_arb` accepts six packed client channel arrays,
indexed legacy0..3/CPU4/DMA5. Each client supplies AW/AR address32,
LEN8 and VALID, W data512/strobe64/LAST/VALID, and response readiness.
It returns channel readiness and B/R payloads including raw physical
IDs. Client SIZE/BURST/ID outputs are fixed by their bridge contracts;
the fabric centrally emits SIZE6, INCR and physical owner ID, with
zero auxiliary AXI attributes. These unused client attribute outputs
are intentionally not arbiter inputs.

Read and write round-robin pointers and ownership are independent.
An idle arbiter selects a pending address and registers address/LEN
and owner, then presents external VALID. The client address handshake
occurs only with the corresponding external address handshake, not
at internal selection. This preserves backpressure and ownership.
Write data routing remains owned until the accepted burst beat count
is exhausted and B is consumed; read ownership lasts to accepted
actual RLAST. Returning a bad ID to the retained owner, rather than
routing by that untrusted ID, lets the owning bridge report the fault.
Round-robin advances after completion, explicitly wrapping5->0.
No write request waits for an unrelated read or vice versa.

## Ownership and degenerate boundaries

The pre/post-edge and reset table in `SPEC.md` is normative. Leaf
simultaneous events use the following order:

1. Sample hardware posts/sources and compute accepted FIFO operations
   from pre-edge occupancy.
2. Execute the previously captured software operation exactly once.
3. Publish its response and sticky/event updates post-edge.

Semaphore full-post then TAKE records overflow even if TAKE creates
space; it does not pretend the rejected post was accepted. Full FIFO
pop/push succeeds in both directions. Empty FIFO pop/push fails pop
but accepts push, with no bypass. Pointer wrap compares against
DEPTH-1 explicitly; DEPTH1 never creates a zero-width pointer.

## Connected X3 integration

`furnace_x3_top` directly instantiates every required block and the four
legacy width adapters. The preserved parent remains a literal
`furnace_x2_top legacy_soc`, with no new hierarchical references or numerical
substitutions. FW_MODE resets to zero; mode-zero stream signals pass through
the parent. Mode-one gates the external stream handshakes and consumes the
parent result internally, independently of host result readiness.

### RV64IM core

`furnace_rv64im_core` uses a non-overlapped boundary/fetch/decode/execute/
retire machine. The register file, PC, counters, CSR state and protocol
ownership reset asynchronously. Operand reads are captured at decode;
control/ALU results are captured at execute, then retired separately.
Branches and JALR validate the destination before any link writeback.
Loads/stores validate alignment before presenting a request; bus errors
enter the appropriate precise trap without retirement.

The M datapath uses a 128-bit shift/add accumulator and a 64-bit multiplier
shift register, or a 65-bit restoring-divider trial remainder and a 64-bit
quotient. Every M operation advances exactly64 iterations, followed by
separate normalization, sign/result and retirement edges. W inputs are
normalized to their specified signedness and every W result sign-extends.
Zero-divisor and minimum/-1 outcomes use the same fixed schedule.
No combinational multiply, division or modulo implements M execution.

CSRs are read at execute and written only at retirement. Counter writes
override that instruction's automatic counter increment; read-only cycle/
instret aliases trap on attempted writes. Implemented machine mode fixes
MPP=M and misa=0x8000000000001100. Only MEIE is implemented in mie, mip.MEIP
reflects ext_irq and its writes have no effect. misa writes retain the fixed
ISA. mstatus implements MIE/MPIE and machine-only MPP; mepc masks bits1:0.
mtvec writes with a non-direct mode trap rather than changing the request.
The core serializes FENCE/FENCE.I, and WFI wakes on an individually enabled
external interrupt even while global MIE is clear. RUN removal stops only
at a boundary after accepted work has completed.

Additional internal outputs implement the frozen event/status boundary:
`trap_valid` is a one-edge trap-entry pulse, `trap_cause[63:0]` and
`trap_pc[63:0]` retain the last trap, and `bus_error` is a one-edge bus-fault
event. These connect only to control/interrupt blocks; no product debug port
was added. Control caches trap status so core-only reset does not erase it.

### Host/CPU transaction and memory boundaries

`furnace_x3_mmio_arb` accepts the public AXI-Lite slave channels and the
core's unified request/response interface. It buffers AW and W independently
and has a separate AR slot. Round-robin chooses host versus CPU, initially
host; a separate alternating preference prevents starvation of host reads
by host writes. The selected owner remains selected through delivery of
its response, including all parent AXI-Lite backpressure. Future host
addresses/data may fill the bounded input slots but cannot execute early.

The arbiter's `dev_req_*`/`dev_rsp_*` boundary retains the unified64-bit
address/data,8-bit strobe and2-bit size convention, adding `dev_req_host`
to distinguish host apertures. It serializes CPU local/DDR operations as
well as MMIO, which is conservative but does not reduce required ISA,
memory-client concurrency or fairness. `furnace_x3_control` captures this
request and routes complete-address comparisons; it never silently narrows
unsupported physical addresses.

Control `memory_req_valid/ready[1:0]` and corresponding response arrays
select local memory at index0 and the CPU DDR bridge at index1. The
`memory_req_host/write/instr/addr/wdata/wstrb/size` fields are shared and
stable until the selected request is accepted. Response data has two64-bit
lanes; validity, error and readiness have two bits. A retained request owns
control through response; an unselected response is never consumed.

`furnace_x3_local_memory` accepts that same unified bus plus `req_host`
and `cpu_running`. Two2048x64 byte-enabled, unreset RAM banks implement
IMEM/DMEM. Synchronous array access is in a separate non-reset process;
only valid captured requests can access RAM. Registered response ownership
and error flags reset. A capture at En performs the RAM read/write at
En+1; the response and registered RAM read are visible post-En+1.
Byte selection/normalization uses the captured offset and width.
Hosts must initialize every byte they read or execute; reset is not
an implicit initialization of either RAM. Host writes sampled while the
CPU runs, CPU IMEM writes, instruction fetch from DMEM and bad sizes/
alignment/addresses return errors without a RAM side effect.

Control `leaf_req_valid/ready[2:0]` and response arrays select IRQ0,
semaphores1 and mailboxes2. Shared request fields are write, byte-offset8,
data32 and strobe4; response data has three32-bit lanes. The existing
leaves enforce their register offsets and side-effect/error rules.
Parent `p_axil_*` is a full32-bit AXI-Lite master boundary: independent
AW/W sent flags and retained ownership cover the response. Parent errors
propagate and set the X3 protocol status.

### Control, mode transition and firmware slots

Control owns RUN, the one-cycle core-reset pulse, sticky FW_MODE and errors,
DMA configuration/sticky completion, trap mirrors and two stream slots.
`dma_cmd_valid/ready/src/dst/bytes` connects directly to the real DMA;
configuration is held stable while busy. Accepted command writes return
only after their command handshake, not after an invented completion.
`dma_done_*` is always consumed and latched in control, while the separate
DMA `completion` event drives semaphore0 and IRQ source1 exactly once.
The internally consumed real parent result drives semaphore1 and IRQ
source2. Sticky error W1C loses to concurrent new event setting.

FW_MODE transition holds the transaction while control reads public parent
busy, head, tail and multimodal status CSRs. It requires a halted CPU, no
partial external packets, equal ring head/tail and idle engines/feature
credits. Any external stream activity during this probe rejects the switch.
`legacy_v_transfer/last`, `legacy_a_transfer/last` and
`legacy_stream_activity` are actual stream-boundary observations, not
hierarchical internal probes. Once set, ownership cannot be cleared except
by global reset. No parent register or engine is reset by the transition.

`fw_v_valid/ready/pixel/id/last` and `fw_a_valid/ready/sample/id/last`
connect the control slots to the actual parent streams. Metadata is
captured with DATA at its execution edge, not read live from metadata
registers while stalled. Capacity allows replacing a token on the same
edge that the parent accepts the old token; empty slots have no bypass.
Full slots cause DATA service to wait, without blocking hardware engines,
DMA progress or completion token accounting.

### Firmware ownership

`firmware/build.py` assembles only standard RV64IM/Zicsr instructions from
`firmware/scheduler.S`, without a cross-compiler or external package.
The firmware snapshots and validates the graph, checks dependency closure,
initializes public status records, then scans runnable nodes. Independent
resource slots allow native DMA, descriptor processing and frame progress
to overlap. Descriptor copying writes the real parent ring and publishes
its tail only after all128 bytes are acknowledged and fenced.

Completion handling uses the real parent retirement counter/error,
hardware completion tokens and frame status. It never advances a
dependent on command acceptance. Vision/audio feeding is incremental and
nonblocking with respect to the other resources. Interrupt wait/resume
uses the real aggregator and precise MRET; the final completion check
is protected against an ISR/WFI race. Terminal status words are committed
before the final mailbox notification. Failure propagation and software
layout/error ABI are detailed in `SPEC.md` and `firmware/README.md`.

Independent Verifier owns test sources/models, functional experiments,
mutation evidence and complete-hierarchy synthesis. No functional,
numerical, synthesis, timing or physical result is asserted here.
