`default_nettype none

module furnace_crc_output_stage #(
    parameter integer DATA_WIDTH = 512
) (
    input  wire clk,
    input  wire rst_n,
    input  wire advance,
    input  wire in_valid,
    input  wire [DATA_WIDTH+(DATA_WIDTH>>3)+106:0] in_meta,
    input  wire [31:0] in_crc32c,
    input  wire [63:0] in_crc64_nvme,
    output wire [DATA_WIDTH-1:0] m_axis_tdata,
    output wire [(DATA_WIDTH>>3)-1:0] m_axis_tkeep,
    output wire m_axis_tvalid,
    output wire m_axis_tlast,
    input  wire m_axis_tready,
    output wire m_crc_valid,
    input  wire m_crc_ready,
    output wire [31:0] m_crc32c,
    output wire [63:0] m_crc64_nvme,
    output wire [1:0] m_crc_mismatch,
    output wire m_crc_protocol_error
);
    localparam integer BYTE_LANES = DATA_WIDTH >> 3;
    localparam integer LAST_BIT = DATA_WIDTH + BYTE_LANES;
    reg [DATA_WIDTH-1:0] payload_data;
    reg [BYTE_LANES-1:0] payload_keep;
    reg payload_last;
    reg payload_valid;
    reg result_valid;
    reg [31:0] result32;
    reg [63:0] result64;
    reg [1:0] result_mismatch;
    reg result_error;
    wire [31:0] final32 = in_crc32c ^ 32'hffffffff;
    wire [63:0] final64 = in_crc64_nvme ^ 64'hffffffffffffffff;
    wire protocol_error = in_meta[LAST_BIT+106];
    wire [1:0] check_enable = in_meta[LAST_BIT+1 +: 2];
    wire [1:0] mismatches = {
        check_enable[1] && (final64 != in_meta[LAST_BIT+35 +: 64]),
        check_enable[0] && (final32 != in_meta[LAST_BIT+3 +: 32])
    };

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            payload_data <= {DATA_WIDTH{1'b0}};
            payload_keep <= {BYTE_LANES{1'b0}};
            payload_last <= 1'b0;
            payload_valid <= 1'b0;
            result_valid <= 1'b0;
            result32 <= 32'b0;
            result64 <= 64'b0;
            result_mismatch <= 2'b0;
            result_error <= 1'b0;
        end else if (advance) begin
            payload_valid <= in_valid;
            payload_data <= in_valid ? in_meta[0 +: DATA_WIDTH] :
                                       {DATA_WIDTH{1'b0}};
            payload_keep <= in_valid ? in_meta[DATA_WIDTH +: BYTE_LANES] :
                                       {BYTE_LANES{1'b0}};
            payload_last <= in_valid && in_meta[LAST_BIT];
            result_valid <= in_valid && in_meta[LAST_BIT];
            if (in_valid && in_meta[LAST_BIT]) begin
                result32 <= final32;
                result64 <= final64;
                result_mismatch <= protocol_error ? 2'b0 : mismatches;
                result_error <= protocol_error;
            end else begin
                result32 <= 32'b0;
                result64 <= 64'b0;
                result_mismatch <= 2'b0;
                result_error <= 1'b0;
            end
        end else begin
            if (payload_valid && m_axis_tready)
                payload_valid <= 1'b0;
            if (result_valid && m_crc_ready)
                result_valid <= 1'b0;
        end
    end

    assign m_axis_tdata = rst_n ? payload_data : {DATA_WIDTH{1'b0}};
    assign m_axis_tkeep = rst_n ? payload_keep : {BYTE_LANES{1'b0}};
    assign m_axis_tlast = rst_n && payload_last;
    assign m_axis_tvalid = rst_n && payload_valid;
    assign m_crc_valid = rst_n && result_valid;
    assign m_crc32c = rst_n ? result32 : 32'b0;
    assign m_crc64_nvme = rst_n ? result64 : 64'b0;
    assign m_crc_mismatch = rst_n ? result_mismatch : 2'b0;
    assign m_crc_protocol_error = rst_n && result_error;
endmodule

`default_nettype wire
