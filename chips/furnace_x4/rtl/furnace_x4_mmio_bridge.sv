module furnace_x4_mmio_bridge (
    input wire clk, rst_n,
    input wire [31:0] s_axil_awaddr,
    input wire [2:0] s_axil_awprot,
    input wire s_axil_awvalid,
    output wire s_axil_awready,
    input wire [63:0] s_axil_wdata,
    input wire [7:0] s_axil_wstrb,
    input wire s_axil_wvalid,
    output wire s_axil_wready,
    output wire [1:0] s_axil_bresp,
    output wire s_axil_bvalid,
    input wire s_axil_bready,
    input wire [31:0] s_axil_araddr,
    input wire [2:0] s_axil_arprot,
    input wire s_axil_arvalid,
    output wire s_axil_arready,
    output wire [63:0] s_axil_rdata,
    output wire [1:0] s_axil_rresp,
    output wire s_axil_rvalid,
    input wire s_axil_rready,
    output wire [15:0] m_axil_awaddr,
    output wire [2:0] m_axil_awprot,
    output wire m_axil_awvalid,
    input wire m_axil_awready,
    output wire [31:0] m_axil_wdata,
    output wire [3:0] m_axil_wstrb,
    output wire m_axil_wvalid,
    input wire m_axil_wready,
    input wire [1:0] m_axil_bresp,
    input wire m_axil_bvalid,
    output wire m_axil_bready,
    output wire [15:0] m_axil_araddr,
    output wire [2:0] m_axil_arprot,
    output wire m_axil_arvalid,
    input wire m_axil_arready,
    input wire [31:0] m_axil_rdata,
    input wire [1:0] m_axil_rresp,
    input wire m_axil_rvalid,
    output wire m_axil_rready
);
    localparam [1:0] COLLECT=0, ISSUE=1, WAIT_RESPONSE=2, RESPONSE=3;
    reg [1:0] ws, rs;
    reg aw_full, w_full, aw_sent, w_sent;
    reg [31:0] awaddr_q, araddr_q;
    reg [2:0] awprot_q, arprot_q;
    reg [63:0] wdata_q, rdata_q;
    reg [7:0] wstrb_q;
    reg [1:0] bresp_q, rresp_q;
    wire aw_bad = awaddr_q < 32'h20000000 ||
        awaddr_q > 32'h2000fffc || |awaddr_q[1:0];
    wire ar_bad = s_axil_araddr < 32'h20000000 ||
        s_axil_araddr > 32'h2000fffc || |s_axil_araddr[1:0];
    wire mask_bad = awaddr_q[2] ? |wstrb_q[3:0] : |wstrb_q[7:4];
    wire [31:0] write_offset = awaddr_q - 32'h20000000;
    wire [31:0] read_offset = araddr_q - 32'h20000000;

    assign s_axil_awready = rst_n && ws == COLLECT && !aw_full;
    assign s_axil_wready = rst_n && ws == COLLECT && !w_full;
    assign s_axil_bvalid = rst_n && ws == RESPONSE;
    assign s_axil_bresp = s_axil_bvalid ? bresp_q : 2'b0;
    assign s_axil_arready = rst_n && rs == COLLECT;
    assign s_axil_rvalid = rst_n && rs == RESPONSE;
    assign s_axil_rresp = s_axil_rvalid ? rresp_q : 2'b0;
    assign s_axil_rdata = s_axil_rvalid ? rdata_q : 64'b0;

    assign m_axil_awvalid = rst_n && ws == ISSUE && !aw_sent;
    assign m_axil_awaddr = m_axil_awvalid ? write_offset[15:0] : 16'b0;
    assign m_axil_awprot = m_axil_awvalid ? awprot_q : 3'b0;
    assign m_axil_wvalid = rst_n && ws == ISSUE && !w_sent;
    assign m_axil_wdata = m_axil_wvalid ?
        (awaddr_q[2] ? wdata_q[63:32] : wdata_q[31:0]) : 32'b0;
    assign m_axil_wstrb = m_axil_wvalid ?
        (awaddr_q[2] ? wstrb_q[7:4] : wstrb_q[3:0]) : 4'b0;
    assign m_axil_bready = rst_n && ws == WAIT_RESPONSE;
    assign m_axil_arvalid = rst_n && rs == ISSUE;
    assign m_axil_araddr = m_axil_arvalid ? read_offset[15:0] : 16'b0;
    assign m_axil_arprot = m_axil_arvalid ? arprot_q : 3'b0;
    assign m_axil_rready = rst_n && rs == WAIT_RESPONSE;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ws <= COLLECT;
            rs <= COLLECT;
            aw_full <= 0;
            w_full <= 0;
            aw_sent <= 0;
            w_sent <= 0;
            awaddr_q <= 0;
            araddr_q <= 0;
            awprot_q <= 0;
            arprot_q <= 0;
            wdata_q <= 0;
            wstrb_q <= 0;
            rdata_q <= 0;
            bresp_q <= 0;
            rresp_q <= 0;
        end else begin
            case (ws)
                COLLECT: begin
                    if (s_axil_awvalid && s_axil_awready) begin
                        aw_full <= 1;
                        awaddr_q <= s_axil_awaddr;
                        awprot_q <= s_axil_awprot;
                    end
                    if (s_axil_wvalid && s_axil_wready) begin
                        w_full <= 1;
                        wdata_q <= s_axil_wdata;
                        wstrb_q <= s_axil_wstrb;
                    end
                    if (aw_full && w_full) begin
                        aw_sent <= 0;
                        w_sent <= 0;
                        if (aw_bad || mask_bad) begin
                            bresp_q <= aw_bad ? 2'b11 : 2'b10;
                            ws <= RESPONSE;
                        end else ws <= ISSUE;
                    end
                end
                ISSUE: begin
                    if (m_axil_awvalid && m_axil_awready) aw_sent <= 1;
                    if (m_axil_wvalid && m_axil_wready) w_sent <= 1;
                    if ((aw_sent || m_axil_awready) &&
                        (w_sent || m_axil_wready)) ws <= WAIT_RESPONSE;
                end
                WAIT_RESPONSE: if (m_axil_bvalid) begin
                    bresp_q <= m_axil_bresp;
                    ws <= RESPONSE;
                end
                RESPONSE: if (s_axil_bready) begin
                    aw_full <= 0;
                    w_full <= 0;
                    ws <= COLLECT;
                end
                default: ws <= COLLECT;
            endcase
            case (rs)
                COLLECT: if (s_axil_arvalid) begin
                    araddr_q <= s_axil_araddr;
                    arprot_q <= s_axil_arprot;
                    rdata_q <= 0;
                    rresp_q <= 0;
                    if (ar_bad) begin
                        rresp_q <= 2'b11;
                        rs <= RESPONSE;
                    end else rs <= ISSUE;
                end
                ISSUE: if (m_axil_arready) rs <= WAIT_RESPONSE;
                WAIT_RESPONSE: if (m_axil_rvalid) begin
                    rdata_q <= araddr_q[2] ?
                        {m_axil_rdata,32'b0} : {32'b0,m_axil_rdata};
                    rresp_q <= m_axil_rresp;
                    rs <= RESPONSE;
                end
                RESPONSE: if (s_axil_rready) rs <= COLLECT;
                default: rs <= COLLECT;
            endcase
        end
    end
endmodule
