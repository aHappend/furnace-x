# FURNACE-X3 architecture

## Increment and preservation

This is the design description of an incomplete implementation increment,
not an engineering acceptance report. All26 original parent modules have
project-local copies in `rtl/`, without numerical or interface changes.
The original source directory is not an arithmetic oracle or a passing
baseline. Missing historical timing/PPA is disclosed in `SPEC.md`.

The intended integration retains the full parent engine subsystem behind
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

## Remaining integration

The CPU, local memories, MMIO arbiter, X3 control/top, firmware builder
and scheduler still need implementation and must wire the completed leaves.
These must retain the exact contracts in `SPEC.md` and the admitted work
order. In particular, firmware must observe real engine completions,
DMA must overlap independent parent activity, and autonomous final
mailbox notification must follow committed DDR node statuses.

Independent Verifier owns test sources/models, functional experiments,
mutation evidence and complete-hierarchy synthesis. No functional,
numerical, synthesis, timing or physical result is asserted here.
