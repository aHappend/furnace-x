module furnace_xxh32 (
    input wire clk, rst_n, cancel,
    input wire start_valid,
    output wire start_ready,
    input wire s_valid,
    output wire s_ready,
    input wire [7:0] s_data,
    input wire finish_valid,
    output wire finish_ready,
    output wire done_valid,
    input wire done_ready,
    output wire [31:0] digest
);
    localparam [31:0] P1=32'h9e3779b1, P2=32'h85ebca77,
        P3=32'hc2b2ae3d, P4=32'h27d4eb2f, P5=32'h165667b1;
    localparam [4:0] IDLE=0, FEED=1, STR_MUL=2, STR_ADD=3,
        STR_END=4, INIT=5, TAIL=6, WORD_MUL=7, WORD_ADD=8,
        WORD_END=9, BYTE_MUL=10, BYTE_ADD=11, BYTE_END=12,
        AV0=13, AV1=14, AV2=15, AV3=16, AV4=17, DONE=18;
    reg enabled;
    reg [4:0] state;
    reg [31:0] total, v0,v1,v2,v3, w0,w1,w2,w3;
    reg [31:0] t0,t1,t2,t3, hash, work, answer;
    reg [127:0] tail_bytes;
    reg [4:0] count, cursor;
    wire [127:0] shifted_tail = tail_bytes >> {cursor,3'b000};
    wire [31:0] word_plus = hash + work;
    function automatic [31:0] rol(input [31:0] x,input integer n);
        rol=(x << n) | (x >> (32-n));
    endfunction
    assign start_ready=rst_n && enabled && state==IDLE;
    assign s_ready=rst_n && enabled && state==FEED;
    assign finish_ready=rst_n && enabled && state==FEED && !s_valid;
    assign done_valid=rst_n && enabled && state==DONE;
    assign digest=(rst_n && enabled) ? answer : 32'b0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enabled<=0; state<=IDLE; total<=0; count<=0; cursor<=0;
            v0<=0; v1<=0; v2<=0; v3<=0;
            w0<=0; w1<=0; w2<=0; w3<=0;
            t0<=0; t1<=0; t2<=0; t3<=0;
            tail_bytes<=0; hash<=0; work<=0; answer<=0;
        end else begin
            enabled<=1;
            if (cancel) begin state<=IDLE; answer<=0; end
            else case (state)
                IDLE: if (start_valid && start_ready) begin
                    total<=0; count<=0; cursor<=0; tail_bytes<=0;
                    v0<=P1+P2; v1<=P2; v2<=0; v3<=32'b0-P1;
                    answer<=0; state<=FEED;
                end
                FEED: begin
                    if (s_valid && s_ready) begin
                        tail_bytes[{count[3:0],3'b000}+:8]<=s_data;
                        total<=total+1'b1;
                        if (count==15) begin
                            w0<=tail_bytes[31:0]; w1<=tail_bytes[63:32];
                            w2<=tail_bytes[95:64];
                            w3<={s_data,tail_bytes[119:96]};
                            count<=0; state<=STR_MUL;
                        end else count<=count+1'b1;
                    end else if (finish_valid && finish_ready) state<=INIT;
                end
                STR_MUL: begin
                    t0<=w0*P2; t1<=w1*P2; t2<=w2*P2; t3<=w3*P2;
                    state<=STR_ADD;
                end
                STR_ADD: begin
                    t0<=rol(v0+t0,13); t1<=rol(v1+t1,13);
                    t2<=rol(v2+t2,13); t3<=rol(v3+t3,13);
                    state<=STR_END;
                end
                STR_END: begin
                    v0<=t0*P1; v1<=t1*P1; v2<=t2*P1; v3<=t3*P1;
                    state<=FEED;
                end
                INIT: begin
                    if (total>=16)
                        hash<=rol(v0,1)+rol(v1,7)+rol(v2,12)+rol(v3,18);
                    else hash<=P5;
                    cursor<=0; state<=TAIL;
                end
                TAIL: begin
                    hash<=hash+total;
                    state<=WORD_MUL;
                end
                WORD_MUL: begin
                    if (cursor+5'd4<=count) begin
                        work<=shifted_tail[31:0]*P3; state<=WORD_ADD;
                    end else state<=BYTE_MUL;
                end
                WORD_ADD: begin
                    work<=rol(word_plus,17); state<=WORD_END;
                end
                WORD_END: begin
                    hash<=work*P4; cursor<=cursor+5'd4; state<=WORD_MUL;
                end
                BYTE_MUL: begin
                    if (cursor<count) begin
                        work<={24'b0,shifted_tail[7:0]}*P5; state<=BYTE_ADD;
                    end else state<=AV0;
                end
                BYTE_ADD: begin
                    work<=rol(word_plus,11); state<=BYTE_END;
                end
                BYTE_END: begin
                    hash<=work*P1; cursor<=cursor+1'b1; state<=BYTE_MUL;
                end
                AV0: begin hash<=hash^(hash>>15); state<=AV1; end
                AV1: begin hash<=hash*P2; state<=AV2; end
                AV2: begin hash<=hash^(hash>>13); state<=AV3; end
                AV3: begin hash<=hash*P3; state<=AV4; end
                AV4: begin answer<=hash^(hash>>16); state<=DONE; end
                DONE: if (done_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
