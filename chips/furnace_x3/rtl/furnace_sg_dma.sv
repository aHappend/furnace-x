`default_nettype none
module furnace_sg_dma #(
    parameter integer DATA_WIDTH=512,
    parameter integer MAX_PACKET_BYTES=9216,
    parameter integer MAX_SG=16
) (
    input wire clk, rst_n,
    input wire pf_valid,
    input wire [2:0] pf_queue,
    input wire [31:0] pf_seq,
    input wire [63:0] pf_desc_addr,
    input wire [15:0] pf_burst,
    output wire pf_ready,
    output wire pf_done_valid,
    output wire [2:0] pf_done_queue,
    output wire [31:0] pf_done_seq, pf_done_bytes, pf_done_cookie,
    output wire [2:0] pf_done_status,
    input wire pf_done_ready,
    input wire run_valid,
    input wire [2:0] run_queue,
    input wire [31:0] run_seq, run_bytes,
    output wire run_ready,
    output wire run_done_valid,
    output wire [2:0] run_done_queue,
    output wire [31:0] run_done_seq,
    output wire [2:0] run_done_status,
    input wire run_done_ready,
    output wire pkt_valid,
    output reg [DATA_WIDTH-1:0] pkt_data,
    output reg [(DATA_WIDTH>>3)-1:0] pkt_keep,
    output reg pkt_last,
    input wire pkt_ready, x2_done,
    input wire retire_fire,
    input wire [2:0] evt_queue,
    input wire [31:0] evt_seq, evt_bytes,
    output wire dma_busy,
    output wire dma_rd_valid,
    output wire [63:0] dma_rd_addr,
    output wire [15:0] dma_rd_len,
    input wire dma_rd_ready,
    input wire dma_rsp_valid,
    input wire [DATA_WIDTH-1:0] dma_rsp_data,
    input wire [(DATA_WIDTH>>3)-1:0] dma_rsp_keep,
    input wire dma_rsp_last, dma_rsp_error,
    output wire dma_rsp_ready
);
    localparam integer LANES=DATA_WIDTH>>3;
    localparam IDLE=0, DESC_START=1, DESC_WAIT=2, DESC_CHECK=3,
        SG_START=4, SG_WAIT=5, SG_CHECK=6, SG_ACCUM=7, PF_PUBLISH=8,
        PF_RESULT=9, LOAD_SEG=10, PAY_START=11, PAY_WAIT=12,
        RAM_READ=15, RAM_APPEND=16,
        PACK_PUBLISH=17, PACK_SEND=18, X2_WAIT=19, RESULT_DELAY=20,
        RUN_RESULT=21, RETIRE_WAIT=22, SG_ADVANCE=23;
    reg [4:0] state;
    reg [2:0] work_queue, work_status;
    reg [31:0] work_seq, work_bytes, work_cookie;
    reg [15:0] work_burst;
    reg [63:0] descriptor_addr, sg_addr;
    reg [255:0] descriptor;
    reg [127:0] sg_entry;
    reg [7:0] sg_count, sg_index;
    reg [32:0] sg_sum;
    reg [64:0] checked_end;
    reg [32:0] checked_sum;
    reg [7:0] cache_valid;
    reg [31:0] cache_seq [0:7];
    reg [7:0] cache_count [0:7];
    (* nomem2reg *) reg [63:0] cache_addr [0:8*MAX_SG-1];
    (* nomem2reg *) reg [31:0] cache_len [0:8*MAX_SG-1];
    reg [63:0] segment_addr;
    reg [31:0] segment_len, packet_written, output_index;
    reg [DATA_WIDTH-1:0] assembly;
    reg [LANES-1:0] assembly_keep;
    reg [6:0] assembly_count;
    reg assembly_last;
    (* ramstyle = "M20K", nomem2reg *) reg [7:0] packet_ram [0:MAX_PACKET_BYTES-1];
    reg [7:0] ram_q;
    wire read_start = state==DESC_START || state==SG_START || state==PAY_START;
    wire read_start_ready, read_byte_valid, read_done_valid;
    wire [7:0] read_byte;
    wire [31:0] read_byte_index, read_count;
    wire [2:0] read_status;
    wire [63:0] read_addr = state==DESC_START ? descriptor_addr :
                           state==SG_START ? sg_addr : segment_addr;
    wire [15:0] read_len = state==DESC_START ? 16'd32 :
                          state==SG_START ? 16'd16 : segment_len[15:0];
    wire read_done_ready = state==DESC_WAIT || state==SG_WAIT || state==PAY_WAIT;
    wire payload_write = rst_n && state==PAY_WAIT && read_byte_valid &&
                         packet_written<MAX_PACKET_BYTES;
    wire [64:0] desc_sg_end = {1'b0,descriptor[63:0]}+
                             ({57'b0,descriptor[103:96]}<<4)-65'd1;
    wire desc_bad = descriptor[63:0]==64'hffffffffffffffff ||
        descriptor[3:0]!=0 || descriptor[95:64]==0 ||
        descriptor[95:64]>MAX_PACKET_BYTES || descriptor[95:64]>{16'b0,work_burst} ||
        descriptor[103:96]==0 || descriptor[103:96]>MAX_SG ||
        descriptor[127:104]!=0 || descriptor[255:160]!=0 || desc_sg_end[64];
    wire [64:0] sg_payload_end={1'b0,sg_entry[63:0]}+
                               {33'b0,sg_entry[95:64]}-65'd1;
    wire [32:0] sg_next_sum=sg_sum+{1'b0,sg_entry[95:64]};
    wire run_identity = cache_valid[run_queue] && cache_seq[run_queue]==run_seq;
    assign pf_ready=rst_n && state==IDLE && !run_valid;
    assign pf_done_valid=rst_n && state==PF_RESULT;
    assign pf_done_queue=work_queue;
    assign pf_done_seq=work_seq;
    assign pf_done_bytes=work_bytes;
    assign pf_done_cookie=work_cookie;
    assign pf_done_status=work_status;
    assign run_ready=rst_n && state==IDLE && run_identity;
    assign run_done_valid=rst_n && state==RUN_RESULT;
    assign run_done_queue=work_queue;
    assign run_done_seq=work_seq;
    assign run_done_status=work_status;
    assign dma_busy=rst_n && state!=IDLE;
    assign pkt_valid=rst_n && state==PACK_SEND;

    furnace_dma_reader #(.DATA_WIDTH(DATA_WIDTH)) response_reader (
        .clk(clk), .rst_n(rst_n), .start_valid(read_start),
        .start_ready(read_start_ready), .start_addr(read_addr), .start_len(read_len),
        .byte_valid(read_byte_valid), .byte_data(read_byte),
        .byte_index(read_byte_index), .done_valid(read_done_valid),
        .done_ready(read_done_ready), .done_status(read_status), .done_count(read_count),
        .dma_rd_valid(dma_rd_valid), .dma_rd_addr(dma_rd_addr), .dma_rd_len(dma_rd_len),
        .dma_rd_ready(dma_rd_ready), .dma_rsp_valid(dma_rsp_valid),
        .dma_rsp_data(dma_rsp_data), .dma_rsp_keep(dma_rsp_keep),
        .dma_rsp_last(dma_rsp_last), .dma_rsp_error(dma_rsp_error),
        .dma_rsp_ready(dma_rsp_ready)
    );
    always @(posedge clk) begin
        if (payload_write) packet_ram[packet_written]<=read_byte;
        if (rst_n && state==RAM_READ) ram_q<=packet_ram[output_index];
        if (rst_n && state==LOAD_SEG) begin
            segment_addr<=cache_addr[work_queue*MAX_SG+sg_index];
            segment_len<=cache_len[work_queue*MAX_SG+sg_index];
        end
        if (rst_n && state==SG_ACCUM && !checked_end[64] &&
            sg_entry[95:64]!=0 && sg_entry[127:96]==0 &&
            !checked_sum[32] && checked_sum<={1'b0,work_bytes}) begin
            cache_addr[work_queue*MAX_SG+sg_index]<=sg_entry[63:0];
            cache_len[work_queue*MAX_SG+sg_index]<=sg_entry[95:64];
        end
    end
    integer i, lane;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; work_queue<=0; work_seq<=0; work_bytes<=0;
            work_cookie<=0; work_burst<=0; work_status<=0; descriptor_addr<=0;
            sg_addr<=0; descriptor<=0; sg_entry<=0; sg_count<=0; sg_index<=0;
            sg_sum<=0; checked_end<=0; checked_sum<=0; cache_valid<=0;
            packet_written<=0; output_index<=0;
            assembly<=0; assembly_keep<=0; assembly_count<=0; assembly_last<=0;
            pkt_data<=0; pkt_keep<=0; pkt_last<=0;
            for (i=0;i<8;i=i+1) begin cache_seq[i]<=0; cache_count[i]<=0; end
        end else begin
            if (read_byte_valid && state==DESC_WAIT)
                descriptor<={read_byte,descriptor[255:8]};
            if (read_byte_valid && state==SG_WAIT)
                sg_entry<={read_byte,sg_entry[127:8]};
            if (payload_write) packet_written<=packet_written+1'b1;
            if (retire_fire && cache_seq[evt_queue]==evt_seq)
                cache_valid[evt_queue]<=0;
            case (state)
                IDLE: begin
                    if (run_valid && run_ready) begin
                        work_queue<=run_queue; work_seq<=run_seq; work_bytes<=run_bytes;
                        work_status<=0; sg_index<=0;
                        packet_written<=0; output_index<=0; state<=LOAD_SEG;
                    end else if (pf_valid && pf_ready) begin
                        work_queue<=pf_queue; work_seq<=pf_seq; work_bytes<=0;
                        work_cookie<=0; work_burst<=pf_burst; work_status<=0;
                        descriptor_addr<=pf_desc_addr; descriptor<=0;
                        cache_valid[pf_queue]<=0; state<=DESC_START;
                    end
                end
                DESC_START: if (read_start_ready) state<=DESC_WAIT;
                DESC_WAIT: if (read_done_valid) begin
                    if (read_count>=32) begin
                        work_cookie<=descriptor[159:128];
                        work_bytes<=descriptor[95:64];
                    end
                    if (read_status!=0) begin work_status<=read_status; state<=PF_PUBLISH; end
                    else state<=DESC_CHECK;
                end
                DESC_CHECK: begin
                    if (desc_bad) begin work_status<=1; state<=PF_PUBLISH; end
                    else begin
                        sg_addr<=descriptor[63:0]; sg_count<=descriptor[103:96];
                        sg_index<=0; sg_sum<=0; sg_entry<=0; state<=SG_START;
                    end
                end
                SG_START: if (read_start_ready) state<=SG_WAIT;
                SG_WAIT: if (read_done_valid) begin
                    if (read_status!=0) begin work_status<=read_status; state<=PF_PUBLISH; end
                    else state<=SG_CHECK;
                end
                SG_CHECK: begin
                    checked_end<=sg_payload_end; checked_sum<=sg_next_sum;
                    state<=SG_ACCUM;
                end
                SG_ACCUM: begin
                    if (checked_end[64] || sg_entry[95:64]==0 ||
                        sg_entry[127:96]!=0 || checked_sum[32] ||
                        checked_sum>{1'b0,work_bytes}) begin
                        work_status<=2; state<=PF_PUBLISH;
                    end else begin
                        sg_sum<=checked_sum; state<=SG_ADVANCE;
                    end
                end
                SG_ADVANCE: begin
                    if (sg_index+1'b1==sg_count) begin
                        if (sg_sum!={1'b0,work_bytes}) work_status<=2;
                        else begin
                            cache_valid[work_queue]<=1; cache_seq[work_queue]<=work_seq;
                            cache_count[work_queue]<=sg_count;
                        end
                        state<=PF_PUBLISH;
                    end else begin
                        sg_index<=sg_index+1'b1; sg_addr<=sg_addr+64'd16;
                        sg_entry<=0; state<=SG_START;
                    end
                end
                PF_PUBLISH: state<=PF_RESULT;
                PF_RESULT: if (pf_done_ready) state<=IDLE;
                LOAD_SEG: state<=PAY_START;
                PAY_START: if (read_start_ready) state<=PAY_WAIT;
                PAY_WAIT: if (read_done_valid) begin
                    if (read_status!=0) begin work_status<=read_status; state<=RESULT_DELAY; end
                    else if (sg_index+1'b1==cache_count[work_queue]) begin
                        output_index<=0; assembly<=0; assembly_keep<=0;
                        assembly_count<=0; assembly_last<=0; state<=RAM_READ;
                    end else begin sg_index<=sg_index+1'b1; state<=LOAD_SEG; end
                end
                RAM_READ: state<=RAM_APPEND;
                RAM_APPEND: begin
                    for (lane=0;lane<LANES;lane=lane+1) begin
                        if (assembly_count==lane) begin
                            assembly[lane*8 +:8]<=ram_q;
                            assembly_keep[lane]<=1;
                        end
                    end
                    assembly_count<=assembly_count+1'b1;
                    output_index<=output_index+1'b1;
                    if (output_index+1'b1==work_bytes || assembly_count==LANES-1) begin
                        assembly_last<=output_index+1'b1==work_bytes;
                        state<=PACK_PUBLISH;
                    end else state<=RAM_READ;
                end
                PACK_PUBLISH: begin
                    pkt_data<=assembly; pkt_keep<=assembly_keep; pkt_last<=assembly_last;
                    state<=PACK_SEND;
                end
                PACK_SEND: if (pkt_ready) begin
                    if (pkt_last) state<=X2_WAIT;
                    else begin
                        assembly<=0; assembly_keep<=0; assembly_count<=0;
                        state<=RAM_READ;
                    end
                end
                X2_WAIT: if (x2_done) state<=RESULT_DELAY;
                RESULT_DELAY: state<=RUN_RESULT;
                RUN_RESULT: if (run_done_ready) state<=RETIRE_WAIT;
                RETIRE_WAIT: if (retire_fire && evt_queue==work_queue &&
                                evt_seq==work_seq) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
