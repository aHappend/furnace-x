# FURNACE-X3 freestanding machine-mode scheduler. All addresses are CPU addresses.
.equ PIXELS, IN_WIDTH*IN_HEIGHT
.equ E_GRAPH, 256
.equ E_CYCLE, 257
.equ E_DEPENDENCY, 258
.equ E_DEADLOCK, 259
.equ E_POST_OVERFLOW, 260
.equ E_ARGUMENT, 261
.equ E_TRAP, 262

start:
    csrrci zero, 0x300, 8
    li sp, 0x23ff0
    li s0, 0x20000
    li s1, 0x20100
    li s2, 0x21200
    li s3, 0x21800
    li s10, 0x2000
    li s11, 0x1000
    li s5, 0
    li s6, 0
    li s9, 0
    li t0, 1
    sw t0, 64(s0)
    sw zero, 68(s0)
    sd zero, 72(s0)
    sd zero, 80(s0)
    mv t0, s3
    li t1, 128
clear_work:
    sw zero, 0(t0)
    addi t0, t0, 4
    addi t1, t1, -1
    bne t1, zero, clear_work
    la t0, trap_handler
    csrrw zero, 0x305, t0
    lwu s4, 4(s0)
    beq s4, zero, manifest_error
    li t0, 64
    bltu t0, s4, manifest_error
    sub t0, t0, s4
    li s7, -1
    srl s7, s7, t0
    lwu t0, 0(s0)
    li t1, 0x80000000
    bltu t0, t1, manifest_error
    andi t1, t0, 63
    bne t1, zero, manifest_error
    slli t1, s4, 6
    add t1, t0, t1
    li t2, 0x100000000
    bltu t2, t1, manifest_error
    mv t2, s1
    slli t3, s4, 3
copy_graph:
    ld t4, 0(t0)
    sd t4, 0(t2)
    addi t0, t0, 8
    addi t2, t2, 8
    addi t3, t3, -1
    bne t3, zero, copy_graph
    li s8, 0
check_status_addresses:
    slli t0, s8, 6
    add t0, s1, t0
    lwu t1, 48(t0)
    li t2, 0x80000000
    bltu t1, t2, manifest_error
    andi t2, t1, 15
    bne t2, zero, manifest_error
    addi s8, s8, 1
    bltu s8, s4, check_status_addresses
    li s8, 0
initialize_statuses:
    mv a0, s8
    li a1, 0
    li a2, 0
    call commit_status
    addi s8, s8, 1
    bltu s8, s4, initialize_statuses
    li s8, 0
validate_nodes:
    slli t0, s8, 6
    add t0, s1, t0
    lwu t1, 0(t0)
    beq t1, zero, graph_error
    li t2, 4
    bltu t2, t1, graph_error
    ld t2, 8(t0)
    xori t3, s7, -1
    and t2, t2, t3
    bne t2, zero, graph_error
    lwu t2, 52(t0)
    lwu t3, 56(t0)
    or t2, t2, t3
    lwu t3, 60(t0)
    or t2, t2, t3
    bne t2, zero, graph_error
    lwu t2, 40(t0)
    li t3, 0xffffffff
    beq t2, t3, validate_post
    li t3, 2
    bltu t2, t3, graph_error
    li t3, 15
    bltu t3, t2, graph_error
validate_post:
    lwu t2, 44(t0)
    li t3, 0xffffffff
    beq t2, t3, validate_arguments
    li t3, 2
    bltu t2, t3, graph_error
    li t3, 15
    bltu t3, t2, graph_error
validate_arguments:
    lwu t2, 28(t0)
    lwu t3, 32(t0)
    or t2, t2, t3
    lwu t3, 36(t0)
    or t2, t2, t3
    bne t2, zero, graph_error
    li t2, 2
    beq t1, t2, validate_descriptor_arguments
    li t2, 4
    bne t1, t2, validate_next
    lwu t2, 16(t0)
    bne t2, zero, graph_error
