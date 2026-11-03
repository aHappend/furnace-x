module furnace_x4_top #(
    parameter integer MAX_TILE_BYTES=4096,
    parameter integer RING_DEPTH=8,
    parameter integer IN_WIDTH=8, IN_HEIGHT=8, OUT_WIDTH=8, OUT_HEIGHT=8,
    parameter integer FFT_N=16, FUSION_DEPTH=4,
    parameter integer MAILBOX_DEPTH=4, MAX_DMA_BYTES=1048576
) (
    input wire clk, rst_n,
    input wire uart_rx,
    output wire uart_tx, irq,
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
    output wire [7:0] mm_error,
    output wire [31:0] m_axi_awaddr,
    output wire [4:0] m_axi_awid,
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
    input wire [4:0] m_axi_bid,
    input wire [1:0] m_axi_bresp,
    input wire m_axi_bvalid,
    output wire m_axi_bready,
    output wire [31:0] m_axi_araddr,
    output wire [4:0] m_axi_arid,
    output wire [7:0] m_axi_arlen,
    output wire [2:0] m_axi_arsize,
    output wire [1:0] m_axi_arburst,
    output wire m_axi_arlock,
    output wire [3:0] m_axi_arcache,
    output wire [2:0] m_axi_arprot,
    output wire [3:0] m_axi_arqos, m_axi_arregion,
    output wire m_axi_arvalid,
    input wire m_axi_arready,
    input wire [4:0] m_axi_rid,
    input wire [511:0] m_axi_rdata,
    input wire [1:0] m_axi_rresp,
    input wire m_axi_rlast, m_axi_rvalid,
    output wire m_axi_rready
);
    localparam integer LEGAL = MAX_TILE_BYTES >= 1 && MAX_TILE_BYTES <= 65536 &&
        RING_DEPTH >= 1 && RING_DEPTH <= 16 &&
        IN_WIDTH >= 1 && IN_WIDTH <= 64 && IN_HEIGHT >= 1 && IN_HEIGHT <= 64 &&
        OUT_WIDTH >= 1 && OUT_WIDTH <= 64 && OUT_HEIGHT >= 1 && OUT_HEIGHT <= 64 &&
        (FFT_N == 8 || FFT_N == 16 || FFT_N == 32 || FFT_N == 64) &&
        FUSION_DEPTH >= 1 && FUSION_DEPTH <= 16 &&
        MAILBOX_DEPTH >= 1 && MAILBOX_DEPTH <= 16 &&
        MAX_DMA_BYTES >= 1 && MAX_DMA_BYTES <= 1048576;
    initial if (!LEGAL) $fatal(1,"PARAMETER ERROR: illegal FURNACE-X4 configuration");
    (* async_reg = "true" *) reg [1:0] reset_release;
    wire system_rst_n = rst_n && reset_release[1];
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) reset_release <= 0;
        else reset_release <= {reset_release[0],1'b1};
    end

    wire fabric_irq, fabric_v_ready, fabric_a_ready, fabric_mm_valid, app_uart_tx;
    wire [15:0] fabric_mm_id;
    wire [63:0] fabric_mm_result;
    wire [7:0] fabric_mm_error;
    assign irq = system_rst_n && fabric_irq;
    assign uart_tx = system_rst_n ? app_uart_tx : 1'b1;
    assign v_ready = system_rst_n && fabric_v_ready;
    assign a_ready = system_rst_n && fabric_a_ready;
    assign mm_valid = system_rst_n && fabric_mm_valid;
    assign mm_id = mm_valid ? fabric_mm_id : 16'b0;
    assign mm_result = mm_valid ? fabric_mm_result : 64'b0;
    assign mm_error = mm_valid ? fabric_mm_error : 8'b0;

    wire coh_req_valid, coh_req_ready, coh_rsp_valid, coh_rsp_ready, coh_rsp_error;
    wire app_coh_req_ready;
    reg boot_launch_seen;
    wire coh_release_valid, coh_release_ready;
    wire app_start, startup_error, app_boot_ready, app_boot_error, app_halted;
    wire app_host_ready, app_host_rsp_valid, app_host_rsp_error;
    wire [63:0] app_host_rdata, app_dbg_rdata;
    wire app_trap_valid, app_trap_interrupt, app_retire_valid, app_retire_rd_we;
    wire [63:0] app_trap_pc, app_trap_cause, app_trap_tval;
    wire [1:0] app_trap_target_priv, app_retire_priv;
    wire [63:0] app_retire_pc, app_retire_next_pc, app_retire_rd_data;
    wire [31:0] app_retire_insn;
    wire [4:0] app_retire_rd;
    wire app_retire_mem_valid, app_retire_mem_write;
    wire [63:0] app_retire_mem_addr, app_retire_mem_wdata, app_retire_mem_rdata;
    wire [7:0] app_retire_mem_wmask;
    wire app_stall_load_use, app_stall_mem, app_stall_muldiv, app_redirect_valid, app_ex_valid;
    wire [63:0] app_redirect_pc, app_ex_pc;
    wire [1:0] app_ex_rs1_sel, app_ex_rs2_sel, app_ex_store_sel;
    wire disabled_acc_awready, disabled_acc_wready, disabled_acc_arready;
    wire [3:0] disabled_acc_bid, disabled_acc_rid;
    wire [1:0] disabled_acc_bresp, disabled_acc_rresp;
    wire [63:0] disabled_acc_rdata;
    wire disabled_acc_bvalid, disabled_acc_rvalid, disabled_acc_rlast;

    wire [31:0] app_mmio_awaddr, app_mmio_araddr;
    wire [2:0] app_mmio_awprot, app_mmio_arprot;
    wire app_mmio_awvalid, app_mmio_awready, app_mmio_wvalid, app_mmio_wready;
    wire app_mmio_bvalid, app_mmio_bready, app_mmio_arvalid, app_mmio_arready;
    wire app_mmio_rvalid, app_mmio_rready;
    wire [63:0] app_mmio_wdata, app_mmio_rdata;
    wire [7:0] app_mmio_wstrb;
    wire [1:0] app_mmio_bresp, app_mmio_rresp;
    wire [15:0] fabric_mmio_awaddr, fabric_mmio_araddr;
    wire [2:0] fabric_mmio_awprot, fabric_mmio_arprot;
    wire fabric_mmio_awvalid, fabric_mmio_awready, fabric_mmio_wvalid, fabric_mmio_wready;
    wire fabric_mmio_bvalid, fabric_mmio_bready, fabric_mmio_arvalid, fabric_mmio_arready;
    wire fabric_mmio_rvalid, fabric_mmio_rready;
    wire [31:0] fabric_mmio_wdata, fabric_mmio_rdata;
    wire [3:0] fabric_mmio_wstrb;
    wire [1:0] fabric_mmio_bresp, fabric_mmio_rresp;

    wire [63:0] app_mem_awaddr, app_mem_araddr;
    wire [3:0] app_mem_awid, app_mem_arid, app_mem_bid, app_mem_rid;
    wire [7:0] app_mem_awlen, app_mem_arlen;
    wire [2:0] app_mem_awsize, app_mem_arsize, app_mem_awprot, app_mem_arprot;
    wire [1:0] app_mem_awburst, app_mem_arburst, app_mem_bresp, app_mem_rresp;
    wire [3:0] app_mem_awcache, app_mem_arcache, app_mem_awqos, app_mem_arqos;
    wire app_mem_awlock, app_mem_arlock, app_mem_awvalid, app_mem_awready;
    wire app_mem_arvalid, app_mem_arready, app_mem_wlast, app_mem_wvalid;
    wire app_mem_wready, app_mem_bvalid, app_mem_bready;
    wire app_mem_rlast, app_mem_rvalid, app_mem_rready;
    wire [63:0] app_mem_wdata, app_mem_rdata;
    wire [7:0] app_mem_wstrb;

    // Client 0 is fabric; client 1 is the application width bridge.
    wire [1:0][31:0] memory_awaddr, memory_araddr;
    wire [1:0][3:0] memory_awid, memory_arid, memory_bid, memory_rid;
    wire [1:0][7:0] memory_awlen, memory_arlen;
    wire [1:0][2:0] memory_awsize, memory_arsize, memory_awprot, memory_arprot;
    wire [1:0][1:0] memory_awburst, memory_arburst, memory_bresp, memory_rresp;
    wire [1:0][3:0] memory_awcache, memory_arcache, memory_awqos, memory_arqos;
    wire [1:0][3:0] memory_awregion, memory_arregion;
    wire [1:0] memory_awlock, memory_arlock, memory_awvalid, memory_awready;
    wire [1:0] memory_arvalid, memory_arready, memory_wlast, memory_wvalid;
    wire [1:0] memory_wready, memory_bvalid, memory_bready;
    wire [1:0] memory_rlast, memory_rvalid, memory_rready;
    wire [1:0][511:0] memory_wdata, memory_rdata;
    wire [1:0][63:0] memory_wstrb;

    always @(posedge clk or negedge system_rst_n) begin
        if (!system_rst_n) boot_launch_seen <= 0;
        else if (app_start) boot_launch_seen <= 1;
    end
    assign coh_req_ready = boot_launch_seen && app_coh_req_ready;

    furnace_x4_boot_control boot_control (
        .clk(clk), .rst_n(system_rst_n),
        .app_boot_ready(app_boot_ready), .app_boot_error(app_boot_error),
        .app_halted(app_halted), .app_start(app_start), .startup_error(startup_error));

    hammer_v4_top #(
        .IMEM_WORDS(16384), .DMEM_WORDS(8192), .PRED_MODE(1), .BTB_ENTRIES(16),
        .ICACHE_LINES(64), .DCACHE_LINES(64), .LEGACY_TRAPS(0),
        .ITLB_ENTRIES(8), .DTLB_ENTRIES(8), .BOOT_ENABLE(1)
    ) application_processor (
        .clk(clk), .rst_n(system_rst_n), .start(app_start),
        .coh_req_valid(coh_req_valid && boot_launch_seen), .coh_req_ready(app_coh_req_ready),
        .coh_rsp_valid(coh_rsp_valid), .coh_rsp_ready(coh_rsp_ready),
        .coh_rsp_error(coh_rsp_error),
        .coh_release_valid(coh_release_valid), .coh_release_ready(coh_release_ready),
        .host_valid(1'b0), .host_write(1'b0), .host_imem(1'b0),
        .host_addr(32'b0), .host_wdata(64'b0), .host_wstrb(8'b0),
        .dbg_raddr(5'b0), .halt_req(1'b0), .irq_meip(1'b0), .irq_seip(1'b0),
        .halted(app_halted), .boot_ready(app_boot_ready), .boot_error(app_boot_error),
        .host_ready(app_host_ready), .host_rsp_valid(app_host_rsp_valid),
        .host_rsp_error(app_host_rsp_error), .host_rdata(app_host_rdata),
        .dbg_rdata(app_dbg_rdata), .trap_valid(app_trap_valid),
        .trap_pc(app_trap_pc), .trap_cause(app_trap_cause), .trap_tval(app_trap_tval),
        .trap_target_priv(app_trap_target_priv), .trap_interrupt(app_trap_interrupt),
        .retire_valid(app_retire_valid), .retire_pc(app_retire_pc),
        .retire_next_pc(app_retire_next_pc), .retire_insn(app_retire_insn),
        .retire_priv(app_retire_priv), .retire_rd_we(app_retire_rd_we),
        .retire_rd(app_retire_rd), .retire_rd_data(app_retire_rd_data),
        .retire_mem_valid(app_retire_mem_valid), .retire_mem_write(app_retire_mem_write),
        .retire_mem_addr(app_retire_mem_addr), .retire_mem_wmask(app_retire_mem_wmask),
        .retire_mem_wdata(app_retire_mem_wdata), .retire_mem_rdata(app_retire_mem_rdata),
        .stall_load_use(app_stall_load_use), .stall_mem(app_stall_mem),
        .stall_muldiv(app_stall_muldiv), .redirect_valid(app_redirect_valid),
        .redirect_pc(app_redirect_pc), .ex_valid(app_ex_valid), .ex_pc(app_ex_pc),
        .ex_rs1_sel(app_ex_rs1_sel), .ex_rs2_sel(app_ex_rs2_sel), .ex_store_sel(app_ex_store_sel),
        .uart_rx(uart_rx), .uart_tx(app_uart_tx), .plic_sources({30'b0,fabric_irq}),
        .m_axi_awaddr(app_mmio_awaddr), .m_axi_awprot(app_mmio_awprot),
        .m_axi_awvalid(app_mmio_awvalid), .m_axi_awready(app_mmio_awready),
        .m_axi_wdata(app_mmio_wdata), .m_axi_wstrb(app_mmio_wstrb),
        .m_axi_wvalid(app_mmio_wvalid), .m_axi_wready(app_mmio_wready),
        .m_axi_bresp(app_mmio_bresp), .m_axi_bvalid(app_mmio_bvalid), .m_axi_bready(app_mmio_bready),
        .m_axi_araddr(app_mmio_araddr), .m_axi_arprot(app_mmio_arprot),
        .m_axi_arvalid(app_mmio_arvalid), .m_axi_arready(app_mmio_arready),
        .m_axi_rdata(app_mmio_rdata), .m_axi_rresp(app_mmio_rresp),
        .m_axi_rvalid(app_mmio_rvalid), .m_axi_rready(app_mmio_rready),
        .m_mem_axi_awid(app_mem_awid), .m_mem_axi_awaddr(app_mem_awaddr),
        .m_mem_axi_awlen(app_mem_awlen), .m_mem_axi_awsize(app_mem_awsize),
        .m_mem_axi_awburst(app_mem_awburst), .m_mem_axi_awlock(app_mem_awlock),
        .m_mem_axi_awcache(app_mem_awcache), .m_mem_axi_awprot(app_mem_awprot),
        .m_mem_axi_awqos(app_mem_awqos), .m_mem_axi_awvalid(app_mem_awvalid),
        .m_mem_axi_awready(app_mem_awready), .m_mem_axi_wdata(app_mem_wdata),
        .m_mem_axi_wstrb(app_mem_wstrb), .m_mem_axi_wlast(app_mem_wlast),
        .m_mem_axi_wvalid(app_mem_wvalid), .m_mem_axi_wready(app_mem_wready),
        .m_mem_axi_bid(app_mem_bid), .m_mem_axi_bresp(app_mem_bresp),
        .m_mem_axi_bvalid(app_mem_bvalid), .m_mem_axi_bready(app_mem_bready),
        .m_mem_axi_arid(app_mem_arid), .m_mem_axi_araddr(app_mem_araddr),
        .m_mem_axi_arlen(app_mem_arlen), .m_mem_axi_arsize(app_mem_arsize),
        .m_mem_axi_arburst(app_mem_arburst), .m_mem_axi_arlock(app_mem_arlock),
        .m_mem_axi_arcache(app_mem_arcache), .m_mem_axi_arprot(app_mem_arprot),
        .m_mem_axi_arqos(app_mem_arqos), .m_mem_axi_arvalid(app_mem_arvalid),
        .m_mem_axi_arready(app_mem_arready), .m_mem_axi_rid(app_mem_rid),
        .m_mem_axi_rdata(app_mem_rdata), .m_mem_axi_rresp(app_mem_rresp),
        .m_mem_axi_rlast(app_mem_rlast), .m_mem_axi_rvalid(app_mem_rvalid),
        .m_mem_axi_rready(app_mem_rready),
        .s_acc_axi_awid(4'b0), .s_acc_axi_awaddr(64'b0), .s_acc_axi_awlen(8'b0),
        .s_acc_axi_awsize(3'b0), .s_acc_axi_awburst(2'b0), .s_acc_axi_awlock(1'b0),
        .s_acc_axi_awcache(4'b0), .s_acc_axi_awprot(3'b0), .s_acc_axi_awqos(4'b0),
        .s_acc_axi_awvalid(1'b0), .s_acc_axi_awready(disabled_acc_awready),
        .s_acc_axi_wdata(64'b0), .s_acc_axi_wstrb(8'b0), .s_acc_axi_wlast(1'b0),
        .s_acc_axi_wvalid(1'b0), .s_acc_axi_wready(disabled_acc_wready),
        .s_acc_axi_bid(disabled_acc_bid), .s_acc_axi_bresp(disabled_acc_bresp),
        .s_acc_axi_bvalid(disabled_acc_bvalid), .s_acc_axi_bready(1'b0),
        .s_acc_axi_arid(4'b0), .s_acc_axi_araddr(64'b0), .s_acc_axi_arlen(8'b0),
        .s_acc_axi_arsize(3'b0), .s_acc_axi_arburst(2'b0), .s_acc_axi_arlock(1'b0),
        .s_acc_axi_arcache(4'b0), .s_acc_axi_arprot(3'b0), .s_acc_axi_arqos(4'b0),
        .s_acc_axi_arvalid(1'b0), .s_acc_axi_arready(disabled_acc_arready),
        .s_acc_axi_rid(disabled_acc_rid), .s_acc_axi_rdata(disabled_acc_rdata),
        .s_acc_axi_rresp(disabled_acc_rresp), .s_acc_axi_rlast(disabled_acc_rlast),
        .s_acc_axi_rvalid(disabled_acc_rvalid), .s_acc_axi_rready(1'b0)
    );

    furnace_x4_mmio_bridge mmio_bridge (
        .clk(clk), .rst_n(system_rst_n),
        .s_axil_awaddr(app_mmio_awaddr), .s_axil_awprot(app_mmio_awprot),
        .s_axil_awvalid(app_mmio_awvalid), .s_axil_awready(app_mmio_awready),
        .s_axil_wdata(app_mmio_wdata), .s_axil_wstrb(app_mmio_wstrb),
        .s_axil_wvalid(app_mmio_wvalid), .s_axil_wready(app_mmio_wready),
        .s_axil_bresp(app_mmio_bresp), .s_axil_bvalid(app_mmio_bvalid), .s_axil_bready(app_mmio_bready),
        .s_axil_araddr(app_mmio_araddr), .s_axil_arprot(app_mmio_arprot),
        .s_axil_arvalid(app_mmio_arvalid), .s_axil_arready(app_mmio_arready),
        .s_axil_rdata(app_mmio_rdata), .s_axil_rresp(app_mmio_rresp),
        .s_axil_rvalid(app_mmio_rvalid), .s_axil_rready(app_mmio_rready),
        .m_axil_awaddr(fabric_mmio_awaddr), .m_axil_awprot(fabric_mmio_awprot),
        .m_axil_awvalid(fabric_mmio_awvalid), .m_axil_awready(fabric_mmio_awready),
        .m_axil_wdata(fabric_mmio_wdata), .m_axil_wstrb(fabric_mmio_wstrb),
        .m_axil_wvalid(fabric_mmio_wvalid), .m_axil_wready(fabric_mmio_wready),
        .m_axil_bresp(fabric_mmio_bresp), .m_axil_bvalid(fabric_mmio_bvalid),
        .m_axil_bready(fabric_mmio_bready),
        .m_axil_araddr(fabric_mmio_araddr), .m_axil_arprot(fabric_mmio_arprot),
        .m_axil_arvalid(fabric_mmio_arvalid), .m_axil_arready(fabric_mmio_arready),
        .m_axil_rdata(fabric_mmio_rdata), .m_axil_rresp(fabric_mmio_rresp),
        .m_axil_rvalid(fabric_mmio_rvalid), .m_axil_rready(fabric_mmio_rready)
    );

    furnace_x4_cpu_axi512_bridge cpu_axi512_bridge (
        .clk(clk), .rst_n(system_rst_n),
        .s_axi_awid(app_mem_awid), .s_axi_awaddr(app_mem_awaddr),
        .s_axi_awlen(app_mem_awlen), .s_axi_awsize(app_mem_awsize),
        .s_axi_awburst(app_mem_awburst), .s_axi_awlock(app_mem_awlock),
        .s_axi_awcache(app_mem_awcache), .s_axi_awprot(app_mem_awprot),
        .s_axi_awqos(app_mem_awqos), .s_axi_awvalid(app_mem_awvalid),
        .s_axi_awready(app_mem_awready), .s_axi_wdata(app_mem_wdata),
        .s_axi_wstrb(app_mem_wstrb), .s_axi_wlast(app_mem_wlast),
        .s_axi_wvalid(app_mem_wvalid), .s_axi_wready(app_mem_wready),
        .s_axi_bid(app_mem_bid), .s_axi_bresp(app_mem_bresp),
        .s_axi_bvalid(app_mem_bvalid), .s_axi_bready(app_mem_bready),
        .s_axi_arid(app_mem_arid), .s_axi_araddr(app_mem_araddr),
        .s_axi_arlen(app_mem_arlen), .s_axi_arsize(app_mem_arsize),
        .s_axi_arburst(app_mem_arburst), .s_axi_arlock(app_mem_arlock),
        .s_axi_arcache(app_mem_arcache), .s_axi_arprot(app_mem_arprot),
        .s_axi_arqos(app_mem_arqos), .s_axi_arvalid(app_mem_arvalid),
        .s_axi_arready(app_mem_arready), .s_axi_rid(app_mem_rid),
        .s_axi_rdata(app_mem_rdata), .s_axi_rresp(app_mem_rresp),
        .s_axi_rlast(app_mem_rlast), .s_axi_rvalid(app_mem_rvalid), .s_axi_rready(app_mem_rready),
        .m_axi_awaddr(memory_awaddr[1]), .m_axi_awid(memory_awid[1]),
        .m_axi_awlen(memory_awlen[1]), .m_axi_awsize(memory_awsize[1]),
        .m_axi_awburst(memory_awburst[1]), .m_axi_awlock(memory_awlock[1]),
        .m_axi_awcache(memory_awcache[1]), .m_axi_awprot(memory_awprot[1]),
        .m_axi_awqos(memory_awqos[1]), .m_axi_awregion(memory_awregion[1]),
        .m_axi_awvalid(memory_awvalid[1]), .m_axi_awready(memory_awready[1]),
        .m_axi_wdata(memory_wdata[1]), .m_axi_wstrb(memory_wstrb[1]),
        .m_axi_wlast(memory_wlast[1]), .m_axi_wvalid(memory_wvalid[1]), .m_axi_wready(memory_wready[1]),
        .m_axi_bid(memory_bid[1]), .m_axi_bresp(memory_bresp[1]),
        .m_axi_bvalid(memory_bvalid[1]), .m_axi_bready(memory_bready[1]),
        .m_axi_araddr(memory_araddr[1]), .m_axi_arid(memory_arid[1]),
        .m_axi_arlen(memory_arlen[1]), .m_axi_arsize(memory_arsize[1]),
        .m_axi_arburst(memory_arburst[1]), .m_axi_arlock(memory_arlock[1]),
        .m_axi_arcache(memory_arcache[1]), .m_axi_arprot(memory_arprot[1]),
        .m_axi_arqos(memory_arqos[1]), .m_axi_arregion(memory_arregion[1]),
        .m_axi_arvalid(memory_arvalid[1]), .m_axi_arready(memory_arready[1]),
        .m_axi_rid(memory_rid[1]), .m_axi_rdata(memory_rdata[1]),
        .m_axi_rresp(memory_rresp[1]), .m_axi_rlast(memory_rlast[1]),
        .m_axi_rvalid(memory_rvalid[1]), .m_axi_rready(memory_rready[1])
    );

    furnace_x3_top #(
        .MAX_TILE_BYTES(LEGAL ? MAX_TILE_BYTES : 4096),
        .RING_DEPTH(LEGAL ? RING_DEPTH : 8),
        .IN_WIDTH(LEGAL ? IN_WIDTH : 8), .IN_HEIGHT(LEGAL ? IN_HEIGHT : 8),
        .OUT_WIDTH(LEGAL ? OUT_WIDTH : 8), .OUT_HEIGHT(LEGAL ? OUT_HEIGHT : 8),
        .FFT_N(LEGAL ? FFT_N : 16), .FUSION_DEPTH(LEGAL ? FUSION_DEPTH : 4),
        .MAILBOX_DEPTH(LEGAL ? MAILBOX_DEPTH : 4),
        .MAX_DMA_BYTES(LEGAL ? MAX_DMA_BYTES : 1048576)
    ) heterogeneous_fabric (
        .clk(clk), .rst_n(system_rst_n), .irq(fabric_irq),
        .s_axil_awaddr(fabric_mmio_awaddr), .s_axil_awprot(fabric_mmio_awprot),
        .s_axil_awvalid(fabric_mmio_awvalid), .s_axil_awready(fabric_mmio_awready),
        .s_axil_wdata(fabric_mmio_wdata), .s_axil_wstrb(fabric_mmio_wstrb),
        .s_axil_wvalid(fabric_mmio_wvalid), .s_axil_wready(fabric_mmio_wready),
        .s_axil_bresp(fabric_mmio_bresp), .s_axil_bvalid(fabric_mmio_bvalid),
        .s_axil_bready(fabric_mmio_bready),
        .s_axil_araddr(fabric_mmio_araddr), .s_axil_arprot(fabric_mmio_arprot),
        .s_axil_arvalid(fabric_mmio_arvalid), .s_axil_arready(fabric_mmio_arready),
        .s_axil_rdata(fabric_mmio_rdata), .s_axil_rresp(fabric_mmio_rresp),
        .s_axil_rvalid(fabric_mmio_rvalid), .s_axil_rready(fabric_mmio_rready),
        .m_axi_awaddr(memory_awaddr[0]), .m_axi_awid(memory_awid[0]),
        .m_axi_awlen(memory_awlen[0]), .m_axi_awsize(memory_awsize[0]),
        .m_axi_awburst(memory_awburst[0]), .m_axi_awlock(memory_awlock[0]),
        .m_axi_awcache(memory_awcache[0]), .m_axi_awprot(memory_awprot[0]),
        .m_axi_awqos(memory_awqos[0]), .m_axi_awregion(memory_awregion[0]),
        .m_axi_awvalid(memory_awvalid[0]), .m_axi_awready(memory_awready[0]),
        .m_axi_wdata(memory_wdata[0]), .m_axi_wstrb(memory_wstrb[0]),
        .m_axi_wlast(memory_wlast[0]), .m_axi_wvalid(memory_wvalid[0]), .m_axi_wready(memory_wready[0]),
        .m_axi_bid(memory_bid[0]), .m_axi_bresp(memory_bresp[0]),
        .m_axi_bvalid(memory_bvalid[0]), .m_axi_bready(memory_bready[0]),
        .m_axi_araddr(memory_araddr[0]), .m_axi_arid(memory_arid[0]),
        .m_axi_arlen(memory_arlen[0]), .m_axi_arsize(memory_arsize[0]),
        .m_axi_arburst(memory_arburst[0]), .m_axi_arlock(memory_arlock[0]),
        .m_axi_arcache(memory_arcache[0]), .m_axi_arprot(memory_arprot[0]),
        .m_axi_arqos(memory_arqos[0]), .m_axi_arregion(memory_arregion[0]),
        .m_axi_arvalid(memory_arvalid[0]), .m_axi_arready(memory_arready[0]),
        .m_axi_rid(memory_rid[0]), .m_axi_rdata(memory_rdata[0]),
        .m_axi_rresp(memory_rresp[0]), .m_axi_rlast(memory_rlast[0]),
        .m_axi_rvalid(memory_rvalid[0]), .m_axi_rready(memory_rready[0]),
        .v_valid(v_valid && system_rst_n), .v_ready(fabric_v_ready),
        .v_pixel(v_pixel), .v_id(v_id), .v_last(v_last && system_rst_n),
        .a_valid(a_valid && system_rst_n), .a_ready(fabric_a_ready),
        .a_sample(a_sample), .a_id(a_id), .a_last(a_last && system_rst_n),
        .mm_valid(fabric_mm_valid), .mm_ready(mm_ready && system_rst_n),
        .mm_id(fabric_mm_id), .mm_result(fabric_mm_result), .mm_error(fabric_mm_error)
    );

    furnace_x4_coherent_memory coherent_memory (
        .clk(clk), .rst_n(system_rst_n),
        .s_cpu_axi_awaddr(memory_awaddr[1]), .s_cpu_axi_awid(memory_awid[1]),
        .s_cpu_axi_awlen(memory_awlen[1]), .s_cpu_axi_awsize(memory_awsize[1]),
        .s_cpu_axi_awburst(memory_awburst[1]), .s_cpu_axi_awlock(memory_awlock[1]),
        .s_cpu_axi_awcache(memory_awcache[1]), .s_cpu_axi_awprot(memory_awprot[1]),
        .s_cpu_axi_awqos(memory_awqos[1]), .s_cpu_axi_awregion(memory_awregion[1]),
        .s_cpu_axi_awvalid(memory_awvalid[1]), .s_cpu_axi_awready(memory_awready[1]),
        .s_cpu_axi_wdata(memory_wdata[1]), .s_cpu_axi_wstrb(memory_wstrb[1]),
        .s_cpu_axi_wlast(memory_wlast[1]), .s_cpu_axi_wvalid(memory_wvalid[1]),
        .s_cpu_axi_wready(memory_wready[1]), .s_cpu_axi_bid(memory_bid[1]),
        .s_cpu_axi_bresp(memory_bresp[1]), .s_cpu_axi_bvalid(memory_bvalid[1]),
        .s_cpu_axi_bready(memory_bready[1]),
        .s_cpu_axi_araddr(memory_araddr[1]), .s_cpu_axi_arid(memory_arid[1]),
        .s_cpu_axi_arlen(memory_arlen[1]), .s_cpu_axi_arsize(memory_arsize[1]),
        .s_cpu_axi_arburst(memory_arburst[1]), .s_cpu_axi_arlock(memory_arlock[1]),
        .s_cpu_axi_arcache(memory_arcache[1]), .s_cpu_axi_arprot(memory_arprot[1]),
        .s_cpu_axi_arqos(memory_arqos[1]), .s_cpu_axi_arregion(memory_arregion[1]),
        .s_cpu_axi_arvalid(memory_arvalid[1]), .s_cpu_axi_arready(memory_arready[1]),
        .s_cpu_axi_rid(memory_rid[1]), .s_cpu_axi_rdata(memory_rdata[1]),
        .s_cpu_axi_rresp(memory_rresp[1]), .s_cpu_axi_rlast(memory_rlast[1]),
        .s_cpu_axi_rvalid(memory_rvalid[1]), .s_cpu_axi_rready(memory_rready[1]),
        .s_fabric_axi_awaddr(memory_awaddr[0]), .s_fabric_axi_awid(memory_awid[0]),
        .s_fabric_axi_awlen(memory_awlen[0]), .s_fabric_axi_awsize(memory_awsize[0]),
        .s_fabric_axi_awburst(memory_awburst[0]), .s_fabric_axi_awlock(memory_awlock[0]),
        .s_fabric_axi_awcache(memory_awcache[0]), .s_fabric_axi_awprot(memory_awprot[0]),
        .s_fabric_axi_awqos(memory_awqos[0]), .s_fabric_axi_awregion(memory_awregion[0]),
        .s_fabric_axi_awvalid(memory_awvalid[0]), .s_fabric_axi_awready(memory_awready[0]),
        .s_fabric_axi_wdata(memory_wdata[0]), .s_fabric_axi_wstrb(memory_wstrb[0]),
        .s_fabric_axi_wlast(memory_wlast[0]), .s_fabric_axi_wvalid(memory_wvalid[0]),
        .s_fabric_axi_wready(memory_wready[0]), .s_fabric_axi_bid(memory_bid[0]),
        .s_fabric_axi_bresp(memory_bresp[0]), .s_fabric_axi_bvalid(memory_bvalid[0]),
        .s_fabric_axi_bready(memory_bready[0]),
        .s_fabric_axi_araddr(memory_araddr[0]), .s_fabric_axi_arid(memory_arid[0]),
        .s_fabric_axi_arlen(memory_arlen[0]), .s_fabric_axi_arsize(memory_arsize[0]),
        .s_fabric_axi_arburst(memory_arburst[0]), .s_fabric_axi_arlock(memory_arlock[0]),
        .s_fabric_axi_arcache(memory_arcache[0]), .s_fabric_axi_arprot(memory_arprot[0]),
        .s_fabric_axi_arqos(memory_arqos[0]), .s_fabric_axi_arregion(memory_arregion[0]),
        .s_fabric_axi_arvalid(memory_arvalid[0]), .s_fabric_axi_arready(memory_arready[0]),
        .s_fabric_axi_rid(memory_rid[0]), .s_fabric_axi_rdata(memory_rdata[0]),
        .s_fabric_axi_rresp(memory_rresp[0]), .s_fabric_axi_rlast(memory_rlast[0]),
        .s_fabric_axi_rvalid(memory_rvalid[0]), .s_fabric_axi_rready(memory_rready[0]),
        .m_axi_awid(m_axi_awid), .m_axi_awaddr(m_axi_awaddr),
        .m_axi_awlen(m_axi_awlen), .m_axi_awsize(m_axi_awsize),
        .m_axi_awburst(m_axi_awburst), .m_axi_awlock(m_axi_awlock),
        .m_axi_awcache(m_axi_awcache), .m_axi_awprot(m_axi_awprot),
        .m_axi_awqos(m_axi_awqos), .m_axi_awregion(m_axi_awregion),
        .m_axi_awvalid(m_axi_awvalid), .m_axi_awready(m_axi_awready),
        .m_axi_wdata(m_axi_wdata), .m_axi_wstrb(m_axi_wstrb),
        .m_axi_wlast(m_axi_wlast), .m_axi_wvalid(m_axi_wvalid), .m_axi_wready(m_axi_wready),
        .m_axi_bid(m_axi_bid), .m_axi_bresp(m_axi_bresp),
        .m_axi_bvalid(m_axi_bvalid), .m_axi_bready(m_axi_bready),
        .m_axi_arid(m_axi_arid), .m_axi_araddr(m_axi_araddr),
        .m_axi_arlen(m_axi_arlen), .m_axi_arsize(m_axi_arsize),
        .m_axi_arburst(m_axi_arburst), .m_axi_arlock(m_axi_arlock),
        .m_axi_arcache(m_axi_arcache), .m_axi_arprot(m_axi_arprot),
        .m_axi_arqos(m_axi_arqos), .m_axi_arregion(m_axi_arregion),
        .m_axi_arvalid(m_axi_arvalid), .m_axi_arready(m_axi_arready),
        .m_axi_rid(m_axi_rid), .m_axi_rdata(m_axi_rdata), .m_axi_rresp(m_axi_rresp),
        .m_axi_rlast(m_axi_rlast), .m_axi_rvalid(m_axi_rvalid), .m_axi_rready(m_axi_rready),
        .coh_req_valid(coh_req_valid), .coh_req_ready(coh_req_ready),
        .coh_rsp_valid(coh_rsp_valid), .coh_rsp_ready(coh_rsp_ready),
        .coh_rsp_error(coh_rsp_error),
        .coh_release_valid(coh_release_valid), .coh_release_ready(coh_release_ready)
    );
endmodule
