module furnace_x3_axi512_arb (
    input wire clk, rst_n,
    input wire [5:0][31:0] s_axi_awaddr,
    input wire [5:0][7:0] s_axi_awlen,
    input wire [5:0] s_axi_awvalid,
    output wire [5:0] s_axi_awready,
    input wire [5:0][511:0] s_axi_wdata,
    input wire [5:0][63:0] s_axi_wstrb,
    input wire [5:0] s_axi_wlast, s_axi_wvalid,
    output wire [5:0] s_axi_wready,
    output wire [5:0][3:0] s_axi_bid,
    output wire [5:0][1:0] s_axi_bresp,
    output wire [5:0] s_axi_bvalid,
    input wire [5:0] s_axi_bready,
    input wire [5:0][31:0] s_axi_araddr,
    input wire [5:0][7:0] s_axi_arlen,
    input wire [5:0] s_axi_arvalid,
    output wire [5:0] s_axi_arready,
    output wire [5:0][3:0] s_axi_rid,
    output wire [5:0][511:0] s_axi_rdata,
    output wire [5:0][1:0] s_axi_rresp,
    output wire [5:0] s_axi_rlast, s_axi_rvalid,
    input wire [5:0] s_axi_rready,
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
    output wire m_axi_rready
);
    localparam [1:0] WIDLE = 0, WADDRESS = 1, WDATA = 2, WRESPONSE = 3;
    localparam [1:0] RIDLE = 0, RADDRESS = 1, RDATA = 2;
    reg enabled;
    reg [1:0] wstate, rstate;
    reg [2:0] write_owner, read_owner, write_next, read_next;
    reg [31:0] write_address, read_address;
    reg [7:0] write_length, read_length, write_index;
    reg write_found, read_found;
    reg [2:0] write_choice, read_choice;
    wire active = rst_n && enabled;
    integer n, wi, ri;
    genvar c;

    always @* begin
        write_found = 0;
        read_found = 0;
        write_choice = 0;
        read_choice = 0;
        wi = 0;
        ri = 0;
        for (n = 0; n < 6; n = n + 1) begin
            wi = {29'b0, write_next} + n;
            ri = {29'b0, read_next} + n;
            if (wi >= 6) wi = wi - 6;
            if (ri >= 6) ri = ri - 6;
            if (!write_found && s_axi_awvalid[wi]) begin
                write_found = 1;
                write_choice = wi[2:0];
            end
            if (!read_found && s_axi_arvalid[ri]) begin
                read_found = 1;
                read_choice = ri[2:0];
            end
        end
    end

    assign m_axi_awvalid = active && wstate == WADDRESS;
    assign m_axi_awaddr = m_axi_awvalid ? write_address : 32'b0;
    assign m_axi_awid = m_axi_awvalid ? {1'b0, write_owner} : 4'b0;
    assign m_axi_awlen = m_axi_awvalid ? write_length : 8'b0;
    assign m_axi_awsize = m_axi_awvalid ? 3'd6 : 3'b0;
    assign m_axi_awburst = m_axi_awvalid ? 2'b01 : 2'b0;
    assign m_axi_awlock = 0;
    assign m_axi_awcache = 0;
    assign m_axi_awprot = 0;
    assign m_axi_awqos = 0;
    assign m_axi_awregion = 0;
    assign m_axi_wvalid = active && wstate == WDATA && s_axi_wvalid[write_owner];
    assign m_axi_wdata = m_axi_wvalid ? s_axi_wdata[write_owner] : 512'b0;
    assign m_axi_wstrb = m_axi_wvalid ? s_axi_wstrb[write_owner] : 64'b0;
    assign m_axi_wlast = m_axi_wvalid && s_axi_wlast[write_owner];
    assign m_axi_bready = active && wstate == WRESPONSE && s_axi_bready[write_owner];
    assign m_axi_arvalid = active && rstate == RADDRESS;
    assign m_axi_araddr = m_axi_arvalid ? read_address : 32'b0;
    assign m_axi_arid = m_axi_arvalid ? {1'b0, read_owner} : 4'b0;
    assign m_axi_arlen = m_axi_arvalid ? read_length : 8'b0;
    assign m_axi_arsize = m_axi_arvalid ? 3'd6 : 3'b0;
    assign m_axi_arburst = m_axi_arvalid ? 2'b01 : 2'b0;
    assign m_axi_arlock = 0;
    assign m_axi_arcache = 0;
    assign m_axi_arprot = 0;
    assign m_axi_arqos = 0;
    assign m_axi_arregion = 0;
    assign m_axi_rready = active && rstate == RDATA && s_axi_rready[read_owner];

    generate for (c = 0; c < 6; c = c + 1) begin: clients
        wire write_selected = active && write_owner == c;
        wire read_selected = active && read_owner == c;
        assign s_axi_awready[c] = write_selected && wstate == WADDRESS && m_axi_awready;
        assign s_axi_wready[c] = write_selected && wstate == WDATA && m_axi_wready;
        assign s_axi_bvalid[c] = write_selected && wstate == WRESPONSE && m_axi_bvalid;
        assign s_axi_bid[c] = s_axi_bvalid[c] ? m_axi_bid : 4'b0;
        assign s_axi_bresp[c] = s_axi_bvalid[c] ? m_axi_bresp : 2'b0;
        assign s_axi_arready[c] = read_selected && rstate == RADDRESS && m_axi_arready;
        assign s_axi_rvalid[c] = read_selected && rstate == RDATA && m_axi_rvalid;
        assign s_axi_rid[c] = s_axi_rvalid[c] ? m_axi_rid : 4'b0;
        assign s_axi_rdata[c] = s_axi_rvalid[c] ? m_axi_rdata : 512'b0;
        assign s_axi_rresp[c] = s_axi_rvalid[c] ? m_axi_rresp : 2'b0;
        assign s_axi_rlast[c] = s_axi_rvalid[c] && m_axi_rlast;
    end endgenerate

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enabled <= 0;
            wstate <= WIDLE;
            rstate <= RIDLE;
            write_owner <= 0;
            read_owner <= 0;
            write_next <= 0;
            read_next <= 0;
            write_address <= 0;
            read_address <= 0;
            write_length <= 0;
            read_length <= 0;
            write_index <= 0;
        end else begin
            enabled <= 1;
            case (wstate)
                WIDLE: if (active && write_found) begin
                    write_owner <= write_choice;
                    write_address <= s_axi_awaddr[write_choice];
                    write_length <= s_axi_awlen[write_choice];
                    write_index <= 0;
                    wstate <= WADDRESS;
                end
                WADDRESS: if (m_axi_awvalid && m_axi_awready) wstate <= WDATA;
                WDATA: if (m_axi_wvalid && m_axi_wready) begin
                    if (write_index == write_length) wstate <= WRESPONSE;
                    else write_index <= write_index + 8'd1;
                end
                WRESPONSE: if (m_axi_bvalid && m_axi_bready) begin
                    if (write_owner == 5) write_next <= 0;
                    else write_next <= write_owner + 3'd1;
                    wstate <= WIDLE;
                end
                default: wstate <= WIDLE;
            endcase
            case (rstate)
                RIDLE: if (active && read_found) begin
                    read_owner <= read_choice;
                    read_address <= s_axi_araddr[read_choice];
                    read_length <= s_axi_arlen[read_choice];
                    rstate <= RADDRESS;
                end
                RADDRESS: if (m_axi_arvalid && m_axi_arready) rstate <= RDATA;
                RDATA: if (m_axi_rvalid && m_axi_rready && m_axi_rlast) begin
                    if (read_owner == 5) read_next <= 0;
                    else read_next <= read_owner + 3'd1;
                    rstate <= RIDLE;
                end
                default: rstate <= RIDLE;
            endcase
        end
    end
endmodule
