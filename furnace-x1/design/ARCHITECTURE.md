# FURNACE-X1 architecture

This is the design intent for the admitted SoC, not a passing baseline.

## Dataflow and ownership

One descriptor executor consumes a hardware ring in FIFO order. Four real AXI
initiators connect through a 4x4 crossbar: compressed-frame reads, authenticated
plaintext writes, tensor reads/result writes, and descriptor/completion traffic.
Each target independently arbitrates reads and writes. The executor serializes
tile lifetimes, not the crossbar's independent requester/target protocol.

The LZ4 frontend has a fixed 64-KiB circular history and a single elastic byte
output. Total decoded length is separate from the circular address and
block-local history validity. This permits 131072-byte standalone frames without
increasing integrated quarantine. A registered history read followed by a
separate byte-publication state makes overlap copies observe newly written data.
Independent blocks discard history ownership without clearing RAM.

Three seed-zero XXH32 helpers own header, current encoded block and decoded
content contexts. Hash input acceptance fences parser advancement. Sixteen-byte
stripe arithmetic and final avalanche have registered multiplication boundaries;
there is no combinational full-message hash.

AES expands and commits a key before accepting a block. Twenty-one registered
block stages after the input register split each nonfinal round at
SubBytes/ShiftRows and MixColumns/AddRoundKey. A bounded 128-step GHASH
multiplier authenticates the fixed 52-byte AAD and ciphertext independently
padded. CTR plaintext goes into private synchronous RAM. Publication requires
both the complete tag comparison and the LZ4 completion fence; a provisional
LZ4 last beat is never authentication. RAM ownership/length state, not RAM reset,
prevents stale or failing bytes from escaping.

The tensor engine uses eight lanes and a fixed balanced reduction tree.
Binary32 multiplication occupies four edges and each binary32 addition five.
Accumulator recurrence admits only one uncommitted vector; no hidden recurrence
bypass or one-vector-per-cycle claim. Integer results traverse the same public
24-edge post-accept schedule. The full numerical contract is in SPEC.md.

## Capacity and traffic

For V vectors and W decoded weight bytes, activation traffic is 16*V bytes.
W is 4*V in W4 modes and 16*V in BF16 mode. In addition to frame and descriptor
reads, a successful tile writes W plaintext bytes, rereads W weights, reads
16*V activations, writes a 16-byte result and a 16-byte completion. Rounded DMA
read allocations cover trailing beat bytes; write strobes do not modify guards.
This is traffic accounting, not measured bandwidth. Eight lanes at 100 MHz
would be 800 million lane multiplies per second only with no dependency or
memory bubbles; the specified serialized accumulator recurrence deliberately
does not attain that peak.

History consumes 65536 bytes regardless of leaf frame bound. Quarantine consumes
MAX_TILE_BYTES, not the standalone decoder's larger bound. Key expansion and
GHASH state are registers. Memory inference, target resource fit and physical
timing require independent implementation evidence.

## Dependencies and failure containment

| Consumer assumption | Producer guarantee |
| --- | --- |
| DMA can pause byte delivery | All byte streams hold valid/data/last under stalls. |
| Crypto can quarantine provisional ciphertext | LZ4 emits exactly one terminal completion with error status. |
| Plaintext is safe to write | Crypto publishes only after tag and frame success. |
| Tensor reads initialized data | Executor waits for accepted authenticated write responses. |
| Ring can make progress after faults | Executor retires a terminal completion fault without retry deadlock. |
| RAM contents need not reset | Reset clears all ownership and external-valid state. |
| AXI responses route correctly | Crossbar holds target ownership and encodes initiator into ID. |

Descriptor validation precedes data-buffer writes, using widened range arithmetic
and pairwise overlap checks. Untrusted fetch data cannot supply a completion
address. Downstream write errors are reported but do not claim rollback.
Authentication failure never permits a plaintext or result write. Every later
tile starts independent decoder, cryptographic and accumulator ownership.

## Implementation status

Source completion and independent verification are separate handoffs. Partial
source work must not be presented as a complete SoC or as acceptance of any
simulation, synthesis, timing or physical-hardware requirement. The runtime
retains those decisions and the final product-report ownership.
