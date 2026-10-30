module furnace_axi4_xbar (
    input wire clk, rst_n,
    input wire [3:0][31:0] s_axi_awaddr,
    input wire [3:0][1:0] s_axi_awid,
    input wire [3:0][7:0] s_axi_awlen,
    input wire [3:0][2:0] s_axi_awsize,
    input wire [3:0][1:0] s_axi_awburst,
    input wire [3:0] s_axi_awlock,
    input wire [3:0][3:0] s_axi_awcache,
    input wire [3:0][2:0] s_axi_awprot,
    input wire [3:0][3:0] s_axi_awqos,s_axi_awregion,
    input wire [3:0] s_axi_awvalid,
    output reg [3:0] s_axi_awready,
    input wire [3:0][127:0] s_axi_wdata,
    input wire [3:0][15:0] s_axi_wstrb,
    input wire [3:0] s_axi_wlast,s_axi_wvalid,
    output reg [3:0] s_axi_wready,
    output reg [3:0][1:0] s_axi_bid,s_axi_bresp,
    output reg [3:0] s_axi_bvalid,
    input wire [3:0] s_axi_bready,
    input wire [3:0][31:0] s_axi_araddr,
    input wire [3:0][1:0] s_axi_arid,
    input wire [3:0][7:0] s_axi_arlen,
    input wire [3:0][2:0] s_axi_arsize,
    input wire [3:0][1:0] s_axi_arburst,
    input wire [3:0] s_axi_arlock,
    input wire [3:0][3:0] s_axi_arcache,
    input wire [3:0][2:0] s_axi_arprot,
    input wire [3:0][3:0] s_axi_arqos,s_axi_arregion,
    input wire [3:0] s_axi_arvalid,
    output reg [3:0] s_axi_arready,
    output reg [3:0][1:0] s_axi_rid,
    output reg [3:0][127:0] s_axi_rdata,
    output reg [3:0][1:0] s_axi_rresp,
    output reg [3:0] s_axi_rlast,s_axi_rvalid,
    input wire [3:0] s_axi_rready,
    output reg [3:0][31:0] m_axi_awaddr,
    output reg [3:0][3:0] m_axi_awid,
    output reg [3:0][7:0] m_axi_awlen,
    output reg [3:0][2:0] m_axi_awsize,
    output reg [3:0][1:0] m_axi_awburst,
    output reg [3:0] m_axi_awlock,
    output reg [3:0][3:0] m_axi_awcache,
    output reg [3:0][2:0] m_axi_awprot,
    output reg [3:0][3:0] m_axi_awqos,m_axi_awregion,
    output reg [3:0] m_axi_awvalid,
    input wire [3:0] m_axi_awready,
    output reg [3:0][127:0] m_axi_wdata,
    output reg [3:0][15:0] m_axi_wstrb,
    output reg [3:0] m_axi_wlast,m_axi_wvalid,
    input wire [3:0] m_axi_wready,
    input wire [3:0][3:0] m_axi_bid,
    input wire [3:0][1:0] m_axi_bresp,
    input wire [3:0] m_axi_bvalid,
    output reg [3:0] m_axi_bready,
    output reg [3:0][31:0] m_axi_araddr,
    output reg [3:0][3:0] m_axi_arid,
    output reg [3:0][7:0] m_axi_arlen,
    output reg [3:0][2:0] m_axi_arsize,
    output reg [3:0][1:0] m_axi_arburst,
    output reg [3:0] m_axi_arlock,
    output reg [3:0][3:0] m_axi_arcache,
    output reg [3:0][2:0] m_axi_arprot,
    output reg [3:0][3:0] m_axi_arqos,m_axi_arregion,
    output reg [3:0] m_axi_arvalid,
    input wire [3:0] m_axi_arready,
    input wire [3:0][3:0] m_axi_rid,
    input wire [3:0][127:0] m_axi_rdata,
    input wire [3:0][1:0] m_axi_rresp,
    input wire [3:0] m_axi_rlast,m_axi_rvalid,
    output reg [3:0] m_axi_rready
);
    function automatic header_valid(
        input [31:0] address,
        input [7:0] length,
        input [2:0] size,
        input [1:0] burst
    );
        reg [12:0] end_in_page;
        begin
            end_in_page={1'b0,address[11:0]}+({5'b0,length}+13'd1)*13'd16;
            header_valid=address[3:0]==0 && length<16 && size==4 &&
                burst==1 && end_in_page<=4096;
        end
    endfunction
    localparam [2:0] WIDLE=0, WADDR=1, WDATA=2, WRESP=3, WDRAIN=4, WERROR=5;
    localparam [1:0] RIDLE=0, RADDR=1, RDATA=2, RERROR=3;
    reg enabled;
    reg [3:0] write_busy,read_busy;
    reg [2:0] wstate [0:3];
    reg [1:0] rstate [0:3];
    reg [1:0] write_owner [0:3],read_owner [0:3];
    reg [1:0] write_priority [0:3],read_priority [0:3];
    reg [1:0] write_id [0:3],read_id [0:3];
    reg [7:0] write_length [0:3],read_length [0:3];
    reg [7:0] write_beat [0:3],read_beat [0:3];
    reg [64:0] write_header [0:3],read_header [0:3];
    reg [3:0] write_pick_valid,read_pick_valid;
    reg [1:0] write_pick [0:3],read_pick [0:3];
    wire [31:0] aw_address [0:3],ar_address [0:3];
    wire [3:0] good_write,good_read;
    genvar g;
    generate for (g=0;g<4;g=g+1) begin: headers
        assign aw_address[g]=s_axi_awaddr[g];
        assign ar_address[g]=s_axi_araddr[g];
        assign good_write[g]=header_valid(s_axi_awaddr[g],s_axi_awlen[g],
            s_axi_awsize[g],s_axi_awburst[g]);
        assign good_read[g]=header_valid(s_axi_araddr[g],s_axi_arlen[g],
            s_axi_arsize[g],s_axi_arburst[g]);
    end endgenerate
    integer t,k,candidate;
    always @* begin
        s_axi_awready=0; s_axi_wready=0; s_axi_bid=0; s_axi_bresp=0; s_axi_bvalid=0;
        s_axi_arready=0; s_axi_rid=0; s_axi_rdata=0; s_axi_rresp=0;
        s_axi_rlast=0; s_axi_rvalid=0;
        m_axi_awaddr=0; m_axi_awid=0; m_axi_awlen=0; m_axi_awsize=0;
        m_axi_awburst=0; m_axi_awlock=0; m_axi_awcache=0; m_axi_awprot=0;
        m_axi_awqos=0; m_axi_awregion=0; m_axi_awvalid=0;
        m_axi_wdata=0; m_axi_wstrb=0; m_axi_wlast=0; m_axi_wvalid=0; m_axi_bready=0;
        m_axi_araddr=0; m_axi_arid=0; m_axi_arlen=0; m_axi_arsize=0;
        m_axi_arburst=0; m_axi_arlock=0; m_axi_arcache=0; m_axi_arprot=0;
        m_axi_arqos=0; m_axi_arregion=0; m_axi_arvalid=0; m_axi_rready=0;
        write_pick_valid=0; read_pick_valid=0; candidate=0;
        for (t=0;t<4;t=t+1) begin
            write_pick[t]=0; read_pick[t]=0;
            if (rst_n && enabled) begin
                if (wstate[t]==WIDLE) begin
                    for (k=0;k<4;k=k+1) begin
                        candidate=({30'b0,write_priority[t]}+k)&3;
                        if (!write_pick_valid[t] && s_axi_awvalid[candidate] &&
                            !write_busy[candidate] && aw_address[candidate][31:30]==t) begin
                            write_pick_valid[t]=1; write_pick[t]=candidate[1:0];
                            s_axi_awready[candidate]=1;
                        end
                    end
                end
                if (rstate[t]==RIDLE) begin
                    for (k=0;k<4;k=k+1) begin
                        candidate=({30'b0,read_priority[t]}+k)&3;
                        if (!read_pick_valid[t] && s_axi_arvalid[candidate] &&
                            !read_busy[candidate] && ar_address[candidate][31:30]==t) begin
                            read_pick_valid[t]=1; read_pick[t]=candidate[1:0];
                            s_axi_arready[candidate]=1;
                        end
                    end
                end
                case (wstate[t])
                    WADDR:begin
                        {m_axi_awaddr[t],m_axi_awid[t],m_axi_awlen[t],
                            m_axi_awsize[t],m_axi_awburst[t],m_axi_awlock[t],
                            m_axi_awcache[t],m_axi_awprot[t],m_axi_awqos[t],
                            m_axi_awregion[t]}=write_header[t];
                        m_axi_awvalid[t]=1;
                    end
                    WDATA:begin
                        m_axi_wdata[t]=s_axi_wdata[write_owner[t]];
                        m_axi_wstrb[t]=s_axi_wstrb[write_owner[t]];
                        m_axi_wlast[t]=s_axi_wlast[write_owner[t]];
                        m_axi_wvalid[t]=s_axi_wvalid[write_owner[t]];
                        s_axi_wready[write_owner[t]]=m_axi_wready[t];
                    end
                    WRESP:begin
                        s_axi_bid[write_owner[t]]=m_axi_bid[t];
                        s_axi_bresp[write_owner[t]]=m_axi_bresp[t];
                        s_axi_bvalid[write_owner[t]]=m_axi_bvalid[t];
                        m_axi_bready[t]=s_axi_bready[write_owner[t]];
                    end
                    WDRAIN:s_axi_wready[write_owner[t]]=1;
                    WERROR:begin
                        s_axi_bid[write_owner[t]]=write_id[t];
                        s_axi_bresp[write_owner[t]]=2'b11;
                        s_axi_bvalid[write_owner[t]]=1;
                    end
                    default:begin end
                endcase
                case (rstate[t])
                    RADDR:begin
                        {m_axi_araddr[t],m_axi_arid[t],m_axi_arlen[t],
                            m_axi_arsize[t],m_axi_arburst[t],m_axi_arlock[t],
                            m_axi_arcache[t],m_axi_arprot[t],m_axi_arqos[t],
                            m_axi_arregion[t]}=read_header[t];
                        m_axi_arvalid[t]=1;
                    end
                    RDATA:begin
                        s_axi_rid[read_owner[t]]=m_axi_rid[t];
                        s_axi_rdata[read_owner[t]]=m_axi_rdata[t];
                        s_axi_rresp[read_owner[t]]=m_axi_rresp[t];
                        s_axi_rlast[read_owner[t]]=m_axi_rlast[t];
                        s_axi_rvalid[read_owner[t]]=m_axi_rvalid[t];
                        m_axi_rready[t]=s_axi_rready[read_owner[t]];
                    end
                    RERROR:begin
                        s_axi_rid[read_owner[t]]=read_id[t];
                        s_axi_rdata[read_owner[t]]=0; s_axi_rresp[read_owner[t]]=2'b11;
                        s_axi_rlast[read_owner[t]]=read_beat[t]==read_length[t];
                        s_axi_rvalid[read_owner[t]]=1;
                    end
                    default:begin end
                endcase
            end
        end
    end
    integer n;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enabled<=0; write_busy<=0; read_busy<=0;
            for (n=0;n<4;n=n+1) begin
                wstate[n]<=WIDLE; rstate[n]<=RIDLE;
                write_owner[n]<=0; read_owner[n]<=0;
                write_priority[n]<=0; read_priority[n]<=0;
                write_id[n]<=0; read_id[n]<=0;
                write_length[n]<=0; read_length[n]<=0; write_beat[n]<=0; read_beat[n]<=0;
                write_header[n]<=0; read_header[n]<=0;
            end
        end else begin
            enabled<=1;
            for (n=0;n<4;n=n+1) begin
                case (wstate[n])
                    WIDLE:if (write_pick_valid[n]) begin
                        write_owner[n]<=write_pick[n]; write_busy[write_pick[n]]<=1;
                        write_id[n]<=s_axi_awid[write_pick[n]];
                        write_length[n]<=s_axi_awlen[write_pick[n]]; write_beat[n]<=0;
                        write_header[n]<={s_axi_awaddr[write_pick[n]],
                            write_pick[n],s_axi_awid[write_pick[n]],s_axi_awlen[write_pick[n]],
                            s_axi_awsize[write_pick[n]],s_axi_awburst[write_pick[n]],
                            s_axi_awlock[write_pick[n]],s_axi_awcache[write_pick[n]],
                            s_axi_awprot[write_pick[n]],s_axi_awqos[write_pick[n]],
                            s_axi_awregion[write_pick[n]]};
                        if (good_write[write_pick[n]]) wstate[n]<=WADDR;
                        else wstate[n]<=WDRAIN;
                    end
                    WADDR:if (m_axi_awready[n]) wstate[n]<=WDATA;
                    WDATA:if (s_axi_wvalid[write_owner[n]] && m_axi_wready[n]) begin
                        if (write_beat[n]==write_length[n]) wstate[n]<=WRESP;
                        else write_beat[n]<=write_beat[n]+1'b1;
                    end
                    WRESP:if (m_axi_bvalid[n] && s_axi_bready[write_owner[n]]) begin
                        write_busy[write_owner[n]]<=0;
                        write_priority[n]<=write_owner[n]+1'b1; wstate[n]<=WIDLE;
                    end
                    WDRAIN:if (s_axi_wvalid[write_owner[n]]) begin
                        if (write_beat[n]==write_length[n]) wstate[n]<=WERROR;
                        else write_beat[n]<=write_beat[n]+1'b1;
                    end
                    WERROR:if (s_axi_bready[write_owner[n]]) begin
                        write_busy[write_owner[n]]<=0;
                        write_priority[n]<=write_owner[n]+1'b1; wstate[n]<=WIDLE;
                    end
                    default:wstate[n]<=WIDLE;
                endcase
                case (rstate[n])
                    RIDLE:if (read_pick_valid[n]) begin
                        read_owner[n]<=read_pick[n]; read_busy[read_pick[n]]<=1;
                        read_id[n]<=s_axi_arid[read_pick[n]];
                        read_length[n]<=s_axi_arlen[read_pick[n]]; read_beat[n]<=0;
                        read_header[n]<={s_axi_araddr[read_pick[n]],
                            read_pick[n],s_axi_arid[read_pick[n]],s_axi_arlen[read_pick[n]],
                            s_axi_arsize[read_pick[n]],s_axi_arburst[read_pick[n]],
                            s_axi_arlock[read_pick[n]],s_axi_arcache[read_pick[n]],
                            s_axi_arprot[read_pick[n]],s_axi_arqos[read_pick[n]],
                            s_axi_arregion[read_pick[n]]};
                        if (good_read[read_pick[n]]) rstate[n]<=RADDR;
                        else rstate[n]<=RERROR;
                    end
                    RADDR:if (m_axi_arready[n]) rstate[n]<=RDATA;
                    RDATA:if (m_axi_rvalid[n] && s_axi_rready[read_owner[n]] &&
                        m_axi_rlast[n]) begin
                        read_busy[read_owner[n]]<=0;
                        read_priority[n]<=read_owner[n]+1'b1; rstate[n]<=RIDLE;
                    end
                    RERROR:if (s_axi_rready[read_owner[n]]) begin
                        if (read_beat[n]==read_length[n]) begin
                            read_busy[read_owner[n]]<=0;
                            read_priority[n]<=read_owner[n]+1'b1; rstate[n]<=RIDLE;
                        end else read_beat[n]<=read_beat[n]+1'b1;
                    end
                    default:rstate[n]<=RIDLE;
                endcase
            end
        end
    end
endmodule