validate_descriptor_arguments:
    lwu t2, 20(t0)
    lwu t3, 24(t0)
    or t2, t2, t3
    bne t2, zero, graph_error
validate_next:
    addi s8, s8, 1
    bltu s8, s4, validate_nodes

# Independent graph-index dependency closure, before launching any device.
    li t0, 0
dependency_pass:
    mv t1, t0
    li t2, 0
dependency_scan:
    slli t3, t2, 6
    add t3, s1, t3
    ld t3, 8(t3)
    xori t4, t0, -1
    and t3, t3, t4
    bne t3, zero, dependency_next
    li t3, 1
    sll t3, t3, t2
    or t0, t0, t3
dependency_next:
    addi t2, t2, 1
    bltu t2, s4, dependency_scan
    beq t0, s7, configure_devices
    bne t0, t1, dependency_pass
    li a2, E_CYCLE
    j reject_graph
graph_error:
    li a2, E_GRAPH
reject_graph:
    sw a2, 40(s3)
    li s8, 0
reject_next:
    mv a0, s8
    li a1, 3
    lwu a2, 40(s3)
    call commit_status
    addi s8, s8, 1
    bltu s8, s4, reject_next
    j finish_graph
manifest_error:
    li a2, E_GRAPH
    sw a2, 68(s0)
    li t0, 3
    sw t0, 64(s0)
    li a0, 0x5843ff00
    or a0, a0, a2
    j notify_and_halt

configure_devices:
    sw zero, 4(s11)
    lwu t0, 8(s0)
    li t1, 0x80000000
    bltu t0, t1, graph_error
    andi t1, t0, 127
    bne t1, zero, graph_error
    lwu t1, 28(zero)
    sw t1, 28(s3)
    slli t2, t1, 7
    add t2, t0, t2
    li t3, 0x100000000
    bltu t3, t2, graph_error
    sw t0, 24(zero)
    lwu t0, 36(zero)
    sw t0, 24(s3)
    lwu t0, 24(s0)
    sw t0, 48(zero)
    lwu t0, 28(s0)
    sw t0, 52(zero)
    lwu t0, 32(s0)
    sw t0, 56(zero)
    lwu t0, 36(s0)
    sw t0, 60(zero)
    li t0, 1
    sw t0, 64(zero)
    lwu t0, 12(s0)
    sw t0, 16(s11)
    lwu t0, 16(s0)
    sw t0, 20(s11)
    lwu t0, 20(s0)
    sw t0, 24(s11)
    li t0, 3
    sw t0, 4(s11)
    sw t0, 12(zero)
    sw t0, 16(zero)
    li t0, 1
    sw t0, 4(zero)
    li t0, 7
    sw t0, 0x108(s10)
    li t0, 6
    sw t0, 0x104(s10)
    li t0, 0x800
    csrrw zero, 0x304, t0
    csrrsi zero, 0x300, 8

schedule:
    sw zero, 36(s3)
    call service_dma
    call service_descriptor
    call service_frame
    beq s6, s7, finish_graph
    li s8, 0
scan_node:
    slli t0, s8, 4
    add t0, s2, t0
    lwu t0, 0(t0)
    bne t0, zero, scan_next
    slli t0, s8, 6
    add t0, s1, t0
    ld t1, 8(t0)
    xor t2, s6, s5
    and t2, t2, t1
    bne t2, zero, dependency_failed
    xori t2, s5, -1
    and t1, t1, t2
    bne t1, zero, scan_next
    lwu t1, 0(t0)
    li t2, 1
    beq t1, t2, can_launch_dma
    li t2, 2
    beq t1, t2, can_launch_descriptor
    li t2, 3
    beq t1, t2, can_launch_frame
    mv a0, s8
    call take_wait_token
    beq a0, zero, scan_next
    mv a0, s8
    li a1, 2
    li a2, 0
    call commit_status
    j scan_next
dependency_failed:
    mv a0, s8
    li a1, 4
    li a2, E_DEPENDENCY
    call commit_status
    j scan_next
