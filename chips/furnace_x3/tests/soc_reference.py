"""Architectural firmware/device reference with mathematical engine effects.

Device completion dates are independent abstract instruction ticks, not RTL
pipeline schedules. Commands snapshot operands, create future obligations and
commit data before posting completion tokens. DDR is a byte-addressed oracle.
"""

import heapq
import struct

from crypto_reference import FrameError, gcm_decrypt, lz4_decode
from numerical_reference import audio_features, tensor_vector, vision_features
from rv64_reference import BusFault


class SoC:
    def __init__(self, image, memory, geometry, ring_depth, fusion_depth,
                 mailbox_depth, max_dma_bytes):
        self.imem = image.ljust(16384, b"\0")
        self.dmem = bytearray(16384)
        self.ddr = bytearray(memory)
        self.geometry = geometry
        self.ring_depth, self.fusion_depth = ring_depth, fusion_depth
        self.mailbox_depth, self.max_dma_bytes = mailbox_depth, max_dma_bytes
        self.time = self.sequence = 0
        self.events = []
        self.semaphores = [0] * 16
        self.mailboxes = [[] for _ in range(4)]
        self.pending = self.mask = self.parent_irq = 0
        self.irq_enable = 0
        self.irq_ack = 0
        self.errors = 0
        self.overflow = False
        self.run = True
        self.registers = {4: 0, 0x18: 0, 0x20: 0, 0x24: 0, 0x2c: 0, 0x14: 0,
                          0x28: 0, 0x1004: 0, 0x1010: 0, 0x1014: 0, 0x1018: 0,
                          0x1020: 0, 0x1024: 0, 0x1028: 0, 0x1030: 0xf4c8f,
                          0x2040: 0, 0x2044: 0, 0x2048: 0}
        self.key_shadow = bytearray(16)
        self.key = None
        self.mm_weights = None
        self.legacy_busy = self.dma_busy = False
        self.dma_done = self.dma_error = 0
        self.vision_meta = self.audio_meta = 0
        self.vision_samples, self.audio_samples = [], []
        self.vision_packets, self.audio_packets = [], []
        self.vision_count = self.audio_count = self.frame_count = 0
        self.dma_completions = self.descriptor_completions = self.frame_completions = 0
        self.last_trap = (0, 0)

    def schedule(self, delay, function):
        self.sequence += 1
        heapq.heappush(self.events, (self.time + delay, self.sequence, function))

    def post(self, index):
        if self.semaphores[index] == 65535:
            self.overflow = True
            self.errors |= 2
        else:
            self.semaphores[index] += 1

    def sources(self):
        levels = (int(bool(self.parent_irq & self.irq_enable)) |
                  (8 if self.errors & 1 else 0) | (256 if self.overflow else 0))
        for index, queue in enumerate(self.mailboxes):
            if queue:
                levels |= 1 << (4 + index)
        return levels

    def tick(self):
        self.time += 1
        while self.events and self.events[0][0] <= self.time:
            _, _, callback = heapq.heappop(self.events)
            callback()
        self.pending |= self.sources()

    def external_irq(self):
        return bool(self.pending & self.mask)

    def trap_event(self):
        self.pending |= 1 << 9

    def region(self, address, size, instruction=False):
        if 0x10000 <= address and address + size <= 0x14000:
            return self.imem, address - 0x10000
        if instruction:
            raise BusFault("instruction access")
        if 0x20000 <= address and address + size <= 0x24000:
            return self.dmem, address - 0x20000
        if 0x80000000 <= address and address + size <= 0x80000000 + len(self.ddr):
            return self.ddr, address - 0x80000000
        raise BusFault(f"unmapped address {address:#x}/{size}")

    def read(self, address, size, instruction=False):
        if not instruction and address < 0x3000:
            if size != 4 or address & 3:
                raise BusFault("MMIO access shape")
            return self.mmio_read(address)
        memory, offset = self.region(address, size, instruction)
        return int.from_bytes(memory[offset:offset + size], "little")

    def write(self, address, size, value):
        if address < 0x3000:
            if size != 4 or address & 3:
                raise BusFault("MMIO access shape")
            self.mmio_write(address, value)
            return
        memory, offset = self.region(address, size)
        if memory is self.imem:
            raise BusFault("IMEM is read-only for CPU")
        memory[offset:offset + size] = value.to_bytes(size, "little")

    def ddr_bytes(self, address, length):
        memory, offset = self.region(address, length)
        if memory is not self.ddr:
            raise BusFault("engine address outside DDR")
        return bytes(memory[offset:offset + length])

    def ddr_store(self, address, data):
        memory, offset = self.region(address, len(data))
        if memory is not self.ddr:
            raise BusFault("engine address outside DDR")
        memory[offset:offset + len(data)] = data

    def mmio_read(self, address):
        if address == 0:
            return 0x01000000
        if address == 8:
            return int(self.legacy_busy) | (2 if self.key is not None else 0)
        if address == 0x1c:
            return self.ring_depth
        if address == 0x1000:
            return 0x02000000
        if address == 0x1008:
            return (int(self.mm_weights is not None) |
                    (4 if self.vision_samples or self.vision_packets else 0) |
                    (8 if self.audio_samples or self.audio_packets else 0))
        if address == 0x101c:
            return self.fusion_depth
        if address == 0xc:
            return self.parent_irq
        if address == 0x10:
            return self.irq_enable
        if address == 0x2000:
            return 0x03000000
        if address == 0x2004:
            return int(self.run)
        if address == 0x2008:
            return 1 if self.run else 2
        if address == 0x2018:
            return self.errors
        if address == 0x2020:
            return 1
        if address == 0x2050:
            return int(self.dma_busy) | (self.dma_done << 1) | (self.dma_error << 8)
        if address == 0x2100:
            return self.pending
        if address == 0x2104:
            return self.mask
        if address == 0x2220:
            return 0
        if 0x2400 <= address < 0x2500:
            index, offset = divmod(address - 0x2400, 16)
            if offset == 0:
                available = self.semaphores[index] != 0
                self.semaphores[index] -= int(available)
                return int(available)
            if offset == 8:
                return self.semaphores[index]
            raise BusFault("semaphore read")
        if 0x2600 <= address < 0x2640:
            index, offset = divmod(address - 0x2600, 16)
            queue = self.mailboxes[index]
            if offset == 4:
                return len(queue) | (256 if not queue else 0) | (
                    512 if len(queue) == self.mailbox_depth else 0)
            if offset == 0 and queue:
                return queue.pop(0)
            raise BusFault("mailbox read")
        if address in self.registers:
            return self.registers[address]
        raise BusFault(f"unsupported read {address:#x}")

    def mmio_write(self, address, value):
        if address == 0x2004:
            if value & ~1:
                raise BusFault("core reset from running CPU")
            self.run = bool(value)
        elif address == 0x2018:
            self.errors &= ~value
            if value & 2:
                self.overflow = False
        elif address == 0xc:
            self.parent_irq &= ~value
        elif address == 0x10:
            self.irq_enable = value
        elif 0x30 <= address < 0x40:
            self.key_shadow[address - 0x30:address - 0x2c] = value.to_bytes(4, "little")
        elif address == 0x40:
            if value == 1:
                self.key = bytes(self.key_shadow)
                self.mm_weights = None
            elif value == 2:
                self.key = None
            else:
                raise BusFault("key command")
        elif address == 0x24:
            self.submit_descriptor(value)
        elif address == 0x204c:
            if value != 1 or self.dma_busy:
                raise BusFault("DMA command")
            self.submit_dma()
        elif address == 0x2054:
            if value & 3:
                self.dma_done = self.dma_error = 0
        elif address == 0x2104:
            self.mask = value & 65535
        elif address == 0x2108:
            self.pending = (self.pending & ~value) | self.sources()
        elif address in (0x2210, 0x2214):
            if value & ~0x1ffff:
                raise BusFault("sample metadata")
            if address == 0x2210:
                self.vision_meta = value
            else:
                self.audio_meta = value
        elif address in (0x2200, 0x2204):
            self.sample(address == 0x2204, value)
        elif 0x2400 <= address < 0x2500:
            index, offset = divmod(address - 0x2400, 16)
            if offset != 4 or value != 1 or self.semaphores[index] == 65535:
                raise BusFault("semaphore GIVE")
            self.semaphores[index] += 1
        elif 0x2600 <= address < 0x2640:
            index, offset = divmod(address - 0x2600, 16)
            if offset or len(self.mailboxes[index]) == self.mailbox_depth:
                raise BusFault("mailbox push")
            self.mailboxes[index].append(value)
        elif address in self.registers:
            self.registers[address] = value
        else:
            raise BusFault(f"unsupported write {address:#x}")

    def submit_dma(self):
        source, destination, length = (self.registers[a] for a in (0x2040, 0x2044, 0x2048))
        legal = (source >= 0x80000000 and destination >= 0x80000000 and
                 source % 64 == destination % 64 == 0 and length <= self.max_dma_bytes and
                 source + length <= 1 << 32 and destination + length <= 1 << 32 and
                 (length == 0 or source + length <= destination or destination + length <= source))
        self.dma_busy = True

        def finish():
            if legal and length:
                self.ddr_store(destination, self.ddr_bytes(source, length))
            self.dma_busy = False
            self.dma_done, self.dma_error = 1, 0 if legal else 1
            self.dma_completions += 1
            self.post(0)
            self.pending |= 2

        self.schedule(400, finish)

    def submit_descriptor(self, tail):
        old_tail = self.registers[0x24]
        if tail != (old_tail + 1) & 0xffffffff or self.legacy_busy:
            raise BusFault("parent tail publication")
        self.registers[0x24] = tail
        address = self.registers[0x18] + (old_tail % self.ring_depth) * 128
        descriptor = self.ddr_bytes(address, 128)
        self.legacy_busy = True

        def finish():
            fields = struct.unpack_from("<10I", descriptor)
            version, flags, frame_address, frame_bytes, plain_address, act_address, result_address = fields[:7]
            weight_bytes, vectors, tile_id = fields[7:]
            completion_address = struct.unpack_from("<I", descriptor, 68)[0]
            error, authenticated = 0, 0
            try:
                mode = flags & 3
                if (version != 1 or flags & ~0x303 or mode == 3 or self.key is None or
                    any(descriptor[72:]) or vectors == 0 or
                    weight_bytes != vectors * (16 if mode == 1 else 4)):
                    raise ValueError("descriptor")
                cipher = lz4_decode(self.ddr_bytes(frame_address, frame_bytes), weight_bytes)
                if len(cipher) != weight_bytes:
                    raise FrameError("decoded bytes")
                try:
                    plain = gcm_decrypt(self.key, descriptor[40:52], descriptor[:52],
                                        cipher, descriptor[52:68])
                except ValueError:
                    error = 4
                    plain = None
                if plain is not None:
                    self.ddr_store(plain_address, plain)
                    authenticated = len(plain)
                    result = 0
                    for index in range(vectors):
                        if mode == 1:
                            weights = list(struct.unpack_from("<8H", plain, 16 * index))
                        else:
                            word = int.from_bytes(plain[4 * index:4 * index + 4], "little")
                            weights = [(word >> (4 * lane)) & 15 for lane in range(8)]
                        activations = list(struct.unpack("<8H", self.ddr_bytes(act_address + 16 * index, 16)))
                        result = tensor_vector(mode, weights, activations, result)
                    self.ddr_store(result_address, struct.pack("<QII", result, tile_id, 0))
                    if flags & 512:
                        self.mm_weights = [(plain[lane // 2] >> (4 * (lane & 1))) & 15
                                           for lane in range(8)]
            except FrameError as failure:
                error = failure.code
            except ValueError:
                error = 1
            self.ddr_store(completion_address, struct.pack("<4I", error, tile_id, authenticated, 0))
            self.registers[0x20] = tail
            self.registers[0x2c] += 1
            self.registers[0x14], self.registers[0x28] = error, tile_id
            self.legacy_busy = False
            self.descriptor_completions += 1
            if flags & 256:
                self.parent_irq |= 2 if error else 1

        self.schedule(1000, finish)

    def sample(self, audio, value):
        iw, ih, ow, oh, fft_n = self.geometry
        packet = self.audio_samples if audio else self.vision_samples
        metadata = self.audio_meta if audio else self.vision_meta
        packet.append((value, metadata & 65535, bool(metadata & 65536)))
        if not metadata & 65536:
            return
        expected_length = fft_n if audio else iw * ih
        identifier = packet[0][1]
        error = 7 if (len(packet) != expected_length or
                      any(token[1] != identifier for token in packet)) else 0
        if error:
            feature = 0
        elif audio:
            samples = [v if v < 32768 else v - 65536 for v, _, _ in packet]
            feature = audio_features(samples)
        else:
            feature = vision_features([v for v, _, _ in packet], iw, ih, ow, oh)
        count = self.audio_count if audio else self.vision_count
        base = self.registers[0x1014 if audio else 0x1010]
        self.ddr_store(base + (count % self.fusion_depth) * 16,
                       struct.pack("<QI HBB", feature, 0, identifier, 0, error))
        if audio:
            self.audio_count += 1
            self.audio_packets.append((feature, identifier, error))
            self.audio_samples = []
        else:
            self.vision_count += 1
            self.vision_packets.append((feature, identifier, error))
            self.vision_samples = []
        if self.vision_packets and self.audio_packets and self.mm_weights is not None:
            vision = self.vision_packets.pop(0)
            sound = self.audio_packets.pop(0)

            def finish():
                error = 8 if vision[1] != sound[1] else vision[2] or sound[2]
                activations = [(vision[0] >> (16 * i)) & 65535 for i in range(4)] + [
                    (sound[0] >> (16 * i)) & 65535 for i in range(4)]
                result = tensor_vector(0, self.mm_weights, activations) if not error else 0
                self.ddr_store(self.registers[0x1018] + (self.frame_count % self.fusion_depth) * 16,
                               struct.pack("<QI HBB", result, 0, vision[1], 0, error))
                self.frame_count += 1
                self.registers[0x1020] += 1
                self.registers[0x1024], self.registers[0x1028] = error, vision[1]
                self.frame_completions += 1
                self.post(1)
                self.pending |= 4

            self.schedule(100, finish)
