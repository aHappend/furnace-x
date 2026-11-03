module furnace_tensor8 (
    input wire clk, rst_n,
    input wire vector_valid,
    output wire vector_ready,
    input wire [1:0] mode,
    input wire first,last,
    input wire [127:0] weight_data,activation_data,
    output wire result_valid,
    input wire result_ready,
    output wire [63:0] result,
    output wire [7:0] error
);
    function automatic [31:0] w4_float(input [3:0] w);
        begin
            case (w)
                0:w4_float=32'h00000000; 1:w4_float=32'h3f800000;
                2:w4_float=32'h40000000; 3:w4_float=32'h40400000;
                4:w4_float=32'h40800000; 5:w4_float=32'h40a00000;
                6:w4_float=32'h40c00000; 7:w4_float=32'h40e00000;
                8:w4_float=32'hc1000000; 9:w4_float=32'hc0e00000;
                10:w4_float=32'hc0c00000; 11:w4_float=32'hc0a00000;
                12:w4_float=32'hc0800000; 13:w4_float=32'hc0400000;
                14:w4_float=32'hc0000000; default:w4_float=32'hbf800000;
            endcase
        end
    endfunction
    reg enabled,busy,tile_active,output_valid;
    reg [4:0] age;
    reg [1:0] mode_latched,tile_mode;
    reg first_latched,last_latched,protocol_error;
    reg [127:0] weights,activations;
    reg [63:0] integer_accumulator,answer;
    reg [31:0] float_accumulator;
    reg [7:0] status;
    wire [31:0] products [0:7];
    wire [31:0] pairs [0:3];
    wire [31:0] quads [0:1];
    wire [31:0] vector_sum,accumulated;
    wire signed [19:0] integer_product [0:7];
    reg signed [19:0] ip1 [0:7];
    reg signed [20:0] ip2 [0:3];
    reg signed [21:0] ip3 [0:1];
    reg signed [22:0] integer_sum [4:19];
    reg [63:0] integer_delay [20:23];
    wire [63:0] integer_next=(first_latched ? 64'b0 : integer_accumulator)+
        {{41{integer_sum[19][22]}},integer_sum[19]};
    genvar i;
    generate for (i=0;i<8;i=i+1) begin: lanes
        wire [31:0] wa=(mode_latched==1) ?
            {weights[16*i+:16],16'b0} : w4_float(weights[4*i+:4]);
        wire [31:0] aa={activations[16*i+:16],16'b0};
        assign integer_product[i]=$signed(weights[4*i+:4])*
            $signed(activations[16*i+:16]);
        furnace_fp32_mul4 multiply (
            .clk(clk),.rst_n(rst_n),.ce(busy),.a(wa),.b(aa),.result(products[i])
        );
    end
    for (i=0;i<4;i=i+1) begin: first_level
        furnace_fp32_add5 add (
            .clk(clk),.rst_n(rst_n),.ce(busy),
            .a(products[2*i]),.b(products[2*i+1]),.result(pairs[i])
        );
    end
    for (i=0;i<2;i=i+1) begin: second_level
        furnace_fp32_add5 add (
            .clk(clk),.rst_n(rst_n),.ce(busy),
            .a(pairs[2*i]),.b(pairs[2*i+1]),.result(quads[i])
        );
    end endgenerate
    furnace_fp32_add5 final_level (
        .clk(clk),.rst_n(rst_n),.ce(busy),.a(quads[0]),.b(quads[1]),.result(vector_sum)
    );
    furnace_fp32_add5 #(.OUTPUT_REGISTER(0)) accumulator (
        .clk(clk),.rst_n(rst_n),.ce(busy),
        .a(first_latched ? 32'b0 : float_accumulator),
        .b(vector_sum),.result(accumulated)
    );
    assign vector_ready=rst_n && enabled && !busy && !output_valid;
    assign result_valid=rst_n && enabled && output_valid;
    assign result=(rst_n && enabled) ? answer : 64'b0;
    assign error=(rst_n && enabled) ? status : 8'b0;
    integer n;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enabled<=0; busy<=0; tile_active<=0; output_valid<=0; age<=0;
            mode_latched<=0; tile_mode<=0; first_latched<=0; last_latched<=0;
            protocol_error<=0; weights<=0; activations<=0;
            integer_accumulator<=0; float_accumulator<=0; answer<=0; status<=0;
            for (n=0;n<8;n=n+1) ip1[n]<=0;
            for (n=0;n<4;n=n+1) ip2[n]<=0;
            for (n=0;n<2;n=n+1) ip3[n]<=0;
            for (n=4;n<20;n=n+1) integer_sum[n]<=0;
            for (n=20;n<24;n=n+1) integer_delay[n]<=0;
        end else begin
            enabled<=1;
            if (output_valid && result_ready) output_valid<=0;
            if (vector_valid && vector_ready) begin
                weights<=weight_data; activations<=activation_data;
                mode_latched<=mode; first_latched<=first; last_latched<=last;
                busy<=1; age<=0; status<=0;
                protocol_error<=mode==3 || (first==tile_active) ||
                    (tile_active && mode!=tile_mode) ||
                    ((mode==0 || mode==2) && weight_data[127:32]!=0);
                if (first) begin
                    tile_mode<=mode; tile_active<=1;
                    integer_accumulator<=0; float_accumulator<=0;
                end
            end else if (busy) begin
                for (n=0;n<8;n=n+1) ip1[n]<=integer_product[n];
                for (n=0;n<4;n=n+1)
                    ip2[n]<=$signed({ip1[2*n][19],ip1[2*n]})+
                        $signed({ip1[2*n+1][19],ip1[2*n+1]});
                for (n=0;n<2;n=n+1)
                    ip3[n]<=$signed({ip2[2*n][20],ip2[2*n]})+
                        $signed({ip2[2*n+1][20],ip2[2*n+1]});
                integer_sum[4]<=$signed({ip3[0][21],ip3[0]})+
                    $signed({ip3[1][21],ip3[1]});
                for (n=5;n<20;n=n+1) integer_sum[n]<=integer_sum[n-1];
                integer_delay[20]<=integer_next;
                for (n=21;n<24;n=n+1) integer_delay[n]<=integer_delay[n-1];
                if (age==23) begin
                    busy<=0;
                    if (protocol_error) begin
                        status<=6; answer<=0; output_valid<=1; tile_active<=0;
                        integer_accumulator<=0; float_accumulator<=0;
                    end else begin
                        integer_accumulator<=integer_delay[23];
                        float_accumulator<=accumulated;
                        if (last_latched) begin
                            tile_active<=0; output_valid<=1;
                            if (mode_latched==0) answer<=integer_delay[23];
                            else answer<={32'b0,accumulated};
                        end
                    end
                end else age<=age+1'b1;
            end
        end
    end
endmodule
