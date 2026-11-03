# FURNACE-X1 design contract

Version: 1.0.0-soc-ai-storage. Target: Intel Arria 10 GX
10AX115N2F45E1SG, one 100 MHz clock (period at most 10 ns).
Top: `furnace_x1_top`. This document records the admitted contract and
implementation interfaces; it is not evidence of verification or timing closure.

## Compatibility and packaging

The unavailable Bellows-L, Rivet-A and Anvil-Q implementations do not establish
binary compatibility. Compatibility here means standard LZ4 frames, AES-128/GCM,
and the numerical and software ABI below. Software encrypts plaintext weights
with AES-GCM, then LZ4-frames the ciphertext. Hardware decompresses, authenticates
and decrypts, publishes authenticated plaintext, and computes the tensor result.
Nonce uniqueness is software's responsibility; there is no replay protection.

Design sources are `rtl/*.sv`. Independent verification sources belong in
`tests/*`, including `tests/verify.py`. Generated evidence is not a design input.
The independently approved product PDF is produced by the shared runtime after
engineering acceptance, not required to run engineering checks.

## Cycle & Degenerate-Boundary Table

| Condition | Required behavior |
| --- | --- |
| Request handshake | Pre-edge valid and ready sample the whole request; post-edge state advances exactly once. |
| Newly asserted response | A post-edge valid cannot be consumed retroactively at that edge. |
| Backpressure | Valid, data, last, error and completion metadata remain stable until accepted. |
| Active reset | Active-low asynchronous reset wins over all handshakes; all outward control, ready, valid, IRQ and payload outputs are zero. |
| Reset release | Outputs stay disabled until a rising edge after release; connected AXI endpoints must reset together. |
| Empty FIFO plus enqueue | No same-edge dequeue of the unregistered newly enqueued request. |
| Full FIFO plus retire | Admission uses advertised pre-edge capacity, not speculative retirement. |
| Depth one | Physical slot remains zero; counters still advance monotonically. |
| Non-power-of-two depth | Explicit equality and wrap, never binary masking or modulo. |
| Singleton byte/vector | First and last can coincide; no extra acceptance or premature result retirement. |
| Simultaneous CSR read/write | Read observes pre-write register state. |
| IRQ set and W1C | Hardware set wins. |
| Error with stalled LZ4 output | Preserve and drain that beat, produce no new beats, then publish error. |
| Reset in flight | Cancel all ownership, lengths, valid bits and work; RAM need not be physically cleared. |

No RTL division or modulo operators are permitted, including constant divisors.
Sequential processes use nonblocking assignments exclusively. RAM read/write
processes have no asynchronous reset; ownership and valid state do.

## Fixed parameters and stream conventions

Top parameters are `MAX_TILE_BYTES=4096` (legal 1..65536) and `RING_DEPTH=8`
(legal 1..16). Lane count is eight, history is 65536 bytes, addresses are 32
bits, AXI data 128 bits and AXI-Lite data 32 bits. Illegal values must reach
an explicit `PARAMETER ERROR` startup diagnostic without an earlier malformed
declaration. Small legal tile configurations may reject non-fitting descriptors.

Byte streams have `s_valid,s_ready,s_data[7:0],s_last` and
`m_valid,m_ready,m_data[7:0],m_last`. Bytes are in increasing memory-address order.
Block control has `start_valid,start_ready,done_valid,done_ready,error[7:0]`.
Only error zero means success.

### Frozen leaf and auxiliary interfaces

All modules have `clk,rst_n`. Unless indicated otherwise, ports are unsigned.

* `furnace_lz4_frontend`: parameter `MAX_DECODED_BYTES=65536`, legal
  1..131072. Inputs `start_valid,start_frame_bytes[31:0],
  start_decoded_bytes[31:0],s_valid,s_data[7:0],s_last,m_ready,done_ready`;
  outputs `start_ready,s_ready,m_valid,m_data[7:0],m_last,done_valid,error[7:0]`.
  The top explicitly instantiates `MAX_DECODED_BYTES=MAX_TILE_BYTES`.
