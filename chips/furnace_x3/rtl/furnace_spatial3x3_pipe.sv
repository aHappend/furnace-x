module furnace_spatial3x3_pipe (
    input wire clk, rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire [71:0] s_window,
    output wire m_valid,
    input wire m_ready,
    output wire [63:0] m_data
);
    reg enabled;
    reg [3:0] valid_pipe;
    reg [71:0] window_data;
    wire signed [11:0] p [0:8];
    genvar g;
    generate for (g=0;g<9;g=g+1) begin: pixels
        assign p[g]=$signed({4'b0,window_data[8*g+:8]});
    end endgenerate
    reg signed [11:0] gx0,gx1,gx2,gy0,gy2,l0,l1,l2;
    reg signed [13:0] gx,gy,laplacian;
    reg [7:0] center1,center2;
    reg [63:0] answer;
    wire advance=!valid_pipe[3] || m_ready;
    assign s_ready=rst_n && enabled && advance;
    assign m_valid=rst_n && enabled && valid_pipe[3];
    assign m_data=(rst_n && enabled) ? answer : 64'b0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enabled<=0; valid_pipe<=0; window_data<=0;
            gx0<=0; gx1<=0; gx2<=0; gy0<=0; gy2<=0;
            l0<=0; l1<=0; l2<=0; gx<=0; gy<=0; laplacian<=0;
            center1<=0; center2<=0; answer<=0;
        end else begin
            enabled<=1;
            if (enabled && advance) begin
                valid_pipe<={valid_pipe[2:0],s_valid && s_ready};
                if (s_valid && s_ready) window_data<=s_window;
                if (valid_pipe[0]) begin
                    gx0<=p[2]-p[0]; gx1<=(p[5]-p[3])<<<1; gx2<=p[8]-p[6];
                    gy0<=-p[0]-(p[1]<<<1)-p[2];
                    gy2<=p[6]+(p[7]<<<1)+p[8];
                    l0<=p[1]; l1<=p[3]-(p[4]<<<2)+p[5]; l2<=p[7];
                    center1<=window_data[32+:8];
                end
                if (valid_pipe[1]) begin
                    gx<=$signed({{2{gx0[11]}},gx0})+
                        $signed({{2{gx1[11]}},gx1})+$signed({{2{gx2[11]}},gx2});
                    gy<=$signed({{2{gy0[11]}},gy0})+$signed({{2{gy2[11]}},gy2});
                    laplacian<=$signed({{2{l0[11]}},l0})+
                        $signed({{2{l1[11]}},l1})+$signed({{2{l2[11]}},l2});
                    center2<=center1;
                end
                if (valid_pipe[2])
                    answer<={{2{laplacian[13]}},laplacian,
                        {2{gy[13]}},gy,{2{gx[13]}},gx,8'b0,center2};
            end
        end
    end
endmodule
