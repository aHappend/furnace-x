module furnace_dma128 (
    input wire clk, rst_n,
    input wire rd_valid,
    output wire rd_ready,
    input wire [31:0] rd_addr,rd_bytes,
    output wire m_valid,
    input wire m_ready,
    output wire [7:0] m_data,
    output wire m_last,
    output wire rd_done,
    input wire rd_done_ready,
    output wire [7:0] rd_error,
    input wire wr_valid,
    output wire wr_ready,
    input wire [31:0] wr_addr,wr_bytes,
    input wire s_valid,
    output wire s_ready,
    input wire [7:0] s_data,
    input wire s_last,
    output wire wr_done,
    input wire wr_done_ready,
    output wire [7:0] wr_error,
    output wire [31:0] m_axi_awaddr,
    output wire [1:0] m_axi_awid,
    output wire [7:0] m_axi_awlen,
    output wire [2:0] m_axi_awsize,
    output wire [1:0] m_axi_awburst,
    output wire m_axi_awlock,
    output wire [3:0] m_axi_awcache,
    output wire [2:0] m_axi_awprot,
    output wire [3:0] m_axi_awqos,m_axi_awregion,
    output wire m_axi_awvalid,
    input wire m_axi_awready,
    output wire [127:0] m_axi_wdata,
    output wire [15:0] m_axi_wstrb,
    output wire m_axi_wlast,m_axi_wvalid,
    input wire m_axi_wready,
    input wire [1:0] m_axi_bid,m_axi_bresp,
    input wire m_axi_bvalid,
    output wire m_axi_bready,
    output wire [31:0] m_axi_araddr,
    output wire [1:0] m_axi_arid,
    output wire [7:0] m_axi_arlen,
    output wire [2:0] m_axi_arsize,
    output wire [1:0] m_axi_arburst,
    output wire m_axi_arlock,
    output wire [3:0] m_axi_arcache,
    output wire [2:0] m_axi_arprot,
    output wire [3:0] m_axi_arqos,m_axi_arregion,
    output wire m_axi_arvalid,
    input wire m_axi_arready,
    input wire [1:0] m_axi_rid,
    input wire [127:0] m_axi_rdata,
    input wire [1:0] m_axi_rresp,
    input wire m_axi_rlast,m_axi_rvalid,
    output wire m_axi_rready
);
    localparam [2:0] RIDLE=0,RADDR=1,RWAIT=2,RBYTES=3,RDRAIN=4,RDONE=5;
    localparam [2:0] WIDLE=0,WGATHER=1,WADDR=2,WDATA=3,WRESP=4,WDONE=5;
    reg enabled;
    reg [2:0] rstate,wstate;
    reg [31:0] raddress,waddress,rleft,wleft;
    reg [127:0] rbuffer,wbuffer;
    reg [15:0] wstrobes;
    reg [3:0] rindex,windex;
    reg [7:0] rstatus,wstatus;
    wire [32:0] rounded_read=({1'b0,rd_bytes}+33'd15) & 33'h1fffffff0;
    wire [32:0] rounded_write=({1'b0,wr_bytes}+33'd15) & 33'h1fffffff0;
    wire [33:0] read_end={2'b0,rd_addr}+{1'b0,rounded_read};
    wire [33:0] write_end={2'b0,wr_addr}+{1'b0,rounded_write};
    wire read_bad=rd_addr[3:0]!=0 || read_end>34'h100000000;
    wire write_bad=wr_addr[3:0]!=0 || write_end>34'h100000000;
    wire active=rst_n && enabled;
    assign rd_ready=active && rstate==RIDLE;
    assign wr_ready=active && wstate==WIDLE;
    assign m_valid=active && rstate==RBYTES;
    assign m_data=m_valid ? rbuffer[{rindex,3'b000}+:8] : 8'b0;
    assign m_last=m_valid && rleft==1;
    assign rd_done=active && rstate==RDONE;
    assign rd_error=active ? rstatus : 8'b0;
    assign s_ready=active && wstate==WGATHER;
    assign wr_done=active && wstate==WDONE;
    assign wr_error=active ? wstatus : 8'b0;
    assign m_axi_awaddr=active ? waddress : 32'b0;
    assign m_axi_awid=0; assign m_axi_awlen=0;
    assign m_axi_awsize=active ? 3'd4 : 3'b0;
    assign m_axi_awburst=active ? 2'b01 : 2'b0;
    assign m_axi_awlock=0; assign m_axi_awcache=0; assign m_axi_awprot=0;
    assign m_axi_awqos=0; assign m_axi_awregion=0;
    assign m_axi_awvalid=active && wstate==WADDR;
    assign m_axi_wdata=active ? wbuffer : 128'b0;
    assign m_axi_wstrb=active ? wstrobes : 16'b0;
    assign m_axi_wlast=active && wstate==WDATA;
    assign m_axi_wvalid=active && wstate==WDATA;
    assign m_axi_bready=active && wstate==WRESP;
    assign m_axi_araddr=active ? raddress : 32'b0;
    assign m_axi_arid=0; assign m_axi_arlen=0;
    assign m_axi_arsize=active ? 3'd4 : 3'b0;
    assign m_axi_arburst=active ? 2'b01 : 2'b0;
    assign m_axi_arlock=0; assign m_axi_arcache=0; assign m_axi_arprot=0;
    assign m_axi_arqos=0; assign m_axi_arregion=0;
    assign m_axi_arvalid=active && rstate==RADDR;
    assign m_axi_rready=active && (rstate==RWAIT || rstate==RDRAIN);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enabled<=0; rstate<=RIDLE; wstate<=WIDLE;
            raddress<=0; waddress<=0; rleft<=0; wleft<=0;
            rbuffer<=0; wbuffer<=0; wstrobes<=0; rindex<=0; windex<=0;
            rstatus<=0; wstatus<=0;
        end else begin
            enabled<=1;
            case (rstate)
                RIDLE:if (rd_valid && rd_ready) begin
                    raddress<=rd_addr; rleft<=rd_bytes; rindex<=0; rstatus<=0;
                    if (read_bad) begin rstatus<=5; rstate<=RDONE; end
                    else if (rd_bytes==0) rstate<=RDONE; else rstate<=RADDR;
                end
                RADDR:if (m_axi_arready) rstate<=RWAIT;
                RWAIT:if (m_axi_rvalid) begin
                    if (m_axi_rresp!=0 || m_axi_rid!=0 || !m_axi_rlast) begin
                        rstatus<=5;
                        if (m_axi_rlast) rstate<=RDONE; else rstate<=RDRAIN;
                    end else begin rbuffer<=m_axi_rdata; rindex<=0; rstate<=RBYTES; end
                end
                RBYTES:if (m_ready) begin
                    rleft<=rleft-1'b1;
                    if (rleft==1) rstate<=RDONE;
                    else if (rindex==15) begin raddress<=raddress+32'd16; rstate<=RADDR; end
                    else rindex<=rindex+1'b1;
                end
                RDRAIN:if (m_axi_rvalid && m_axi_rlast) rstate<=RDONE;
                RDONE:if (rd_done_ready) rstate<=RIDLE;
                default:begin rstatus<=5; rstate<=RDONE; end
            endcase
            case (wstate)
                WIDLE:if (wr_valid && wr_ready) begin
                    waddress<=wr_addr; wleft<=wr_bytes; windex<=0; wstatus<=0;
                    wbuffer<=0; wstrobes<=0;
                    if (write_bad) begin wstatus<=5; wstate<=WDONE; end
                    else if (wr_bytes==0) wstate<=WDONE; else wstate<=WGATHER;
                end
                WGATHER:if (s_valid && s_ready) begin
                    wbuffer[{windex,3'b000}+:8]<=s_data; wstrobes[windex]<=1;
                    wleft<=wleft-1'b1;
                    if (s_last!=(wleft==1)) wstatus<=5;
                    if (windex==15 || wleft==1) wstate<=WADDR;
                    else windex<=windex+1'b1;
                end
                WADDR:if (m_axi_awready) wstate<=WDATA;
                WDATA:if (m_axi_wready) wstate<=WRESP;
                WRESP:if (m_axi_bvalid) begin
                    if (m_axi_bresp!=0 || m_axi_bid!=0) begin wstatus<=5; wstate<=WDONE; end
                    else if (wleft==0) wstate<=WDONE;
                    else begin
                        waddress<=waddress+32'd16; windex<=0; wstrobes<=0;
                        wbuffer<=0; wstate<=WGATHER;
                    end
                end
                WDONE:if (wr_done_ready) wstate<=WIDLE;
                default:begin wstatus<=5; wstate<=WDONE; end
            endcase
        end
    end
endmodule
