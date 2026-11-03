module furnace_x4_coherent_memory (
    input wire clk, rst_n,
    input wire [3:0] s_cpu_axi_awid,
    input wire [31:0] s_cpu_axi_awaddr,
    input wire [7:0] s_cpu_axi_awlen,
    input wire [2:0] s_cpu_axi_awsize,
    input wire [1:0] s_cpu_axi_awburst,
    input wire s_cpu_axi_awlock,
    input wire [3:0] s_cpu_axi_awcache,
    input wire [2:0] s_cpu_axi_awprot,
    input wire [3:0] s_cpu_axi_awqos, s_cpu_axi_awregion,
    input wire s_cpu_axi_awvalid,
    output wire s_cpu_axi_awready,
    input wire [511:0] s_cpu_axi_wdata,
    input wire [63:0] s_cpu_axi_wstrb,
    input wire s_cpu_axi_wlast, s_cpu_axi_wvalid,
    output wire s_cpu_axi_wready,
    output wire [3:0] s_cpu_axi_bid,
    output wire [1:0] s_cpu_axi_bresp,
    output wire s_cpu_axi_bvalid,
    input wire s_cpu_axi_bready,
    input wire [3:0] s_cpu_axi_arid,
    input wire [31:0] s_cpu_axi_araddr,
    input wire [7:0] s_cpu_axi_arlen,
    input wire [2:0] s_cpu_axi_arsize,
    input wire [1:0] s_cpu_axi_arburst,
    input wire s_cpu_axi_arlock,
    input wire [3:0] s_cpu_axi_arcache,
    input wire [2:0] s_cpu_axi_arprot,
    input wire [3:0] s_cpu_axi_arqos, s_cpu_axi_arregion,
    input wire s_cpu_axi_arvalid,
    output wire s_cpu_axi_arready,
    output wire [3:0] s_cpu_axi_rid,
    output wire [511:0] s_cpu_axi_rdata,
    output wire [1:0] s_cpu_axi_rresp,
    output wire s_cpu_axi_rlast, s_cpu_axi_rvalid,
    input wire s_cpu_axi_rready,
    input wire [3:0] s_fabric_axi_awid,
    input wire [31:0] s_fabric_axi_awaddr,
    input wire [7:0] s_fabric_axi_awlen,
    input wire [2:0] s_fabric_axi_awsize,
    input wire [1:0] s_fabric_axi_awburst,
    input wire s_fabric_axi_awlock,
    input wire [3:0] s_fabric_axi_awcache,
    input wire [2:0] s_fabric_axi_awprot,
    input wire [3:0] s_fabric_axi_awqos, s_fabric_axi_awregion,
    input wire s_fabric_axi_awvalid,
    output wire s_fabric_axi_awready,
    input wire [511:0] s_fabric_axi_wdata,
    input wire [63:0] s_fabric_axi_wstrb,
    input wire s_fabric_axi_wlast, s_fabric_axi_wvalid,
    output wire s_fabric_axi_wready,
    output wire [3:0] s_fabric_axi_bid,
    output wire [1:0] s_fabric_axi_bresp,
    output wire s_fabric_axi_bvalid,
    input wire s_fabric_axi_bready,
    input wire [3:0] s_fabric_axi_arid,
    input wire [31:0] s_fabric_axi_araddr,
    input wire [7:0] s_fabric_axi_arlen,
    input wire [2:0] s_fabric_axi_arsize,
    input wire [1:0] s_fabric_axi_arburst,
    input wire s_fabric_axi_arlock,
    input wire [3:0] s_fabric_axi_arcache,
    input wire [2:0] s_fabric_axi_arprot,
    input wire [3:0] s_fabric_axi_arqos, s_fabric_axi_arregion,
    input wire s_fabric_axi_arvalid,
    output wire s_fabric_axi_arready,
    output wire [3:0] s_fabric_axi_rid,
    output wire [511:0] s_fabric_axi_rdata,
    output wire [1:0] s_fabric_axi_rresp,
    output wire s_fabric_axi_rlast, s_fabric_axi_rvalid,
    input wire s_fabric_axi_rready,
    output wire [4:0] m_axi_awid,
    output wire [31:0] m_axi_awaddr,
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
    output wire [4:0] m_axi_arid,
    output wire [31:0] m_axi_araddr,
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
    output wire m_axi_rready,
    output wire coh_req_valid,
    input wire coh_req_ready,
    input wire coh_rsp_valid, coh_rsp_error,
    output wire coh_rsp_ready,
    output wire coh_release_valid,
    input wire coh_release_ready
);
    typedef struct packed {
        logic [31:0] addr;
        logic [3:0] id;
        logic [7:0] len;
        logic [2:0] size;
        logic [1:0] burst;
        logic lock;
        logic [3:0] cache;
        logic [2:0] prot;
        logic [3:0] qos;
        logic [3:0] region;
    } header_t;
    header_t cw, cr, fw, fr, active;
    wire [64:0] cpu_aw_header = {s_cpu_axi_awaddr,s_cpu_axi_awid,
        s_cpu_axi_awlen,s_cpu_axi_awsize,s_cpu_axi_awburst,s_cpu_axi_awlock,
        s_cpu_axi_awcache,s_cpu_axi_awprot,s_cpu_axi_awqos,s_cpu_axi_awregion};
    wire [64:0] cpu_ar_header = {s_cpu_axi_araddr,s_cpu_axi_arid,
        s_cpu_axi_arlen,s_cpu_axi_arsize,s_cpu_axi_arburst,s_cpu_axi_arlock,
        s_cpu_axi_arcache,s_cpu_axi_arprot,s_cpu_axi_arqos,s_cpu_axi_arregion};
    wire [64:0] fabric_aw_header = {s_fabric_axi_awaddr,s_fabric_axi_awid,
        s_fabric_axi_awlen,s_fabric_axi_awsize,s_fabric_axi_awburst,s_fabric_axi_awlock,
        s_fabric_axi_awcache,s_fabric_axi_awprot,s_fabric_axi_awqos,s_fabric_axi_awregion};
    wire [64:0] fabric_ar_header = {s_fabric_axi_araddr,s_fabric_axi_arid,
        s_fabric_axi_arlen,s_fabric_axi_arsize,s_fabric_axi_arburst,s_fabric_axi_arlock,
        s_fabric_axi_arcache,s_fabric_axi_arprot,s_fabric_axi_arqos,s_fabric_axi_arregion};
    wire [1:0] cw_geometry, cr_geometry, fw_geometry, fr_geometry;
    furnace_x4_axi_geometry cpu_write_geometry (
        .addr(s_cpu_axi_awaddr), .len(s_cpu_axi_awlen), .size(s_cpu_axi_awsize),
        .burst(s_cpu_axi_awburst), .lock(s_cpu_axi_awlock), .status(cw_geometry));
    furnace_x4_axi_geometry cpu_read_geometry (
        .addr(s_cpu_axi_araddr), .len(s_cpu_axi_arlen), .size(s_cpu_axi_arsize),
        .burst(s_cpu_axi_arburst), .lock(s_cpu_axi_arlock), .status(cr_geometry));
    furnace_x4_axi_geometry fabric_write_geometry (
        .addr(s_fabric_axi_awaddr), .len(s_fabric_axi_awlen), .size(s_fabric_axi_awsize),
        .burst(s_fabric_axi_awburst), .lock(s_fabric_axi_awlock), .status(fw_geometry));
    furnace_x4_axi_geometry fabric_read_geometry (
        .addr(s_fabric_axi_araddr), .len(s_fabric_axi_arlen), .size(s_fabric_axi_arsize),
        .burst(s_fabric_axi_arburst), .lock(s_fabric_axi_arlock), .status(fr_geometry));

    reg cw_full, cr_full, fw_full, fr_full;
    reg cw_inflight, cr_inflight;
    reg cb_valid, rr_valid, fb_valid, fr_done;
    reg [1:0] cw_status, cr_status, fw_status, fr_status, cb_status, rr_status, fb_status;
    reg [511:0] cw_data, rr_data, fr_data;
    reg [63:0] cw_mask;
    reg [8:0] cw_count, fw_count;
    reg cw_first_last, cw_last_bad;
    reg [7:0] cr_error_remaining;
    wire cw_complete = cw_full && cw_count == {1'b0,cw.len} + 9'd1;
    wire fw_complete = fw_full && fw_count == {1'b0,fw.len} + 9'd1;
    wire cpu_write_bad_last = cw_last_bad ||
        (cw.len == 0 && !cw_first_last) || (cw.len != 0 && cw_first_last);
    wire cpu_write_eligible = cw_complete && !cw_inflight && !cb_valid;
    wire cpu_read_eligible = cr_full && !cr_inflight && !rr_valid;
    reg prefer_cpu, prefer_cpu_write, prefer_fabric_write;

    localparam [2:0] FIDLE=0, FREQUEST=1, FWAIT=2, FOWNED=3,
        FRELEASE=4, FPUBLISH=5, FLOCKED=6;
    reg [2:0] fabric_state;
    reg fabric_write, coherence_fault;
    reg [1:0] fabric_completion_status;
    localparam [3:0] GIDLE=0, GPREPARE=1, GAW=2, GWLOAD=3, GWLATENCY=4,
        GWSEND=5, GBWAIT=6, GAR=7, GRWAIT=8;
    reg [3:0] state;
    reg owner_cpu, active_write;
    reg [31:0] address_q;
    reg [8:0] remaining, segment_beats, segment_index, total_index;
    reg [1:0] write_status;
    wire [4:0] endpoint_id = {owner_cpu,active.id};
    wire [12:0] boundary_bytes = 13'd4096 - {1'b0,address_q[11:0]};
    wire [12:0] boundary_beats = boundary_bytes >> active.size;
    wire [8:0] segment_next = active.burst == 1 && boundary_beats < {4'b0,remaining} ?
        boundary_beats[8:0] : remaining;
    wire [31:0] segment_bytes = {23'b0,segment_beats} << active.size;
    wire [1:0] checked_bresp = m_axi_bid != endpoint_id || m_axi_bresp == 1 ?
        2'b10 : m_axi_bresp;
    wire [1:0] combined_bresp = write_status == 3 || checked_bresp == 3 ? 2'b11 :
        write_status != 0 || checked_bresp != 0 ? 2'b10 : 2'b00;
    wire [1:0] checked_rresp = m_axi_rid != endpoint_id || m_axi_rresp == 1 ||
        m_axi_rlast != (segment_index == segment_beats - 9'd1) ? 2'b10 : m_axi_rresp;

    localparam [1:0] VSTART=0, VLOAD=1, VLATENCY=2, VCHECK=3;
    reg [1:0] validation_state;
    reg validation_done;
    reg [7:0] validation_index;
    reg [31:0] validation_address;
    wire [31:0] validation_step = 32'd1 << fw.size;
    wire [31:0] validation_wrap_mask =
        (({24'b0,fw.len} + 32'd1) << fw.size) - 32'd1;
    wire [31:0] validation_incremented = validation_address + validation_step;
    wire [31:0] validation_next = fw.burst == 0 ? validation_address :
        fw.burst == 1 ? validation_incremented :
        (validation_address & ~validation_wrap_mask) |
        (validation_incremented & validation_wrap_mask);
    wire [63:0] validation_mask =
        (64'hffffffffffffffff >> (7'd64 - (7'd1 << fw.size))) << validation_address[5:0];
    wire [511:0] write_ram_data;
    wire [64:0] write_ram_meta;
    wire write_ram_read = rst_n && (validation_state == VLOAD || state == GWLOAD);
    wire [7:0] write_ram_addr = validation_state == VLOAD ?
        validation_index : total_index[7:0];
    furnace_x4_burst_store #(.META_WIDTH(65)) write_buffer (
        .clk(clk),
        .write_en(s_fabric_axi_wvalid && s_fabric_axi_wready),
        .write_addr(fw_count[7:0]), .write_data(s_fabric_axi_wdata),
        .write_meta({s_fabric_axi_wlast,s_fabric_axi_wstrb}),
        .read_en(write_ram_read), .read_addr(write_ram_addr),
        .read_data(write_ram_data), .read_meta(write_ram_meta));
    wire write_strobe_bad = |(write_ram_meta[63:0] & ~validation_mask);
    wire write_last_bad = write_ram_meta[64] != (validation_index == fw.len);
    wire fabric_write_eligible = fw_full && validation_done && !fb_valid;
    wire fabric_read_eligible = fr_full && !fr_done;
    wire cpu_eligible = cpu_write_eligible || cpu_read_eligible;
    wire fabric_eligible = !coherence_fault &&
        (fabric_write_eligible || fabric_read_eligible);
    wire select_cpu_write = cpu_write_eligible &&
        (!cpu_read_eligible || prefer_cpu_write);
    wire select_fabric_write = fabric_write_eligible &&
        (!fabric_read_eligible || prefer_fabric_write);
    wire select_fabric = fabric_state == FIDLE && fabric_eligible &&
        (!cpu_eligible || !prefer_cpu);

    localparam [1:0] RIDLE=0, RLOAD=1, RLATENCY=2, RHOLD=3;
    reg [1:0] publication_state;
    reg [7:0] publication_index;
    reg fr_synthetic;
    reg [1:0] fr_beat_status;
    wire [511:0] read_ram_data;
    wire [1:0] read_ram_meta;
    furnace_x4_burst_store #(.META_WIDTH(2)) read_buffer (
        .clk(clk),
        .write_en(rst_n && state == GRWAIT && !owner_cpu && m_axi_rvalid),
        .write_addr(total_index[7:0]), .write_data(m_axi_rdata),
        .write_meta(checked_rresp),
        .read_en(rst_n && publication_state == RLOAD && !fr_synthetic),
        .read_addr(publication_index),
        .read_data(read_ram_data), .read_meta(read_ram_meta));

    assign s_cpu_axi_awready = rst_n && !cw_full;
    assign s_cpu_axi_wready = rst_n && !cb_valid && !cw_inflight &&
        (cw_count == 0 || (cw_full && !cw_complete));
    assign s_cpu_axi_bvalid = rst_n && cb_valid;
    assign s_cpu_axi_bid = s_cpu_axi_bvalid ? cw.id : 4'b0;
    assign s_cpu_axi_bresp = s_cpu_axi_bvalid ? cb_status : 2'b0;
    assign s_cpu_axi_arready = rst_n && !cr_full;
    assign s_cpu_axi_rvalid = rst_n && rr_valid;
    assign s_cpu_axi_rid = s_cpu_axi_rvalid ? cr.id : 4'b0;
    assign s_cpu_axi_rdata = s_cpu_axi_rvalid ? rr_data : 512'b0;
    assign s_cpu_axi_rresp = s_cpu_axi_rvalid ? rr_status : 2'b0;
    assign s_cpu_axi_rlast = s_cpu_axi_rvalid && cr_error_remaining == 0;
    assign s_fabric_axi_awready = rst_n && !fw_full && !coherence_fault;
    assign s_fabric_axi_wready = rst_n && fw_full && !fw_complete && !fb_valid;
    assign s_fabric_axi_bvalid = rst_n && fb_valid;
    assign s_fabric_axi_bid = s_fabric_axi_bvalid ? fw.id : 4'b0;
    assign s_fabric_axi_bresp = s_fabric_axi_bvalid ? fb_status : 2'b0;
    assign s_fabric_axi_arready = rst_n && !fr_full && !coherence_fault;
    assign s_fabric_axi_rvalid = rst_n && publication_state == RHOLD;
    assign s_fabric_axi_rid = s_fabric_axi_rvalid ? fr.id : 4'b0;
    assign s_fabric_axi_rdata = s_fabric_axi_rvalid ? fr_data : 512'b0;
    assign s_fabric_axi_rresp = s_fabric_axi_rvalid ? fr_beat_status : 2'b0;
    assign s_fabric_axi_rlast = s_fabric_axi_rvalid && publication_index == fr.len;
    assign coh_req_valid = rst_n && fabric_state == FREQUEST && !coherence_fault;
    assign coh_rsp_ready = rst_n && fabric_state == FWAIT;
    assign coh_release_valid = rst_n && fabric_state == FRELEASE && !coherence_fault;

    assign m_axi_awvalid = rst_n && state == GAW;
    assign m_axi_awid = endpoint_id;
    assign m_axi_awaddr = address_q;
    assign m_axi_awlen = segment_beats[7:0] - 8'd1;
    assign m_axi_awsize = active.size;
    assign m_axi_awburst = active.burst;
    assign m_axi_awlock = active.lock;
    assign m_axi_awcache = active.cache;
    assign m_axi_awprot = active.prot;
    assign m_axi_awqos = active.qos;
    assign m_axi_awregion = active.region;
    assign m_axi_wvalid = rst_n && state == GWSEND;
    assign m_axi_wdata = owner_cpu ? cw_data : write_ram_data;
    assign m_axi_wstrb = owner_cpu ? cw_mask : write_ram_meta[63:0];
    assign m_axi_wlast = m_axi_wvalid && segment_index == segment_beats - 9'd1;
    assign m_axi_bready = rst_n && state == GBWAIT;
    assign m_axi_arvalid = rst_n && state == GAR;
    assign m_axi_arid = endpoint_id;
    assign m_axi_araddr = address_q;
    assign m_axi_arlen = segment_beats[7:0] - 8'd1;
    assign m_axi_arsize = active.size;
    assign m_axi_arburst = active.burst;
    assign m_axi_arlock = active.lock;
    assign m_axi_arcache = active.cache;
    assign m_axi_arprot = active.prot;
    assign m_axi_arqos = active.qos;
    assign m_axi_arregion = active.region;
    assign m_axi_rready = rst_n && state == GRWAIT;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cw <= 0;
            cr <= 0;
            fw <= 0;
            fr <= 0;
            active <= 0;
            cw_full <= 0;
            cr_full <= 0;
            fw_full <= 0;
            fr_full <= 0;
            cw_inflight <= 0;
            cr_inflight <= 0;
            cb_valid <= 0;
            rr_valid <= 0;
            fb_valid <= 0;
            fr_done <= 0;
            cw_status <= 0;
            cr_status <= 0;
            fw_status <= 0;
            fr_status <= 0;
            cb_status <= 0;
            rr_status <= 0;
            fb_status <= 0;
            cw_data <= 0;
            rr_data <= 0;
            fr_data <= 0;
            cw_mask <= 0;
            cw_count <= 0;
            fw_count <= 0;
            cw_first_last <= 0;
            cw_last_bad <= 0;
            cr_error_remaining <= 0;
            prefer_cpu <= 1;
            prefer_cpu_write <= 1;
            prefer_fabric_write <= 1;
            fabric_state <= FIDLE;
            fabric_write <= 0;
            coherence_fault <= 0;
            fabric_completion_status <= 0;
            state <= GIDLE;
            owner_cpu <= 0;
            active_write <= 0;
            address_q <= 0;
            remaining <= 0;
            segment_beats <= 0;
            segment_index <= 0;
            total_index <= 0;
            write_status <= 0;
            validation_state <= VSTART;
            validation_done <= 0;
            validation_index <= 0;
            validation_address <= 0;
            publication_state <= RIDLE;
            publication_index <= 0;
            fr_synthetic <= 0;
            fr_beat_status <= 0;
        end else begin
            if (s_cpu_axi_awvalid && s_cpu_axi_awready) begin
                cw <= cpu_aw_header;
                cw_full <= 1;
                cw_status <= cw_geometry != 0 ? cw_geometry :
                    s_cpu_axi_awlen != 0 || s_cpu_axi_awsize != 6 ||
                    s_cpu_axi_awburst != 1 ? 2'b10 : 2'b0;
            end
            if (s_cpu_axi_wvalid && s_cpu_axi_wready) begin
                cw_count <= cw_count + 9'd1;
                if (cw_count == 0) begin
                    cw_data <= s_cpu_axi_wdata;
                    cw_mask <= s_cpu_axi_wstrb;
                    cw_first_last <= s_cpu_axi_wlast;
                end else if (s_cpu_axi_wlast != (cw_count == {1'b0,cw.len}))
                    cw_last_bad <= 1;
            end
            if (s_cpu_axi_arvalid && s_cpu_axi_arready) begin
                cr <= cpu_ar_header;
                cr_full <= 1;
                cr_status <= cr_geometry != 0 ? cr_geometry :
                    s_cpu_axi_arlen != 0 || s_cpu_axi_arsize != 6 ||
                    s_cpu_axi_arburst != 1 ? 2'b10 : 2'b0;
                cr_error_remaining <= s_cpu_axi_arlen;
            end
            if (s_cpu_axi_bvalid && s_cpu_axi_bready) begin
                cb_valid <= 0;
                cw_full <= 0;
                cw_inflight <= 0;
                cw_count <= 0;
                cw_last_bad <= 0;
            end
            if (s_cpu_axi_rvalid && s_cpu_axi_rready) begin
                if (cr_error_remaining != 0)
                    cr_error_remaining <= cr_error_remaining - 8'd1;
                else begin
                    rr_valid <= 0;
                    cr_full <= 0;
                    cr_inflight <= 0;
                end
            end
            if (s_fabric_axi_awvalid && s_fabric_axi_awready) begin
                fw <= fabric_aw_header;
                fw_full <= 1;
                fw_status <= fw_geometry;
            end
            if (s_fabric_axi_wvalid && s_fabric_axi_wready)
                fw_count <= fw_count + 9'd1;
            if (s_fabric_axi_arvalid && s_fabric_axi_arready) begin
                fr <= fabric_ar_header;
                fr_full <= 1;
                fr_status <= fr_geometry;
            end
            if (s_fabric_axi_bvalid && s_fabric_axi_bready) begin
                fb_valid <= 0;
                fw_full <= 0;
                fw_count <= 0;
                validation_done <= 0;
                validation_state <= VSTART;
            end

            if (!validation_done && !coherence_fault) begin
                case (validation_state)
                    VSTART: if (fw_complete) begin
                        validation_index <= 0;
                        validation_address <= fw.addr;
                        validation_state <= VLOAD;
                    end
                    VLOAD: validation_state <= VLATENCY;
                    VLATENCY: validation_state <= VCHECK;
                    VCHECK: begin
                        if ((write_strobe_bad || write_last_bad) && fw_status == 0)
                            fw_status <= 2'b10;
                        if (validation_index == fw.len) begin
                            validation_done <= 1;
                            validation_state <= VSTART;
                        end else begin
                            validation_index <= validation_index + 8'd1;
                            validation_address <= validation_next;
                            validation_state <= VLOAD;
                        end
                    end
                    default: validation_state <= VSTART;
                endcase
            end

            case (publication_state)
                RIDLE: if (fr_done) begin
                    publication_index <= 0;
                    publication_state <= RLOAD;
                end
                RLOAD: publication_state <= RLATENCY;
                RLATENCY: begin
                    fr_data <= fr_synthetic ? 512'b0 : read_ram_data;
                    fr_beat_status <= fr_synthetic ? fr_status : read_ram_meta;
                    publication_state <= RHOLD;
                end
                RHOLD: if (s_fabric_axi_rready) begin
                    if (publication_index == fr.len) begin
                        fr_full <= 0;
                        fr_done <= 0;
                        publication_state <= RIDLE;
                    end else begin
                        publication_index <= publication_index + 8'd1;
                        publication_state <= RLOAD;
                    end
                end
                default: publication_state <= RIDLE;
            endcase

            case (fabric_state)
                FIDLE: begin end
                FREQUEST: if (coh_req_ready) fabric_state <= FWAIT;
                FWAIT: if (coh_rsp_valid) begin
                    if (coh_rsp_error) begin
                        coherence_fault <= 1;
                        fabric_state <= FLOCKED;
                    end else fabric_state <= FOWNED;
                end
                FOWNED: begin end
                FRELEASE: if (coh_release_ready) fabric_state <= FPUBLISH;
                FPUBLISH: begin
                    if (fabric_write) begin
                        fb_status <= fabric_completion_status;
                        fb_valid <= 1;
                    end else begin
                        fr_synthetic <= 0;
                        fr_done <= 1;
                    end
                    prefer_fabric_write <= !fabric_write;
                    prefer_cpu <= 1;
                    fabric_state <= FIDLE;
                end
                FLOCKED: begin end
                default: begin
                    coherence_fault <= 1;
                    fabric_state <= FLOCKED;
                end
            endcase
            if (coherence_fault) begin
                if (fw_complete && !fb_valid) begin
                    fb_status <= 2'b10;
                    fb_valid <= 1;
                end
                if (fr_full && !fr_done) begin
                    fr_synthetic <= 1;
                    fr_status <= 2'b10;
                    fr_done <= 1;
                end
            end

            case (state)
                GIDLE: begin
                    if (fabric_state == FOWNED) begin
                        owner_cpu <= 0;
                        active_write <= fabric_write;
                        active <= fabric_write ? fw : fr;
                        address_q <= fabric_write ? fw.addr : fr.addr;
                        remaining <= {1'b0,(fabric_write ? fw.len : fr.len)} + 9'd1;
                        segment_index <= 0;
                        total_index <= 0;
                        write_status <= 0;
                        state <= GPREPARE;
                    end else if (select_fabric) begin
                        fabric_write <= select_fabric_write;
                        prefer_cpu <= 1;
                        if (select_fabric_write && fw_status != 0) begin
                            fb_status <= fw_status;
                            fb_valid <= 1;
                            prefer_fabric_write <= 0;
                        end else if (!select_fabric_write && fr_status != 0) begin
                            fr_synthetic <= 1;
                            fr_done <= 1;
                            prefer_fabric_write <= 1;
                        end else fabric_state <= FREQUEST;
                    end else if (cpu_eligible) begin
                        owner_cpu <= 1;
                        active_write <= select_cpu_write;
                        active <= select_cpu_write ? cw : cr;
                        address_q <= select_cpu_write ? cw.addr : cr.addr;
                        remaining <= 1;
                        total_index <= 0;
                        segment_index <= 0;
                        write_status <= 0;
                        if (select_cpu_write) begin
                            cw_inflight <= 1;
                            if (cw_status != 0 || cpu_write_bad_last) begin
                                cb_status <= cw_status != 0 ? cw_status : 2'b10;
                                cb_valid <= 1;
                                prefer_cpu_write <= 0;
                                prefer_cpu <= 0;
                            end else state <= GPREPARE;
                        end else begin
                            cr_inflight <= 1;
                            if (cr_status != 0) begin
                                rr_status <= cr_status;
                                rr_data <= 0;
                                rr_valid <= 1;
                                prefer_cpu_write <= 1;
                                prefer_cpu <= 0;
                            end else state <= GPREPARE;
                        end
                    end
                end
                GPREPARE: begin
                    segment_beats <= segment_next;
                    segment_index <= 0;
                    if (active_write) state <= GAW;
                    else state <= GAR;
                end
                GAW: if (m_axi_awready) begin
                    if (owner_cpu) state <= GWSEND;
                    else state <= GWLOAD;
                end
                GWLOAD: state <= GWLATENCY;
                GWLATENCY: state <= GWSEND;
                GWSEND: if (m_axi_wready) begin
                    total_index <= total_index + 9'd1;
                    if (segment_index == segment_beats - 9'd1) state <= GBWAIT;
                    else begin
                        segment_index <= segment_index + 9'd1;
                        state <= GWLOAD;
                    end
                end
                GBWAIT: if (m_axi_bvalid) begin
                    write_status <= combined_bresp;
                    if (remaining == segment_beats) begin
                        state <= GIDLE;
                        if (owner_cpu) begin
                            cb_status <= combined_bresp;
                            cb_valid <= 1;
                            prefer_cpu_write <= 0;
                            prefer_cpu <= 0;
                        end else begin
                            fabric_completion_status <= combined_bresp;
                            fabric_state <= FRELEASE;
                        end
                    end else begin
                        remaining <= remaining - segment_beats;
                        if (active.burst == 1) address_q <= address_q + segment_bytes;
                        state <= GPREPARE;
                    end
                end
                GAR: if (m_axi_arready) state <= GRWAIT;
                GRWAIT: if (m_axi_rvalid) begin
                    total_index <= total_index + 9'd1;
                    if (segment_index == segment_beats - 9'd1) begin
                        if (remaining == segment_beats) begin
                            state <= GIDLE;
                            if (owner_cpu) begin
                                rr_data <= m_axi_rdata;
                                rr_status <= checked_rresp;
                                rr_valid <= 1;
                                prefer_cpu_write <= 1;
                                prefer_cpu <= 0;
                            end else begin
                                fabric_completion_status <= 0;
                                fabric_state <= FRELEASE;
                            end
                        end else begin
                            remaining <= remaining - segment_beats;
                            if (active.burst == 1) address_q <= address_q + segment_bytes;
                            state <= GPREPARE;
                        end
                    end else segment_index <= segment_index + 9'd1;
                end
                default: state <= GIDLE;
            endcase
        end
    end
endmodule
