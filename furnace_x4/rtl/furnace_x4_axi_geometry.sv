module furnace_x4_axi_geometry (
    input wire [31:0] addr,
    input wire [7:0] len,
    input wire [2:0] size,
    input wire [1:0] burst,
    input wire lock,
    output wire [1:0] status
);
    wire [32:0] beat_bytes = 33'd1 << size;
    wire [32:0] burst_bytes = ({25'b0,len} + 33'd1) << size;
    wire [32:0] wrap_mask = burst_bytes - 33'd1;
    wire wrap_length_legal = len == 1 || len == 3 || len == 7 || len == 15;
    wire [32:0] first_byte = burst == 2 ? ({1'b0,addr} & ~wrap_mask) : {1'b0,addr};
    wire [32:0] last_byte = first_byte +
        (burst == 0 ? beat_bytes : burst_bytes) - 33'd1;
    wire geometry_bad = size > 6 || lock || burst == 3 ||
        (burst == 0 && len > 15) || (burst == 2 && !wrap_length_legal) ||
        (({1'b0,addr} & (beat_bytes - 33'd1)) != 0);
    wire address_bad = first_byte < 33'h080000000 || last_byte > 33'h087ffffff;
    assign status = address_bad ? 2'b11 : geometry_bad ? 2'b10 : 2'b00;
endmodule
