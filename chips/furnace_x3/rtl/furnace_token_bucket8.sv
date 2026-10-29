`default_nettype none
module furnace_token_bucket8 (
    input wire clk, rst_n,
    input wire cfg_commit,
    input wire [2:0] cfg_commit_queue,
    input wire cfg_commit_enable,
    input wire [15:0] cfg_commit_quantum,
    input wire [31:0] cfg_commit_rate,
    input wire [15:0] cfg_commit_burst,
    input wire reserve_fire, refund_fire, retire_fire, retire_reserved,
    input wire [2:0] evt_queue,
    input wire [31:0] evt_seq, evt_bytes,
    output wire [383:0] token_balance
);
    reg [7:0] enabled;
    reg [31:0] rate [0:7];
    reg [47:0] capacity [0:7], balance [0:7];
    reg reservation_valid, reservation_settled;
    reg [2:0] reservation_queue;
    reg [31:0] reservation_seq;
    reg [47:0] reservation_cost;
    wire [47:0] event_cost = {evt_bytes,16'b0};
    wire matching = reservation_valid && reservation_queue==evt_queue &&
                    reservation_seq==evt_seq;
    genvar q;
    generate for (q=0;q<8;q=q+1) begin : g_bucket
        wire refund_here = refund_fire && matching && !reservation_settled &&
                           evt_queue==q;
        wire [49:0] refill_sum = {2'b0,balance[q]}+{18'b0,rate[q]}+
                               (refund_here ? {2'b0,reservation_cost} : 50'b0);
        wire [47:0] refilled = refill_sum>{2'b0,capacity[q]} ?
                              capacity[q] : refill_sum[47:0];
        assign token_balance[q*48 +:48] = rst_n ? balance[q] : 48'b0;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                enabled[q]<=0; rate[q]<=0; capacity[q]<=0; balance[q]<=0;
            end else if (cfg_commit && cfg_commit_queue==q) begin
                enabled[q]<=cfg_commit_enable; rate[q]<=cfg_commit_rate;
                capacity[q]<={16'b0,cfg_commit_burst,16'b0}; balance[q]<=0;
            end else if (enabled[q]) begin
                if (reserve_fire && evt_queue==q) balance[q]<=refilled-event_cost;
                else balance[q]<=refilled;
            end
        end
    end endgenerate
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            reservation_valid<=0; reservation_settled<=0;
            reservation_queue<=0; reservation_seq<=0; reservation_cost<=0;
        end else begin
            if (cfg_commit) begin reservation_valid<=0; reservation_settled<=0; end
            if (reserve_fire) begin
                reservation_valid<=1; reservation_settled<=0;
                reservation_queue<=evt_queue; reservation_seq<=evt_seq;
                reservation_cost<=event_cost;
            end
            if (refund_fire && matching && !reservation_settled)
                reservation_settled<=1;
            if (retire_fire && retire_reserved && matching) begin
                reservation_valid<=0; reservation_settled<=0;
            end
        end
    end
endmodule
`default_nettype wire