* `furnace_xxh32`: streaming, seed-zero hash helper. Inputs
  `cancel,start_valid,s_valid,s_data[7:0],finish_valid,done_ready`; outputs
  `start_ready,s_ready,finish_ready,done_valid,digest[31:0]`.
  Synchronous cancel discards the context and dominates other requests.
  Start creates a new context; finish is separate from the byte stream and
  is accepted only after the final byte. Done holds the digest until retired.
* `furnace_aes128_block`: inputs `cancel,key_valid,key[127:0],s_valid,
  s_data[127:0],m_ready`; outputs `key_ready,keys_ready,s_ready,
  m_valid,m_data[127:0]`. A key handshake invalidates old expanded keys and
  starts expansion; key changes are accepted only with no in-flight block.
  Synchronous cancel invalidates keys and all pending block ownership.
* `furnace_aes128_gcm`: parameter `MAX_TILE_BYTES=4096`; inputs
  `start_valid,key[127:0],nonce[95:0],tag[127:0],aad[415:0],
  data_bytes[31:0],s_valid,s_data[7:0],s_last,m_ready,done_ready,
  frame_done_valid,frame_error[7:0]`; outputs `start_ready,s_ready,
  m_valid,m_data[7:0],m_last,done_valid,error[7:0],frame_done_ready`.
  `frame_done_*` is the necessary integrated frame-validation fence, not a
  benchmark port. It retires one LZ4 completion. Ciphertext stream last alone
  does not authorize publication. A nonzero frame error cancels publication
  and is propagated unchanged; frame error wins over authentication failure.
* `furnace_ghash_mul`: inputs `cancel,start_valid,x[127:0],h[127:0],
  done_ready`; outputs `start_ready,done_valid,product[127:0]`.
  Synchronous cancel discards any pending multiplication.
* `furnace_tensor8`: inputs `vector_valid,mode[1:0],first,last,
  weight_data[127:0],activation_data[127:0],result_ready`;
  outputs `vector_ready,result_valid,result[63:0],error[7:0]`.
* `furnace_fp32_mul4`: inputs `ce,a[31:0],b[31:0]`; output `result[31:0]`.
  Four enabled rising edges perform product/classification, leading-position
  detection, normalization/gradual-underflow shift, and RNE respectively.
* `furnace_fp32_add5`: inputs `ce,a[31:0],b[31:0]`; output `result[31:0]`.
  Five enabled edges perform classification/order, sticky alignment,
  add/subtract, normalization, and RNE. Parameter `OUTPUT_REGISTER=1`;
  setting it to zero leaves the rounding output combinational so the enclosing
  accumulator's architectural register supplies the fifth edge.
* `furnace_fp32_round`: combinational internal rounding helper; inputs
  `sign,significand[26:0],exponent` (signed 12-bit), `special,
  special_value[31:0]`; output `result[31:0]`. The significand is normalized
  or already shifted for gradual underflow and carries guard/round/sticky bits.
* `furnace_command_ring`: parameter `RING_DEPTH=8`; inputs
  `tail_valid,tail_value[31:0],retire`; outputs `tail_ready,tail_error,
  head[31:0],tail[31:0],head_slot[3:0],queued,full`.
  `tail_error` is the combinational doorbell validation result, sampled only
  on a tail handshake. `retire` pulses once after terminal completion/fault.
* `furnace_csr`: parameter `RING_DEPTH=8`; the complete top AXI-Lite group
  with identical signal names; inputs `busy,queued,ring_full,head[31:0],
  tail[31:0],tail_error,completion_valid,completion_error[7:0],
  completion_tile_id[31:0],completion_irq_requested`; outputs `enable,key_valid,key[127:0],
  ring_base[31:0],tail_valid,tail_value[31:0],irq`.
