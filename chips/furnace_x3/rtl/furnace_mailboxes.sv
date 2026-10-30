module furnace_mailboxes #(
    parameter integer MAILBOX_DEPTH = 4
) (
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
    output wire [3:0] nonempty,
    output wire protocol_error
);
    generate
        if (MAILBOX_DEPTH < 1 || MAILBOX_DEPTH > 16) begin: bad_parameter
            initial $fatal(1, "PARAMETER ERROR: MAILBOX_DEPTH must be 1..16");
            assign req_ready = 0;
            assign rsp_valid = 0;
            assign rsp_rdata = 0;
            assign rsp_error = 0;
            assign nonempty = 0;
            assign protocol_error = 0;
        end else begin: registers
            reg enabled, pending, response_valid, response_error, protocol_pulse;
            reg write_q;
            reg [7:0] address_q;
            reg [31:0] data_q, response_data;
            reg [3:0] strobe_q;
            wire active = rst_n && enabled;
            wire [1:0] index_q = address_q[5:4];
            wire legal_address = address_q[7:6] == 0;
            wire data_operation = active && pending && legal_address &&
                                  address_q[3:0] == 0;
            wire [31:0] write_mask = {{8{strobe_q[3]}}, {8{strobe_q[2]}},
                                      {8{strobe_q[1]}}, {8{strobe_q[0]}}};
            wire [3:0] pop_ok, push_ok, empty, full;
            wire [3:0][31:0] pop_data;
            wire [3:0][4:0] count;
            reg [31:0] result;
            reg operation_fault;
            genvar m;
            for (m = 0; m < 4; m = m + 1) begin: queues
                furnace_mailbox_fifo #(.DEPTH(MAILBOX_DEPTH)) queue (
                    .clk(clk), .rst_n(rst_n),
                    .push(data_operation && write_q && index_q == m && strobe_q != 0),
                    .pop(data_operation && !write_q && index_q == m),
                    .push_data(data_q & write_mask),
                    .pop_data(pop_data[m]), .pop_ok(pop_ok[m]), .push_ok(push_ok[m]),
                    .count(count[m]), .empty(empty[m]), .full(full[m])
                );
                assign nonempty[m] = active && !empty[m];
            end

            assign req_ready = active && !pending && !response_valid;
            assign rsp_valid = active && response_valid;
            assign rsp_rdata = rsp_valid ? response_data : 32'b0;
            assign rsp_error = rsp_valid && response_error;
            assign protocol_error = active && protocol_pulse;

            always @* begin
                result = 0;
                operation_fault = 0;
                if (!legal_address) operation_fault = 1;
                else case (address_q[3:0])
                    4'h0: begin
                        if (write_q) begin
                            if (strobe_q != 0 && !push_ok[index_q]) operation_fault = 1;
                        end else begin
                            if (!pop_ok[index_q]) operation_fault = 1;
                            else result = pop_data[index_q];
                        end
                    end
                    4'h4: begin
                        if (write_q) operation_fault = 1;
                        else result = {22'b0, full[index_q], empty[index_q],
                                       3'b0, count[index_q]};
                    end
                    default: operation_fault = 1;
                endcase
            end

            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    enabled <= 0;
                    pending <= 0;
                    response_valid <= 0;
                    response_error <= 0;
                    protocol_pulse <= 0;
                    write_q <= 0;
                    address_q <= 0;
                    data_q <= 0;
                    strobe_q <= 0;
                    response_data <= 0;
                end else begin
                    enabled <= 1;
                    protocol_pulse <= pending && operation_fault;
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
                        response_error <= operation_fault;
                        if (operation_fault) response_data <= 0;
                        else response_data <= result;
                    end
                    if (rsp_valid && rsp_ready) response_valid <= 0;
                end
            end
        end
    endgenerate
endmodule
