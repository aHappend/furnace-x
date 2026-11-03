module furnace_x4_cpu_axi512_bridge (
    input wire clk, rst_n,
    input wire [3:0] s_axi_awid,
    input wire [63:0] s_axi_awaddr,
    input wire [7:0] s_axi_awlen,
    input wire [2:0] s_axi_awsize,
    input wire [1:0] s_axi_awburst,
    input wire s_axi_awlock,
    input wire [3:0] s_axi_awcache,
    input wire [2:0] s_axi_awprot,
    input wire [3:0] s_axi_awqos,
    input wire s_axi_awvalid,
    output wire s_axi_awready,
    input wire [63:0] s_axi_wdata,
    input wire [7:0] s_axi_wstrb,
    input wire s_axi_wlast, s_axi_wvalid,
    output wire s_axi_wready,
    output wire [3:0] s_axi_bid,
    output wire [1:0] s_axi_bresp,
    output wire s_axi_bvalid,
    input wire s_axi_bready,
    input wire [3:0] s_axi_arid,
    input wire [63:0] s_axi_araddr,
    input wire [7:0] s_axi_arlen,
    input wire [2:0] s_axi_arsize,
    input wire [1:0] s_axi_arburst,
    input wire s_axi_arlock,
    input wire [3:0] s_axi_arcache,
    input wire [2:0] s_axi_arprot,
    input wire [3:0] s_axi_arqos,
    input wire s_axi_arvalid,
    output wire s_axi_arready,
    output wire [3:0] s_axi_rid,
    output wire [63:0] s_axi_rdata,
    output wire [1:0] s_axi_rresp,
    output wire s_axi_rlast, s_axi_rvalid,
    input wire s_axi_rready,
    output wire [3:0] m_axi_awid,
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
    input wire [3:0] m_axi_bid,
    input wire [1:0] m_axi_bresp,
    input wire m_axi_bvalid,
    output wire m_axi_bready,
    output wire [3:0] m_axi_arid,
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
    input wire [3:0] m_axi_rid,
    input wire [511:0] m_axi_rdata,
    input wire [1:0] m_axi_rresp,
    input wire m_axi_rlast, m_axi_rvalid,
    output wire m_axi_rready
);
    localparam [1:0] COLLECT=0, ISSUE=1, WAIT_RESPONSE=2, RESPONSE=3;
    reg [1:0] ws, rs;
    reg aw_full, aw_sent, w_sent, wlast_first, wlast_error;
    reg [8:0] wcount;
    reg [63:0] awaddr_q, araddr_q, wdata_q, rdata_q;
    reg [3:0] awid_q, arid_q, awcache_q, arcache_q, awqos_q, arqos_q;
    reg [2:0] awprot_q, arprot_q;
    reg [7:0] awlen_q, wstrb_q, read_remaining;
    reg [1:0] awresp_q, bresp_q, rresp_q;
    reg read_error;
    wire [64:0] aw_bytes = ({57'b0,s_axi_awlen} + 65'd1) << s_axi_awsize;
    wire [64:0] ar_bytes = ({57'b0,s_axi_arlen} + 65'd1) << s_axi_arsize;
    wire [64:0] aw_end = {1'b0,s_axi_awaddr} + aw_bytes - 65'd1;
    wire [64:0] ar_end = {1'b0,s_axi_araddr} + ar_bytes - 65'd1;
    wire aw_address_bad = s_axi_awaddr < 64'h80000000 ||
        aw_end > 65'h087ffffff || |s_axi_awaddr[2:0];
    wire ar_address_bad = s_axi_araddr < 64'h80000000 ||
        ar_end > 65'h087ffffff || |s_axi_araddr[2:0];
    wire aw_geometry_bad = s_axi_awlen != 0 || s_axi_awsize != 3 ||
        s_axi_awburst != 1 || s_axi_awlock;
    wire ar_geometry_bad = s_axi_arlen != 0 || s_axi_arsize != 3 ||
        s_axi_arburst != 1 || s_axi_arlock;
    wire write_complete = aw_full && wcount == {1'b0,awlen_q} + 9'd1;
    wire aw_capture = s_axi_awvalid && s_axi_awready;
    wire w_capture = s_axi_wvalid && s_axi_wready;
    wire [7:0] collected_awlen = aw_full ? awlen_q : s_axi_awlen;
    wire [1:0] collected_awresp = aw_full ? awresp_q :
        aw_address_bad ? 2'b11 : aw_geometry_bad ? 2'b10 : 2'b0;
    wire [8:0] collected_wcount = wcount + {8'b0,w_capture};
    wire collected_wlast_first = wcount == 0 && w_capture ?
        s_axi_wlast : wlast_first;
    wire collected_wlast_error = wlast_error ||
        (w_capture && wcount != 0 &&
         s_axi_wlast != (wcount == {1'b0,collected_awlen}));
    wire write_collected = (aw_full || aw_capture) &&
        collected_wcount == {1'b0,collected_awlen} + 9'd1;
    wire write_last_bad = collected_wlast_error ||
        (collected_awlen == 0 && !collected_wlast_first) ||
        (collected_awlen != 0 && collected_wlast_first);

    assign s_axi_awready = rst_n && ws == COLLECT && !aw_full;
    assign s_axi_wready = rst_n && ws == COLLECT &&
        (wcount == 0 || (aw_full && !write_complete));
    assign s_axi_bvalid = rst_n && ws == RESPONSE;
    assign s_axi_bid = s_axi_bvalid ? awid_q : 4'b0;
    assign s_axi_bresp = s_axi_bvalid ? bresp_q : 2'b0;
    assign s_axi_arready = rst_n && rs == COLLECT;
    assign s_axi_rvalid = rst_n && rs == RESPONSE;
    assign s_axi_rid = s_axi_rvalid ? arid_q : 4'b0;
    assign s_axi_rdata = s_axi_rvalid ? rdata_q : 64'b0;
    assign s_axi_rresp = s_axi_rvalid ? rresp_q : 2'b0;
    assign s_axi_rlast = s_axi_rvalid && read_remaining == 0;

    assign m_axi_awvalid = rst_n && ws == ISSUE && !aw_sent;
    assign m_axi_awid = awid_q;
    assign m_axi_awaddr = {awaddr_q[31:6],6'b0};
    assign m_axi_awlen = 0;
    assign m_axi_awsize = 6;
    assign m_axi_awburst = 1;
    assign m_axi_awlock = 0;
    assign m_axi_awcache = awcache_q;
    assign m_axi_awprot = awprot_q;
    assign m_axi_awqos = awqos_q;
    assign m_axi_awregion = 0;
    assign m_axi_wvalid = rst_n && ws == ISSUE && !w_sent;
    assign m_axi_wdata = {448'b0,wdata_q} << {awaddr_q[5:3],6'b0};
    assign m_axi_wstrb = {56'b0,wstrb_q} << {awaddr_q[5:3],3'b0};
    assign m_axi_wlast = m_axi_wvalid;
    assign m_axi_bready = rst_n && ws == WAIT_RESPONSE;
    assign m_axi_arvalid = rst_n && rs == ISSUE;
    assign m_axi_arid = arid_q;
    assign m_axi_araddr = {araddr_q[31:6],6'b0};
    assign m_axi_arlen = 0;
    assign m_axi_arsize = 6;
    assign m_axi_arburst = 1;
    assign m_axi_arlock = 0;
    assign m_axi_arcache = arcache_q;
    assign m_axi_arprot = arprot_q;
    assign m_axi_arqos = arqos_q;
    assign m_axi_arregion = 0;
    assign m_axi_rready = rst_n && rs == WAIT_RESPONSE;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ws <= COLLECT;
            rs <= COLLECT;
            aw_full <= 0;
            aw_sent <= 0;
            w_sent <= 0;
            wcount <= 0;
            wlast_first <= 0;
            wlast_error <= 0;
            awaddr_q <= 0;
            araddr_q <= 0;
            awid_q <= 0;
            arid_q <= 0;
            awcache_q <= 0;
            arcache_q <= 0;
            awprot_q <= 0;
            arprot_q <= 0;
            awqos_q <= 0;
            arqos_q <= 0;
            awlen_q <= 0;
            wdata_q <= 0;
            wstrb_q <= 0;
            rdata_q <= 0;
            awresp_q <= 0;
            bresp_q <= 0;
            rresp_q <= 0;
            read_remaining <= 0;
            read_error <= 0;
        end else begin
            case (ws)
                COLLECT: begin
                    if (aw_capture) begin
                        aw_full <= 1;
                        awaddr_q <= s_axi_awaddr;
                        awid_q <= s_axi_awid;
                        awcache_q <= s_axi_awcache;
                        awprot_q <= s_axi_awprot;
                        awqos_q <= s_axi_awqos;
                        awlen_q <= s_axi_awlen;
                        awresp_q <= aw_address_bad ? 2'b11 :
                            aw_geometry_bad ? 2'b10 : 2'b0;
                    end
                    if (w_capture) begin
                        wcount <= wcount + 9'd1;
                        if (wcount == 0) begin
                            wdata_q <= s_axi_wdata;
                            wstrb_q <= s_axi_wstrb;
                            wlast_first <= s_axi_wlast;
                        end else if (s_axi_wlast != (wcount == {1'b0,awlen_q}))
                            wlast_error <= 1;
                    end
                    if (write_collected) begin
                        aw_sent <= 0;
                        w_sent <= 0;
                        if (collected_awresp != 0 || write_last_bad) begin
                            bresp_q <= collected_awresp != 0 ?
                                collected_awresp : 2'b10;
                            ws <= RESPONSE;
                        end else ws <= ISSUE;
                    end
                end
                ISSUE: begin
                    if (m_axi_awvalid && m_axi_awready) aw_sent <= 1;
                    if (m_axi_wvalid && m_axi_wready) w_sent <= 1;
                    if ((aw_sent || m_axi_awready) &&
                        (w_sent || m_axi_wready)) ws <= WAIT_RESPONSE;
                end
                WAIT_RESPONSE: if (m_axi_bvalid) begin
                    bresp_q <= m_axi_bid != awid_q ? 2'b10 : m_axi_bresp;
                    ws <= RESPONSE;
                end
                RESPONSE: if (s_axi_bready) begin
                    aw_full <= 0;
                    wcount <= 0;
                    wlast_error <= 0;
                    ws <= COLLECT;
                end
                default: ws <= COLLECT;
            endcase
            case (rs)
                COLLECT: if (s_axi_arvalid) begin
                    araddr_q <= s_axi_araddr;
                    arid_q <= s_axi_arid;
                    arcache_q <= s_axi_arcache;
                    arprot_q <= s_axi_arprot;
                    arqos_q <= s_axi_arqos;
                    read_remaining <= s_axi_arlen;
                    read_error <= ar_address_bad || ar_geometry_bad;
                    rdata_q <= 0;
                    rresp_q <= ar_address_bad ? 2'b11 :
                        ar_geometry_bad ? 2'b10 : 2'b0;
                    if (ar_address_bad || ar_geometry_bad) rs <= RESPONSE;
                    else rs <= ISSUE;
                end
                ISSUE: if (m_axi_arready) rs <= WAIT_RESPONSE;
                WAIT_RESPONSE: if (m_axi_rvalid) begin
                    rdata_q <= m_axi_rdata[{araddr_q[5:3],6'b0} +: 64];
                    rresp_q <= m_axi_rid != arid_q || !m_axi_rlast ?
                        2'b10 : m_axi_rresp;
                    rs <= RESPONSE;
                end
                RESPONSE: if (s_axi_rready) begin
                    if (read_error && read_remaining != 0)
                        read_remaining <= read_remaining - 8'd1;
                    else rs <= COLLECT;
                end
                default: rs <= COLLECT;
            endcase
        end
    end
endmodule
