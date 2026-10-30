module furnace_bilinear_pipe (
    input wire clk, rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire [31:0] s_samples,
    input wire [7:0] s_xfrac, s_yfrac,
    output wire m_valid,
    input wire m_ready,
    output wire [7:0] m_data
);
    reg enabled;
    reg [5:0] valid_pipe;
    reg [31:0] samples;
    reg [7:0] xfrac, yfrac0, yfrac1, yfrac2;
    reg [15:0] horizontal_product [0:3];
    reg [16:0] horizontal_sum [0:1];
    reg [25:0] vertical_product [0:1];
    reg [27:0] rounded_sum;
    reg [7:0] answer;
    wire advance=!valid_pipe[5] || m_ready;
    wire [8:0] inverse_x=9'd256-{1'b0,xfrac};
    wire [8:0] inverse_y=9'd256-{1'b0,yfrac2};
    assign s_ready=rst_n && enabled && advance;
    assign m_valid=rst_n && enabled && valid_pipe[5];
    assign m_data=(rst_n && enabled) ? answer : 8'b0;

    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enabled<=0; valid_pipe<=0; samples<=0; xfrac<=0;
            yfrac0<=0; yfrac1<=0; yfrac2<=0; rounded_sum<=0; answer<=0;
            for (i=0;i<4;i=i+1) horizontal_product[i]<=0;
            for (i=0;i<2;i=i+1) begin
                horizontal_sum[i]<=0; vertical_product[i]<=0;
            end
        end else begin
            enabled<=1;
            if (enabled && advance) begin
                valid_pipe<={valid_pipe[4:0],s_valid && s_ready};
                if (s_valid && s_ready) begin
                    samples<=s_samples; xfrac<=s_xfrac; yfrac0<=s_yfrac;
                end
                if (valid_pipe[0]) begin
                    horizontal_product[0]<=samples[7:0]*inverse_x;
                    horizontal_product[1]<=samples[15:8]*{1'b0,xfrac};
                    horizontal_product[2]<=samples[23:16]*inverse_x;
                    horizontal_product[3]<=samples[31:24]*{1'b0,xfrac};
                    yfrac1<=yfrac0;
                end
                if (valid_pipe[1]) begin
                    horizontal_sum[0]<={1'b0,horizontal_product[0]}+
                        {1'b0,horizontal_product[1]};
                    horizontal_sum[1]<={1'b0,horizontal_product[2]}+
                        {1'b0,horizontal_product[3]};
                    yfrac2<=yfrac1;
                end
                if (valid_pipe[2]) begin
                    vertical_product[0]<=horizontal_sum[0]*inverse_y;
                    vertical_product[1]<=horizontal_sum[1]*{1'b0,yfrac2};
                end
                if (valid_pipe[3])
                    rounded_sum<={2'b0,vertical_product[0]}+
                        {2'b0,vertical_product[1]}+28'd32768;
                if (valid_pipe[4]) answer<=rounded_sum[23:16];
            end
        end
    end
endmodule