can_launch_dma:
    lwu t1, 0(s3)
    bne t1, zero, scan_next
    mv a0, s8
    call take_wait_token
    beq a0, zero, scan_next
    call launch_dma
    j scan_next
can_launch_descriptor:
    lwu t1, 4(s3)
    bne t1, zero, scan_next
    mv a0, s8
    call take_wait_token
    beq a0, zero, scan_next
    call launch_descriptor
    j scan_next
can_launch_frame:
    lwu t1, 8(s3)
    bne t1, zero, scan_next
    mv a0, s8
    call take_wait_token
    beq a0, zero, scan_next
    call launch_frame
scan_next:
    addi s8, s8, 1
    bltu s8, s4, scan_node
    call feed_frame
    beq s6, s7, finish_graph
    lwu t0, 4(s3)
    bne t0, zero, schedule
    lwu t0, 8(s3)
    beq t0, zero, check_idle
    lwu t1, 12(s3)
    li t2, PIXELS
    bltu t1, t2, schedule
    lwu t1, 16(s3)
    li t2, FFT_N
    bltu t1, t2, schedule
check_idle:
    lwu t1, 0(s3)
    or t0, t0, t1
    bne t0, zero, wait_for_device
    lwu t0, 36(s3)
    bne t0, zero, schedule
    li a2, E_DEADLOCK
    sw a2, 40(s3)
    li s8, 0
deadlock_next:
    slli t0, s8, 4
    add t0, s2, t0
    lwu t0, 0(t0)
    bne t0, zero, deadlock_skip
    mv a0, s8
    li a1, 3
    lwu a2, 40(s3)
    call commit_status
deadlock_skip:
    addi s8, s8, 1
    bltu s8, s4, deadlock_next
    j schedule
wait_for_device:
# Mask global delivery across the final condition check and WFI, not MEIE.
    csrrci zero, 0x300, 8
    lwu t0, 0x100(s10)
    andi t0, t0, 7
    bne t0, zero, resume_devices
    lwu t0, 0x408(s10)
    lwu t1, 0x418(s10)
    or t0, t0, t1
    bne t0, zero, resume_devices
    wfi
resume_devices:
    csrrsi zero, 0x300, 8
    j schedule

# a0=index; a1=state; a2=error. Preserve all s-registers except completion masks.
commit_status:
    slli t0, a0, 6
    add t0, s1, t0
    li t1, 2
    bne a1, t1, commit_local
    lwu t1, 44(t0)
    li t2, 0xffffffff
    beq t1, t2, commit_local
    slli t1, t1, 4
    add t1, s10, t1
    lwu t2, 0x408(t1)
    li t3, 65535
    beq t2, t3, post_overflow
    li t2, 1
    sw t2, 0x404(t1)
    j commit_local
post_overflow:
    li a1, 3
    li a2, E_POST_OVERFLOW
commit_local:
    slli t1, a0, 4
    add t1, s2, t1
    sw a1, 0(t1)
    sw a2, 4(t1)
    lwu t1, 48(t0)
    lwu t2, 4(t0)
    sw a2, 4(t1)
    sw t2, 8(t1)
    sw zero, 12(t1)
    fence
    sw a1, 0(t1)
    fence
    li t1, 1
    sw t1, 36(s3)
    li t1, 2
    bltu a1, t1, commit_return
    li t1, 1
    sll t1, t1, a0
    or s6, s6, t1
    li t2, 2
    bne a1, t2, commit_failed
    or s5, s5, t1
    ret
commit_failed:
    li s9, 1
commit_return:
    ret

take_wait_token:
    slli t0, a0, 6
    add t0, s1, t0
    lwu t0, 40(t0)
    li t1, 0xffffffff
    beq t0, t1, wait_token_none
    slli t0, t0, 4
    add t0, s10, t0
    lwu a0, 0x400(t0)
    ret
wait_token_none:
    li a0, 1
    ret

