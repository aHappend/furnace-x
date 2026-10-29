`default_nettype none
module furnace_rss_toeplitz (
    input wire clk, rst_n,
    input wire in_valid,
    input wire [295:0] in_tuple,
    input wire [8:0] in_tuple_bits,
    input wire in_eligible,
    input wire [327:0] in_key,
    output reg out_valid,
    output reg [31:0] out_hash,
    output reg out_eligible
);
    reg [295:0] tuple_shift;
    reg [327:0] key_shift;
    reg [8:0] bit_number, bit_limit;
    reg [31:0] accumulator;
    reg eligible;
    reg [1:0] state;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tuple_shift <= 0;
            key_shift <= 0;
            bit_number <= 0;
            bit_limit <= 0;
            accumulator <= 0;
            eligible <= 0;
            state <= 0;
            out_valid <= 0;
            out_hash <= 0;
            out_eligible <= 0;
        end else begin
            out_valid <= 0;
            if (in_valid && state == 0) begin
                tuple_shift <= {in_tuple[294:0],1'b0};
                key_shift <= {in_key[326:0],1'b0};
                bit_limit <= in_tuple_bits;
                eligible <= in_eligible;
                accumulator <= (in_eligible && in_tuple_bits != 0 &&
                                in_tuple[295]) ? in_key[327:296] : 32'b0;
                bit_number <= 1;
                state <= 1;
            end else if (state == 1) begin
                if (eligible && bit_number < bit_limit && tuple_shift[295])
                    accumulator <= accumulator ^ key_shift[327:296];
                tuple_shift <= {tuple_shift[294:0],1'b0};
                key_shift <= {key_shift[326:0],1'b0};
                bit_number <= bit_number + 1'b1;
                if (bit_number == 295)
                    state <= 2;
            end else if (state == 2) begin
                out_valid <= 1;
                out_hash <= eligible ? accumulator : 32'b0;
                out_eligible <= eligible;
                state <= 0;
            end
        end
    end
endmodule
`default_nettype wire
