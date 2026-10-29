`default_nettype none
module furnace_drr_scheduler (
    input wire clk, rst_n, decision_allow,
    input wire cfg_commit,
    input wire [2:0] cfg_commit_queue,
    input wire cfg_commit_enable,
    input wire [15:0] cfg_commit_quantum,
    input wire [31:0] cfg_commit_rate,
    input wire [15:0] cfg_commit_burst,
    input wire [7:0] q_enabled, q_pending, head_valid,
    input wire [255:0] head_seq, head_bytes,
    input wire [23:0] head_status,
    input wire [127:0] q_quantum,
    input wire [383:0] token_balance,
    output wire grant_valid,
    output reg [2:0] grant_queue,
    output reg [31:0] grant_seq, grant_bytes,
    input wire grant_ready,
    input wire reserve_fire, refund_fire, retire_fire, retire_reserved,
    input wire [2:0] evt_queue,
    input wire [31:0] evt_seq, evt_bytes,
    output wire decision_busy, scheduler_idle
);
    localparam SCAN=0, COMPARE=1, COMMIT=2, GRANT=3, WAIT_RETIRE=4;
    reg [2:0] state, visit_queue;
    reg visit_active;
    reg [31:0] deficit [0:7];
    reg [31:0] snapshot_deficit;
    reg [47:0] snapshot_tokens;
    reg deficit_ok, tokens_ok;
    reg reservation_valid, reservation_settled;
    reg [2:0] reservation_queue;
    reg [31:0] reservation_seq, reservation_cost;
    wire [32:0] visit_sum = {1'b0,deficit[visit_queue]}+
                          {17'b0,q_quantum[visit_queue*16 +:16]};
    wire [32:0] refund_sum = {1'b0,deficit[evt_queue]}+
                            {1'b0,reservation_cost};
    wire matching = reservation_valid && reservation_queue==evt_queue &&
                    reservation_seq==evt_seq;
    assign grant_valid = rst_n && state==GRANT;
    assign decision_busy = rst_n && state!=SCAN;
    assign scheduler_idle = rst_n && state==SCAN && !reservation_valid;
    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=SCAN; visit_queue<=0; visit_active<=0;
            grant_queue<=0; grant_seq<=0; grant_bytes<=0;
            snapshot_deficit<=0; snapshot_tokens<=0; deficit_ok<=0; tokens_ok<=0;
            reservation_valid<=0; reservation_settled<=0;
            reservation_queue<=0; reservation_seq<=0; reservation_cost<=0;
            for (i=0;i<8;i=i+1) deficit[i]<=0;
        end else begin
            case (state)
                SCAN: begin
                    if (!q_enabled[visit_queue] || !q_pending[visit_queue]) begin
                        deficit[visit_queue]<=0; visit_active<=0;
                        if (visit_queue==7) visit_queue<=0;
                        else visit_queue<=visit_queue+1'b1;
                    end else if (!visit_active &&
                                 !(head_valid[visit_queue] &&
                                   head_status[visit_queue*3 +:3]!=0)) begin
                        deficit[visit_queue]<=visit_sum[32] ? 32'hffffffff :
                                                visit_sum[31:0];
                        visit_active<=1;
                    end else if (decision_allow && head_valid[visit_queue] &&
                                 head_status[visit_queue*3 +:3]==0) begin
                        grant_queue<=visit_queue;
                        grant_seq<=head_seq[visit_queue*32 +:32];
                        grant_bytes<=head_bytes[visit_queue*32 +:32];
                        snapshot_deficit<=deficit[visit_queue];
                        snapshot_tokens<=token_balance[visit_queue*48 +:48];
                        state<=COMPARE;
                    end
                end
                COMPARE: begin
                    deficit_ok<=snapshot_deficit>=grant_bytes;
                    tokens_ok<=snapshot_tokens>={grant_bytes,16'b0};
                    state<=COMMIT;
                end
                COMMIT: begin
                    if (deficit_ok && tokens_ok) state<=GRANT;
                    else begin
                        state<=SCAN; visit_active<=0;
                        if (visit_queue==7) visit_queue<=0;
                        else visit_queue<=visit_queue+1'b1;
                    end
                end
                GRANT: if (grant_valid && grant_ready) state<=WAIT_RETIRE;
                WAIT_RETIRE: if (retire_fire && retire_reserved && matching)
                    state<=SCAN;
                default: state<=SCAN;
            endcase
            if (cfg_commit) begin
                deficit[cfg_commit_queue]<=0;
                visit_queue<=0; visit_active<=0; state<=SCAN;
                reservation_valid<=0; reservation_settled<=0;
            end
            if (reserve_fire) begin
                deficit[evt_queue]<=deficit[evt_queue]-evt_bytes;
                reservation_valid<=1; reservation_settled<=0;
                reservation_queue<=evt_queue; reservation_seq<=evt_seq;
                reservation_cost<=evt_bytes;
            end
            if (refund_fire && matching && !reservation_settled) begin
                deficit[evt_queue]<=refund_sum[32] ? 32'hffffffff : refund_sum[31:0];
                reservation_settled<=1;
            end
            if (retire_fire && retire_reserved && matching) begin
                reservation_valid<=0; reservation_settled<=0;
            end
        end
    end
endmodule
`default_nettype wire
