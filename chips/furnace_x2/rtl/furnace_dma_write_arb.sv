module furnace_dma_write_arb (
    input wire clk, rst_n,
    input wire [2:0] c_valid,
    output reg [2:0] c_ready,
    input wire [2:0][31:0] c_address,c_length,
    input wire [2:0][3:0] c_qos,
    input wire [2:0] c_data_valid,
    output reg [2:0] c_data_ready,
    input wire [2:0][7:0] c_data,
    input wire [2:0] c_last,
    output reg [2:0] c_done,
    input wire [2:0] c_done_ready,
    output reg [2:0][7:0] c_error,
    output wire d_valid,
    input wire d_ready,
    output wire [31:0] d_address,d_length,
    output wire [3:0] d_qos,
    output wire d_data_valid,
    input wire d_data_ready,
    output wire [7:0] d_data,
    output wire d_last,
    input wire d_done,
    output wire d_done_ready,
    input wire [7:0] d_error
);
    localparam [1:0] PICK=0,HEADER=1,TRANSFER=2;
    reg enabled;
    reg [1:0] state,owner,cursor;
    reg [31:0] address,length;
    reg [3:0] qos;
    reg pick_valid;
    reg [1:0] pick;
    integer k,candidate;
    wire active=rst_n && enabled;
    always @* begin
        pick_valid=0; pick=0; candidate=0;
        c_ready=0; c_data_ready=0; c_done=0; c_error=0;
        for (k=0;k<3;k=k+1) begin
            candidate=cursor+k;
            if (candidate>=3) candidate=candidate-3;
            if (!pick_valid && c_valid[candidate]) begin
                pick_valid=1; pick=candidate[1:0];
            end
        end
        if (active && state==HEADER) c_ready[owner]=d_ready;
        if (active && state==TRANSFER) begin
            c_data_ready[owner]=d_data_ready;
            c_done[owner]=d_done; c_error[owner]=d_error;
        end
    end
    assign d_valid=active && state==HEADER;
    assign d_address=active ? address : 32'b0;
    assign d_length=active ? length : 32'b0;
    assign d_qos=active ? qos : 4'b0;
    assign d_data_valid=active && state==TRANSFER && c_data_valid[owner];
    assign d_data=(active && state==TRANSFER) ? c_data[owner] : 8'b0;
    assign d_last=active && state==TRANSFER && c_last[owner];
    assign d_done_ready=active && state==TRANSFER && c_done_ready[owner];
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enabled<=0; state<=PICK; owner<=0; cursor<=0;
            address<=0; length<=0; qos<=0;
        end else begin
            enabled<=1;
            case (state)
                PICK:if (enabled && pick_valid) begin
                    owner<=pick; address<=c_address[pick]; length<=c_length[pick];
                    qos<=c_qos[pick]; state<=HEADER;
                end
                HEADER:if (d_valid && d_ready) begin
                    if (owner==2) cursor<=0; else cursor<=owner+1'b1;
                    state<=TRANSFER;
                end
                TRANSFER:if (d_done && d_done_ready) state<=PICK;
                default:state<=PICK;
            endcase
        end
    end
endmodule
