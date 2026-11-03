module furnace_fft_radix2 #(
    parameter integer FFT_N=16
) (
    input wire clk, rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire signed [15:0] s_data,
    output wire m_valid,
    input wire m_ready,
    output wire signed [31:0] m_re, m_im,
    output wire [5:0] m_index,
    output wire m_last
);
    generate if (FFT_N!=8 && FFT_N!=16 && FFT_N!=32 && FFT_N!=64) begin: bad_parameter
        initial $fatal(1,"PARAMETER ERROR: FFT_N must be 8,16,32,64");
        assign s_ready=0; assign m_valid=0; assign m_re=0;
        assign m_im=0; assign m_index=0; assign m_last=0;
    end else begin: transform
        localparam integer L=$clog2(FFT_N);
        localparam integer BUTTERFLIES=FFT_N>>1;
        localparam [2:0] LOAD=0, RUN=1, FETCH=2, PRIME=3, OUTPUT_BINS=4;
        function automatic [5:0] reversed(input [5:0] index);
            integer b;
            begin
                reversed=0;
                for (b=0;b<L;b=b+1) reversed[L-1-b]=index[b];
            end
        endfunction
        function automatic signed [16:0] quarter_cos(input [4:0] index);
            begin
                case (index)
                    0:quarter_cos=17'sd32768; 1:quarter_cos=17'sd32610;
                    2:quarter_cos=17'sd32138; 3:quarter_cos=17'sd31357;
                    4:quarter_cos=17'sd30274; 5:quarter_cos=17'sd28899;
                    6:quarter_cos=17'sd27246; 7:quarter_cos=17'sd25330;
                    8:quarter_cos=17'sd23170; 9:quarter_cos=17'sd20788;
                    10:quarter_cos=17'sd18205; 11:quarter_cos=17'sd15447;
                    12:quarter_cos=17'sd12540; 13:quarter_cos=17'sd9512;
                    14:quarter_cos=17'sd6393; 15:quarter_cos=17'sd3212;
                    default:quarter_cos=0;
                endcase
            end
        endfunction
        function automatic signed [16:0] cos64(input [5:0] index);
            reg [6:0] folded;
            begin
                if (index<=16) begin
                    folded={1'b0,index}; cos64=quarter_cos(folded[4:0]);
                end else if (index<=32) begin
                    folded=7'd32-{1'b0,index}; cos64=-quarter_cos(folded[4:0]);
                end else if (index<=48) begin
                    folded={1'b0,index}-7'd32; cos64=-quarter_cos(folded[4:0]);
                end else begin
                    folded=7'd64-{1'b0,index}; cos64=quarter_cos(folded[4:0]);
                end
            end
        endfunction
        function automatic signed [31:0] saturate32(input signed [50:0] value);
            begin
                if (value>51'sd2147483647) saturate32=32'sh7fffffff;
                else if (value< -51'sd2147483648) saturate32=32'sh80000000;
                else saturate32=value[31:0];
            end
        endfunction

        reg enabled,source_bank,output_valid;
        reg [2:0] state,stage;
        reg [5:0] input_index,output_index;
        reg [6:0] stage_cycle;
        reg [4:0] butterfly_valid;
        (* nomem2reg *) reg signed [31:0] real0 [0:FFT_N-1];
        (* nomem2reg *) reg signed [31:0] imag0 [0:FFT_N-1];
        (* nomem2reg *) reg signed [31:0] real1 [0:FFT_N-1];
        (* nomem2reg *) reg signed [31:0] imag1 [0:FFT_N-1];
        reg signed [31:0] ar0,ai0,br0,bi0;
        reg signed [31:0] ar1,ai1,ar2,ai2,ar3,ai3;
        reg signed [16:0] wr0,wi0;
        reg signed [48:0] rr1,ii1,ri1,ir1;
        reg signed [49:0] real2,imag2,real3,imag3;
        reg signed [50:0] plus_re4,plus_im4,minus_re4,minus_im4;
        reg [5:0] address_a [0:4];
        reg [5:0] address_b [0:4];
        reg signed [31:0] output_q_re,output_q_im,answer_re,answer_im;
        wire active=rst_n && enabled;
        wire launch=active && state==RUN && stage_cycle<BUTTERFLIES;
        wire [6:0] half_span=7'd1<<stage;
        wire [6:0] inner=stage_cycle & (half_span-1'b1);
        wire [6:0] group_base=(stage_cycle>>stage)<<(stage+1'b1);
        wire [5:0] launch_a=group_base[5:0]+inner[5:0];
        wire [5:0] launch_b=launch_a+half_span[5:0];
        wire [5:0] twiddle_index=inner[5:0]<<(5-stage);
        wire signed [16:0] twiddle_re=cos64(twiddle_index);
        wire signed [16:0] twiddle_im=cos64(twiddle_index+6'd16);
        wire [5:0] input_address=reversed(input_index);
        wire [5:0] output_address=(state==FETCH) ? 6'd0 :
            (state==PRIME) ? 6'd1 : output_index+6'd2;
        wire output_read=active && (state==FETCH || state==PRIME ||
            (state==OUTPUT_BINS && output_valid && m_ready && output_index<FFT_N-2));
        wire signed [31:0] saturated_plus_re=saturate32(plus_re4);
        wire signed [31:0] saturated_plus_im=saturate32(plus_im4);
        wire signed [31:0] saturated_minus_re=saturate32(minus_re4);
        wire signed [31:0] saturated_minus_im=saturate32(minus_im4);
        assign s_ready=active && state==LOAD;
        assign m_valid=active && output_valid;
        assign m_re=active ? answer_re : 32'sd0;
        assign m_im=active ? answer_im : 32'sd0;
        assign m_index=active ? output_index : 6'b0;
        assign m_last=m_valid && output_index==FFT_N-1;

        always @(posedge clk) begin
            if (s_valid && s_ready) begin
                real0[input_address]<={{16{s_data[15]}},s_data};
                imag0[input_address]<=0;
            end
            if (launch) begin
                if (!source_bank) begin
                    ar0<=real0[launch_a]; ai0<=imag0[launch_a];
                    br0<=real0[launch_b]; bi0<=imag0[launch_b];
                end else begin
                    ar0<=real1[launch_a]; ai0<=imag1[launch_a];
                    br0<=real1[launch_b]; bi0<=imag1[launch_b];
                end
            end
            if (active && state==RUN && butterfly_valid[4]) begin
                if (!source_bank) begin
                    real1[address_a[4]]<=saturated_plus_re;
                    imag1[address_a[4]]<=saturated_plus_im;
                    real1[address_b[4]]<=saturated_minus_re;
                    imag1[address_b[4]]<=saturated_minus_im;
                end else begin
                    real0[address_a[4]]<=saturated_plus_re;
                    imag0[address_a[4]]<=saturated_plus_im;
                    real0[address_b[4]]<=saturated_minus_re;
                    imag0[address_b[4]]<=saturated_minus_im;
                end
            end
            if (output_read) begin
                if (!source_bank) begin
                    output_q_re<=real0[output_address];
                    output_q_im<=imag0[output_address];
                end else begin
                    output_q_re<=real1[output_address];
                    output_q_im<=imag1[output_address];
                end
            end
        end

        integer i;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                enabled<=0; source_bank<=0; output_valid<=0; state<=LOAD;
                stage<=0; input_index<=0; output_index<=0; stage_cycle<=0;
                butterfly_valid<=0; wr0<=0; wi0<=0;
                ar1<=0; ai1<=0; ar2<=0; ai2<=0; ar3<=0; ai3<=0;
                rr1<=0; ii1<=0; ri1<=0; ir1<=0;
                real2<=0; imag2<=0; real3<=0; imag3<=0;
                plus_re4<=0; plus_im4<=0; minus_re4<=0; minus_im4<=0;
                answer_re<=0; answer_im<=0;
                for (i=0;i<5;i=i+1) begin address_a[i]<=0; address_b[i]<=0; end
            end else begin
                enabled<=1;
                butterfly_valid<={butterfly_valid[3:0],launch};
                if (launch) begin
                    wr0<=twiddle_re; wi0<=twiddle_im;
                    address_a[0]<=launch_a; address_b[0]<=launch_b;
                end
                for (i=1;i<5;i=i+1) begin
                    address_a[i]<=address_a[i-1]; address_b[i]<=address_b[i-1];
                end
                if (butterfly_valid[0]) begin
                    rr1<=br0*wr0; ii1<=bi0*wi0; ri1<=br0*wi0; ir1<=bi0*wr0;
                    ar1<=ar0; ai1<=ai0;
                end
                if (butterfly_valid[1]) begin
                    real2<=$signed({rr1[48],rr1})-$signed({ii1[48],ii1});
                    imag2<=$signed({ri1[48],ri1})+$signed({ir1[48],ir1});
                    ar2<=ar1; ai2<=ai1;
                end
                if (butterfly_valid[2]) begin
                    real3<=real2>>>15; imag3<=imag2>>>15; ar3<=ar2; ai3<=ai2;
                end
                if (butterfly_valid[3]) begin
                    plus_re4<=$signed({{19{ar3[31]}},ar3})+$signed({real3[49],real3});
                    plus_im4<=$signed({{19{ai3[31]}},ai3})+$signed({imag3[49],imag3});
                    minus_re4<=$signed({{19{ar3[31]}},ar3})-$signed({real3[49],real3});
                    minus_im4<=$signed({{19{ai3[31]}},ai3})-$signed({imag3[49],imag3});
                end
                case (state)
                    LOAD:if (s_valid && s_ready) begin
                        if (input_index==FFT_N-1) begin
                            input_index<=0; stage<=0; stage_cycle<=0;
                            source_bank<=0; state<=RUN;
                        end else input_index<=input_index+1'b1;
                    end
                    RUN:begin
                        if (stage_cycle==BUTTERFLIES+5) begin
                            source_bank<=!source_bank; stage_cycle<=0;
                            if (stage==L-1) begin output_index<=0; state<=FETCH; end
                            else stage<=stage+1'b1;
                        end else stage_cycle<=stage_cycle+1'b1;
                    end
                    FETCH:state<=PRIME;
                    PRIME:begin
                        answer_re<=output_q_re; answer_im<=output_q_im;
                        output_valid<=1; state<=OUTPUT_BINS;
                    end
                    OUTPUT_BINS:if (output_valid && m_ready) begin
                        if (output_index==FFT_N-1) begin
                            output_valid<=0; state<=LOAD; output_index<=0;
                        end else begin
                            answer_re<=output_q_re; answer_im<=output_q_im;
                            output_index<=output_index+1'b1;
                        end
                    end
                    default:begin state<=LOAD; output_valid<=0; end
                endcase
            end
        end
    end endgenerate
endmodule