launch_dma:
    addi sp, sp, -16
    sd ra, 0(sp)
    mv a0, s8
    li a1, 1
    li a2, 0
    call commit_status
    addi t0, s8, 1
    sw t0, 0(s3)
    slli t0, s8, 6
    add t0, s1, t0
    lwu t1, 16(t0)
    sw t1, 0x40(s10)
    lwu t1, 20(t0)
    sw t1, 0x44(s10)
    lwu t1, 24(t0)
    sw t1, 0x48(s10)
    li t1, 3
    sw t1, 0x54(s10)
    li t1, 1
    sw t1, 0x4c(s10)
    ld ra, 0(sp)
    addi sp, sp, 16
    ret
service_dma:
    addi sp, sp, -16
    sd ra, 0(sp)
    lwu t0, 0(s3)
    beq t0, zero, service_dma_return
    lwu t1, 0x400(s10)
    beq t1, zero, service_dma_return
    addi a0, t0, -1
    sw zero, 0(s3)
    lwu a2, 0x50(s10)
    srli a2, a2, 8
    andi a2, a2, 255
    li a1, 2
    beq a2, zero, service_dma_commit
    li a1, 3
service_dma_commit:
    call commit_status
    li t0, 3
    sw t0, 0x54(s10)
service_dma_return:
    ld ra, 0(sp)
    addi sp, sp, 16
    ret

launch_descriptor:
    addi sp, sp, -16
    sd ra, 0(sp)
    slli t0, s8, 6
    add t0, s1, t0
    lwu t1, 16(t0)
    li t2, 0x80000000
    bltu t1, t2, descriptor_argument_error
    andi t2, t1, 7
    bne t2, zero, descriptor_argument_error
    addi t2, t1, 128
    li t3, 0x100000000
    bltu t3, t2, descriptor_argument_error
    mv a0, s8
    li a1, 1
    li a2, 0
    call commit_status
    lwu t0, 44(zero)
    sw t0, 44(s3)
    lwu t0, 24(s3)
    lwu t1, 28(s3)
    remu t2, t0, t1
    slli t2, t2, 7
    lwu t1, 8(s0)
    add t2, t2, t1
    slli t1, s8, 6
    add t1, s1, t1
    lwu t1, 16(t1)
    li t3, 16
copy_descriptor:
    ld t4, 0(t1)
    sd t4, 0(t2)
    addi t1, t1, 8
    addi t2, t2, 8
    addi t3, t3, -1
    bne t3, zero, copy_descriptor
    fence
    addiw t0, t0, 1
    sw t0, 24(s3)
    sw t0, 36(zero)
    addi t0, s8, 1
    sw t0, 4(s3)
    j launch_descriptor_return
descriptor_argument_error:
    mv a0, s8
    li a1, 3
    li a2, E_ARGUMENT
    call commit_status
launch_descriptor_return:
    ld ra, 0(sp)
    addi sp, sp, 16
    ret
service_descriptor:
    addi sp, sp, -16
    sd ra, 0(sp)
    lwu t0, 4(s3)
    beq t0, zero, service_descriptor_return
    lwu t1, 44(zero)
    lwu t2, 44(s3)
    beq t1, t2, service_descriptor_return
    addi a0, t0, -1
    sw zero, 4(s3)
    lwu a2, 20(zero)
    li a1, 2
    beq a2, zero, service_descriptor_commit
    li a1, 3
service_descriptor_commit:
    call commit_status
service_descriptor_return:
    ld ra, 0(sp)
    addi sp, sp, 16
    ret

launch_frame:
    addi sp, sp, -16
    sd ra, 0(sp)
    slli t0, s8, 6
    add t0, s1, t0
    lwu t1, 16(t0)
    lwu t2, 20(t0)
    li t3, 0x80000000
    bltu t1, t3, frame_argument_error
    bltu t2, t3, frame_argument_error
    andi t3, t2, 1
    bne t3, zero, frame_argument_error
    li t3, PIXELS
    add t1, t1, t3
    addi t2, t2, FFT_N*2
    li t3, 0x100000000
    bltu t3, t1, frame_argument_error
    bltu t3, t2, frame_argument_error
    lwu t1, 24(t0)
    srli t1, t1, 16
    bne t1, zero, frame_argument_error
    mv a0, s8
    li a1, 1
    li a2, 0
    call commit_status
    addi t0, s8, 1
    sw t0, 8(s3)
    sw zero, 12(s3)
    sw zero, 16(s3)
    j launch_frame_return
