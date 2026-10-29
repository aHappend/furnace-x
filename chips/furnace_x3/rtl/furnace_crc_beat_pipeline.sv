`default_nettype none

module furnace_crc_beat_pipeline #(
    parameter integer DATA_WIDTH = 512
) (
    input  wire clk,
    input  wire rst_n,
    input  wire advance,
    input  wire in_valid,
    input  wire [DATA_WIDTH+(DATA_WIDTH>>3)+106:0] in_meta,
    output wire out_valid,
    output wire [DATA_WIDTH+(DATA_WIDTH>>3)+106:0] out_meta,
    output wire [31:0] out_crc32c,
    output wire [63:0] out_crc64_nvme
);
    localparam integer BYTE_LANES = DATA_WIDTH >> 3;
    localparam integer META_WIDTH = DATA_WIDTH + BYTE_LANES + 107;
    reg [6:0] valid_pipe;
    reg [META_WIDTH-1:0] meta_pipe [0:6];
    reg [95:0] contribution [0:126];

    genvar position;
    generate
        for (position = 0; position < 64; position = position + 1) begin : g_byte
            wire [95:0] byte_crc;
            if (position < BYTE_LANES) begin : g_used
                wire [7:0] byte_value;
                assign byte_value = in_meta[DATA_WIDTH+position] ?
                                    in_meta[8*position +: 8] : 8'b0;
                furnace_crc_linear #(
                    .WIDTH(32), .INPUT_WIDTH(8),
                    .POLYNOMIAL(32'h82f63b78),
                    .BIT_STEPS(8*(BYTE_LANES-position))
                ) crc32c_byte (
                    .value_in(byte_value), .value_out(byte_crc[31:0])
                );
                furnace_crc_linear #(
                    .WIDTH(64), .INPUT_WIDTH(8),
                    .POLYNOMIAL(64'h9a6c9329ac4bc9b5),
                    .BIT_STEPS(8*(BYTE_LANES-position))
                ) crc64_byte (
                    .value_in(byte_value), .value_out(byte_crc[95:32])
                );
            end else begin : g_unused
                assign byte_crc = 96'b0;
            end
            always @(posedge clk or negedge rst_n) begin
                if (!rst_n)
                    contribution[63+position] <= 96'b0;
                else if (advance)
                    contribution[63+position] <= in_valid ? byte_crc : 96'b0;
            end
        end
        for (position = 0; position < 63; position = position + 1) begin : g_sum
            always @(posedge clk or negedge rst_n) begin
                if (!rst_n)
                    contribution[position] <= 96'b0;
                else if (advance)
                    contribution[position] <= contribution[2*position+1] ^
                                              contribution[2*position+2];
            end
        end
        for (position = 0; position < 7; position = position + 1) begin : g_meta
            if (position == 0) begin : g_first
                always @(posedge clk or negedge rst_n) begin
                    if (!rst_n) begin
                        valid_pipe[position] <= 1'b0;
                        meta_pipe[position] <= {META_WIDTH{1'b0}};
                    end else if (advance) begin
                        valid_pipe[position] <= in_valid;
                        meta_pipe[position] <= in_valid ? in_meta :
                                               {META_WIDTH{1'b0}};
                    end
                end
            end else begin : g_later
                always @(posedge clk or negedge rst_n) begin
                    if (!rst_n) begin
                        valid_pipe[position] <= 1'b0;
                        meta_pipe[position] <= {META_WIDTH{1'b0}};
                    end else if (advance) begin
                        valid_pipe[position] <= valid_pipe[position-1];
                        meta_pipe[position] <= meta_pipe[position-1];
                    end
                end
            end
        end
    endgenerate
    assign out_valid = valid_pipe[6];
    assign out_meta = meta_pipe[6];
    assign out_crc32c = contribution[0][31:0];
    assign out_crc64_nvme = contribution[0][95:32];
endmodule

`default_nettype wire
