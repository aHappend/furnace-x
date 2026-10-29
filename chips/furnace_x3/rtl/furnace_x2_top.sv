`default_nettype none
module furnace_x2_top #(
    parameter integer DATA_WIDTH = 512
) (
    input wire clk, rst_n,
    input wire [((DATA_WIDTH > 0) ? DATA_WIDTH : 1)-1:0] s_axis_tdata,
    input wire [((DATA_WIDTH >= 8) ? (DATA_WIDTH>>3) : 1)-1:0] s_axis_tkeep,
    input wire s_axis_tvalid, s_axis_tlast,
    output wire s_axis_tready,
    input wire [1:0] s_check_enable,
    input wire [31:0] s_expected_crc32c,
    input wire [63:0] s_expected_crc64_nvme,
    output wire [((DATA_WIDTH > 0) ? DATA_WIDTH : 1)-1:0] m_axis_tdata,
    output wire [((DATA_WIDTH >= 8) ? (DATA_WIDTH>>3) : 1)-1:0] m_axis_tkeep,
    output wire m_axis_tvalid, m_axis_tlast,
    input wire m_axis_tready,
    output wire m_crc_valid,
    input wire m_crc_ready,
    output wire [31:0] m_crc32c,
    output wire [63:0] m_crc64_nvme,
    output wire [1:0] m_crc_mismatch,
    output wire m_crc_protocol_error,
    input wire cfg_valid,
    input wire [1:0] cfg_op,
    input wire [5:0] cfg_index,
    input wire [511:0] cfg_value, cfg_mask,
    input wire [31:0] cfg_action,
    input wire cfg_enable,
    input wire [327:0] cfg_rss_key,
    output wire cfg_ready,
    output wire m_meta_valid,
    output wire [511:0] m_header,
    output wire [31:0] m_packet_bytes, m_rss_hash,
    output wire m_rss_valid, m_rule_hit,
    output wire [5:0] m_rule_index,
    output wire [31:0] m_action,
    input wire m_meta_ready
);
    generate if (DATA_WIDTH==64 || DATA_WIDTH==512) begin : g_legal
        localparam [327:0] DEFAULT_KEY =
            328'h6d5a56da255b0ec24167253d43a38fb0d0ca2bcbae7b30b477cb2da38030f20c6a42b73bbeac01fa00;
        reg occupied, input_ended, payload_done, crc_done, meta_done;
        reg [327:0] rss_key;
        reg [31:0] default_action;
        wire core_ready;
        wire ingress_allowed = rst_n && !input_ended &&
                               (occupied || !cfg_valid);
        wire in_fire = s_axis_tvalid && s_axis_tready;
        wire cfg_fire = cfg_valid && cfg_ready;
        wire parser_valid;
        wire [511:0] parser_header;
        wire [295:0] parser_tuple;
        wire [8:0] parser_bits;
        wire [31:0] parser_bytes;
        wire rss_valid, rss_eligible;
        wire [31:0] rss_hash;
        wire classifier_valid, classifier_hit;
        wire [5:0] classifier_index;
        wire [31:0] classifier_action;
        reg [511:0] held_header, meta_header;
        reg [31:0] held_bytes, held_hash, meta_bytes, meta_hash, meta_action;
        reg held_eligible, meta_eligible, meta_hit, meta_valid;
        reg [5:0] meta_index;
        wire payload_terminal = m_axis_tvalid && m_axis_tready && m_axis_tlast;
        wire crc_terminal = m_crc_valid && m_crc_ready;
        wire meta_terminal = m_meta_valid && m_meta_ready;
        assign cfg_ready = rst_n && !occupied;
        assign s_axis_tready = ingress_allowed && core_ready;

        furnace_x1_top #(.DATA_WIDTH(DATA_WIDTH)) crc_core (
            .clk(clk), .rst_n(rst_n),
            .s_axis_tdata(s_axis_tdata), .s_axis_tkeep(s_axis_tkeep),
            .s_axis_tvalid(s_axis_tvalid && ingress_allowed),
            .s_axis_tlast(s_axis_tlast), .s_axis_tready(core_ready),
            .s_check_enable(s_check_enable), .s_expected_crc32c(s_expected_crc32c),
            .s_expected_crc64_nvme(s_expected_crc64_nvme),
            .m_axis_tdata(m_axis_tdata), .m_axis_tkeep(m_axis_tkeep),
            .m_axis_tvalid(m_axis_tvalid), .m_axis_tlast(m_axis_tlast),
            .m_axis_tready(m_axis_tready), .m_crc_valid(m_crc_valid),
            .m_crc_ready(m_crc_ready), .m_crc32c(m_crc32c),
            .m_crc64_nvme(m_crc64_nvme), .m_crc_mismatch(m_crc_mismatch),
            .m_crc_protocol_error(m_crc_protocol_error)
        );
        furnace_header_parser #(.DATA_WIDTH(DATA_WIDTH)) parser (
            .clk(clk), .rst_n(rst_n), .in_fire(in_fire), .in_data(s_axis_tdata),
            .in_keep(s_axis_tkeep), .in_last(s_axis_tlast),
            .out_valid(parser_valid), .out_header(parser_header),
            .out_tuple(parser_tuple), .out_tuple_bits(parser_bits),
            .out_packet_bytes(parser_bytes)
        );
        furnace_rss_toeplitz rss (
            .clk(clk), .rst_n(rst_n), .in_valid(parser_valid),
            .in_tuple(parser_tuple), .in_tuple_bits(parser_bits),
            .in_eligible(parser_bits!=0), .in_key(rss_key),
            .out_valid(rss_valid), .out_hash(rss_hash), .out_eligible(rss_eligible)
        );
        furnace_classifier64 classifier (
            .clk(clk), .rst_n(rst_n),
            .cfg_write(cfg_fire && cfg_op==0), .cfg_clear(cfg_fire && cfg_op==2),
            .cfg_index(cfg_index), .cfg_value(cfg_value), .cfg_mask(cfg_mask),
            .cfg_action(cfg_action), .cfg_enable(cfg_enable),
            .in_valid(rss_valid), .in_key(held_header),
            .in_default_action(default_action), .out_valid(classifier_valid),
            .out_hit(classifier_hit), .out_index(classifier_index),
            .out_action(classifier_action)
        );
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                occupied<=0; input_ended<=0;
                payload_done<=0; crc_done<=0; meta_done<=0;
                rss_key<=DEFAULT_KEY; default_action<=0;
                held_header<=0; held_bytes<=0; held_hash<=0; held_eligible<=0;
                meta_header<=0; meta_bytes<=0; meta_hash<=0; meta_eligible<=0;
                meta_hit<=0; meta_index<=0; meta_action<=0; meta_valid<=0;
            end else begin
                if (cfg_fire) begin
                    if (cfg_op==1) rss_key<=cfg_rss_key;
                    if (cfg_op==3) default_action<=cfg_action;
                end
                if (in_fire) begin
                    occupied<=1;
                    if (s_axis_tlast) input_ended<=1;
                end
                if (payload_terminal) payload_done<=1;
                if (crc_terminal) crc_done<=1;
                if (meta_terminal) begin meta_done<=1; meta_valid<=0; end
                if (occupied && input_ended &&
                    (payload_done || payload_terminal) &&
                    (crc_done || crc_terminal) &&
                    (meta_done || meta_terminal)) begin
                    occupied<=0; input_ended<=0;
                    payload_done<=0; crc_done<=0; meta_done<=0;
                end
                if (parser_valid) begin
                    held_header<=parser_header;
                    held_bytes<=parser_bytes;
                end
                if (rss_valid) begin
                    held_hash<=rss_hash;
                    held_eligible<=rss_eligible;
                end
                if (classifier_valid) begin
                    meta_valid<=1;
                    meta_header<=held_header; meta_bytes<=held_bytes;
                    meta_hash<=held_hash; meta_eligible<=held_eligible;
                    meta_hit<=classifier_hit; meta_index<=classifier_index;
                    meta_action<=classifier_action;
                end
            end
        end
        assign m_meta_valid = rst_n && meta_valid;
        assign m_header = rst_n ? meta_header : 512'b0;
        assign m_packet_bytes = rst_n ? meta_bytes : 32'b0;
        assign m_rss_hash = rst_n ? meta_hash : 32'b0;
        assign m_rss_valid = rst_n && meta_eligible;
        assign m_rule_hit = rst_n && meta_hit;
        assign m_rule_index = rst_n ? meta_index : 6'b0;
        assign m_action = rst_n ? meta_action : 32'b0;
    end else begin : g_illegal
        initial $fatal(1,"PARAMETER ERROR: DATA_WIDTH must be 64 or 512");
        assign s_axis_tready=0; assign cfg_ready=0;
        assign m_axis_tdata=0; assign m_axis_tkeep=0;
        assign m_axis_tvalid=0; assign m_axis_tlast=0;
        assign m_crc_valid=0; assign m_crc32c=0; assign m_crc64_nvme=0;
        assign m_crc_mismatch=0; assign m_crc_protocol_error=0;
        assign m_meta_valid=0; assign m_header=0; assign m_packet_bytes=0;
        assign m_rss_hash=0; assign m_rss_valid=0; assign m_rule_hit=0;
        assign m_rule_index=0; assign m_action=0;
    end endgenerate
endmodule
`default_nettype wire
