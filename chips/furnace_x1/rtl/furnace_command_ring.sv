module furnace_command_ring #(
    parameter integer RING_DEPTH=8
) (
    input wire clk, rst_n,
    input wire tail_valid,
    output wire tail_ready,
    input wire [31:0] tail_value,
    output wire tail_error,
    input wire retire,
    output wire [31:0] head,tail,
    output wire [3:0] head_slot,
    output wire queued,full
);
    generate if (RING_DEPTH<1 || RING_DEPTH>16) begin: bad_parameter
        initial $fatal(1,"PARAMETER ERROR: RING_DEPTH must be 1..16");
        assign tail_ready=0; assign tail_error=0; assign head=0; assign tail=0;
        assign head_slot=0; assign queued=0; assign full=0;
    end else begin: ring
        reg enabled;
        reg [31:0] consumer,producer;
        reg [3:0] slot;
        wire [31:0] occupancy=producer-consumer;
        wire [31:0] advance=tail_value-producer;
        wire [31:0] free_slots=RING_DEPTH-occupancy;
        assign tail_ready=rst_n && enabled;
        assign tail_error=rst_n && enabled && (advance[31] || advance>free_slots);
        assign head=(rst_n && enabled) ? consumer : 32'b0;
        assign tail=(rst_n && enabled) ? producer : 32'b0;
        assign head_slot=(rst_n && enabled) ? slot : 4'b0;
        assign queued=rst_n && enabled && consumer!=producer;
        assign full=rst_n && enabled && occupancy==RING_DEPTH;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin enabled<=0; consumer<=0; producer<=0; slot<=0; end
            else begin
                enabled<=1;
                if (tail_valid && tail_ready && !tail_error) producer<=tail_value;
                if (retire && queued) begin
                    consumer<=consumer+1'b1;
                    if (slot==RING_DEPTH-1) slot<=0; else slot<=slot+1'b1;
                end
            end
        end
    end endgenerate
endmodule
