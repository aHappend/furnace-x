module furnace_axi128_to512 #(
    parameter integer CLIENT_ID = 0
) (
    input wire clk, rst_n,
    input wire [31:0] s_axi_awaddr,
    input wire [3:0] s_axi_awid,
    input wire [7:0] s_axi_awlen,
    input wire [2:0] s_axi_awsize,
    input wire [1:0] s_axi_awburst,
    input wire s_axi_awlock,
    input wire [3:0] s_axi_awcache,
    input wire [2:0] s_axi_awprot,
    input wire [3:0] s_axi_awqos, s_axi_awregion,
    input wire s_axi_awvalid,
    output wire s_axi_awready,
    input wire [127:0] s_axi_wdata,
    input wire [15:0] s_axi_wstrb,
    input wire s_axi_wlast, s_axi_wvalid,
    output wire s_axi_wready,
    output wire [3:0] s_axi_bid,
    output wire [1:0] s_axi_bresp,
    output wire s_axi_bvalid,
    input wire s_axi_bready,
    input wire [31:0] s_axi_araddr,
    input wire [3:0] s_axi_arid,
    input wire [7:0] s_axi_arlen,
    input wire [2:0] s_axi_arsize,
    input wire [1:0] s_axi_arburst,
    input wire s_axi_arlock,
    input wire [3:0] s_axi_arcache,
    input wire [2:0] s_axi_arprot,
    input wire [3:0] s_axi_arqos, s_axi_arregion,
    input wire s_axi_arvalid,
    output wire s_axi_arready,
    output wire [3:0] s_axi_rid,
    output wire [127:0] s_axi_rdata,
    output wire [1:0] s_axi_rresp,
    output wire s_axi_rlast, s_axi_rvalid,
    input wire s_axi_rready,
    output wire [31:0] m_axi_awaddr,
    output wire [3:0] m_axi_awid,
    output wire [7:0] m_axi_awlen,
    output wire [2:0] m_axi_awsize,
    output wire [1:0] m_axi_awburst,
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
    output wire m_axi_arvalid,
    input wire m_axi_arready,
    input wire [3:0] m_axi_rid,
    input wire [511:0] m_axi_rdata,
    input wire [1:0] m_axi_rresp,
    input wire m_axi_rlast, m_axi_rvalid,
    output wire m_axi_rready
);
    generate
        if (CLIENT_ID < 0 || CLIENT_ID > 3) begin: bad_parameter
            initial $fatal(1, "PARAMETER ERROR: legacy CLIENT_ID must be 0..3");
            assign s_axi_awready = 0;
            assign s_axi_wready = 0;
            assign s_axi_bid = 0;
            assign s_axi_bresp = 0;
            assign s_axi_bvalid = 0;
            assign s_axi_arready = 0;
            assign s_axi_rid = 0;
            assign s_axi_rdata = 0;
            assign s_axi_rresp = 0;
            assign s_axi_rlast = 0;
            assign s_axi_rvalid = 0;
            assign m_axi_awaddr = 0;
            assign m_axi_awid = 0;
            assign m_axi_awlen = 0;
            assign m_axi_awsize = 0;
            assign m_axi_awburst = 0;
            assign m_axi_awvalid = 0;
            assign m_axi_wdata = 0;
            assign m_axi_wstrb = 0;
            assign m_axi_wlast = 0;
            assign m_axi_wvalid = 0;
            assign m_axi_bready = 0;
            assign m_axi_araddr = 0;
            assign m_axi_arid = 0;
            assign m_axi_arlen = 0;
            assign m_axi_arsize = 0;
            assign m_axi_arburst = 0;
            assign m_axi_arvalid = 0;
            assign m_axi_rready = 0;
        end else begin: adapter
            localparam [3:0] PHYSICAL_ID = CLIENT_ID;
            localparam [2:0] WHOLD = 0, WADDR = 1, WDATA = 2, WWAIT = 3, WRESP = 4;
            localparam [2:0] RIDLE = 0, RVALIDATE = 1, RADDR = 2,
                RWAIT = 3, RDRAIN = 4, RRESP = 5;
            reg enabled, aw_held, w_held, aw_bad, ar_bad, w_last;
            reg [2:0] wstate, rstate;
            reg [31:0] write_address, read_address;
            reg [3:0] write_id, read_id;
            reg [127:0] write_data, read_data;
            reg [15:0] write_strobes;
            reg [511:0] write_line;
            reg [63:0] line_strobes;
            reg [1:0] write_response, read_response;
            wire active = rst_n && enabled;
            wire bad_write_address = !s_axi_awaddr[31] || s_axi_awaddr[3:0] != 0 ||
                s_axi_awlen != 0 || s_axi_awsize != 4 ||
                s_axi_awburst != 1 || s_axi_awlock;
            wire bad_read_address = !s_axi_araddr[31] || s_axi_araddr[3:0] != 0 ||
                s_axi_arlen != 0 || s_axi_arsize != 4 ||
                s_axi_arburst != 1 || s_axi_arlock;

            assign s_axi_awready = active && wstate == WHOLD && !aw_held;
            assign s_axi_wready = active && wstate == WHOLD && !w_held;
            assign s_axi_bvalid = active && wstate == WRESP;
            assign s_axi_bid = s_axi_bvalid ? write_id : 4'b0;
            assign s_axi_bresp = s_axi_bvalid ? write_response : 2'b0;
            assign s_axi_arready = active && rstate == RIDLE;
            assign s_axi_rvalid = active && rstate == RRESP;
            assign s_axi_rid = s_axi_rvalid ? read_id : 4'b0;
            assign s_axi_rdata = s_axi_rvalid ? read_data : 128'b0;
            assign s_axi_rresp = s_axi_rvalid ? read_response : 2'b0;
            assign s_axi_rlast = s_axi_rvalid;
            assign m_axi_awvalid = active && wstate == WADDR;
            assign m_axi_awaddr = m_axi_awvalid ? {write_address[31:6], 6'b0} : 32'b0;
            assign m_axi_awid = m_axi_awvalid ? PHYSICAL_ID : 4'b0;
            assign m_axi_awlen = 0;
            assign m_axi_awsize = m_axi_awvalid ? 3'd6 : 3'b0;
            assign m_axi_awburst = m_axi_awvalid ? 2'b01 : 2'b0;
            assign m_axi_wvalid = active && wstate == WDATA;
            assign m_axi_wdata = m_axi_wvalid ? write_line : 512'b0;
            assign m_axi_wstrb = m_axi_wvalid ? line_strobes : 64'b0;
            assign m_axi_wlast = m_axi_wvalid;
            assign m_axi_bready = active && wstate == WWAIT;
            assign m_axi_arvalid = active && rstate == RADDR;
            assign m_axi_araddr = m_axi_arvalid ? {read_address[31:6], 6'b0} : 32'b0;
            assign m_axi_arid = m_axi_arvalid ? PHYSICAL_ID : 4'b0;
            assign m_axi_arlen = 0;
            assign m_axi_arsize = m_axi_arvalid ? 3'd6 : 3'b0;
            assign m_axi_arburst = m_axi_arvalid ? 2'b01 : 2'b0;
            assign m_axi_rready = active && (rstate == RWAIT || rstate == RDRAIN);

            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    enabled <= 0;
                    aw_held <= 0;
                    w_held <= 0;
                    aw_bad <= 0;
                    ar_bad <= 0;
                    w_last <= 0;
                    wstate <= WHOLD;
                    rstate <= RIDLE;
                    write_address <= 0;
                    read_address <= 0;
                    write_id <= 0;
                    read_id <= 0;
                    write_data <= 0;
                    read_data <= 0;
                    write_strobes <= 0;
                    write_line <= 0;
                    line_strobes <= 0;
                    write_response <= 0;
                    read_response <= 0;
                end else begin
                    enabled <= 1;
                    if (s_axi_awvalid && s_axi_awready) begin
                        aw_held <= 1;
                        write_address <= s_axi_awaddr;
                        write_id <= s_axi_awid;
                        aw_bad <= bad_write_address;
                    end
                    if (s_axi_wvalid && s_axi_wready) begin
                        w_held <= 1;
                        write_data <= s_axi_wdata;
                        write_strobes <= s_axi_wstrb;
                        w_last <= s_axi_wlast;
                    end
                    case (wstate)
                        WHOLD: if (aw_held && w_held) begin
                            if (aw_bad || !w_last) begin
                                write_response <= 2'b10;
                                wstate <= WRESP;
                            end else begin
                                write_line <= {384'b0, write_data} <<
                                              {write_address[5:4], 7'b0};
                                line_strobes <= {48'b0, write_strobes} <<
                                                {write_address[5:4], 4'b0};
                                wstate <= WADDR;
                            end
                        end
                        WADDR: if (m_axi_awvalid && m_axi_awready) wstate <= WDATA;
                        WDATA: if (m_axi_wvalid && m_axi_wready) wstate <= WWAIT;
                        WWAIT: if (m_axi_bvalid && m_axi_bready) begin
                            if (m_axi_bid != PHYSICAL_ID || m_axi_bresp != 0)
                                write_response <= 2'b10;
                            else write_response <= 0;
                            wstate <= WRESP;
                        end
                        WRESP: if (s_axi_bvalid && s_axi_bready) begin
                            aw_held <= 0;
                            w_held <= 0;
                            wstate <= WHOLD;
                        end
                        default: begin
                            write_response <= 2'b10;
                            wstate <= WRESP;
                        end
                    endcase
                    case (rstate)
                        RIDLE: if (s_axi_arvalid && s_axi_arready) begin
                            read_address <= s_axi_araddr;
                            read_id <= s_axi_arid;
                            ar_bad <= bad_read_address;
                            read_data <= 0;
                            read_response <= 0;
                            rstate <= RVALIDATE;
                        end
                        RVALIDATE: begin
                            if (ar_bad) begin
                                read_response <= 2'b10;
                                rstate <= RRESP;
                            end else rstate <= RADDR;
                        end
                        RADDR: if (m_axi_arvalid && m_axi_arready) rstate <= RWAIT;
                        RWAIT: if (m_axi_rvalid && m_axi_rready) begin
                            if (!m_axi_rlast) begin
                                read_response <= 2'b10;
                                rstate <= RDRAIN;
                            end else begin
                                if (m_axi_rid != PHYSICAL_ID || m_axi_rresp != 0)
                                    read_response <= 2'b10;
                                else read_data <=
                                    m_axi_rdata[{read_address[5:4], 7'b0} +: 128];
                                rstate <= RRESP;
                            end
                        end
                        RDRAIN: if (m_axi_rvalid && m_axi_rready && m_axi_rlast)
                            rstate <= RRESP;
                        RRESP: if (s_axi_rvalid && s_axi_rready) rstate <= RIDLE;
                        default: begin
                            read_data <= 0;
                            read_response <= 2'b10;
                            rstate <= RRESP;
                        end
                    endcase
                end
            end
        end
    endgenerate
endmodule
