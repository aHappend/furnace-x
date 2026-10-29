`default_nettype none

module furnace_crc_packet_accumulator #(
    parameter integer DATA_WIDTH = 512
) (
    input  wire clk,
    input  wire rst_n,
    input  wire advance,
    input  wire in_valid,
    input  wire [DATA_WIDTH+(DATA_WIDTH>>3)+106:0] in_meta,
    input  wire [31:0] in_crc32c,
    input  wire [63:0] in_crc64_nvme,
    output reg out_valid,
    output reg [DATA_WIDTH+(DATA_WIDTH>>3)+106:0] out_meta,
    output reg [31:0] out_crc32c,
    output reg [63:0] out_crc64_nvme
);
    localparam integer BYTE_LANES = DATA_WIDTH >> 3;
    localparam integer LAST_BIT = DATA_WIDTH + BYTE_LANES;
    localparam integer META_WIDTH = LAST_BIT + 107;
    reg [31:0] state32;
    reg [63:0] state64;
    reg packet_open;
    reg packet_error;
    reg [1:0] packet_enable;
    reg [31:0] packet_expected32;
    reg [63:0] packet_expected64;
    wire [31:0] advanced32;
    wire [63:0] advanced64;
    wire [31:0] next32 = advanced32 ^ in_crc32c;
    wire [63:0] next64 = advanced64 ^ in_crc64_nvme;
    wire beat_last = in_meta[LAST_BIT];
    wire combined_error = in_meta[LAST_BIT+106] |
                                 (packet_open && packet_error);
    wire [1:0] selected_enable = packet_open ? packet_enable :
                                                in_meta[LAST_BIT+1 +: 2];
    wire [31:0] selected_expected32 = packet_open ? packet_expected32 :
                                                in_meta[LAST_BIT+3 +: 32];
    wire [63:0] selected_expected64 = packet_open ? packet_expected64 :
                                                in_meta[LAST_BIT+35 +: 64];

    furnace_crc_linear #(
        .WIDTH(32), .POLYNOMIAL(32'h82f63b78),
        .BIT_STEPS(DATA_WIDTH)
    ) advance32 (
        .value_in(state32), .value_out(advanced32)
    );
    furnace_crc_linear #(
        .WIDTH(64), .POLYNOMIAL(64'h9a6c9329ac4bc9b5),
        .BIT_STEPS(DATA_WIDTH)
    ) advance64 (
        .value_in(state64), .value_out(advanced64)
    );

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state32 <= 32'hffffffff;
            state64 <= 64'hffffffffffffffff;
            packet_open <= 1'b0;
            packet_error <= 1'b0;
            packet_enable <= 2'b0;
            packet_expected32 <= 32'b0;
            packet_expected64 <= 64'b0;
            out_valid <= 1'b0;
            out_meta <= {META_WIDTH{1'b0}};
            out_crc32c <= 32'b0;
            out_crc64_nvme <= 64'b0;
        end else if (advance) begin
            out_valid <= in_valid;
            if (in_valid) begin
                out_crc32c <= next32;
                out_crc64_nvme <= next64;
                out_meta <= {
                    combined_error, in_meta[LAST_BIT+99 +: 7],
                    selected_expected64, selected_expected32, selected_enable,
                    in_meta[LAST_BIT:0]
                };
                state32 <= beat_last ? 32'hffffffff : next32;
                state64 <= beat_last ? 64'hffffffffffffffff : next64;
                packet_open <= !beat_last;
                packet_error <= !beat_last && combined_error;
                if (!packet_open) begin
                    packet_enable <= in_meta[LAST_BIT+1 +: 2];
                    packet_expected32 <= in_meta[LAST_BIT+3 +: 32];
                    packet_expected64 <= in_meta[LAST_BIT+35 +: 64];
                end
            end else begin
                out_meta <= {META_WIDTH{1'b0}};
                out_crc32c <= 32'b0;
                out_crc64_nvme <= 64'b0;
            end
        end
    end
endmodule

`default_nettype wire
