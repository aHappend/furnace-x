module furnace_dma512 #(
    parameter integer MAX_DMA_BYTES = 1048576
) (
    input wire clk, rst_n,
    input wire cmd_valid,
    output wire cmd_ready,
    input wire [31:0] cmd_src, cmd_dst, cmd_bytes,
    output wire busy,
    output wire done_valid,
    input wire done_ready,
    output wire [7:0] done_error,
    output wire completion,
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
        if (MAX_DMA_BYTES < 1 || MAX_DMA_BYTES > 1048576) begin: bad_parameter
            initial $fatal(1, "PARAMETER ERROR: MAX_DMA_BYTES must be 1..1048576");
            assign cmd_ready = 0;
            assign busy = 0;
            assign done_valid = 0;
            assign done_error = 0;
            assign completion = 0;
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
        end else begin: engine
            localparam [3:0] IDLE = 0, VALIDATE = 1, PLAN = 2,
                READ_ADDRESS = 3, READ_DATA = 4, READ_DRAIN = 5,
                WRITE_FIRST_FETCH = 6, WRITE_ADDRESS = 7, WRITE_DATA = 8,
                WRITE_NEXT_FETCH = 9, WRITE_RESPONSE = 10, DONE = 11;
            reg enabled;
            reg [3:0] state;
            reg [31:0] source, destination, remaining;
            reg [4:0] beats, read_index, write_index;
            reg burst_fault, completion_pulse;
            reg [7:0] error_code;
            reg [63:0] write_strobes;
            (* ramstyle = "M20K", nomem2reg *) reg [511:0] buffer [0:15];
            reg [511:0] buffer_q;
            wire active = rst_n && enabled;
            wire [32:0] source_end = {1'b0, source} + {1'b0, remaining};
            wire [32:0] destination_end = {1'b0, destination} + {1'b0, remaining};
            wire overlap = remaining != 0 &&
                {1'b0, source} < destination_end &&
                {1'b0, destination} < source_end;
            wire invalid_command = !source[31] || !destination[31] ||
                source[5:0] != 0 || destination[5:0] != 0 ||
                remaining > MAX_DMA_BYTES ||
                source_end > 33'h100000000 ||
                destination_end > 33'h100000000 || overlap;
            wire [32:0] remaining_beats = ({1'b0, remaining} + 33'd63) >> 6;
            wire [6:0] source_page_beats = 7'd64 - {1'b0, source[11:6]};
            wire [6:0] destination_page_beats = 7'd64 - {1'b0, destination[11:6]};
            wire [31:0] burst_bytes = {21'b0, beats, 6'b0};
            wire [31:0] write_offset = {21'b0, write_index, 6'b0};
            wire expected_read_last = read_index == beats - 5'd1;
            wire read_beat_fault = m_axi_rid != 4'd5 || m_axi_rresp != 0 ||
                                  m_axi_rlast != expected_read_last;
            wire ram_write = active && state == READ_DATA &&
                             m_axi_rvalid && m_axi_rready;
            wire ram_read = active &&
                (state == WRITE_FIRST_FETCH || state == WRITE_NEXT_FETCH);
            reg [6:0] planned_beats;
            reg [63:0] planned_strobes;
            integer b;

            assign cmd_ready = active && state == IDLE;
            assign busy = active && state != IDLE;
            assign done_valid = active && state == DONE;
            assign done_error = done_valid ? error_code : 8'b0;
            assign completion = active && completion_pulse;
            assign m_axi_awvalid = active && state == WRITE_ADDRESS;
            assign m_axi_awaddr = m_axi_awvalid ? destination : 32'b0;
            assign m_axi_awid = m_axi_awvalid ? 4'd5 : 4'b0;
            assign m_axi_awlen = m_axi_awvalid ? {3'b0, beats} - 8'd1 : 8'b0;
            assign m_axi_awsize = m_axi_awvalid ? 3'd6 : 3'b0;
            assign m_axi_awburst = m_axi_awvalid ? 2'b01 : 2'b0;
            assign m_axi_wvalid = active && state == WRITE_DATA;
            assign m_axi_wdata = m_axi_wvalid ? buffer_q : 512'b0;
            assign m_axi_wstrb = m_axi_wvalid ? write_strobes : 64'b0;
            assign m_axi_wlast = m_axi_wvalid && write_index == beats - 5'd1;
            assign m_axi_bready = active && state == WRITE_RESPONSE;
            assign m_axi_arvalid = active && state == READ_ADDRESS;
            assign m_axi_araddr = m_axi_arvalid ? source : 32'b0;
            assign m_axi_arid = m_axi_arvalid ? 4'd5 : 4'b0;
            assign m_axi_arlen = m_axi_arvalid ? {3'b0, beats} - 8'd1 : 8'b0;
            assign m_axi_arsize = m_axi_arvalid ? 3'd6 : 3'b0;
            assign m_axi_arburst = m_axi_arvalid ? 2'b01 : 2'b0;
            assign m_axi_rready = active &&
                (state == READ_DATA || state == READ_DRAIN);

            always @* begin
                planned_beats = 7'd16;
                if (remaining_beats < {26'b0, planned_beats})
                    planned_beats = remaining_beats[6:0];
                if (source_page_beats < planned_beats)
                    planned_beats = source_page_beats;
                if (destination_page_beats < planned_beats)
                    planned_beats = destination_page_beats;
                planned_strobes = 64'hffffffffffffffff;
                if (remaining - write_offset < 32'd64) begin
                    for (b = 0; b < 64; b = b + 1)
                        planned_strobes[b] = remaining[5:0] > b;
                end
            end

            always @(posedge clk) begin
                if (ram_write) buffer[read_index[3:0]] <= m_axi_rdata;
                if (ram_read) buffer_q <= buffer[write_index[3:0]];
            end

            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    enabled <= 0;
                    state <= IDLE;
                    source <= 0;
                    destination <= 0;
                    remaining <= 0;
                    beats <= 0;
                    read_index <= 0;
                    write_index <= 0;
                    burst_fault <= 0;
                    completion_pulse <= 0;
                    error_code <= 0;
                    write_strobes <= 0;
                end else begin
                    enabled <= 1;
                    completion_pulse <= 0;
                    case (state)
                        IDLE: if (cmd_valid && cmd_ready) begin
                            source <= cmd_src;
                            destination <= cmd_dst;
                            remaining <= cmd_bytes;
                            error_code <= 0;
                            state <= VALIDATE;
                        end
                        VALIDATE: begin
                            if (invalid_command) begin
                                error_code <= 1;
                                completion_pulse <= 1;
                                state <= DONE;
                            end else if (remaining == 0) begin
                                completion_pulse <= 1;
                                state <= DONE;
                            end else state <= PLAN;
                        end
                        PLAN: begin
                            beats <= planned_beats[4:0];
                            read_index <= 0;
                            write_index <= 0;
                            burst_fault <= 0;
                            state <= READ_ADDRESS;
                        end
                        READ_ADDRESS: if (m_axi_arvalid && m_axi_arready)
                            state <= READ_DATA;
                        READ_DATA: if (m_axi_rvalid && m_axi_rready) begin
                            if (read_beat_fault) burst_fault <= 1;
                            if (m_axi_rlast) begin
                                if (read_beat_fault || burst_fault) begin
                                    error_code <= 2;
                                    completion_pulse <= 1;
                                    state <= DONE;
                                end else state <= WRITE_FIRST_FETCH;
                            end else if (expected_read_last) begin
                                state <= READ_DRAIN;
                            end else read_index <= read_index + 5'd1;
                        end
                        READ_DRAIN: if (m_axi_rvalid && m_axi_rready && m_axi_rlast) begin
                            error_code <= 2;
                            completion_pulse <= 1;
                            state <= DONE;
                        end
                        WRITE_FIRST_FETCH: begin
                            write_strobes <= planned_strobes;
                            state <= WRITE_ADDRESS;
                        end
                        WRITE_ADDRESS: if (m_axi_awvalid && m_axi_awready)
                            state <= WRITE_DATA;
                        WRITE_DATA: if (m_axi_wvalid && m_axi_wready) begin
                            if (m_axi_wlast) state <= WRITE_RESPONSE;
                            else begin
                                write_index <= write_index + 5'd1;
                                state <= WRITE_NEXT_FETCH;
                            end
                        end
                        WRITE_NEXT_FETCH: begin
                            write_strobes <= planned_strobes;
                            state <= WRITE_DATA;
                        end
                        WRITE_RESPONSE: if (m_axi_bvalid && m_axi_bready) begin
                            if (m_axi_bid != 4'd5 || m_axi_bresp != 0) begin
                                error_code <= 2;
                                completion_pulse <= 1;
                                state <= DONE;
                            end else if (remaining <= burst_bytes) begin
                                completion_pulse <= 1;
                                state <= DONE;
                            end else begin
                                source <= source + burst_bytes;
                                destination <= destination + burst_bytes;
                                remaining <= remaining - burst_bytes;
                                state <= PLAN;
                            end
                        end
                        DONE: if (done_valid && done_ready) state <= IDLE;
                        default: begin
                            error_code <= 2;
                            completion_pulse <= 1;
                            state <= DONE;
                        end
                    endcase
                end
            end
        end
    endgenerate
endmodule
