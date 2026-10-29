`default_nettype none

module furnace_crc_linear #(
    parameter integer WIDTH = 32,
    parameter integer INPUT_WIDTH = WIDTH,
    parameter [WIDTH-1:0] POLYNOMIAL = 32'h82f63b78,
    parameter integer BIT_STEPS = 8,
    parameter integer INVERSE = 0
) (
    input  wire [INPUT_WIDTH-1:0] value_in,
    output wire [WIDTH-1:0] value_out
);
    localparam integer LEAVES = (INPUT_WIDTH <= 8) ? 8 :
                               (INPUT_WIDTH <= 32) ? 32 : 64;

    function automatic [WIDTH-1:0] column;
        input integer position;
        reg [WIDTH-1:0] state;
        integer step;
        begin
            state = {{(WIDTH-1){1'b0}}, 1'b1} << position;
            for (step = 0; step < BIT_STEPS; step = step + 1) begin
                if (INVERSE != 0) begin
                    if (state[WIDTH-1])
                        state = ((state ^ POLYNOMIAL) << 1) |
                                {{(WIDTH-1){1'b0}}, 1'b1};
                    else
                        state = state << 1;
                end else begin
                    if (state[0])
                        state = (state >> 1) ^ POLYNOMIAL;
                    else
                        state = state >> 1;
                end
            end
            column = state;
        end
    endfunction

    wire [WIDTH-1:0] tree [0:2*LEAVES-2];
    genvar leaf;
    generate
        for (leaf = 0; leaf < LEAVES; leaf = leaf + 1) begin : g_leaf
            if (leaf < INPUT_WIDTH) begin : g_used
                localparam [WIDTH-1:0] COEFFICIENT = column(leaf);
                assign tree[LEAVES-1+leaf] =
                    COEFFICIENT & {WIDTH{value_in[leaf]}};
            end else begin : g_unused
                assign tree[LEAVES-1+leaf] = {WIDTH{1'b0}};
            end
        end
        for (leaf = 0; leaf < LEAVES-1; leaf = leaf + 1) begin : g_reduce
            assign tree[leaf] = tree[2*leaf+1] ^ tree[2*leaf+2];
        end
    endgenerate
    assign value_out = tree[0];
endmodule

`default_nettype wire
