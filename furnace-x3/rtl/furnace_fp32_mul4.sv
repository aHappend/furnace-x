module furnace_fp32_mul4 (
    input wire clk, rst_n, ce,
    input wire [31:0] a,b,
    output wire [31:0] result
);
    function automatic [5:0] leading_position(input [47:0] x);
        reg [7:0] octet;
        reg [5:0] base;
        reg [2:0] local_position;
        begin
            if (|x[47:40]) begin octet=x[47:40]; base=40; end
            else if (|x[39:32]) begin octet=x[39:32]; base=32; end
            else if (|x[31:24]) begin octet=x[31:24]; base=24; end
            else if (|x[23:16]) begin octet=x[23:16]; base=16; end
            else if (|x[15:8]) begin octet=x[15:8]; base=8; end
            else begin octet=x[7:0]; base=0; end
            casez (octet)
                8'b1???????:local_position=7;
                8'b01??????:local_position=6;
                8'b001?????:local_position=5;
                8'b0001????:local_position=4;
                8'b00001???:local_position=3;
                8'b000001??:local_position=2;
                8'b0000001?:local_position=1;
                default:local_position=0;
            endcase
            leading_position=base+{3'b0,local_position};
        end
    endfunction
    wire [7:0] ea=(a[30:23]==0) ? 8'd1 : a[30:23];
    wire [7:0] eb=(b[30:23]==0) ? 8'd1 : b[30:23];
    wire [23:0] ma={a[30:23]!=0,a[22:0]};
    wire [23:0] mb={b[30:23]!=0,b[22:0]};
    wire a_nan=a[30:23]==255 && a[22:0]!=0;
    wire b_nan=b[30:23]==255 && b[22:0]!=0;
    wire a_inf=a[30:23]==255 && a[22:0]==0;
    wire b_inf=b[30:23]==255 && b[22:0]==0;
    wire a_zero=a[30:0]==0;
    wire b_zero=b[30:0]==0;
    wire invalid=a_nan || b_nan || (a_inf && b_zero) || (b_inf && a_zero);
    wire input_special=invalid || a_inf || b_inf || a_zero || b_zero;
    wire [31:0] special_input=invalid ? 32'h7fc00000 :
        (a_inf || b_inf) ? {a[31]^b[31],8'hff,23'b0} :
        {a[31]^b[31],31'b0};
    wire [47:0] raw_product=ma*mb;
    wire signed [11:0] exponent_base=
        $signed({4'b0,ea})+$signed({4'b0,eb})-12'sd127;
    reg [47:0] product1,product2;
    reg signed [11:0] exponent1,exponent2,exponent3;
    reg [5:0] position2;
    reg sign1,sign2,sign3,special1,special2,special3;
    reg [31:0] value1,value2,value3,answer;
    reg [26:0] significand3;
    wire [5:0] position1=leading_position(product1);
    wire signed [11:0] normalized_exponent=
        exponent1+$signed({6'b0,position1})-12'sd46;
    wire signed [11:0] underflow_shift=(exponent2<1) ?
        12'sd1-exponent2 : 12'sd0;
    wire signed [11:0] shift_count=
        $signed({6'b0,position2})-12'sd26+underflow_shift;
    reg [47:0] shifted;
    reg [26:0] normalized_significand;
    reg sticky;
    wire [31:0] rounded;
    always @* begin
        shifted=0; sticky=0;
        if (shift_count>=48) begin
            shifted=0; sticky=|product2;
        end else if (shift_count>0) begin
            shifted=product2 >> shift_count;
            sticky=|(product2 & ~(48'hffffffffffff << shift_count));
        end else shifted=product2 << (-shift_count);
        normalized_significand=shifted[26:0];
        normalized_significand[0]=shifted[0] | sticky;
    end
    furnace_fp32_round rounder (
        .sign(sign3),.significand(significand3),.exponent(exponent3),
        .special(special3),.special_value(value3),.result(rounded)
    );
    assign result=rst_n ? answer : 32'b0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            product1<=0; product2<=0; exponent1<=0; exponent2<=0;
            exponent3<=0; position2<=0; sign1<=0; sign2<=0; sign3<=0;
            special1<=0; special2<=0; special3<=0;
            value1<=0; value2<=0; value3<=0; significand3<=0; answer<=0;
        end else if (ce) begin
            product1<=raw_product; exponent1<=exponent_base;
            sign1<=a[31]^b[31]; special1<=input_special; value1<=special_input;
            product2<=product1; exponent2<=normalized_exponent; position2<=position1;
            sign2<=sign1; special2<=special1; value2<=value1;
            significand3<=normalized_significand; exponent3<=exponent2;
            sign3<=sign2; special3<=special2; value3<=value2;
            answer<=rounded;
        end
    end
endmodule
