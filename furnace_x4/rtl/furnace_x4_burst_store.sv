module furnace_x4_burst_store #(
    parameter integer META_WIDTH=65
) (
    input wire clk,
    input wire write_en,
    input wire [7:0] write_addr,
    input wire [511:0] write_data,
    input wire [META_WIDTH-1:0] write_meta,
    input wire read_en,
    input wire [7:0] read_addr,
    output wire [511:0] read_data,
    output reg [META_WIDTH-1:0] read_meta
);
    genvar lane;
    generate for (lane=0; lane<64; lane=lane+1) begin : g_byte
        (* ramstyle = "M20K", nomem2reg *) reg [7:0] bytes [0:255];
        reg [7:0] data_q;
        always @(posedge clk) begin
            if (write_en) bytes[write_addr] <= write_data[lane*8 +: 8];
            if (read_en) data_q <= bytes[read_addr];
        end
        assign read_data[lane*8 +: 8] = data_q;
    end endgenerate
    (* ramstyle = "M20K", nomem2reg *) reg [META_WIDTH-1:0] metadata [0:255];
    always @(posedge clk) begin
        if (write_en) metadata[write_addr] <= write_meta;
        if (read_en) read_meta <= metadata[read_addr];
    end
endmodule
