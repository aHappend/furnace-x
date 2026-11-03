module furnace_x3_local_memory (
    input wire clk, rst_n,
    input wire cpu_running,
    input wire req_valid,
    output wire req_ready,
    input wire req_host, req_write, req_instr,
    input wire [63:0] req_addr, req_wdata,
    input wire [7:0] req_wstrb,
    input wire [1:0] req_size,
    output wire rsp_valid,
    input wire rsp_ready,
    output wire [63:0] rsp_rdata,
    output wire rsp_error
);
    reg enabled, pending, response_valid, response_error;
    reg host_q, write_q, instruction_q, running_q;
    reg [63:0] address_q, data_q;
    reg [7:0] strobe_q;
    reg [1:0] size_q;
    reg [63:0] memory_read;
    (* ramstyle = "M20K", nomem2reg *) reg [63:0] imem [0:2047];
    (* ramstyle = "M20K", nomem2reg *) reg [63:0] dmem [0:2047];
    wire active=rst_n && enabled;
    wire imem_selected=host_q ?
        address_q>=64'h4000 && address_q<64'h8000 :
        address_q>=64'h10000 && address_q<64'h14000;
    wire dmem_selected=host_q ?
        address_q>=64'h8000 && address_q<64'hc000 :
        address_q>=64'h20000 && address_q<64'h24000;
    wire [2:0] alignment_mask=3'b111 >> (3-size_q);
    wire [7:0] legal_strobes=8'hff >> (8-(1<<size_q));
    wire invalid_access=(!imem_selected && !dmem_selected) ||
        (address_q[2:0] & alignment_mask)!=0 ||
        (host_q && (size_q!=2 || instruction_q)) ||
        (instruction_q && (!imem_selected || write_q || size_q!=2)) ||
        (write_q && ((!host_q && imem_selected) ||
            (host_q && running_q) || (strobe_q & ~legal_strobes)!=0));
    wire [10:0] word_address=address_q[13:3];
    wire [63:0] shifted_write=data_q << {address_q[2:0],3'b0};
    wire [7:0] shifted_strobes=strobe_q << address_q[2:0];
    wire [63:0] shifted_read=memory_read >> {address_q[2:0],3'b0};
    wire [63:0] read_mask=64'hffffffffffffffff >> (64-(8<<size_q));
    assign req_ready=active && !pending && !response_valid;
    assign rsp_valid=active && response_valid;
    assign rsp_error=rsp_valid && response_error;
    assign rsp_rdata=rsp_valid && !response_error && !write_q ?
        shifted_read & read_mask : 64'b0;

    integer lane;
    always @(posedge clk) begin
        if (active && pending && !invalid_access) begin
            if (imem_selected) begin
                memory_read<=imem[word_address];
                for (lane=0;lane<8;lane=lane+1)
                    if (write_q && shifted_strobes[lane])
                        imem[word_address][8*lane+:8]<=shifted_write[8*lane+:8];
            end else begin
                memory_read<=dmem[word_address];
                for (lane=0;lane<8;lane=lane+1)
                    if (write_q && shifted_strobes[lane])
                        dmem[word_address][8*lane+:8]<=shifted_write[8*lane+:8];
            end
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enabled<=0; pending<=0; response_valid<=0; response_error<=0;
            host_q<=0; write_q<=0; instruction_q<=0; running_q<=0;
            address_q<=0; data_q<=0; strobe_q<=0; size_q<=0;
        end else begin
            enabled<=1;
            if (req_valid && req_ready) begin
                pending<=1; host_q<=req_host; write_q<=req_write;
                instruction_q<=req_instr; running_q<=cpu_running;
                address_q<=req_addr; data_q<=req_wdata;
                strobe_q<=req_wstrb; size_q<=req_size;
            end
            if (pending) begin
                pending<=0; response_valid<=1; response_error<=invalid_access;
            end
            if (rsp_valid && rsp_ready) response_valid<=0;
        end
    end
endmodule