* `furnace_axi4_xbar`: `s_axi_*` packed initiator arrays, first dimension
  `[3:0]`, two-bit local IDs; `m_axi_*` target arrays with four-bit IDs.
  Complete AXI4 channels and attributes match the top master group.
  No USER signals. No extra concurrency-observation ports.
* `furnace_dma128`: independent byte-stream read and write DMA. Inputs
  `rd_valid,rd_addr[31:0],rd_bytes[31:0],m_ready,rd_done_ready,
  wr_valid,wr_addr[31:0],wr_bytes[31:0],s_valid,s_data[7:0],s_last,
  wr_done_ready`; outputs `rd_ready,m_valid,m_data[7:0],m_last,
  rd_done,rd_error[7:0],wr_ready,s_ready,wr_done,wr_error[7:0]`.
  The scalar complete `m_axi_*` master group uses two-bit local IDs.
  Single-beat INCR transfers deliberately trade throughput for simple bounded
  ownership; zero-byte helper requests complete without bus traffic.

## LZ4

Magic bytes are `04 22 4d 18`; FLG version is 01, BD is exactly 0x40.
Support independent/linked blocks, optional content size, block checksum and
content checksum, all with standard seed-zero XXH32. Reject dictionary IDs,
reserved bits, unsupported BD, skippable/concatenated frames, trailing bytes,
bad checksums, malformed terminal sequences and truncated declared input.
Compressed and raw blocks are bounded to 65536 encoded and decoded bytes.
Tokens support repeated 255 length extensions, offsets 1..65535, minimum
match length four and overlapping copies. Independent blocks invalidate
previous history. The final compressed sequence contains literals only; after
a match its final literal run has at least five bytes and the last match
starts at least twelve decoded bytes before block end.

Starts accept frame length 1..`2*MAX_DECODED_BYTES+256` and decoded length
0..`MAX_DECODED_BYTES`. Invalid starts complete with error 2 without input or
output. Lengths are latched at the handshake. Every accepted input has last
iff it is the declared final byte. An input source that stops without a declared
termination has no fabricated timeout. Exact decoded size is mandatory. The
final output byte alone carries last; empty output has no output transfer.
Decoded output is provisional until successful completion, including checksum
validation. Terminal errors stop new input immediately and drain any existing
stalled output before completion. Error 2 is format/checksum/length; error 3
is zero or unavailable offset. Reset/new frame cannot expose stale history.

The standalone 131072-byte extension uses the identical decoder and fixed
65536-byte history, not a full-frame RAM or larger integrated tile. Independent
verification must observe the admitted B1/B2/B3 linked frames (decoded lengths
65556/65557/65578), exact 131072-byte output, empty/singleton output, declared
overrun, backpressure, reset, invalid parameters and smaller-instance rejection.
Extended leaf successes never count as successful integrated tiles.

## AES and GCM

AES is AES-128 with ten rounds and full key expansion. Numeric key, nonce and
tag ports use most-significant-byte-first cryptographic notation. AAD byte i
is `aad[8*i+:8]`; ciphertext/plaintext streams retain memory byte order.
Nonce is 96 bits; `J0=nonce || 32'h00000001`, first payload counter is two.
GHASH uses the standard polynomial x^128+x^7+x^2+x+1, fixed 52-byte AAD
padded separately from ciphertext, and the big-endian 64-bit bit lengths.
Final partial blocks are zero-padded only for authentication, not publication.
All 128 tag bits are compared. There is no truncated-tag mode.

AES leaf no-stall edges: E0 input register; E1 AddRoundKey; E2/E3 through
E18/E19 nine SubBytes+ShiftRows / MixColumns+AddRoundKey pairs; E20 final
SubBytes+ShiftRows; E21 final AddRoundKey and valid. Earliest retirement E22.
Output backpressure freezes the complete pipeline. Key expansion is a bounded
40-cycle four-microstep-per-round sequence after key acceptance; readiness
asserts after the fortieth edge. GHASH is 128 registered single-bit recurrence
steps after acceptance, with valid after the 128th edge and retirement no earlier
than the next edge.