frame_argument_error:
    mv a0, s8
    li a1, 3
    li a2, E_ARGUMENT
    call commit_status
launch_frame_return:
    ld ra, 0(sp)
    addi sp, sp, 16
    ret
feed_frame:
    lwu t0, 8(s3)
    beq t0, zero, feed_frame_return
    addi t0, t0, -1
    slli t0, t0, 6
    add t0, s1, t0
    lwu t1, 12(s3)
    li t2, PIXELS
    bgeu t1, t2, feed_audio
    lwu t3, 0x220(s10)
    andi t3, t3, 1
    bne t3, zero, feed_audio
    lwu t3, 16(t0)
    add t3, t3, t1
    lbu t3, 0(t3)
    lwu t4, 24(t0)
    addi t1, t1, 1
    bne t1, t2, vision_metadata_ready
    li t5, 0x10000
    or t4, t4, t5
vision_metadata_ready:
    sw t4, 0x210(s10)
    sw t3, 0x200(s10)
    sw t1, 12(s3)
feed_audio:
    lwu t1, 16(s3)
    li t2, FFT_N
    bgeu t1, t2, feed_frame_return
    lwu t3, 0x220(s10)
    andi t3, t3, 2
    bne t3, zero, feed_frame_return
    lwu t3, 20(t0)
    slli t4, t1, 1
    add t3, t3, t4
    lhu t3, 0(t3)
    lwu t4, 24(t0)
    addi t1, t1, 1
    bne t1, t2, audio_metadata_ready
    li t5, 0x10000
    or t4, t4, t5
audio_metadata_ready:
    sw t4, 0x214(s10)
    sw t3, 0x204(s10)
    sw t1, 16(s3)
feed_frame_return:
    ret
service_frame:
    addi sp, sp, -16
    sd ra, 0(sp)
    lwu t0, 8(s3)
    beq t0, zero, service_frame_return
    lwu t1, 0x410(s10)
    beq t1, zero, service_frame_return
    addi a0, t0, -1
    sw zero, 8(s3)
    lwu a2, 36(s11)
    li a1, 2
    beq a2, zero, service_frame_commit
    li a1, 3
service_frame_commit:
    call commit_status
service_frame_return:
    ld ra, 0(sp)
    addi sp, sp, 16
    ret

finish_graph:
    csrrci zero, 0x300, 8
    csrrw zero, 0x304, zero
    li t0, 2
    beq s9, zero, final_state_ready
    li t0, 3
final_state_ready:
    sw t0, 64(s0)
    sw s9, 68(s0)
    fence
    li a0, 0x58430000
    or a0, a0, s4
    slli t0, s9, 15
    or a0, a0, t0
notify_and_halt:
    lwu t0, 0x604(s10)
    andi t0, t0, 512
    bne t0, zero, notify_and_halt
    fence
    sw a0, 0x600(s10)
    sw zero, 4(s10)
halted_forever:
    j halted_forever

trap_handler:
    addi sp, sp, -32
    sd t0, 0(sp)
    sd t1, 8(sp)
    sd t2, 16(sp)
    csrrs t0, 0x342, zero
    bge t0, zero, synchronous_failure
    li t0, 3
    sw t0, 12(zero)
    li t0, 7
    sw t0, 0x108(s10)
    ld t0, 0(sp)
    ld t1, 8(sp)
    ld t2, 16(sp)
    addi sp, sp, 32
    mret
synchronous_failure:
    sd t0, 72(s0)
    csrrs t1, 0x341, zero
    sd t1, 80(s0)
    csrrw zero, 0x304, zero
    li t0, 3
    sw t0, 64(s0)
    li t0, E_TRAP
    sw t0, 68(s0)
    li a0, 0x5843ff00
    or a0, a0, t0
    j notify_and_halt
