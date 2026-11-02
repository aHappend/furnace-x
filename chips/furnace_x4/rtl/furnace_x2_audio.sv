module furnace_x2_audio #(
    parameter integer FFT_N=16
) (
    input wire clk, rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire signed [15:0] s_data,
    input wire [15:0] s_id,
    input wire s_last,
    output wire m_valid,
    input wire m_ready,
    output wire [63:0] m_data,
    output wire [15:0] m_id,
    output wire [7:0] m_error
);
    generate if (FFT_N!=8 && FFT_N!=16 && FFT_N!=32 && FFT_N!=64) begin: bad_parameter
        initial $fatal(1,"PARAMETER ERROR: FFT_N must be 8,16,32,64");
        assign s_ready=0; assign m_valid=0; assign m_data=0;
        assign m_id=0; assign m_error=0;
    end else begin: frontend
        localparam integer L=$clog2(FFT_N);
        localparam [2:0] COLLECT=0, BINS=1, REDUCE=2, DRAIN=3, ERROR_TOKEN=4, OUTPUT_TOKEN=5;
        function automatic [32:0] abs32(input signed [31:0] value);
            reg signed [32:0] wide;
            begin
                wide={value[31],value};
                if (value[31]) abs32=-wide; else abs32=wide;
            end
        endfunction
        function automatic [15:0] spectral_lane(input [39:0] value);
            reg [39:0] mean;
            begin
                mean=value>>L;
                if (mean>32767) spectral_lane=16'd32767;
                else spectral_lane=mean[15:0];
            end
        endfunction
        reg enabled,output_valid;
        reg [2:0] state;
        reg [5:0] sample_index;
        reg [15:0] packet_id;
        reg [63:0] answer;
        reg [7:0] status;
        reg [31:0] fir_abs_sum;
        reg [39:0] dc_sum,low_sum,high_sum;
        wire engine_rst_n=rst_n && state!=DRAIN && state!=ERROR_TOKEN;
        wire fir_ready,fir_valid,fft_ready,fft_valid,fft_last;
        wire signed [15:0] fir_data;
        wire signed [31:0] fft_re,fft_im;
        wire [5:0] fft_index;
        wire take=s_valid && s_ready;
        wire active=rst_n && enabled;
        wire signed [16:0] fir_wide={fir_data[15],fir_data};
        wire [16:0] fir_abs=fir_data[15] ? -fir_wide : fir_wide;
        wire [32:0] fft_abs_re=abs32(fft_re),fft_abs_im=abs32(fft_im);
        wire [33:0] bin_energy={1'b0,fft_abs_re}+{1'b0,fft_abs_im};
        wire [31:0] fir_mean=fir_abs_sum>>L;
        assign s_ready=active && ((state==COLLECT && fir_ready) || state==DRAIN);
        assign m_valid=active && output_valid;
        assign m_data=active ? answer : 64'b0;
        assign m_id=active ? packet_id : 16'b0;
        assign m_error=active ? status : 8'b0;
        furnace_fir4_pipe fir_kernel (
            .clk(clk),.rst_n(engine_rst_n),
            .s_valid(active && state==COLLECT && s_valid),.s_ready(fir_ready),
            .s_data(s_data),.s_first(sample_index==0),
            .m_valid(fir_valid),.m_ready(fft_ready),.m_data(fir_data)
        );
        furnace_fft_radix2 #(.FFT_N(FFT_N)) fft_kernel (
            .clk(clk),.rst_n(engine_rst_n),.s_valid(fir_valid),.s_ready(fft_ready),
            .s_data(fir_data),.m_valid(fft_valid),.m_ready(state==BINS && active),
            .m_re(fft_re),.m_im(fft_im),.m_index(fft_index),.m_last(fft_last)
        );
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                enabled<=0; output_valid<=0; state<=COLLECT; sample_index<=0;
                packet_id<=0; answer<=0; status<=0; fir_abs_sum<=0;
                dc_sum<=0; low_sum<=0; high_sum<=0;
            end else begin
                enabled<=1;
                if (fir_valid && fft_ready) fir_abs_sum<=fir_abs_sum+{15'b0,fir_abs};
                if (fft_valid && state==BINS) begin
                    if (fft_index==0) dc_sum<={6'b0,bin_energy};
                    else if (fft_index<=FFT_N>>2) low_sum<=low_sum+{6'b0,bin_energy};
                    else if (fft_index<=FFT_N>>1) high_sum<=high_sum+{6'b0,bin_energy};
                    if (fft_last) state<=REDUCE;
                end
                case (state)
                    COLLECT:if (take) begin
                        if (sample_index==0) begin
                            packet_id<=s_id; status<=0; answer<=0;
                            fir_abs_sum<=0; dc_sum<=0; low_sum<=0; high_sum<=0;
                        end
                        if ((sample_index!=0 && s_id!=packet_id) ||
                            s_last!=(sample_index==FFT_N-1)) begin
                            status<=7; answer<=0;
                            if (s_last) state<=ERROR_TOKEN; else state<=DRAIN;
                        end else if (sample_index==FFT_N-1) state<=BINS;
                        else sample_index<=sample_index+1'b1;
                    end
                    BINS:begin end
                    REDUCE:begin
                        answer<={spectral_lane(high_sum),spectral_lane(low_sum),
                            spectral_lane(dc_sum),fir_mean[15:0]};
                        output_valid<=1; state<=OUTPUT_TOKEN;
                    end
                    DRAIN:if (take && s_last) state<=ERROR_TOKEN;
                    ERROR_TOKEN:begin
                        answer<=0; status<=7; output_valid<=1; state<=OUTPUT_TOKEN;
                    end
                    OUTPUT_TOKEN:if (output_valid && m_ready) begin
                        output_valid<=0; sample_index<=0; state<=COLLECT;
                    end
                    default:begin status<=7; answer<=0; state<=ERROR_TOKEN; end
                endcase
            end
        end
    end endgenerate
endmodule
