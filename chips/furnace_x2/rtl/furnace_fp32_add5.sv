module furnace_fp32_add5 #(
    parameter integer OUTPUT_REGISTER=1
) (
    input wire clk, rst_n, ce,
    input wire [31:0] a,b,
    output wire [31:0] result
);
    function automatic [4:0] leading_position(input [27:0] x);
        reg [3:0] nibble;
        reg [4:0] base;
        reg [1:0] local_position;
        begin
            if (|x[27:24]) begin nibble=x[27:24]; base=24; end
            else if (|x[23:20]) begin nibble=x[23:20]; base=20; end
            else if (|x[19:16]) begin nibble=x[19:16]; base=16; end
            else if (|x[15:12]) begin nibble=x[15:12]; base=12; end
            else if (|x[11:8]) begin nibble=x[11:8]; base=8; end
            else if (|x[7:4]) begin nibble=x[7:4]; base=4; end
            else begin nibble=x[3:0]; base=0; end
            casez (nibble)
                4'b1???:local_position=3;
                4'b01??:local_position=2;
                4'b001?:local_position=1;
                default:local_position=0;
            endcase
            leading_position=base+{3'b0,local_position};
        end
    endfunction
    wire choose_a=a[30:0]>=b[30:0];
    wire [31:0] big=choose_a ? a : b;
    wire [31:0] smaller=choose_a ? b : a;
    wire [7:0] big_e=(big[30:23]==0) ? 8'd1 : big[30:23];
    wire [7:0] small_e=(smaller[30:23]==0) ? 8'd1 : smaller[30:23];
    wire a_nan=a[30:23]==255 && a[22:0]!=0;
    wire b_nan=b[30:23]==255 && b[22:0]!=0;
    wire a_inf=a[30:23]==255 && a[22:0]==0;
    wire b_inf=b[30:23]==255 && b[22:0]==0;
    wire invalid=a_nan || b_nan || (a_inf && b_inf && a[31]!=b[31]);
    wire input_special=invalid || a_inf || b_inf;
    wire [31:0] special_input=invalid ? 32'h7fc00000 :
        a_inf ? {a[31],8'hff,23'b0} : {b[31],8'hff,23'b0};
    reg [26:0] big1,small1,big2,small2;
    reg [7:0] delta1;
    reg signed [11:0] exponent1,exponent2,exponent3,exponent4;
    reg sign1,sign2,sign3,sign4,subtract1,subtract2;
    reg special1,special2,special3,special4;
    reg [31:0] value1,value2,value3,value4;
    reg [27:0] sum3;
    reg [26:0] significand4;
    reg [26:0] aligned;
    wire [27:0] arithmetic_result=subtract2 ?
        {1'b0,big2}-{1'b0,small2} : {1'b0,big2}+{1'b0,small2};
    wire [4:0] position3=leading_position(sum3);
    reg [4:0] left_shift;
    reg [27:0] normalized;
    reg [26:0] next_significand;
    reg signed [11:0] next_exponent;
    wire [31:0] rounded;
    always @* begin
        if (delta1>=27) aligned={26'b0,(|small1)};
        else begin
            aligned=small1 >> delta1;
            aligned[0]=aligned[0] |
                (|(small1 & ~(27'h7ffffff << delta1)));
        end
    end
    always @* begin
        left_shift=0; normalized=0; next_significand=0; next_exponent=0;
        if (sum3[27]) begin
            next_significand=sum3[27:1];
            next_significand[0]=sum3[1] | sum3[0];
            next_exponent=exponent3+12'sd1;
        end else if (sum3!=0) begin
            left_shift=5'd26-position3;
            if ($signed({7'b0,left_shift})>exponent3-12'sd1)
                left_shift=exponent3[4:0]-1'b1;
            normalized=sum3 << left_shift;
            next_significand=normalized[26:0];
            if (normalized[26]) next_exponent=exponent3-$signed({7'b0,left_shift});
            else next_exponent=0;
        end
    end
    furnace_fp32_round rounder (
        .sign(sign4),.significand(significand4),.exponent(exponent4),
        .special(special4),.special_value(value4),.result(rounded)
    );
    generate if (OUTPUT_REGISTER==1) begin: registered_output
        reg [31:0] answer;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) answer<=0;
            else if (ce) answer<=rounded;
        end
        assign result=rst_n ? answer : 32'b0;
    end else if (OUTPUT_REGISTER==0) begin: enclosing_output_register
        assign result=rst_n ? rounded : 32'b0;
    end else begin: bad_parameter
        initial $fatal(1,"PARAMETER ERROR: OUTPUT_REGISTER must be 0 or 1");
        assign result=0;
    end endgenerate
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            big1<=0; small1<=0; big2<=0; small2<=0; delta1<=0;
            exponent1<=0; exponent2<=0; exponent3<=0; exponent4<=0;
            sign1<=0; sign2<=0; sign3<=0; sign4<=0;
            subtract1<=0; subtract2<=0;
            special1<=0; special2<=0; special3<=0; special4<=0;
            value1<=0; value2<=0; value3<=0; value4<=0;
            sum3<=0; significand4<=0;
        end else if (ce) begin
            big1<={big[30:23]!=0,big[22:0],3'b0};
            small1<={smaller[30:23]!=0,smaller[22:0],3'b0};
            delta1<=big_e-small_e; exponent1<=$signed({4'b0,big_e});
            sign1<=big[31]; subtract1<=big[31]^smaller[31];
            special1<=input_special; value1<=special_input;
            big2<=big1; small2<=aligned; exponent2<=exponent1;
            sign2<=sign1; subtract2<=subtract1; special2<=special1; value2<=value1;
            sum3<=arithmetic_result; exponent3<=exponent2;
            if (subtract2 && arithmetic_result==0) sign3<=0; else sign3<=sign2;
            special3<=special2; value3<=value2;
            significand4<=next_significand; exponent4<=next_exponent;
            sign4<=sign3; special4<=special3; value4<=value3;
        end
    end
endmodule
