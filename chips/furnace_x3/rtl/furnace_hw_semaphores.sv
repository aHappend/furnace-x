module furnace_hw_semaphores (
    input wire clk, rst_n,
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
    input wire [15:0] hw_post,
    input wire clear_overflow,
    output wire overflow,
    output wire overflow_event,
    output wire protocol_error
);
    reg enabled, pending, response_valid;
    reg write_q;
    reg [7:0] address_q;
    reg [31:0] data_q, response_data;
    reg [3:0] strobe_q;
    reg response_error, overflow_q, overflow_pulse, protocol_pulse;
    reg [15:0] tokens [0:15];
    reg [15:0] next_tokens [0:15];
    reg [31:0] result;
    reg operation_fault, software_overflow, post_overflow;
    wire active = rst_n && enabled;
    wire [3:0] index_q = address_q[7:4];
    wire [31:0] write_mask = {{8{strobe_q[3]}}, {8{strobe_q[2]}},
                              {8{strobe_q[1]}}, {8{strobe_q[0]}}};
    wire [31:0] strobed_data = data_q & write_mask;
    integer i, j;

    assign req_ready = active && !pending && !response_valid;
    assign rsp_valid = active && response_valid;
    assign rsp_rdata = rsp_valid ? response_data : 32'b0;
    assign rsp_error = rsp_valid && response_error;
    assign overflow = active && overflow_q;
    assign overflow_event = active && overflow_pulse;
    assign protocol_error = active && protocol_pulse;

    always @* begin
        post_overflow = 0;
        software_overflow = 0;
        operation_fault = 0;
        result = 0;
        for (i = 0; i < 16; i = i + 1) begin
            next_tokens[i] = tokens[i];
            if (active && hw_post[i]) begin
                if (tokens[i] == 16'hffff) post_overflow = 1;
                else next_tokens[i] = tokens[i] + 16'd1;
            end
        end
        if (active && pending) begin
            case (address_q[3:0])
                4'h0: begin
                    if (write_q) operation_fault = 1;
                    else if (next_tokens[index_q] != 0) begin
                        result = 1;
                        next_tokens[index_q] = next_tokens[index_q] - 16'd1;
                    end
                end
                4'h4: begin
                    if (!write_q) operation_fault = 1;
                    else if (strobe_q != 0) begin
                        if (strobed_data != 1) operation_fault = 1;
                        else if (next_tokens[index_q] == 16'hffff)
                            software_overflow = 1;
                        else next_tokens[index_q] = next_tokens[index_q] + 16'd1;
                    end
                end
                4'h8: begin
                    if (write_q) operation_fault = 1;
                    else result = {16'b0, next_tokens[index_q]};
                end
                default: operation_fault = 1;
            endcase
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enabled <= 0;
            pending <= 0;
            response_valid <= 0;
            write_q <= 0;
            address_q <= 0;
            data_q <= 0;
            strobe_q <= 0;
            response_data <= 0;
            response_error <= 0;
            overflow_q <= 0;
            overflow_pulse <= 0;
            protocol_pulse <= 0;
            for (j = 0; j < 16; j = j + 1) tokens[j] <= 0;
        end else begin
            enabled <= 1;
            overflow_pulse <= post_overflow || software_overflow;
            protocol_pulse <= pending && operation_fault;
            if (clear_overflow) overflow_q <= 0;
            if (post_overflow || software_overflow) overflow_q <= 1;
            for (j = 0; j < 16; j = j + 1) tokens[j] <= next_tokens[j];
            if (req_valid && req_ready) begin
                pending <= 1;
                write_q <= req_write;
                address_q <= req_addr;
                data_q <= req_wdata;
                strobe_q <= req_wstrb;
            end
            if (pending) begin
                pending <= 0;
                response_valid <= 1;
                response_error <= operation_fault || software_overflow;
                if (operation_fault || software_overflow) response_data <= 0;
                else response_data <= result;
            end
            if (rsp_valid && rsp_ready) response_valid <= 0;
        end
    end
endmodule
