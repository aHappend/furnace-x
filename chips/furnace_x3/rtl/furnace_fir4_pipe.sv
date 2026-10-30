module furnace_fir4_pipe (
    input wire clk, rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire signed [15:0] s_data,
    input wire s_first,
    output wire m_valid,
    input wire m_ready,
    output wire signed [15:0] m_data
);
    reg enabled;
    reg [3:0] valid_pipe;
    reg signed [15:0] history0,history1,history2,answer;
    wire signed [17:0] x=$signed({{2{s_data[15]}},s_data});
    wire signed [17:0] h0=s_first ? 18'sd0 :
        $signed({{2{history0[15]}},history0});
    wire signed [17:0] h1=s_first ? 18'sd0 :
        $signed({{2{history1[15]}},history1});
    wire signed [17:0] h2=s_first ? 18'sd0 :
        $signed({{2{history2[15]}},history2});
    reg signed [17:0] product0,product1,product2,product3;
    reg signed [18:0] pair0,pair1;
    reg signed [19:0] full_sum;
    wire advance=!valid_pipe[3] || m_ready;
    assign s_ready=rst_n && enabled && advance;
    assign m_valid=rst_n && enabled && valid_pipe[3];
    assign m_data=(rst_n && enabled) ? answer : 16'sd0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enabled<=0; valid_pipe<=0; history0<=0; history1<=0; history2<=0;
            product0<=0; product1<=0; product2<=0; product3<=0;
            pair0<=0; pair1<=0; full_sum<=0; answer<=0;
        end else begin
            enabled<=1;
            if (enabled && advance) begin
                valid_pipe<={valid_pipe[2:0],s_valid && s_ready};
                if (s_valid && s_ready) begin
                    product0<=x; product1<=h0+(h0<<<1);
                    product2<=h1+(h1<<<1); product3<=h2;
                    history0<=s_data;
                    if (s_first) begin history1<=0; history2<=0; end
                    else begin history1<=history0; history2<=history1; end
                end
                if (valid_pipe[0]) begin
                    pair0<=$signed({product0[17],product0})+
                        $signed({product1[17],product1});
                    pair1<=$signed({product2[17],product2})+
                        $signed({product3[17],product3});
                end
                if (valid_pipe[1])
                    full_sum<=$signed({pair0[18],pair0})+$signed({pair1[18],pair1});
                if (valid_pipe[2]) answer<=full_sum>>>3;
            end
        end
    end
endmodule
