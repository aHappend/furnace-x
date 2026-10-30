module furnace_interrupt_aggregator (
    input wire clk, rst_n,
    input wire [15:0] sources,
    input wire req_valid,
    output wire req_ready,
    input wire req_write,
    input wire [7:0] req_addr,
    input wire [31:0] req_wdata,
    input wire [3:0] req_wstrb,
    output wire rsp_valid,
    input wire rsp_ready,
    output wire [31:0] rsp_rdata,
    output wire rsp_error,
    output wire [15:0] pending, mask,
    output wire irq,
    output wire protocol_error
);
    reg enabled, request_pending, response_valid, response_error, protocol_pulse;
    reg write_q;
    reg [7:0] address_q;
    reg [31:0] data_q, response_data;
    reg [3:0] strobe_q;
    reg [15:0] pending_q, mask_q;
    reg [15:0] ack_bits, mask_next;
    reg [31:0] result;
    reg operation_fault;
    wire active = rst_n && enabled;
    wire [31:0] write_mask = {{8{strobe_q[3]}}, {8{strobe_q[2]}},
                              {8{strobe_q[1]}}, {8{strobe_q[0]}}};
    wire [31:0] strobed_data = data_q & write_mask;

    assign req_ready = active && !request_pending && !response_valid;
    assign rsp_valid = active && response_valid;
    assign rsp_rdata = rsp_valid ? response_data : 32'b0;
    assign rsp_error = rsp_valid && response_error;
    assign pending = active ? pending_q : 16'b0;
    assign mask = active ? mask_q : 16'b0;
    assign irq = active && |(pending_q & mask_q);
    assign protocol_error = active && protocol_pulse;

    always @* begin
        ack_bits = 0;
        mask_next = mask_q;
        result = 0;
        operation_fault = 0;
        if (active && request_pending) begin
            case (address_q)
                8'h00: begin
                    if (write_q) operation_fault = 1;
                    else result = {16'b0, pending_q};
                end
                8'h04: begin
                    if (!write_q) result = {16'b0, mask_q};
                    else if (strobed_data[31:16] != 0) operation_fault = 1;
                    else mask_next = (mask_q & ~write_mask[15:0]) |
                                     strobed_data[15:0];
                end
                8'h08: begin
                    if (!write_q || strobed_data[31:16] != 0) operation_fault = 1;
                    else ack_bits = strobed_data[15:0];
                end
                default: operation_fault = 1;
            endcase
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enabled <= 0;
            request_pending <= 0;
            response_valid <= 0;
            response_error <= 0;
            protocol_pulse <= 0;
            write_q <= 0;
            address_q <= 0;
            data_q <= 0;
            strobe_q <= 0;
            response_data <= 0;
            pending_q <= 0;
            mask_q <= 0;
        end else begin
            enabled <= 1;
            if (enabled) pending_q <= (pending_q & ~ack_bits) | sources;
            mask_q <= mask_next;
            protocol_pulse <= request_pending && operation_fault;
            if (req_valid && req_ready) begin
                request_pending <= 1;
                write_q <= req_write;
                address_q <= req_addr;
                data_q <= req_wdata;
                strobe_q <= req_wstrb;
            end
            if (request_pending) begin
                request_pending <= 0;
                response_valid <= 1;
                response_error <= operation_fault;
                if (operation_fault) response_data <= 0;
                else response_data <= result;
            end
            if (rsp_valid && rsp_ready) response_valid <= 0;
        end
    end
endmodule
