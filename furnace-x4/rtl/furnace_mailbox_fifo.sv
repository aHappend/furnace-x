module furnace_mailbox_fifo #(
    parameter integer DEPTH = 4
) (
    input wire clk, rst_n,
    input wire push, pop,
    input wire [31:0] push_data,
    output wire [31:0] pop_data,
    output wire push_ok, pop_ok,
    output wire [4:0] count,
    output wire empty, full
);
    generate
        if (DEPTH < 1 || DEPTH > 16) begin: bad_parameter
            initial $fatal(1, "PARAMETER ERROR: mailbox DEPTH must be 1..16");
            assign pop_data = 0;
            assign push_ok = 0;
            assign pop_ok = 0;
            assign count = 0;
            assign empty = 0;
            assign full = 0;
        end else begin: fifo
            localparam integer PTR_BITS = DEPTH > 1 ? $clog2(DEPTH) : 1;
            localparam [PTR_BITS-1:0] LAST_SLOT = DEPTH - 1;
            localparam [4:0] CAPACITY = DEPTH;
            reg enabled;
            reg [PTR_BITS-1:0] read_pointer, write_pointer;
            reg [4:0] occupancy;
            (* nomem2reg *) reg [31:0] storage [0:DEPTH-1];
            wire active = rst_n && enabled;
            wire take = active && pop && occupancy != 0;
            wire put = active && push && (occupancy < CAPACITY || take);

            assign pop_data = active && occupancy != 0 ? storage[read_pointer] : 32'b0;
            assign pop_ok = take;
            assign push_ok = put;
            assign count = active ? occupancy : 5'b0;
            assign empty = active && occupancy == 0;
            assign full = active && occupancy == CAPACITY;

            always @(posedge clk) begin
                if (put) storage[write_pointer] <= push_data;
            end

            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    enabled <= 0;
                    read_pointer <= 0;
                    write_pointer <= 0;
                    occupancy <= 0;
                end else begin
                    enabled <= 1;
                    if (take) begin
                        if (read_pointer == LAST_SLOT) read_pointer <= 0;
                        else read_pointer <= read_pointer + 1'b1;
                    end
                    if (put) begin
                        if (write_pointer == LAST_SLOT) write_pointer <= 0;
                        else write_pointer <= write_pointer + 1'b1;
                    end
                    case ({put, take})
                        2'b10: occupancy <= occupancy + 5'd1;
                        2'b01: occupancy <= occupancy - 5'd1;
                        default: begin end
                    endcase
                end
            end
        end
    endgenerate
endmodule
