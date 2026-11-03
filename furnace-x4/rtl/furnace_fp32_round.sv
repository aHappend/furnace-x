module furnace_fp32_round (
    input wire sign,
    input wire [26:0] significand,
    input wire signed [11:0] exponent,
    input wire special,
    input wire [31:0] special_value,
    output reg [31:0] result
);
    reg [24:0] rounded;
    reg signed [11:0] incremented_exponent;
    always @* begin
        rounded={1'b0,significand[26:3]}+
            {24'b0,(significand[2] &&
            (significand[1] || significand[0] || significand[3]))};
        incremented_exponent=exponent+12'sd1;
        if (special) result=special_value;
        else if (exponent>=255) result={sign,8'hff,23'b0};
        else if (exponent<=0) begin
            if (rounded[23]) result={sign,8'd1,rounded[22:0]};
            else result={sign,8'b0,rounded[22:0]};
        end else if (rounded[24]) begin
            if (incremented_exponent>=255) result={sign,8'hff,23'b0};
            else result={sign,incremented_exponent[7:0],rounded[23:1]};
        end else result={sign,exponent[7:0],rounded[22:0]};
    end
endmodule
