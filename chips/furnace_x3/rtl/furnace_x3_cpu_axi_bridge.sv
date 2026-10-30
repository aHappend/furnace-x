module furnace_x3_cpu_axi_bridge (
    input wire clk, rst_n,
    input wire req_valid,
    output wire req_ready,
    input wire req_write, req_instr,
    input wire [63:0] req_addr, req_wdata,
    input wire [7:0] req_wstrb,
    input wire [1:0] req_size,
    output wire rsp_valid,
    input wire rsp_ready,
    output wire [63:0] rsp_rdata,
    output wire rsp_error,
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
    localparam [3:0] IDLE = 0, VALIDATE = 1, WRITE_ADDRESS = 2,
        WRITE_DATA = 3, WRITE_RESPONSE = 4, READ_ADDRESS = 5,
        READ_DATA = 6, READ_DRAIN = 7, NORMALIZE = 8, RESPONSE = 9;
    reg enabled, write_q, instruction_q, response_error;
    reg [3:0] state;
    reg [63:0] address_q, write_data_q, response_data;
    reg [7:0] strobe_q;
    reg [1:0] size_q;
    reg [511:0] write_line, read_line;
    reg [63:0] write_strobes;
    wire active = rst_n && enabled;
    wire [7:0] legal_strobes = 8'hff >> (8 - (1 << size_q));
    wire [2:0] alignment_mask = 3'b111 >> (3 - size_q);
    wire invalid_request = address_q[63:32] != 0 || !address_q[31] ||
        (address_q[2:0] & alignment_mask) != 0 ||
        (instruction_q && (write_q || size_q != 2)) ||
        (write_q && (strobe_q & ~legal_strobes) != 0);
    wire [511:0] shifted_read = read_line >> {address_q[5:0], 3'b0};
    wire [63:0] read_mask = 64'hffffffffffffffff >> (64 - (8 << size_q));

    assign req_ready = active && state == IDLE;
    assign rsp_valid = active && state == RESPONSE;
    assign rsp_rdata = rsp_valid ? response_data : 64'b0;
    assign rsp_error = rsp_valid && response_error;
    assign m_axi_awvalid = active && state == WRITE_ADDRESS;
    assign m_axi_awaddr = m_axi_awvalid ? {address_q[31:6], 6'b0} : 32'b0;
    assign m_axi_awid = m_axi_awvalid ? 4'd4 : 4'b0;
    assign m_axi_awlen = 0;
    assign m_axi_awsize = m_axi_awvalid ? 3'd6 : 3'b0;
    assign m_axi_awburst = m_axi_awvalid ? 2'b01 : 2'b0;
    assign m_axi_wvalid = active && state == WRITE_DATA;
    assign m_axi_wdata = m_axi_wvalid ? write_line : 512'b0;
    assign m_axi_wstrb = m_axi_wvalid ? write_strobes : 64'b0;
    assign m_axi_wlast = m_axi_wvalid;
    assign m_axi_bready = active && state == WRITE_RESPONSE;
    assign m_axi_arvalid = active && state == READ_ADDRESS;
    assign m_axi_araddr = m_axi_arvalid ? {address_q[31:6], 6'b0} : 32'b0;
    assign m_axi_arid = m_axi_arvalid ? 4'd4 : 4'b0;
    assign m_axi_arlen = 0;
    assign m_axi_arsize = m_axi_arvalid ? 3'd6 : 3'b0;
    assign m_axi_arburst = m_axi_arvalid ? 2'b01 : 2'b0;
    assign m_axi_rready = active && (state == READ_DATA || state == READ_DRAIN);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enabled <= 0;
            state <= IDLE;
            write_q <= 0;
            instruction_q <= 0;
            address_q <= 0;
            write_data_q <= 0;
            strobe_q <= 0;
            size_q <= 0;
            response_data <= 0;
            response_error <= 0;
            write_line <= 0;
            read_line <= 0;
            write_strobes <= 0;
        end else begin
            enabled <= 1;
            case (state)
                IDLE: if (req_valid && req_ready) begin
                    write_q <= req_write;
                    instruction_q <= req_instr;
                    address_q <= req_addr;
                    write_data_q <= req_wdata;
                    strobe_q <= req_wstrb;
                    size_q <= req_size;
                    response_data <= 0;
                    response_error <= 0;
                    state <= VALIDATE;
                end
                VALIDATE: begin
                    if (invalid_request) begin
                        response_error <= 1;
                        state <= RESPONSE;
                    end else if (write_q) begin
                        write_line <= {448'b0, write_data_q} <<
                                      {address_q[5:0], 3'b0};
                        write_strobes <= {56'b0, strobe_q} << address_q[5:0];
                        state <= WRITE_ADDRESS;
                    end else state <= READ_ADDRESS;
                end
                WRITE_ADDRESS: if (m_axi_awvalid && m_axi_awready)
                    state <= WRITE_DATA;
                WRITE_DATA: if (m_axi_wvalid && m_axi_wready)
                    state <= WRITE_RESPONSE;
                WRITE_RESPONSE: if (m_axi_bvalid && m_axi_bready) begin
                    response_error <= m_axi_bid != 4'd4 || m_axi_bresp != 0;
                    state <= RESPONSE;
                end
                READ_ADDRESS: if (m_axi_arvalid && m_axi_arready)
                    state <= READ_DATA;
                READ_DATA: if (m_axi_rvalid && m_axi_rready) begin
                    if (!m_axi_rlast) begin
                        response_error <= 1;
                        state <= READ_DRAIN;
                    end else if (m_axi_rid != 4'd4 || m_axi_rresp != 0) begin
                        response_error <= 1;
                        state <= RESPONSE;
                    end else begin
                        read_line <= m_axi_rdata;
                        state <= NORMALIZE;
                    end
                end
                READ_DRAIN: if (m_axi_rvalid && m_axi_rready && m_axi_rlast)
                    state <= RESPONSE;
                NORMALIZE: begin
                    response_data <= shifted_read[63:0] & read_mask;
                    state <= RESPONSE;
                end
                RESPONSE: if (rsp_valid && rsp_ready) state <= IDLE;
                default: begin
                    response_data <= 0;
                    response_error <= 1;
                    state <= RESPONSE;
                end
            endcase
        end
    end
endmodule
