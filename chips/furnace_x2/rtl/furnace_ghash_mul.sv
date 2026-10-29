module furnace_ghash_mul (
    input wire clk, rst_n, cancel,
    input wire start_valid,
    output wire start_ready,
    input wire [127:0] x,h,
    output wire done_valid,
    input wire done_ready,
    output wire [127:0] product
);
    reg enabled, busy, valid;
    reg [6:0] step;
    reg [127:0] bits_left, v,z,answer;
    wire [127:0] next_z=z^(v & {128{bits_left[127]}});
    assign start_ready=rst_n && enabled && !busy && !valid;
    assign done_valid=rst_n && enabled && valid;
    assign product=(rst_n && enabled) ? answer : 128'b0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enabled<=0; busy<=0; valid<=0; step<=0;
            bits_left<=0; v<=0; z<=0; answer<=0;
        end else begin
            enabled<=1;
            if (cancel) begin busy<=0; valid<=0; answer<=0; end
            else if (start_valid && start_ready) begin
                bits_left<=x; v<=h; z<=0; step<=0; busy<=1;
            end else if (busy) begin
                z<=next_z; bits_left<={bits_left[126:0],1'b0};
                v<={1'b0,v[127:1]}^(128'he1000000000000000000000000000000 &
                    {128{v[0]}});
                if (step==127) begin answer<=next_z; busy<=0; valid<=1; end
                else step<=step+1'b1;
            end else if (valid && done_ready) valid<=0;
        end
    end
endmodule
