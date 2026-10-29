`default_nettype none
module furnace_dma_reader #(
    parameter integer DATA_WIDTH=512
) (
    input wire clk, rst_n,
    input wire start_valid,
    output wire start_ready,
    input wire [63:0] start_addr,
    input wire [15:0] start_len,
    output wire byte_valid,
    output wire [7:0] byte_data,
    output wire [31:0] byte_index,
    output wire done_valid,
    input wire done_ready,
    output wire [2:0] done_status,
    output wire [31:0] done_count,
    output wire dma_rd_valid,
    output reg [63:0] dma_rd_addr,
    output reg [15:0] dma_rd_len,
    input wire dma_rd_ready,
    input wire dma_rsp_valid,
    input wire [DATA_WIDTH-1:0] dma_rsp_data,
    input wire [(DATA_WIDTH>>3)-1:0] dma_rsp_keep,
    input wire dma_rsp_last, dma_rsp_error,
    output wire dma_rsp_ready
);
    localparam integer LANES=DATA_WIDTH>>3;
    localparam IDLE=0, REQUEST=1, RESPONSE=2, UNPACK=3, DONE=4;
    reg [2:0] state, status;
    reg [DATA_WIDTH-1:0] stage_data;
    reg [LANES-1:0] stage_keep;
    reg [6:0] stage_left;
    reg stage_last;
    reg [31:0] consumed, received;
    wire [6:0] count_tree [0:126];
    wire [LANES-1:0] prefix_fault;
    genvar n;
    generate
        for (n=0;n<64;n=n+1) begin : g_count
            if (n<LANES) assign count_tree[63+n]={6'b0,dma_rsp_keep[n]};
            else assign count_tree[63+n]=0;
        end
        for (n=0;n<63;n=n+1) begin : g_sum
            assign count_tree[n]=count_tree[2*n+1]+count_tree[2*n+2];
        end
        for (n=0;n<LANES;n=n+1) begin : g_prefix
            if (n==0) assign prefix_fault[n]=0;
            else assign prefix_fault[n]=dma_rsp_keep[n] && !dma_rsp_keep[n-1];
        end
    endgenerate
    wire [32:0] next_received={1'b0,received}+{26'b0,count_tree[0]};
    wire format_fault = dma_rsp_last ?
        ((count_tree[0]==0) || (|prefix_fault) ||
         next_received!={17'b0,dma_rd_len}) :
        ((!(&dma_rsp_keep)) || next_received>={17'b0,dma_rd_len});
    assign start_ready=rst_n && state==IDLE;
    assign dma_rd_valid=rst_n && state==REQUEST;
    assign dma_rsp_ready=rst_n && state==RESPONSE;
    assign byte_valid=rst_n && state==UNPACK && stage_keep[0] &&
                      consumed<{16'b0,dma_rd_len};
    assign byte_data=stage_data[7:0];
    assign byte_index=consumed;
    assign done_valid=rst_n && state==DONE;
    assign done_status=status;
    assign done_count=received;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; status<=0; stage_data<=0; stage_keep<=0;
            stage_left<=0; stage_last<=0; consumed<=0; received<=0;
            dma_rd_addr<=0; dma_rd_len<=0;
        end else begin
            case (state)
                IDLE: if (start_valid && start_ready) begin
                    dma_rd_addr<=start_addr; dma_rd_len<=start_len;
                    consumed<=0; received<=0; status<=0; state<=REQUEST;
                end
                REQUEST: if (dma_rd_ready) state<=RESPONSE;
                RESPONSE: if (dma_rsp_valid && dma_rsp_ready) begin
                    stage_data<=dma_rsp_data; stage_keep<=dma_rsp_keep;
                    stage_last<=dma_rsp_last;
                    if (!(|prefix_fault) && count_tree[0]!=0)
                        stage_left<=count_tree[0];
                    else stage_left<=LANES;
                    received<=next_received[32] ? 32'hffffffff :
                                                next_received[31:0];
                    if (status==0) begin
                        if (dma_rsp_error) status<=3;
                        else if (format_fault) status<=4;
                    end
                    state<=UNPACK;
                end
                UNPACK: begin
                    stage_data<=stage_data>>8; stage_keep<=stage_keep>>1;
                    if (stage_keep[0] && consumed!=32'hffffffff)
                        consumed<=consumed+1'b1;
                    stage_left<=stage_left-1'b1;
                    if (stage_left==1) begin
                        if (stage_last) state<=DONE; else state<=RESPONSE;
                    end
                end
                DONE: if (done_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
