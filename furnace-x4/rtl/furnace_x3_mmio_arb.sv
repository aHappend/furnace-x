module furnace_x3_mmio_arb (
    input wire clk, rst_n,
    input wire [15:0] s_axil_awaddr,
    input wire [2:0] s_axil_awprot,
    input wire s_axil_awvalid,
    output wire s_axil_awready,
    input wire [31:0] s_axil_wdata,
    input wire [3:0] s_axil_wstrb,
    input wire s_axil_wvalid,
    output wire s_axil_wready,
    output wire [1:0] s_axil_bresp,
    output wire s_axil_bvalid,
    input wire s_axil_bready,
    input wire [15:0] s_axil_araddr,
    input wire [2:0] s_axil_arprot,
    input wire s_axil_arvalid,
    output wire s_axil_arready,
    output wire [31:0] s_axil_rdata,
    output wire [1:0] s_axil_rresp,
    output wire s_axil_rvalid,
    input wire s_axil_rready,
    input wire cpu_req_valid,
    output wire cpu_req_ready,
    input wire cpu_req_write, cpu_req_instr,
    input wire [63:0] cpu_req_addr, cpu_req_wdata,
    input wire [7:0] cpu_req_wstrb,
    input wire [1:0] cpu_req_size,
    output wire cpu_rsp_valid,
    input wire cpu_rsp_ready,
    output wire [63:0] cpu_rsp_rdata,
    output wire cpu_rsp_error,
    output wire dev_req_valid,
    input wire dev_req_ready,
    output wire dev_req_host, dev_req_write, dev_req_instr,
    output wire [63:0] dev_req_addr, dev_req_wdata,
    output wire [7:0] dev_req_wstrb,
    output wire [1:0] dev_req_size,
    input wire dev_rsp_valid,
    output wire dev_rsp_ready,
    input wire [63:0] dev_rsp_rdata,
    input wire dev_rsp_error
);
    localparam [1:0] IDLE=0, REQUEST=1, WAIT_RESPONSE=2, RESPONSE=3;
    reg enabled, aw_held, w_held, ar_held, prefer_host, prefer_write;
    reg [15:0] aw_address, ar_address;
    reg [31:0] w_data;
    reg [3:0] w_strobe;
    reg [1:0] state;
    reg host_q, write_q, instruction_q, response_error;
    reg [63:0] address_q, data_q, response_data;
    reg [7:0] strobe_q;
    reg [1:0] size_q;
    wire active=rst_n && enabled;
    wire host_write_available=aw_held && w_held;
    wire host_available=host_write_available || ar_held;
    wire select_host=host_available && (prefer_host || !cpu_req_valid);
    wire select_write=host_write_available && (prefer_write || !ar_held);
    assign s_axil_awready=active && !aw_held;
    assign s_axil_wready=active && !w_held;
    assign s_axil_arready=active && !ar_held;
    assign cpu_req_ready=active && state==IDLE && !select_host;
    assign dev_req_valid=active && state==REQUEST;
    assign dev_req_host=dev_req_valid && host_q;
    assign dev_req_write=dev_req_valid && write_q;
    assign dev_req_instr=dev_req_valid && instruction_q;
    assign dev_req_addr=dev_req_valid ? address_q : 64'b0;
    assign dev_req_wdata=dev_req_valid ? data_q : 64'b0;
    assign dev_req_wstrb=dev_req_valid ? strobe_q : 8'b0;
    assign dev_req_size=dev_req_valid ? size_q : 2'b0;
    assign dev_rsp_ready=active && state==WAIT_RESPONSE;
    assign s_axil_bvalid=active && state==RESPONSE && host_q && write_q;
    assign s_axil_bresp=s_axil_bvalid && response_error ? 2'b10 : 2'b0;
    assign s_axil_rvalid=active && state==RESPONSE && host_q && !write_q;
    assign s_axil_rdata=s_axil_rvalid ? response_data[31:0] : 32'b0;
    assign s_axil_rresp=s_axil_rvalid && response_error ? 2'b10 : 2'b0;
    assign cpu_rsp_valid=active && state==RESPONSE && !host_q;
    assign cpu_rsp_rdata=cpu_rsp_valid ? response_data : 64'b0;
    assign cpu_rsp_error=cpu_rsp_valid && response_error;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enabled<=0; aw_held<=0; w_held<=0; ar_held<=0;
            prefer_host<=1; prefer_write<=1; aw_address<=0; ar_address<=0;
            w_data<=0; w_strobe<=0; state<=IDLE;
            host_q<=0; write_q<=0; instruction_q<=0; response_error<=0;
            address_q<=0; data_q<=0; response_data<=0; strobe_q<=0; size_q<=0;
        end else begin
            enabled<=1;
            if (s_axil_awvalid && s_axil_awready) begin
                aw_held<=1; aw_address<=s_axil_awaddr;
            end
            if (s_axil_wvalid && s_axil_wready) begin
                w_held<=1; w_data<=s_axil_wdata; w_strobe<=s_axil_wstrb;
            end
            if (s_axil_arvalid && s_axil_arready) begin
                ar_held<=1; ar_address<=s_axil_araddr;
            end
            case (state)
                IDLE: if (active && (host_available || cpu_req_valid)) begin
                    host_q<=select_host;
                    if (select_host) begin
                        instruction_q<=0; size_q<=2;
                        write_q<=select_write;
                        if (select_write) begin
                            address_q<={48'b0,aw_address};
                            data_q<={32'b0,w_data}; strobe_q<={4'b0,w_strobe};
                            aw_held<=0; w_held<=0;
                        end else begin
                            address_q<={48'b0,ar_address};
                            data_q<=0; strobe_q<=0; ar_held<=0;
                        end
                    end else begin
                        write_q<=cpu_req_write; instruction_q<=cpu_req_instr;
                        size_q<=cpu_req_size; address_q<=cpu_req_addr;
                        data_q<=cpu_req_wdata; strobe_q<=cpu_req_wstrb;
                    end
                    state<=REQUEST;
                end
                REQUEST: if (dev_req_valid && dev_req_ready) state<=WAIT_RESPONSE;
                WAIT_RESPONSE: if (dev_rsp_valid && dev_rsp_ready) begin
                    response_error<=dev_rsp_error;
                    response_data<=dev_rsp_error ? 64'b0 : dev_rsp_rdata;
                    state<=RESPONSE;
                end
                RESPONSE: if ((cpu_rsp_valid && cpu_rsp_ready) ||
                    (s_axil_bvalid && s_axil_bready) ||
                    (s_axil_rvalid && s_axil_rready)) begin
                    prefer_host<=!host_q;
                    if (host_q) prefer_write<=!write_q;
                    state<=IDLE;
                end
            endcase
        end
    end
endmodule
