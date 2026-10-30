module furnace_x3_top #(
    parameter integer MAX_TILE_BYTES=4096,
    parameter integer RING_DEPTH=8,
    parameter integer IN_WIDTH=8, IN_HEIGHT=8, OUT_WIDTH=8, OUT_HEIGHT=8,
    parameter integer FFT_N=16, FUSION_DEPTH=4,
    parameter integer MAILBOX_DEPTH=4, MAX_DMA_BYTES=1048576
) (
    input wire clk, rst_n,
    output wire irq,
    input wire [15:0] s_axil_awaddr,
    input wire [2:0] s_axil_awprot,
    input wire s_axil_awvalid,
    output wire s_axil_awready,
    input wire [31:0] s_axil_wdata,
    input wire [3:0] s_axil_wstrb,
    input wire s_axil_wvalid,
    output wire s_axil_wready,
    output wire [1:0] s_axil_bresp,
    output wire s_axil_bvalid,
    input wire s_axil_bready,
    input wire [15:0] s_axil_araddr,
    input wire [2:0] s_axil_arprot,
    input wire s_axil_arvalid,
    output wire s_axil_arready,
    output wire [31:0] s_axil_rdata,
    output wire [1:0] s_axil_rresp,
    output wire s_axil_rvalid,
    input wire s_axil_rready,
    output wire [31:0] m_axi_awaddr,
    output wire [3:0] m_axi_awid,
    output wire [7:0] m_axi_awlen,
    output wire [2:0] m_axi_awsize,
    output wire [1:0] m_axi_awburst,
    output wire m_axi_awlock,
    output wire [3:0] m_axi_awcache,
    output wire [2:0] m_axi_awprot,
    output wire [3:0] m_axi_awqos, m_axi_awregion,
    output wire m_axi_awvalid,
    input wire m_axi_awready,
    output wire [511:0] m_axi_wdata,
    output wire [63:0] m_axi_wstrb,
    output wire m_axi_wlast, m_axi_wvalid,
    input wire m_axi_wready,
    input wire [3:0] m_axi_bid,
    input wire [1:0] m_axi_bresp,
    input wire m_axi_bvalid,
    output wire m_axi_bready,
    output wire [31:0] m_axi_araddr,
    output wire [3:0] m_axi_arid,
    output wire [7:0] m_axi_arlen,
    output wire [2:0] m_axi_arsize,
    output wire [1:0] m_axi_arburst,
    output wire m_axi_arlock,
    output wire [3:0] m_axi_arcache,
    output wire [2:0] m_axi_arprot,
    output wire [3:0] m_axi_arqos, m_axi_arregion,
    output wire m_axi_arvalid,
    input wire m_axi_arready,
    input wire [3:0] m_axi_rid,
    input wire [511:0] m_axi_rdata,
    input wire [1:0] m_axi_rresp,
    input wire m_axi_rlast, m_axi_rvalid,
    output wire m_axi_rready,
    input wire v_valid,
    output wire v_ready,
    input wire [7:0] v_pixel,
    input wire [15:0] v_id,
    input wire v_last,
    input wire a_valid,
    output wire a_ready,
    input wire signed [15:0] a_sample,
    input wire [15:0] a_id,
    input wire a_last,
    output wire mm_valid,
    input wire mm_ready,
    output wire [15:0] mm_id,
    output wire [63:0] mm_result,
    output wire [7:0] mm_error
);
    wire cpu_run, cpu_reset, cpu_halted, cpu_trap_valid, cpu_bus_error, fw_mode;
    wire [63:0] cpu_trap_cause, cpu_trap_pc;
    wire cpu_req_valid, cpu_req_ready, cpu_req_write, cpu_req_instr;
    wire [63:0] cpu_req_addr, cpu_req_wdata, cpu_rsp_rdata;
    wire [7:0] cpu_req_wstrb;
    wire [1:0] cpu_req_size;
    wire cpu_rsp_valid, cpu_rsp_ready, cpu_rsp_error;
    wire dev_req_valid, dev_req_ready, dev_req_host, dev_req_write, dev_req_instr;
    wire [63:0] dev_req_addr, dev_req_wdata, dev_rsp_rdata;
    wire [7:0] dev_req_wstrb;
    wire [1:0] dev_req_size;
    wire dev_rsp_valid, dev_rsp_ready, dev_rsp_error;
    wire [1:0] memory_req_valid, memory_req_ready, memory_rsp_valid;
    wire [1:0] memory_rsp_ready, memory_rsp_error, memory_req_size;
    wire [1:0][63:0] memory_rsp_rdata;
    wire memory_req_host, memory_req_write, memory_req_instr;
    wire [63:0] memory_req_addr, memory_req_wdata;
    wire [7:0] memory_req_wstrb;
    wire [2:0] leaf_req_valid, leaf_req_ready, leaf_rsp_valid;
    wire [2:0] leaf_rsp_ready, leaf_rsp_error, leaf_protocol_error;
    wire [2:0][31:0] leaf_rsp_rdata;
    wire leaf_req_write;
    wire [7:0] leaf_req_addr;
    wire [31:0] leaf_req_wdata;
    wire [3:0] leaf_req_wstrb;
    wire [15:0] irq_sources, irq_pending, irq_mask;
    wire [3:0] mailbox_nonempty;
    wire semaphore_overflow, semaphore_overflow_event, clear_semaphore_overflow;
    wire x3_protocol_error;
    wire dma_cmd_valid, dma_cmd_ready, dma_busy, dma_done_valid, dma_done_ready;
    wire [31:0] dma_src, dma_dst, dma_bytes;
    wire [7:0] dma_done_error;
    wire dma_completion;
    wire [15:0] p_awaddr, p_araddr;
    wire [2:0] p_awprot, p_arprot;
    wire p_awvalid, p_awready, p_wvalid, p_wready, p_bvalid, p_bready;
    wire [31:0] p_wdata, p_rdata;
    wire [3:0] p_wstrb;
    wire [1:0] p_bresp, p_rresp;
    wire p_arvalid, p_arready, p_rvalid, p_rready, parent_irq;
    wire fw_v_valid, fw_v_last, fw_a_valid, fw_a_last;
    wire [7:0] fw_v_pixel;
    wire [15:0] fw_v_id, fw_a_id;
    wire signed [15:0] fw_a_sample;
    wire parent_v_ready, parent_a_ready, parent_mm_valid;
    wire [15:0] parent_mm_id;
    wire [63:0] parent_mm_result;
    wire [7:0] parent_mm_error;
    wire mm_completion=fw_mode && parent_mm_valid;
    wire [3:0][31:0] legacy_awaddr, legacy_araddr;
    wire [3:0][3:0] legacy_awid, legacy_arid, legacy_bid, legacy_rid;
    wire [3:0][7:0] legacy_awlen, legacy_arlen;
    wire [3:0][2:0] legacy_awsize, legacy_arsize, legacy_awprot, legacy_arprot;
    wire [3:0][1:0] legacy_awburst, legacy_arburst, legacy_bresp, legacy_rresp;
    wire [3:0][3:0] legacy_awcache, legacy_arcache, legacy_awqos, legacy_arqos;
    wire [3:0][3:0] legacy_awregion, legacy_arregion;
    wire [3:0] legacy_awlock, legacy_arlock, legacy_awvalid, legacy_awready;
    wire [3:0] legacy_arvalid, legacy_arready, legacy_wlast, legacy_wvalid;
    wire [3:0] legacy_wready, legacy_bvalid, legacy_bready;
    wire [3:0] legacy_rlast, legacy_rvalid, legacy_rready;
    wire [3:0][127:0] legacy_wdata, legacy_rdata;
    wire [3:0][15:0] legacy_wstrb;
    wire [5:0][31:0] client_awaddr, client_araddr;
    wire [5:0][7:0] client_awlen, client_arlen;
    wire [5:0] client_awvalid, client_awready, client_arvalid, client_arready;
    wire [5:0][511:0] client_wdata, client_rdata;
    wire [5:0][63:0] client_wstrb;
    wire [5:0] client_wlast, client_wvalid, client_wready;
    wire [5:0][3:0] client_bid, client_rid;
    wire [5:0][1:0] client_bresp, client_rresp;
    wire [5:0] client_bvalid, client_bready, client_rlast, client_rvalid, client_rready;

    assign v_ready=!fw_mode && parent_v_ready;
    assign a_ready=!fw_mode && parent_a_ready;
    assign mm_valid=!fw_mode && parent_mm_valid;
    assign mm_id=fw_mode ? 16'b0 : parent_mm_id;
    assign mm_result=fw_mode ? 64'b0 : parent_mm_result;
    assign mm_error=fw_mode ? 8'b0 : parent_mm_error;
    assign irq_sources={6'b0,cpu_trap_valid,semaphore_overflow,mailbox_nonempty,
        x3_protocol_error,mm_completion,dma_completion,parent_irq};

    furnace_rv64im_core control_cpu (
        .clk(clk), .rst_n(rst_n && !cpu_reset), .run(cpu_run), .ext_irq(irq),
        .halted(cpu_halted), .req_valid(cpu_req_valid), .req_ready(cpu_req_ready),
        .req_write(cpu_req_write), .req_instr(cpu_req_instr),
        .req_addr(cpu_req_addr), .req_wdata(cpu_req_wdata),
        .req_wstrb(cpu_req_wstrb), .req_size(cpu_req_size),
        .rsp_valid(cpu_rsp_valid), .rsp_ready(cpu_rsp_ready),
        .rsp_rdata(cpu_rsp_rdata), .rsp_error(cpu_rsp_error),
        .trap_valid(cpu_trap_valid), .trap_cause(cpu_trap_cause),
        .trap_pc(cpu_trap_pc), .bus_error(cpu_bus_error)
    );
    furnace_x3_mmio_arb mmio_arbiter (
        .clk(clk), .rst_n(rst_n),
        .s_axil_awaddr(s_axil_awaddr), .s_axil_awprot(s_axil_awprot),
        .s_axil_awvalid(s_axil_awvalid), .s_axil_awready(s_axil_awready),
        .s_axil_wdata(s_axil_wdata), .s_axil_wstrb(s_axil_wstrb),
        .s_axil_wvalid(s_axil_wvalid), .s_axil_wready(s_axil_wready),
        .s_axil_bresp(s_axil_bresp), .s_axil_bvalid(s_axil_bvalid), .s_axil_bready(s_axil_bready),
        .s_axil_araddr(s_axil_araddr), .s_axil_arprot(s_axil_arprot),
        .s_axil_arvalid(s_axil_arvalid), .s_axil_arready(s_axil_arready),
        .s_axil_rdata(s_axil_rdata), .s_axil_rresp(s_axil_rresp),
        .s_axil_rvalid(s_axil_rvalid), .s_axil_rready(s_axil_rready),
        .cpu_req_valid(cpu_req_valid), .cpu_req_ready(cpu_req_ready),
        .cpu_req_write(cpu_req_write), .cpu_req_instr(cpu_req_instr),
        .cpu_req_addr(cpu_req_addr), .cpu_req_wdata(cpu_req_wdata),
        .cpu_req_wstrb(cpu_req_wstrb), .cpu_req_size(cpu_req_size),
        .cpu_rsp_valid(cpu_rsp_valid), .cpu_rsp_ready(cpu_rsp_ready),
        .cpu_rsp_rdata(cpu_rsp_rdata), .cpu_rsp_error(cpu_rsp_error),
        .dev_req_valid(dev_req_valid), .dev_req_ready(dev_req_ready),
        .dev_req_host(dev_req_host), .dev_req_write(dev_req_write), .dev_req_instr(dev_req_instr),
        .dev_req_addr(dev_req_addr), .dev_req_wdata(dev_req_wdata),
        .dev_req_wstrb(dev_req_wstrb), .dev_req_size(dev_req_size),
        .dev_rsp_valid(dev_rsp_valid), .dev_rsp_ready(dev_rsp_ready),
        .dev_rsp_rdata(dev_rsp_rdata), .dev_rsp_error(dev_rsp_error)
    );
    furnace_x3_control control (
        .clk(clk), .rst_n(rst_n),
        .req_valid(dev_req_valid), .req_ready(dev_req_ready),
        .req_host(dev_req_host), .req_write(dev_req_write), .req_instr(dev_req_instr),
        .req_addr(dev_req_addr), .req_wdata(dev_req_wdata),
        .req_wstrb(dev_req_wstrb), .req_size(dev_req_size),
        .rsp_valid(dev_rsp_valid), .rsp_ready(dev_rsp_ready),
        .rsp_rdata(dev_rsp_rdata), .rsp_error(dev_rsp_error),
        .cpu_halted(cpu_halted), .cpu_trap_valid(cpu_trap_valid),
        .cpu_bus_error(cpu_bus_error), .cpu_trap_cause(cpu_trap_cause), .cpu_trap_pc(cpu_trap_pc),
        .cpu_run(cpu_run), .cpu_reset(cpu_reset), .fw_mode(fw_mode),
        .legacy_v_transfer(!fw_mode && v_valid && parent_v_ready), .legacy_v_last(v_last),
        .legacy_a_transfer(!fw_mode && a_valid && parent_a_ready), .legacy_a_last(a_last),
        .legacy_stream_activity(!fw_mode && (v_valid || a_valid || parent_mm_valid)),
        .fw_v_valid(fw_v_valid), .fw_v_ready(parent_v_ready),
        .fw_v_pixel(fw_v_pixel), .fw_v_id(fw_v_id), .fw_v_last(fw_v_last),
        .fw_a_valid(fw_a_valid), .fw_a_ready(parent_a_ready),
        .fw_a_sample(fw_a_sample), .fw_a_id(fw_a_id), .fw_a_last(fw_a_last),
        .dma_cmd_valid(dma_cmd_valid), .dma_cmd_ready(dma_cmd_ready), .dma_busy(dma_busy),
        .dma_src(dma_src), .dma_dst(dma_dst), .dma_bytes(dma_bytes),
        .dma_done_valid(dma_done_valid), .dma_done_ready(dma_done_ready), .dma_done_error(dma_done_error),
        .semaphore_overflow_event(semaphore_overflow_event),
        .clear_semaphore_overflow(clear_semaphore_overflow),
        .leaf_protocol_error(leaf_protocol_error),
        .leaf_req_valid(leaf_req_valid), .leaf_req_ready(leaf_req_ready),
        .leaf_req_write(leaf_req_write), .leaf_req_addr(leaf_req_addr),
        .leaf_req_wdata(leaf_req_wdata), .leaf_req_wstrb(leaf_req_wstrb),
        .leaf_rsp_valid(leaf_rsp_valid), .leaf_rsp_ready(leaf_rsp_ready),
        .leaf_rsp_rdata(leaf_rsp_rdata), .leaf_rsp_error(leaf_rsp_error),
        .memory_req_valid(memory_req_valid), .memory_req_ready(memory_req_ready),
        .memory_req_host(memory_req_host), .memory_req_write(memory_req_write),
        .memory_req_instr(memory_req_instr), .memory_req_addr(memory_req_addr),
        .memory_req_wdata(memory_req_wdata), .memory_req_wstrb(memory_req_wstrb),
        .memory_req_size(memory_req_size), .memory_rsp_valid(memory_rsp_valid),
        .memory_rsp_ready(memory_rsp_ready), .memory_rsp_rdata(memory_rsp_rdata),
        .memory_rsp_error(memory_rsp_error),
        .p_axil_awaddr(p_awaddr), .p_axil_awprot(p_awprot),
        .p_axil_awvalid(p_awvalid), .p_axil_awready(p_awready),
        .p_axil_wdata(p_wdata), .p_axil_wstrb(p_wstrb),
        .p_axil_wvalid(p_wvalid), .p_axil_wready(p_wready),
        .p_axil_bresp(p_bresp), .p_axil_bvalid(p_bvalid), .p_axil_bready(p_bready),
        .p_axil_araddr(p_araddr), .p_axil_arprot(p_arprot),
        .p_axil_arvalid(p_arvalid), .p_axil_arready(p_arready),
        .p_axil_rdata(p_rdata), .p_axil_rresp(p_rresp),
        .p_axil_rvalid(p_rvalid), .p_axil_rready(p_rready),
        .protocol_error(x3_protocol_error)
    );
    furnace_x3_local_memory local_memory (
        .clk(clk), .rst_n(rst_n), .cpu_running(!cpu_halted),
        .req_valid(memory_req_valid[0]), .req_ready(memory_req_ready[0]),
        .req_host(memory_req_host), .req_write(memory_req_write), .req_instr(memory_req_instr),
        .req_addr(memory_req_addr), .req_wdata(memory_req_wdata),
        .req_wstrb(memory_req_wstrb), .req_size(memory_req_size),
        .rsp_valid(memory_rsp_valid[0]), .rsp_ready(memory_rsp_ready[0]),
        .rsp_rdata(memory_rsp_rdata[0]), .rsp_error(memory_rsp_error[0])
    );
    furnace_hw_semaphores semaphores (
        .clk(clk), .rst_n(rst_n),
        .req_valid(leaf_req_valid[1]), .req_ready(leaf_req_ready[1]),
        .req_write(leaf_req_write), .req_addr(leaf_req_addr),
        .req_wdata(leaf_req_wdata), .req_wstrb(leaf_req_wstrb),
        .rsp_valid(leaf_rsp_valid[1]), .rsp_ready(leaf_rsp_ready[1]),
        .rsp_rdata(leaf_rsp_rdata[1]), .rsp_error(leaf_rsp_error[1]),
        .hw_post({14'b0,mm_completion,dma_completion}),
        .clear_overflow(clear_semaphore_overflow), .overflow(semaphore_overflow),
        .overflow_event(semaphore_overflow_event), .protocol_error(leaf_protocol_error[1])
    );
    furnace_mailboxes #(.MAILBOX_DEPTH(MAILBOX_DEPTH)) mailboxes (
        .clk(clk), .rst_n(rst_n),
        .req_valid(leaf_req_valid[2]), .req_ready(leaf_req_ready[2]),
        .req_write(leaf_req_write), .req_addr(leaf_req_addr),
        .req_wdata(leaf_req_wdata), .req_wstrb(leaf_req_wstrb),
        .rsp_valid(leaf_rsp_valid[2]), .rsp_ready(leaf_rsp_ready[2]),
        .rsp_rdata(leaf_rsp_rdata[2]), .rsp_error(leaf_rsp_error[2]),
        .nonempty(mailbox_nonempty), .protocol_error(leaf_protocol_error[2])
    );
    furnace_interrupt_aggregator interrupts (
        .clk(clk), .rst_n(rst_n), .sources(irq_sources),
        .req_valid(leaf_req_valid[0]), .req_ready(leaf_req_ready[0]),
        .req_write(leaf_req_write), .req_addr(leaf_req_addr),
        .req_wdata(leaf_req_wdata), .req_wstrb(leaf_req_wstrb),
        .rsp_valid(leaf_rsp_valid[0]), .rsp_ready(leaf_rsp_ready[0]),
        .rsp_rdata(leaf_rsp_rdata[0]), .rsp_error(leaf_rsp_error[0]),
        .pending(irq_pending), .mask(irq_mask), .irq(irq),
        .protocol_error(leaf_protocol_error[0])
    );
    furnace_x2_top #(
        .MAX_TILE_BYTES(MAX_TILE_BYTES), .RING_DEPTH(RING_DEPTH),
        .IN_WIDTH(IN_WIDTH), .IN_HEIGHT(IN_HEIGHT),
        .OUT_WIDTH(OUT_WIDTH), .OUT_HEIGHT(OUT_HEIGHT),
        .FFT_N(FFT_N), .FUSION_DEPTH(FUSION_DEPTH)
    ) legacy_soc (
        .clk(clk), .rst_n(rst_n), .irq(parent_irq),
        .s_axil_awaddr(p_awaddr), .s_axil_awprot(p_awprot),
        .s_axil_awvalid(p_awvalid), .s_axil_awready(p_awready),
        .s_axil_wdata(p_wdata), .s_axil_wstrb(p_wstrb),
        .s_axil_wvalid(p_wvalid), .s_axil_wready(p_wready),
        .s_axil_bresp(p_bresp), .s_axil_bvalid(p_bvalid), .s_axil_bready(p_bready),
        .s_axil_araddr(p_araddr), .s_axil_arprot(p_arprot),
        .s_axil_arvalid(p_arvalid), .s_axil_arready(p_arready),
        .s_axil_rdata(p_rdata), .s_axil_rresp(p_rresp),
        .s_axil_rvalid(p_rvalid), .s_axil_rready(p_rready),
        .m_axi_awaddr(legacy_awaddr), .m_axi_awid(legacy_awid),
        .m_axi_awlen(legacy_awlen), .m_axi_awsize(legacy_awsize),
        .m_axi_awburst(legacy_awburst), .m_axi_awlock(legacy_awlock),
        .m_axi_awcache(legacy_awcache), .m_axi_awprot(legacy_awprot),
        .m_axi_awqos(legacy_awqos), .m_axi_awregion(legacy_awregion),
        .m_axi_awvalid(legacy_awvalid), .m_axi_awready(legacy_awready),
        .m_axi_wdata(legacy_wdata), .m_axi_wstrb(legacy_wstrb),
        .m_axi_wlast(legacy_wlast), .m_axi_wvalid(legacy_wvalid), .m_axi_wready(legacy_wready),
        .m_axi_bid(legacy_bid), .m_axi_bresp(legacy_bresp),
        .m_axi_bvalid(legacy_bvalid), .m_axi_bready(legacy_bready),
        .m_axi_araddr(legacy_araddr), .m_axi_arid(legacy_arid),
        .m_axi_arlen(legacy_arlen), .m_axi_arsize(legacy_arsize),
        .m_axi_arburst(legacy_arburst), .m_axi_arlock(legacy_arlock),
        .m_axi_arcache(legacy_arcache), .m_axi_arprot(legacy_arprot),
        .m_axi_arqos(legacy_arqos), .m_axi_arregion(legacy_arregion),
        .m_axi_arvalid(legacy_arvalid), .m_axi_arready(legacy_arready),
        .m_axi_rid(legacy_rid), .m_axi_rdata(legacy_rdata), .m_axi_rresp(legacy_rresp),
        .m_axi_rlast(legacy_rlast), .m_axi_rvalid(legacy_rvalid), .m_axi_rready(legacy_rready),
        .v_valid(fw_mode ? fw_v_valid : v_valid), .v_ready(parent_v_ready),
        .v_pixel(fw_mode ? fw_v_pixel : v_pixel), .v_id(fw_mode ? fw_v_id : v_id),
        .v_last(fw_mode ? fw_v_last : v_last),
        .a_valid(fw_mode ? fw_a_valid : a_valid), .a_ready(parent_a_ready),
        .a_sample(fw_mode ? fw_a_sample : a_sample), .a_id(fw_mode ? fw_a_id : a_id),
        .a_last(fw_mode ? fw_a_last : a_last),
        .mm_valid(parent_mm_valid), .mm_ready(fw_mode || mm_ready),
        .mm_id(parent_mm_id), .mm_result(parent_mm_result), .mm_error(parent_mm_error)
    );
    genvar port_index;
    generate for (port_index=0;port_index<4;port_index=port_index+1) begin: legacy_memory_ports
        furnace_axi128_to512 #(.CLIENT_ID(port_index)) adapter (
            .clk(clk), .rst_n(rst_n),
            .s_axi_awaddr(legacy_awaddr[port_index]), .s_axi_awid(legacy_awid[port_index]),
            .s_axi_awlen(legacy_awlen[port_index]), .s_axi_awsize(legacy_awsize[port_index]),
            .s_axi_awburst(legacy_awburst[port_index]), .s_axi_awlock(legacy_awlock[port_index]),
            .s_axi_awcache(legacy_awcache[port_index]), .s_axi_awprot(legacy_awprot[port_index]),
            .s_axi_awqos(legacy_awqos[port_index]), .s_axi_awregion(legacy_awregion[port_index]),
            .s_axi_awvalid(legacy_awvalid[port_index]), .s_axi_awready(legacy_awready[port_index]),
            .s_axi_wdata(legacy_wdata[port_index]), .s_axi_wstrb(legacy_wstrb[port_index]),
            .s_axi_wlast(legacy_wlast[port_index]), .s_axi_wvalid(legacy_wvalid[port_index]),
            .s_axi_wready(legacy_wready[port_index]), .s_axi_bid(legacy_bid[port_index]),
            .s_axi_bresp(legacy_bresp[port_index]), .s_axi_bvalid(legacy_bvalid[port_index]),
            .s_axi_bready(legacy_bready[port_index]),
            .s_axi_araddr(legacy_araddr[port_index]), .s_axi_arid(legacy_arid[port_index]),
            .s_axi_arlen(legacy_arlen[port_index]), .s_axi_arsize(legacy_arsize[port_index]),
            .s_axi_arburst(legacy_arburst[port_index]), .s_axi_arlock(legacy_arlock[port_index]),
            .s_axi_arcache(legacy_arcache[port_index]), .s_axi_arprot(legacy_arprot[port_index]),
            .s_axi_arqos(legacy_arqos[port_index]), .s_axi_arregion(legacy_arregion[port_index]),
            .s_axi_arvalid(legacy_arvalid[port_index]), .s_axi_arready(legacy_arready[port_index]),
            .s_axi_rid(legacy_rid[port_index]), .s_axi_rdata(legacy_rdata[port_index]),
            .s_axi_rresp(legacy_rresp[port_index]), .s_axi_rlast(legacy_rlast[port_index]),
            .s_axi_rvalid(legacy_rvalid[port_index]), .s_axi_rready(legacy_rready[port_index]),
            .m_axi_awaddr(client_awaddr[port_index]), .m_axi_awid(),
            .m_axi_awlen(client_awlen[port_index]), .m_axi_awsize(), .m_axi_awburst(),
            .m_axi_awvalid(client_awvalid[port_index]), .m_axi_awready(client_awready[port_index]),
            .m_axi_wdata(client_wdata[port_index]), .m_axi_wstrb(client_wstrb[port_index]),
            .m_axi_wlast(client_wlast[port_index]), .m_axi_wvalid(client_wvalid[port_index]),
            .m_axi_wready(client_wready[port_index]), .m_axi_bid(client_bid[port_index]),
            .m_axi_bresp(client_bresp[port_index]), .m_axi_bvalid(client_bvalid[port_index]),
            .m_axi_bready(client_bready[port_index]),
            .m_axi_araddr(client_araddr[port_index]), .m_axi_arid(),
            .m_axi_arlen(client_arlen[port_index]), .m_axi_arsize(), .m_axi_arburst(),
            .m_axi_arvalid(client_arvalid[port_index]), .m_axi_arready(client_arready[port_index]),
            .m_axi_rid(client_rid[port_index]), .m_axi_rdata(client_rdata[port_index]),
            .m_axi_rresp(client_rresp[port_index]), .m_axi_rlast(client_rlast[port_index]),
            .m_axi_rvalid(client_rvalid[port_index]), .m_axi_rready(client_rready[port_index])
        );
    end endgenerate
    furnace_x3_cpu_axi_bridge cpu_memory_bridge (
        .clk(clk), .rst_n(rst_n),
        .req_valid(memory_req_valid[1]), .req_ready(memory_req_ready[1]),
        .req_write(memory_req_write), .req_instr(memory_req_instr),
        .req_addr(memory_req_addr), .req_wdata(memory_req_wdata),
        .req_wstrb(memory_req_wstrb), .req_size(memory_req_size),
        .rsp_valid(memory_rsp_valid[1]), .rsp_ready(memory_rsp_ready[1]),
        .rsp_rdata(memory_rsp_rdata[1]), .rsp_error(memory_rsp_error[1]),
        .m_axi_awaddr(client_awaddr[4]), .m_axi_awid(),
        .m_axi_awlen(client_awlen[4]), .m_axi_awsize(), .m_axi_awburst(),
        .m_axi_awvalid(client_awvalid[4]), .m_axi_awready(client_awready[4]),
        .m_axi_wdata(client_wdata[4]), .m_axi_wstrb(client_wstrb[4]),
        .m_axi_wlast(client_wlast[4]), .m_axi_wvalid(client_wvalid[4]),
        .m_axi_wready(client_wready[4]), .m_axi_bid(client_bid[4]),
        .m_axi_bresp(client_bresp[4]), .m_axi_bvalid(client_bvalid[4]), .m_axi_bready(client_bready[4]),
        .m_axi_araddr(client_araddr[4]), .m_axi_arid(),
        .m_axi_arlen(client_arlen[4]), .m_axi_arsize(), .m_axi_arburst(),
        .m_axi_arvalid(client_arvalid[4]), .m_axi_arready(client_arready[4]),
        .m_axi_rid(client_rid[4]), .m_axi_rdata(client_rdata[4]),
        .m_axi_rresp(client_rresp[4]), .m_axi_rlast(client_rlast[4]),
        .m_axi_rvalid(client_rvalid[4]), .m_axi_rready(client_rready[4])
    );
    furnace_dma512 #(.MAX_DMA_BYTES(MAX_DMA_BYTES)) burst_dma (
        .clk(clk), .rst_n(rst_n),
        .cmd_valid(dma_cmd_valid), .cmd_ready(dma_cmd_ready),
        .cmd_src(dma_src), .cmd_dst(dma_dst), .cmd_bytes(dma_bytes),
        .busy(dma_busy), .done_valid(dma_done_valid), .done_ready(dma_done_ready),
        .done_error(dma_done_error), .completion(dma_completion),
        .m_axi_awaddr(client_awaddr[5]), .m_axi_awid(),
        .m_axi_awlen(client_awlen[5]), .m_axi_awsize(), .m_axi_awburst(),
        .m_axi_awvalid(client_awvalid[5]), .m_axi_awready(client_awready[5]),
        .m_axi_wdata(client_wdata[5]), .m_axi_wstrb(client_wstrb[5]),
        .m_axi_wlast(client_wlast[5]), .m_axi_wvalid(client_wvalid[5]),
        .m_axi_wready(client_wready[5]), .m_axi_bid(client_bid[5]),
        .m_axi_bresp(client_bresp[5]), .m_axi_bvalid(client_bvalid[5]), .m_axi_bready(client_bready[5]),
        .m_axi_araddr(client_araddr[5]), .m_axi_arid(),
        .m_axi_arlen(client_arlen[5]), .m_axi_arsize(), .m_axi_arburst(),
        .m_axi_arvalid(client_arvalid[5]), .m_axi_arready(client_arready[5]),
        .m_axi_rid(client_rid[5]), .m_axi_rdata(client_rdata[5]),
        .m_axi_rresp(client_rresp[5]), .m_axi_rlast(client_rlast[5]),
        .m_axi_rvalid(client_rvalid[5]), .m_axi_rready(client_rready[5])
    );
    furnace_x3_axi512_arb memory_arbiter (
        .clk(clk), .rst_n(rst_n),
        .s_axi_awaddr(client_awaddr), .s_axi_awlen(client_awlen),
        .s_axi_awvalid(client_awvalid), .s_axi_awready(client_awready),
        .s_axi_wdata(client_wdata), .s_axi_wstrb(client_wstrb),
        .s_axi_wlast(client_wlast), .s_axi_wvalid(client_wvalid), .s_axi_wready(client_wready),
        .s_axi_bid(client_bid), .s_axi_bresp(client_bresp),
        .s_axi_bvalid(client_bvalid), .s_axi_bready(client_bready),
        .s_axi_araddr(client_araddr), .s_axi_arlen(client_arlen),
        .s_axi_arvalid(client_arvalid), .s_axi_arready(client_arready),
        .s_axi_rid(client_rid), .s_axi_rdata(client_rdata), .s_axi_rresp(client_rresp),
        .s_axi_rlast(client_rlast), .s_axi_rvalid(client_rvalid), .s_axi_rready(client_rready),
        .m_axi_awaddr(m_axi_awaddr), .m_axi_awid(m_axi_awid),
        .m_axi_awlen(m_axi_awlen), .m_axi_awsize(m_axi_awsize),
        .m_axi_awburst(m_axi_awburst), .m_axi_awlock(m_axi_awlock),
        .m_axi_awcache(m_axi_awcache), .m_axi_awprot(m_axi_awprot),
        .m_axi_awqos(m_axi_awqos), .m_axi_awregion(m_axi_awregion),
        .m_axi_awvalid(m_axi_awvalid), .m_axi_awready(m_axi_awready),
        .m_axi_wdata(m_axi_wdata), .m_axi_wstrb(m_axi_wstrb),
        .m_axi_wlast(m_axi_wlast), .m_axi_wvalid(m_axi_wvalid), .m_axi_wready(m_axi_wready),
        .m_axi_bid(m_axi_bid), .m_axi_bresp(m_axi_bresp),
        .m_axi_bvalid(m_axi_bvalid), .m_axi_bready(m_axi_bready),
        .m_axi_araddr(m_axi_araddr), .m_axi_arid(m_axi_arid),
        .m_axi_arlen(m_axi_arlen), .m_axi_arsize(m_axi_arsize),
        .m_axi_arburst(m_axi_arburst), .m_axi_arlock(m_axi_arlock),
        .m_axi_arcache(m_axi_arcache), .m_axi_arprot(m_axi_arprot),
        .m_axi_arqos(m_axi_arqos), .m_axi_arregion(m_axi_arregion),
        .m_axi_arvalid(m_axi_arvalid), .m_axi_arready(m_axi_arready),
        .m_axi_rid(m_axi_rid), .m_axi_rdata(m_axi_rdata), .m_axi_rresp(m_axi_rresp),
        .m_axi_rlast(m_axi_rlast), .m_axi_rvalid(m_axi_rvalid), .m_axi_rready(m_axi_rready)
    );
endmodule
