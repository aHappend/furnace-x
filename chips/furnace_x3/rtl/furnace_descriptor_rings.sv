`default_nettype none
module furnace_descriptor_rings (
    input wire clk, rst_n, dma_enable, ctl_allow, pf_allow,
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
    output reg ctl_valid,
    output reg [2:0] ctl_queue, ctl_code,
    input wire ctl_ready,
    output wire cfg_commit,
    output wire [2:0] cfg_commit_queue,
    output wire cfg_commit_enable,
    output wire [15:0] cfg_commit_quantum,
    output wire [31:0] cfg_commit_rate,
    output wire [15:0] cfg_commit_burst,
    output wire [7:0] q_enabled, q_pending, head_valid,
    output wire [255:0] head_seq, head_bytes, head_cookie,
    output wire [23:0] head_status,
    output wire [127:0] q_quantum, q_burst,
    output reg pf_valid,
    output reg [2:0] pf_queue,
    output reg [31:0] pf_seq,
    output reg [63:0] pf_desc_addr,
    output reg [15:0] pf_burst,
    input wire pf_ready,
    input wire pf_done_valid,
    input wire [2:0] pf_done_queue,
    input wire [31:0] pf_done_seq, pf_done_bytes, pf_done_cookie,
    input wire [2:0] pf_done_status,
    output wire pf_done_ready,
    input wire retire_fire,
    input wire [2:0] evt_queue,
    input wire [31:0] evt_seq, evt_bytes,
    output wire rings_idle
);
    reg [7:0] enabled, configured, valid_head, claimed;
    reg [63:0] base [0:7];
    reg [8:0] entries [0:7], physical_index [0:7];
    reg [31:0] producer [0:7], consumer [0:7];
    reg [15:0] quantum [0:7], burst [0:7];
    reg [31:0] bytes_head [0:7], cookie_head [0:7];
    reg [2:0] status_head [0:7];
    reg [2:0] pf_cursor;
    wire [64:0] cfg_end = {1'b0,q_cfg_ring_base} +
                           ({56'b0,q_cfg_ring_entries} << 5) - 65'd1;
    wire cfg_legal = q_cfg_ring_entries>=1 && q_cfg_ring_entries<=256 &&
                     q_cfg_ring_base[4:0]==0 && !cfg_end[64] &&
                     (!q_cfg_enable || (q_cfg_quantum!=0 && q_cfg_burst!=0));
    wire [31:0] occupancy = producer[db_queue]-consumer[db_queue];
    wire [31:0] delta = db_producer-producer[db_queue];
    wire [31:0] free_slots = {23'b0,entries[db_queue]}-occupancy;
    wire db_legal = configured[db_queue] && enabled[db_queue] &&
                    delta<=free_slots;
    assign rings_idle = rst_n && !(|q_pending) && !(|valid_head) &&
                        !(|claimed) && !pf_valid && !ctl_valid;
    assign q_cfg_ready = rst_n && dma_enable && ctl_allow && rings_idle;
    assign db_ready = rst_n && dma_enable && !ctl_valid && !q_cfg_valid;
    assign cfg_commit = q_cfg_valid && q_cfg_ready && cfg_legal;
    assign cfg_commit_queue = q_cfg_id;
    assign cfg_commit_enable = q_cfg_enable;
    assign cfg_commit_quantum = q_cfg_quantum;
    assign cfg_commit_rate = q_cfg_rate;
    assign cfg_commit_burst = q_cfg_burst;
    assign q_enabled = rst_n ? enabled : 8'b0;
    assign head_valid = rst_n ? valid_head : 8'b0;
    assign pf_done_ready = rst_n && claimed[pf_done_queue] &&
                          consumer[pf_done_queue]==pf_done_seq;
    genvar q;
    generate for (q=0;q<8;q=q+1) begin : g_view
        assign q_pending[q] = rst_n && producer[q]!=consumer[q];
        assign head_seq[q*32 +:32] = rst_n ? consumer[q] : 32'b0;
        assign head_bytes[q*32 +:32] = rst_n ? bytes_head[q] : 32'b0;
        assign head_cookie[q*32 +:32] = rst_n ? cookie_head[q] : 32'b0;
        assign head_status[q*3 +:3] = rst_n ? status_head[q] : 3'b0;
        assign q_quantum[q*16 +:16] = rst_n ? quantum[q] : 16'b0;
        assign q_burst[q*16 +:16] = rst_n ? burst[q] : 16'b0;
    end endgenerate
    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enabled<=0; configured<=0; valid_head<=0; claimed<=0;
            ctl_valid<=0; ctl_queue<=0; ctl_code<=0;
            pf_valid<=0; pf_queue<=0; pf_seq<=0; pf_desc_addr<=0;
            pf_burst<=0; pf_cursor<=0;
            for (i=0;i<8;i=i+1) begin
                base[i]<=0; entries[i]<=0; physical_index[i]<=0;
                producer[i]<=0; consumer[i]<=0; quantum[i]<=0; burst[i]<=0;
                bytes_head[i]<=0; cookie_head[i]<=0; status_head[i]<=0;
            end
        end else begin
            if (ctl_valid && ctl_ready) ctl_valid<=0;
            if (q_cfg_valid && q_cfg_ready) begin
                ctl_valid<=1; ctl_queue<=q_cfg_id;
                if (cfg_legal) ctl_code<=0; else ctl_code<=1;
            end else if (db_valid && db_ready) begin
                ctl_valid<=1; ctl_queue<=db_queue;
                if (db_legal) begin ctl_code<=0; producer[db_queue]<=db_producer; end
                else ctl_code<=2;
            end
            if (cfg_commit) begin
                configured[q_cfg_id]<=1; enabled[q_cfg_id]<=q_cfg_enable;
                base[q_cfg_id]<=q_cfg_ring_base; entries[q_cfg_id]<=q_cfg_ring_entries;
                quantum[q_cfg_id]<=q_cfg_quantum; burst[q_cfg_id]<=q_cfg_burst;
                producer[q_cfg_id]<=0; consumer[q_cfg_id]<=0;
                physical_index[q_cfg_id]<=0; valid_head[q_cfg_id]<=0;
                claimed[q_cfg_id]<=0; bytes_head[q_cfg_id]<=0;
                cookie_head[q_cfg_id]<=0; status_head[q_cfg_id]<=0;
            end
            if (!pf_valid && pf_allow) begin
                if (enabled[pf_cursor] && q_pending[pf_cursor] &&
                    !valid_head[pf_cursor] && !claimed[pf_cursor]) begin
                    pf_valid<=1; pf_queue<=pf_cursor;
                    pf_seq<=consumer[pf_cursor]; pf_burst<=burst[pf_cursor];
                    pf_desc_addr<=base[pf_cursor]+
                                  ({55'b0,physical_index[pf_cursor]}<<5);
                end else if (pf_cursor==7) pf_cursor<=0;
                else pf_cursor<=pf_cursor+1'b1;
            end
            if (pf_valid && pf_ready) begin
                pf_valid<=0; claimed[pf_queue]<=1;
                if (pf_queue==7) pf_cursor<=0; else pf_cursor<=pf_queue+1'b1;
            end
            if (pf_done_valid && pf_done_ready) begin
                claimed[pf_done_queue]<=0; valid_head[pf_done_queue]<=1;
                bytes_head[pf_done_queue]<=pf_done_bytes;
                cookie_head[pf_done_queue]<=pf_done_cookie;
                status_head[pf_done_queue]<=pf_done_status;
            end
            if (retire_fire) begin
                consumer[evt_queue]<=consumer[evt_queue]+1'b1;
                if (physical_index[evt_queue]==entries[evt_queue]-1'b1)
                    physical_index[evt_queue]<=0;
                else physical_index[evt_queue]<=physical_index[evt_queue]+1'b1;
                valid_head[evt_queue]<=0;
            end
        end
    end
endmodule
`default_nettype wire
