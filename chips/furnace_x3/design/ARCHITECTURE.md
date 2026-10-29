# FURNACE-X3 architecture

## Connected ownership

`furnace_x3_top` instantiates `x2_core:furnace_x2_top`,
`queue_rings:furnace_descriptor_rings`, `scheduler:furnace_drr_scheduler`,
`shaper:furnace_token_bucket8` and `dma_engine:furnace_sg_dma`.
X2 retains `crc_core`, `parser`, `rss`, `classifier`; X1 retains
`beat_pipeline`, `packet_accumulator`, `tail_pipeline`, `output_stage`.
The legal-datapath generate branch is not a replacement hierarchy.

| Module | Storage / responsibility | Release boundary |
|---|---|---|
| descriptor_rings | eight configurations, producer/consumer sequences, independent physical indices, head records and prefetch claims | external completion handshake |
| drr_scheduler | visit queue/active flag, eight deficits, E0 snapshots, E1 comparisons, E2 grant, single reservation | rejection or reserved retirement |
| token_bucket8 | eight Q32.16 balances, refill operands, one reservation and settled flag | reserved retirement |
| sg_dma | eight identity-tagged SG caches, one outstanding exact read, staged beat, byte RAM and registered packet assembly | prefetch publication for command lock; completion handshake for executed identity/cache |
| top | registered arbitration, one active descriptor, public result-drain flags and held completion | external completion handshake |

SPEC.md is the complete public/internal port, arithmetic, cycle and host ABI
contract. Internal ready/valid transfers and reserve/refund/retire event buses
are distinct. A cached head is never dequeued on scheduling, and a failed
payload is refunded before held error completion without releasing ownership.

## Resource and timing choices

One globally active packet and one outstanding read avoid reorder tables,
competing reservations and ambiguous completion attribution. Prefetch is
sequential and round-robin, with one validated head per queue. Error heads are
retired through the same externally backpressured path without credits.
Registered arbitration provides cached service before new discovery and never
changes a captured decision. Waiting on a successor retains the DRR visit.

Maximum payload RAM is 9216 bytes, independent of lane width. SG cache is
8*16*(64+32)=12288 bits plus tags/counts. Eight cached packets are not stored:
only SG records are replicated. Descriptor and SG reads add 32+16*N bytes per
packet; payload traffic is exactly packet length. These are storage/traffic
counts, not measured throughput. Byte-serial response unpack and synchronous
one-byte output assembly deliberately trade throughput for shallow bounded
logic. No minimum line rate is asserted by the work order.

All payload writes and reads are synchronous in a dedicated non-reset RAM
process. Response capture, byte consumption, final validation, RAM read,
assembly and output publication are separated by registers. Fixed-byte shifts
avoid packet-length combinational chains. Widened address and credit arithmetic
is explicit; ring index wrap uses comparison, not division. Eligibility is a
three-edge snapshot/compare/commit decision, never same-edge refill borrowing.
Target-specific timing remains a mandatory independent STA gate; structure
alone is not proof of 100 MHz.

## Integration obligations and limitations

The bridge is byte addressed, preserves request order, provides valid terminal
masks, and performs physical PCIe alignment/splitting. Host descriptors and all
referenced bytes remain immutable from accepted posting through completion.
The environment resets outstanding bridge responses with the DUT. dma_enable
is static during all work. X2 classifier action is opaque; ring identity selects
the transmit queue. There is no receive-to-host DMA or device-specific PCIe IP.
Missing terminal responses, downstream stalls and permanently zero-rate queues
have no finite progress bound. These are explicit integration obligations, not
exceptions to error detection or ownership.

## Handoff and reproduction

Build sources are exactly `rtl/*.sv`, with no implicit reference-RTL search.
Read SPEC.md for reset/start order: reset bridge and DUT, release reset, choose
mode while quiescent, configure queues, initialize host descriptor/SG/payload
storage, then post producer updates and accept controls/results/completions.
The supplied `furnace_x2_reference/rtl/*.sv` remains read-only provenance.
Verifier owns flat `tests/*` and executes the four SPEC.md commands; native
runtime owns timing/board gates and the post-acceptance product report.
No functional, synthesis, timing, physical or product-report result is implied
by the presence of these source files.