Quarantine capacity is MAX_TILE_BYTES. No plaintext is released until exact
ciphertext length, successful full-frame fence and tag success. A frame failure
can arrive after provisional ciphertext and must still forbid publication.
Authentication mismatch is error 4. A later short success cannot reveal stale
bytes from earlier longer or failing requests.

## Tensor numerical ABI

Mode 0: signed two's-complement W4 (-8..7) times signed A16
(-32768..32767), exact signed 20-bit products, balanced 21/22/23-bit reduction,
signed 64-bit wrapping accumulator. Modes 1 and 2: BF16 weights times BF16
activations, and signed W4 times BF16 activations respectively. Mode 3 is illegal.
Lane i activation is `[16*i+:16]`; BF16 weight uses the same position; W4
uses `[4*i+:4]` with upper weight bits zero.

BF16 and W4 convert exactly to binary32. Every product, every node of
`((p0+p1)+(p2+p3))+((p4+p5)+(p6+p7))`, and each vector's accumulator
addition rounds binary32 nearest ties-to-even. Support gradual underflow,
normal/subnormal values, signed zeros, infinities and overflow; any NaN or
invalid operation becomes canonical 0x7fc00000. Exact cancellation gives +0;
same-sign zero addition retains sign; zero multiplication uses XOR signs.
The FP result is low32 with high32 zero. No tolerance or reassociation.

E0 accepts; E1..E4 multiply; E5..E9 pair sums; E10..E14 second level;
E15..E19 final sum; E20..E24 accumulator add. Integer mode is delayed to the
same schedule. Only one vector can be pending until accumulator commit.
First initializes the accumulator; only last publishes a result, post-E24,
held through retirement (earliest E25). No next tile before retirement.

## AXI, software ABI and execution

Top exposes the admitted complete `s_axil_*` AXI4-Lite group with 16-bit
addresses and the complete `m_axi_*` four-target AXI4 group: 32-bit address,
128-bit data, four-bit ID, eight-bit LEN, SIZE, BURST, LOCK, CACHE, PROT,
QOS and REGION, no USER. Target select is address[31:30], forwarded unchanged.
Internal initiators are compressed DMA (0), authenticated writeback (1),
tensor DMA (2), and descriptor/completion DMA (3). Target ID is
`{initiator[1:0],local_id[1:0]}`. Read/write arbitration is independent per
target, round robin after complete response. One transaction per direction
per target and initiator; hold write ownership from AW through B and read
ownership through RLAST. W follows accepted AW, never interleaves, and need
not arrive with AW. Four continuously eligible contenders receive grants
within four completed arbitration turns.

Legal headers: 16-byte aligned, SIZE=4, INCR, 1..16 beats, no 4-KiB or
target-region crossing. Invalid reads return the requested number of DECERR
beats; invalid writes drain without forwarding and then DECERR. DMA emits only
legal headers. Partial writes use exact byte strobes; rounded read allocations
must cover the final 16-byte beat. Result/completion writes are one beat.
Propagate downstream faults, with no assumption of fixed readiness/latency.

AXI-Lite decouples AW/W, honors WSTRB, and can service read/write concurrently.
Unknown/unaligned accesses, RO writes, reserved nonzero bits and forbidden busy
writes fail SLVERR. All reset configuration is zero.

