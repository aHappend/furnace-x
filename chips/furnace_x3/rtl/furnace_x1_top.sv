`default_nettype none

module furnace_x1_top #(
    parameter integer DATA_WIDTH = 512
) (
    input  wire clk,
    input  wire rst_n,
    input  wire [((DATA_WIDTH > 0) ? DATA_WIDTH : 1)-1:0] s_axis_tdata,
    input  wire [(((DATA_WIDTH>>3) > 0) ? (DATA_WIDTH>>3) : 1)-1:0] s_axis_tkeep,
    input  wire s_axis_tvalid,
    input  wire s_axis_tlast,
    output wire s_axis_tready,
    input  wire [1:0] s_check_enable,
    input  wire [31:0] s_expected_crc32c,
    input  wire [63:0] s_expected_crc64_nvme,
    output wire [((DATA_WIDTH > 0) ? DATA_WIDTH : 1)-1:0] m_axis_tdata,
    output wire [(((DATA_WIDTH>>3) > 0) ? (DATA_WIDTH>>3) : 1)-1:0] m_axis_tkeep,
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
    generate
        if ((DATA_WIDTH == 64) || (DATA_WIDTH == 512)) begin : g_legal
            localparam integer BYTE_LANES = DATA_WIDTH >> 3;
            localparam integer META_WIDTH = DATA_WIDTH + BYTE_LANES + 107;
            wire advance = rst_n &&
                           (!m_axis_tvalid || m_axis_tready) &&
                           (!m_crc_valid || m_crc_ready);
            wire [6:0] missing_tree [0:126];
            wire [BYTE_LANES-1:0] prefix_violation;
            genvar lane;
            for (lane = 0; lane < 64; lane = lane + 1) begin : g_count
                if (lane < BYTE_LANES) begin : g_used
                    assign missing_tree[63+lane] = {6'b0, !s_axis_tkeep[lane]};
                end else begin : g_unused
                    assign missing_tree[63+lane] = 7'b0;
                end
            end
            for (lane = 0; lane < 63; lane = lane + 1) begin : g_count_sum
                assign missing_tree[lane] = missing_tree[2*lane+1] +
                                            missing_tree[2*lane+2];
            end
            assign prefix_violation[0] = 1'b0;
            for (lane = 1; lane < BYTE_LANES; lane = lane + 1) begin : g_prefix
                assign prefix_violation[lane] = s_axis_tkeep[lane] &&
                                                !s_axis_tkeep[lane-1];
            end
            wire malformed = s_axis_tlast ? (|prefix_violation) :
                                                   !(&s_axis_tkeep);
            wire [META_WIDTH-1:0] input_meta = {
                malformed, missing_tree[0], s_expected_crc64_nvme,
                s_expected_crc32c, s_check_enable, s_axis_tlast,
                s_axis_tkeep, s_axis_tdata
            };
            wire beat_valid;
            wire [META_WIDTH-1:0] beat_meta;
            wire [31:0] beat32;
            wire [63:0] beat64;
            wire packet_valid;
            wire [META_WIDTH-1:0] packet_meta;
            wire [31:0] packet32;
            wire [63:0] packet64;
            wire tail_valid;
            wire [META_WIDTH-1:0] tail_meta;
            wire [31:0] tail32;
            wire [63:0] tail64;

            assign s_axis_tready = advance;
            furnace_crc_beat_pipeline #(.DATA_WIDTH(DATA_WIDTH)) beat_pipeline (
                .clk(clk), .rst_n(rst_n), .advance(advance),
                .in_valid(s_axis_tvalid), .in_meta(input_meta),
                .out_valid(beat_valid), .out_meta(beat_meta),
                .out_crc32c(beat32), .out_crc64_nvme(beat64)
            );
            furnace_crc_packet_accumulator #(.DATA_WIDTH(DATA_WIDTH)) packet_accumulator (
                .clk(clk), .rst_n(rst_n), .advance(advance),
                .in_valid(beat_valid), .in_meta(beat_meta),
                .in_crc32c(beat32), .in_crc64_nvme(beat64),
                .out_valid(packet_valid), .out_meta(packet_meta),
                .out_crc32c(packet32), .out_crc64_nvme(packet64)
            );
            furnace_crc_tail_pipeline #(.DATA_WIDTH(DATA_WIDTH)) tail_pipeline (
                .clk(clk), .rst_n(rst_n), .advance(advance),
                .in_valid(packet_valid), .in_meta(packet_meta),
                .in_crc32c(packet32), .in_crc64_nvme(packet64),
                .out_valid(tail_valid), .out_meta(tail_meta),
                .out_crc32c(tail32), .out_crc64_nvme(tail64)
            );
            furnace_crc_output_stage #(.DATA_WIDTH(DATA_WIDTH)) output_stage (
                .clk(clk), .rst_n(rst_n), .advance(advance),
                .in_valid(tail_valid), .in_meta(tail_meta),
                .in_crc32c(tail32), .in_crc64_nvme(tail64),
                .m_axis_tdata(m_axis_tdata), .m_axis_tkeep(m_axis_tkeep),
                .m_axis_tvalid(m_axis_tvalid), .m_axis_tlast(m_axis_tlast),
                .m_axis_tready(m_axis_tready), .m_crc_valid(m_crc_valid),
                .m_crc_ready(m_crc_ready), .m_crc32c(m_crc32c),
                .m_crc64_nvme(m_crc64_nvme), .m_crc_mismatch(m_crc_mismatch),
                .m_crc_protocol_error(m_crc_protocol_error)
            );
        end else begin : g_illegal
            initial begin
                $fatal(1, "PARAMETER ERROR: DATA_WIDTH must be 64 or 512");
            end
            assign s_axis_tready = 1'b0;
            assign m_axis_tdata = '0;
            assign m_axis_tkeep = '0;
            assign m_axis_tvalid = 1'b0;
            assign m_axis_tlast = 1'b0;
            assign m_crc_valid = 1'b0;
            assign m_crc32c = 32'b0;
            assign m_crc64_nvme = 64'b0;
            assign m_crc_mismatch = 2'b0;
            assign m_crc_protocol_error = 1'b0;
        end
    endgenerate
endmodule

`default_nettype wire
