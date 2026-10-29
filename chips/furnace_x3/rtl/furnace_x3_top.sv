`default_nettype none
module furnace_x3_top #(
    parameter integer DATA_WIDTH=512,
    parameter integer MAX_PACKET_BYTES=9216,
    parameter integer MAX_SG=16
) (
    input wire clk, rst_n,
    input wire [((DATA_WIDTH>0)?DATA_WIDTH:1)-1:0] s_axis_tdata,
    input wire [((DATA_WIDTH>=8)?(DATA_WIDTH>>3):1)-1:0] s_axis_tkeep,
    input wire s_axis_tvalid, s_axis_tlast,
    output wire s_axis_tready,
    input wire [1:0] s_check_enable,
    input wire [31:0] s_expected_crc32c,
    input wire [63:0] s_expected_crc64_nvme,
    output wire [((DATA_WIDTH>0)?DATA_WIDTH:1)-1:0] m_axis_tdata,
    output wire [((DATA_WIDTH>=8)?(DATA_WIDTH>>3):1)-1:0] m_axis_tkeep,
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
    input wire m_meta_ready,
    input wire dma_enable,
    input wire q_cfg_valid,
    input wire [2:0] q_cfg_id,
    input wire q_cfg_enable,
    input wire [63:0] q_cfg_ring_base,
    input wire [8:0] q_cfg_ring_entries,
    input wire [15:0] q_cfg_quantum,
    input wire [31:0] q_cfg_rate,
    input wire [15:0] q_cfg_burst,
    output wire q_cfg_ready,
    input wire db_valid,
    input wire [2:0] db_queue,
    input wire [31:0] db_producer,
    output wire db_ready,
    output wire ctl_valid,
    output wire [2:0] ctl_queue, ctl_code,
    input wire ctl_ready,
    output wire dma_rd_valid,
    output wire [63:0] dma_rd_addr,
    output wire [15:0] dma_rd_len,
    input wire dma_rd_ready,
    input wire dma_rsp_valid,
    input wire [((DATA_WIDTH>0)?DATA_WIDTH:1)-1:0] dma_rsp_data,
    input wire [((DATA_WIDTH>=8)?(DATA_WIDTH>>3):1)-1:0] dma_rsp_keep,
    input wire dma_rsp_last, dma_rsp_error,
    output wire dma_rsp_ready,
    output wire dma_cpl_valid,
    output wire [2:0] dma_cpl_queue,
    output wire [31:0] dma_cpl_cookie,
    output wire [2:0] dma_cpl_status,
    output wire [31:0] dma_cpl_bytes,
    input wire dma_cpl_ready,
    output wire dma_idle
);
    generate if ((DATA_WIDTH==64 || DATA_WIDTH==512) &&
                 MAX_PACKET_BYTES>=1 && MAX_PACKET_BYTES<=9216 &&
                 MAX_SG>=1 && MAX_SG<=16) begin : g_legal
        localparam BOUNDARY=0, SERVICE=1, PREFETCH=2, PF_WAIT=3, ACTIVE=4;
        reg [2:0] arbitration;
        reg [5:0] service_clocks;
        reg saw_decision;
        reg active_valid, active_reserved;
        reg [2:0] active_queue, error_cursor;
        reg [31:0] active_seq, active_bytes, active_cookie;
        reg completion_valid;
        reg [2:0] completion_status;
        reg [31:0] completion_bytes;
        reg x2_occupied, payload_done, crc_done, meta_done, done_sent;
        wire [7:0] q_enabled, q_pending, head_valid;
        wire [255:0] head_seq, head_bytes, head_cookie;
        wire [23:0] head_status;
        wire [127:0] q_quantum, q_burst;
        wire [383:0] token_balance;
        wire cfg_commit, cfg_commit_enable;
        wire [2:0] cfg_commit_queue;
        wire [15:0] cfg_commit_quantum, cfg_commit_burst;
        wire [31:0] cfg_commit_rate;
        wire pf_valid, pf_ready;
        wire [2:0] pf_queue;
        wire [31:0] pf_seq;
        wire [63:0] pf_desc_addr;
        wire [15:0] pf_burst;
        wire pf_done_valid, pf_done_ready;
        wire [2:0] pf_done_queue, pf_done_status;
        wire [31:0] pf_done_seq, pf_done_bytes, pf_done_cookie;
        wire grant_valid, grant_ready;
        wire [2:0] grant_queue;
        wire [31:0] grant_seq, grant_bytes;
        wire run_valid, run_ready, run_done_valid, run_done_ready;
        wire [2:0] run_queue, run_done_queue, run_done_status;
        wire [31:0] run_seq, run_bytes, run_done_seq;
        wire pkt_valid, pkt_ready, pkt_last;
        wire [DATA_WIDTH-1:0] pkt_data;
        wire [(DATA_WIDTH>>3)-1:0] pkt_keep;
        wire decision_busy, scheduler_idle, rings_idle, dma_busy;
        reg error_found;
        reg [2:0] error_queue, search_queue;
        integer k;
        always @* begin
            error_found=0; error_queue=0; search_queue=0;
            if (rst_n) begin
                for (k=0;k<8;k=k+1) begin
                    search_queue=error_cursor+k;
                    if (!error_found && head_valid[search_queue] &&
                        head_status[search_queue*3 +:3]!=0) begin
                        error_found=1; error_queue=search_queue;
                    end
                end
            end
        end
        wire need_prefetch=|(q_enabled & q_pending & ~head_valid);
        wire global_clear=!dma_busy && !pf_valid && !decision_busy &&
                          !active_valid && !completion_valid && !x2_occupied;
        wire ctl_allow=rst_n && dma_enable && global_clear;
        wire pf_allow=rst_n && dma_enable && arbitration==PREFETCH &&
                      !active_valid && !decision_busy && !dma_busy;
        wire decision_allow=rst_n && dma_enable && arbitration==SERVICE &&
                            !active_valid && !error_found;
        wire dispatch_available=rst_n && dma_enable && !active_valid &&
                                !completion_valid && !dma_busy && !pf_valid;
        assign run_valid=grant_valid && dispatch_available;
        assign grant_ready=run_ready && dispatch_available;
        assign run_queue=grant_queue;
        assign run_seq=grant_seq;
        assign run_bytes=grant_bytes;
        wire reserve_fire=grant_valid && grant_ready;
        wire retire_fire=dma_cpl_valid && dma_cpl_ready;
        assign run_done_ready=rst_n && active_valid && active_reserved &&
                              !completion_valid && run_done_queue==active_queue &&
                              run_done_seq==active_seq;
        wire refund_fire=run_done_valid && run_done_ready && run_done_status!=0;
        wire [2:0] evt_queue=reserve_fire ? grant_queue : active_queue;
        wire [31:0] evt_seq=reserve_fire ? grant_seq : active_seq;
        wire [31:0] evt_bytes=reserve_fire ? grant_bytes :
                                  active_reserved ? active_bytes : 32'b0;
        wire retire_reserved=active_reserved;
        wire core_ready;
        wire [DATA_WIDTH-1:0] core_data=dma_enable ? pkt_data : s_axis_tdata;
        wire [(DATA_WIDTH>>3)-1:0] core_keep=dma_enable ? pkt_keep : s_axis_tkeep;
        wire core_valid=dma_enable ? pkt_valid : s_axis_tvalid;
        wire core_last=dma_enable ? pkt_last : s_axis_tlast;
        wire input_fire=core_valid && core_ready;
        wire payload_terminal=m_axis_tvalid && m_axis_tready && m_axis_tlast;
        wire crc_terminal=m_crc_valid && m_crc_ready;
        wire meta_terminal=m_meta_valid && m_meta_ready;
        wire all_results=x2_occupied && (payload_done || payload_terminal) &&
                         (crc_done || crc_terminal) && (meta_done || meta_terminal);
        wire x2_done=rst_n && active_valid && active_reserved &&
                     !done_sent && all_results;
        assign s_axis_tready=rst_n && !dma_enable && core_ready;
        assign pkt_ready=rst_n && dma_enable && core_ready;
        assign dma_cpl_valid=rst_n && dma_enable && completion_valid;
        assign dma_cpl_queue=rst_n ? active_queue : 3'b0;
        assign dma_cpl_cookie=rst_n ? active_cookie : 32'b0;
        assign dma_cpl_status=rst_n ? completion_status : 3'b0;
        assign dma_cpl_bytes=rst_n ? completion_bytes : 32'b0;
        assign dma_idle=rst_n && rings_idle && scheduler_idle && !dma_busy &&
                        !pf_valid && !active_valid && !completion_valid &&
                        !x2_occupied;

        furnace_x2_top #(.DATA_WIDTH(DATA_WIDTH)) x2_core (
            .clk(clk), .rst_n(rst_n), .s_axis_tdata(core_data), .s_axis_tkeep(core_keep),
            .s_axis_tvalid(core_valid), .s_axis_tlast(core_last), .s_axis_tready(core_ready),
            .s_check_enable(dma_enable ? 2'b0 : s_check_enable),
            .s_expected_crc32c(dma_enable ? 32'b0 : s_expected_crc32c),
            .s_expected_crc64_nvme(dma_enable ? 64'b0 : s_expected_crc64_nvme),
            .m_axis_tdata(m_axis_tdata), .m_axis_tkeep(m_axis_tkeep),
            .m_axis_tvalid(m_axis_tvalid), .m_axis_tlast(m_axis_tlast),
            .m_axis_tready(m_axis_tready), .m_crc_valid(m_crc_valid), .m_crc_ready(m_crc_ready),
            .m_crc32c(m_crc32c), .m_crc64_nvme(m_crc64_nvme), .m_crc_mismatch(m_crc_mismatch),
            .m_crc_protocol_error(m_crc_protocol_error), .cfg_valid(cfg_valid),
            .cfg_op(cfg_op), .cfg_index(cfg_index), .cfg_value(cfg_value), .cfg_mask(cfg_mask),
            .cfg_action(cfg_action), .cfg_enable(cfg_enable), .cfg_rss_key(cfg_rss_key),
            .cfg_ready(cfg_ready), .m_meta_valid(m_meta_valid), .m_header(m_header),
            .m_packet_bytes(m_packet_bytes), .m_rss_hash(m_rss_hash),
            .m_rss_valid(m_rss_valid), .m_rule_hit(m_rule_hit), .m_rule_index(m_rule_index),
            .m_action(m_action), .m_meta_ready(m_meta_ready)
        );
        furnace_descriptor_rings queue_rings (
            .clk(clk), .rst_n(rst_n), .dma_enable(dma_enable),
            .ctl_allow(ctl_allow), .pf_allow(pf_allow),
            .q_cfg_valid(q_cfg_valid), .q_cfg_id(q_cfg_id), .q_cfg_enable(q_cfg_enable),
            .q_cfg_ring_base(q_cfg_ring_base), .q_cfg_ring_entries(q_cfg_ring_entries),
            .q_cfg_quantum(q_cfg_quantum), .q_cfg_rate(q_cfg_rate), .q_cfg_burst(q_cfg_burst),
            .q_cfg_ready(q_cfg_ready), .db_valid(db_valid), .db_queue(db_queue),
            .db_producer(db_producer), .db_ready(db_ready), .ctl_valid(ctl_valid),
            .ctl_queue(ctl_queue), .ctl_code(ctl_code), .ctl_ready(ctl_ready),
            .cfg_commit(cfg_commit), .cfg_commit_queue(cfg_commit_queue),
            .cfg_commit_enable(cfg_commit_enable), .cfg_commit_quantum(cfg_commit_quantum),
            .cfg_commit_rate(cfg_commit_rate), .cfg_commit_burst(cfg_commit_burst),
            .q_enabled(q_enabled), .q_pending(q_pending), .head_valid(head_valid),
            .head_seq(head_seq), .head_bytes(head_bytes), .head_cookie(head_cookie),
            .head_status(head_status), .q_quantum(q_quantum), .q_burst(q_burst),
            .pf_valid(pf_valid), .pf_queue(pf_queue), .pf_seq(pf_seq),
            .pf_desc_addr(pf_desc_addr), .pf_burst(pf_burst), .pf_ready(pf_ready),
            .pf_done_valid(pf_done_valid), .pf_done_queue(pf_done_queue),
            .pf_done_seq(pf_done_seq), .pf_done_bytes(pf_done_bytes),
            .pf_done_cookie(pf_done_cookie), .pf_done_status(pf_done_status),
            .pf_done_ready(pf_done_ready), .retire_fire(retire_fire),
            .evt_queue(evt_queue), .evt_seq(evt_seq), .evt_bytes(evt_bytes),
            .rings_idle(rings_idle)
        );
        furnace_drr_scheduler scheduler (
            .clk(clk), .rst_n(rst_n), .decision_allow(decision_allow),
            .cfg_commit(cfg_commit), .cfg_commit_queue(cfg_commit_queue),
            .cfg_commit_enable(cfg_commit_enable), .cfg_commit_quantum(cfg_commit_quantum),
            .cfg_commit_rate(cfg_commit_rate), .cfg_commit_burst(cfg_commit_burst),
            .q_enabled(q_enabled), .q_pending(q_pending), .head_valid(head_valid),
            .head_seq(head_seq), .head_bytes(head_bytes), .head_status(head_status),
            .q_quantum(q_quantum), .token_balance(token_balance),
            .grant_valid(grant_valid), .grant_queue(grant_queue), .grant_seq(grant_seq),
            .grant_bytes(grant_bytes), .grant_ready(grant_ready),
            .reserve_fire(reserve_fire), .refund_fire(refund_fire), .retire_fire(retire_fire),
            .retire_reserved(retire_reserved), .evt_queue(evt_queue),
            .evt_seq(evt_seq), .evt_bytes(evt_bytes), .decision_busy(decision_busy),
            .scheduler_idle(scheduler_idle)
        );
        furnace_token_bucket8 shaper (
            .clk(clk), .rst_n(rst_n), .cfg_commit(cfg_commit),
            .cfg_commit_queue(cfg_commit_queue), .cfg_commit_enable(cfg_commit_enable),
            .cfg_commit_quantum(cfg_commit_quantum), .cfg_commit_rate(cfg_commit_rate),
            .cfg_commit_burst(cfg_commit_burst), .reserve_fire(reserve_fire),
            .refund_fire(refund_fire), .retire_fire(retire_fire),
            .retire_reserved(retire_reserved), .evt_queue(evt_queue),
            .evt_seq(evt_seq), .evt_bytes(evt_bytes), .token_balance(token_balance)
        );
        furnace_sg_dma #(.DATA_WIDTH(DATA_WIDTH), .MAX_PACKET_BYTES(MAX_PACKET_BYTES),
                         .MAX_SG(MAX_SG)) dma_engine (
            .clk(clk), .rst_n(rst_n), .pf_valid(pf_valid), .pf_queue(pf_queue),
            .pf_seq(pf_seq), .pf_desc_addr(pf_desc_addr), .pf_burst(pf_burst),
            .pf_ready(pf_ready), .pf_done_valid(pf_done_valid),
            .pf_done_queue(pf_done_queue), .pf_done_seq(pf_done_seq),
            .pf_done_bytes(pf_done_bytes), .pf_done_cookie(pf_done_cookie),
            .pf_done_status(pf_done_status), .pf_done_ready(pf_done_ready),
            .run_valid(run_valid), .run_queue(run_queue), .run_seq(run_seq),
            .run_bytes(run_bytes), .run_ready(run_ready), .run_done_valid(run_done_valid),
            .run_done_queue(run_done_queue), .run_done_seq(run_done_seq),
            .run_done_status(run_done_status), .run_done_ready(run_done_ready),
            .pkt_valid(pkt_valid), .pkt_data(pkt_data), .pkt_keep(pkt_keep),
            .pkt_last(pkt_last), .pkt_ready(pkt_ready), .x2_done(x2_done),
            .retire_fire(retire_fire), .evt_queue(evt_queue), .evt_seq(evt_seq),
            .evt_bytes(evt_bytes), .dma_busy(dma_busy), .dma_rd_valid(dma_rd_valid),
            .dma_rd_addr(dma_rd_addr), .dma_rd_len(dma_rd_len), .dma_rd_ready(dma_rd_ready),
            .dma_rsp_valid(dma_rsp_valid), .dma_rsp_data(dma_rsp_data),
            .dma_rsp_keep(dma_rsp_keep), .dma_rsp_last(dma_rsp_last),
            .dma_rsp_error(dma_rsp_error), .dma_rsp_ready(dma_rsp_ready)
        );

        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                arbitration<=BOUNDARY; service_clocks<=0; saw_decision<=0;
                active_valid<=0; active_reserved<=0; active_queue<=0;
                active_seq<=0; active_bytes<=0; active_cookie<=0; error_cursor<=0;
                completion_valid<=0; completion_status<=0; completion_bytes<=0;
                x2_occupied<=0; payload_done<=0; crc_done<=0; meta_done<=0; done_sent<=0;
            end else begin
                if (input_fire) x2_occupied<=1;
                if (payload_terminal) payload_done<=1;
                if (crc_terminal) crc_done<=1;
                if (meta_terminal) meta_done<=1;
                if (all_results) begin
                    x2_occupied<=0; payload_done<=0; crc_done<=0; meta_done<=0;
                end
                if (x2_done) done_sent<=1;
                case (arbitration)
                    BOUNDARY: begin
                        service_clocks<=0; saw_decision<=0;
                        if (dma_enable && !active_valid && !dma_busy && !pf_valid) begin
                            if (error_found && !decision_busy) begin
                                active_valid<=1; active_reserved<=0; active_queue<=error_queue;
                                active_seq<=head_seq[error_queue*32 +:32];
                                active_bytes<=head_bytes[error_queue*32 +:32];
                                active_cookie<=head_cookie[error_queue*32 +:32];
                                completion_valid<=1; completion_bytes<=0;
                                completion_status<=head_status[error_queue*3 +:3];
                                if (error_queue==7) error_cursor<=0;
                                else error_cursor<=error_queue+1'b1;
                                arbitration<=ACTIVE;
                            end else arbitration<=SERVICE;
                        end
                    end
                    SERVICE: begin
                        if (decision_busy) saw_decision<=1;
                        if (!decision_busy) begin
                            if (error_found || saw_decision) arbitration<=BOUNDARY;
                            else if (service_clocks==31) begin
                                if (need_prefetch) arbitration<=PREFETCH;
                                else arbitration<=BOUNDARY;
                            end else service_clocks<=service_clocks+1'b1;
                        end
                    end
                    PREFETCH: begin
                        if (pf_valid && pf_ready) arbitration<=PF_WAIT;
                        else if (!need_prefetch && !pf_valid) arbitration<=BOUNDARY;
                    end
                    PF_WAIT: if (!dma_busy && !pf_valid) arbitration<=BOUNDARY;
                    ACTIVE: if (retire_fire) arbitration<=BOUNDARY;
                    default: arbitration<=BOUNDARY;
                endcase
                if (reserve_fire) begin
                    active_valid<=1; active_reserved<=1; active_queue<=grant_queue;
                    active_seq<=grant_seq; active_bytes<=grant_bytes;
                    active_cookie<=head_cookie[grant_queue*32 +:32];
                    payload_done<=0; crc_done<=0; meta_done<=0; done_sent<=0;
                    arbitration<=ACTIVE;
                end
                if (run_done_valid && run_done_ready) begin
                    completion_valid<=1; completion_status<=run_done_status;
                    if (run_done_status==0) completion_bytes<=active_bytes;
                    else completion_bytes<=0;
                end
                if (retire_fire) begin
                    completion_valid<=0; active_valid<=0; active_reserved<=0;
                end
            end
        end
    end else begin : g_illegal
        initial $fatal(1,"PARAMETER ERROR: DATA_WIDTH=64/512, MAX_PACKET_BYTES=1..9216, MAX_SG=1..16 required");
        assign s_axis_tready=0; assign cfg_ready=0;
        assign m_axis_tdata=0; assign m_axis_tkeep=0; assign m_axis_tvalid=0;
        assign m_axis_tlast=0; assign m_crc_valid=0; assign m_crc32c=0;
        assign m_crc64_nvme=0; assign m_crc_mismatch=0; assign m_crc_protocol_error=0;
        assign m_meta_valid=0; assign m_header=0; assign m_packet_bytes=0;
        assign m_rss_hash=0; assign m_rss_valid=0; assign m_rule_hit=0;
        assign m_rule_index=0; assign m_action=0;
        assign q_cfg_ready=0; assign db_ready=0; assign ctl_valid=0;
        assign ctl_queue=0; assign ctl_code=0;
        assign dma_rd_valid=0; assign dma_rd_addr=0; assign dma_rd_len=0;
        assign dma_rsp_ready=0; assign dma_cpl_valid=0; assign dma_cpl_queue=0;
        assign dma_cpl_cookie=0; assign dma_cpl_status=0; assign dma_cpl_bytes=0;
        assign dma_idle=0;
    end endgenerate
endmodule
`default_nettype wire
