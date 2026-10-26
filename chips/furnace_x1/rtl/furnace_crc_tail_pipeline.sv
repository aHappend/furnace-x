`default_nettype none

module furnace_crc_tail_pipeline #(
    parameter integer DATA_WIDTH = 512
) (
    input  wire clk,
    input  wire rst_n,
    input  wire advance,
    input  wire in_valid,
    input  wire [DATA_WIDTH+(DATA_WIDTH>>3)+106:0] in_meta,
    input  wire [31:0] in_crc32c,
    input  wire [63:0] in_crc64_nvme,
    output wire out_valid,
    output wire [DATA_WIDTH+(DATA_WIDTH>>3)+106:0] out_meta,
    output wire [31:0] out_crc32c,
    output wire [63:0] out_crc64_nvme
);
    localparam integer LAST_BIT = DATA_WIDTH + (DATA_WIDTH >> 3);
    localparam integer META_WIDTH = LAST_BIT + 107;
    wire [6:0] stage_valid;
    wire [META_WIDTH-1:0] stage_meta [0:6];
    wire [31:0] stage32 [0:6];
    wire [63:0] stage64 [0:6];
    reg [6:0] valid_pipe;
    reg [META_WIDTH-1:0] meta_pipe [0:6];
    reg [31:0] crc32_pipe [0:6];
    reg [63:0] crc64_pipe [0:6];

    genvar stage;
    generate
        for (stage = 0; stage < 7; stage = stage + 1) begin : g_tail
            if (stage == 0) begin : g_first
                assign stage_valid[stage] = in_valid;
                assign stage_meta[stage] = in_meta;
                assign stage32[stage] = in_crc32c;
                assign stage64[stage] = in_crc64_nvme;
            end else begin : g_later
                assign stage_valid[stage] = valid_pipe[stage-1];
                assign stage_meta[stage] = meta_pipe[stage-1];
                assign stage32[stage] = crc32_pipe[stage-1];
                assign stage64[stage] = crc64_pipe[stage-1];
            end
            wire [31:0] inverse32;
            wire [63:0] inverse64;
            wire correct_tail = stage_meta[stage][LAST_BIT] &&
                                stage_meta[stage][LAST_BIT+99+stage];
            furnace_crc_linear #(
                .WIDTH(32), .POLYNOMIAL(32'h82f63b78),
                .BIT_STEPS(8*(1 << stage)), .INVERSE(1)
            ) undo32 (
                .value_in(stage32[stage]), .value_out(inverse32)
            );
            furnace_crc_linear #(
                .WIDTH(64), .POLYNOMIAL(64'h9a6c9329ac4bc9b5),
                .BIT_STEPS(8*(1 << stage)), .INVERSE(1)
            ) undo64 (
                .value_in(stage64[stage]), .value_out(inverse64)
            );
            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    valid_pipe[stage] <= 1'b0;
                    meta_pipe[stage] <= {META_WIDTH{1'b0}};
                    crc32_pipe[stage] <= 32'b0;
                    crc64_pipe[stage] <= 64'b0;
                end else if (advance) begin
                    valid_pipe[stage] <= stage_valid[stage];
                    meta_pipe[stage] <= stage_meta[stage];
                    crc32_pipe[stage] <= correct_tail ? inverse32 : stage32[stage];
                    crc64_pipe[stage] <= correct_tail ? inverse64 : stage64[stage];
                end
            end
        end
    endgenerate
    assign out_valid = valid_pipe[6];
    assign out_meta = meta_pipe[6];
    assign out_crc32c = crc32_pipe[6];
    assign out_crc64_nvme = crc64_pipe[6];
endmodule

`default_nettype wire