| Address | Register |
| --- | --- |
| 0x000 | VERSION RO = 0x01000000 |
| 0x004 | CONTROL RW enable bit0 |
| 0x008 | STATUS RO busy/key_valid/ring_full/fault bits0..3 |
| 0x00c | IRQ_STATUS W1C success/failure bits0..1 |
| 0x010 | IRQ_ENABLE RW bits0..1 |
| 0x014 | LAST_ERROR RO |
| 0x018 | RING_BASE RW, 128-byte aligned |
| 0x01c | RING_DEPTH RO |
| 0x020 | HEAD RO |
| 0x024 | TAIL RW doorbell |
| 0x028 | LAST_TILE_ID RO |
| 0x02c | COMPLETED_COUNT RO, wraps 32 bits |
| 0x030..0x03c | KEY words WO, reads zero |
| 0x040 | KEY_COMMIT WO bit0 commit / bit1 invalidate, mutually exclusive |

Key words are little-endian memory words containing key bytes in address order,
converted explicitly to the AES numeric key. Commit requires all four words
written since reset/invalidate/previous commit; byte strobes track all sixteen
fresh bytes, so partial writes cannot commit stale key bytes. Key, base and commit changes
are forbidden while busy or queued. Enable clear stops new fetches but drains
current work. IRQ is the OR of enabled sticky completion bits, hardware set
winning over W1C. A requested successful completion sets the success sticky bit;
every failed completion sets the failure bit and reset-sticky fault, including
untrusted descriptor-fetch and terminal completion bus faults. Descriptor flag
bit8 requests the normal success interrupt; failure notification is not suppressed.

HEAD/TAIL are monotonic 32-bit counters; doorbells may advance only by currently
free slots and less than 2^31. Physical slot wraps explicitly for every depth.
HEAD advances once after completion response or terminal completion bus fault.
Busy spans fetch through completion response. Descriptor-fetch faults must not
use an untrusted completion address. Normal tile failures permit recovery.

Each 128-byte little-endian descriptor is: opcode u32 at0 (=1), flags u32 at4
(mode bits1:0, IRQ request bit8 only), frame address/bytes at8/12, plaintext
address16, activation address20, result address24, weight bytes28, vector count32,
tile ID36, nonce bytes40..51, tag bytes52..67, completion address68, reserved
zero bytes72..127. AAD is exactly bytes0..51. All buffers are 16-byte aligned,
mutually nonoverlapping with this live descriptor, and checked for overflow
before writes. Frame length <=2*MAX_TILE_BYTES+256; weight length
1..MAX_TILE_BYTES; vector count>=1; W4 weight length=4*vectors, BF16
weight length=16*vectors; activations allocate16*vectors. Check products in
wide arithmetic before truncation.

Success publishes plaintext, then one result beat containing result64,
tile_id32,status32=0. Completion contains status32,tile_id32,
authenticated_bytes32,reserved32=0. Status: 0 success, 1 configuration,
2 LZ4 format/length/checksum, 3 history/offset, 4 tag, 5 AXI, 6 numerical
protocol. Failure forbids result writes; unauthenticated failures also forbid
plaintext writes. Authenticated bytes is zero unless authentication succeeded.
External writes already accepted cannot be rolled back on a later bus fault.
No failed-tile accumulator state survives into the next tile.

## Independent acceptance and reproduction

From the delivered root, using declared installed Python 3, Icarus, Verilator,
make, a C++ compiler and Yosys:

```
python3 tests/verify.py --suite behavior
python3 tests/verify.py --suite boundaries
python3 tests/verify.py --suite defects
python3 tests/verify.py --suite synthesis
python3 tests/verify.py --suite portable
```

These Verifier-owned entrypoints must be self-contained. The admitted coverage
matrix, bit-exact reference comparisons, six executed functional mutants, fresh
portable copy, retained failures, and zero-latch/black-box/div/mod structural
checks remain mandatory. No source-list or output selector includes runtime
metadata. L1 does not substitute for the shared runtime's timing lint, actual
Quartus 17.1 STA (WNS>=0, no unconstrained functional clock paths, target fit),
or three consecutive deterministic physical PCIe Gen3x8 HIL passes. No tool
version, simulation result, timing result or board result has yet been measured
by this document.
