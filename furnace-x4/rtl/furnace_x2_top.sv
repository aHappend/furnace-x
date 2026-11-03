module furnace_x2_top #(
    parameter integer MAX_TILE_BYTES=4096,
    parameter integer RING_DEPTH=8,
    parameter integer IN_WIDTH=8,IN_HEIGHT=8,OUT_WIDTH=8,OUT_HEIGHT=8,
    parameter integer FFT_N=16,FUSION_DEPTH=4
) (
    input wire clk, rst_n,
    output wire irq,
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
    output wire [3:0][31:0] m_axi_awaddr,
    output wire [3:0][3:0] m_axi_awid,
    output wire [3:0][7:0] m_axi_awlen,
    output wire [3:0][2:0] m_axi_awsize,
    output wire [3:0][1:0] m_axi_awburst,
    output wire [3:0] m_axi_awlock,
    output wire [3:0][3:0] m_axi_awcache,
    output wire [3:0][2:0] m_axi_awprot,
    output wire [3:0][3:0] m_axi_awqos,m_axi_awregion,
    output wire [3:0] m_axi_awvalid,
    input wire [3:0] m_axi_awready,
    output wire [3:0][127:0] m_axi_wdata,
    output wire [3:0][15:0] m_axi_wstrb,
    output wire [3:0] m_axi_wlast,m_axi_wvalid,
    input wire [3:0] m_axi_wready,
    input wire [3:0][3:0] m_axi_bid,
    input wire [3:0][1:0] m_axi_bresp,
    input wire [3:0] m_axi_bvalid,
    output wire [3:0] m_axi_bready,
    output wire [3:0][31:0] m_axi_araddr,
    output wire [3:0][3:0] m_axi_arid,
    output wire [3:0][7:0] m_axi_arlen,
    output wire [3:0][2:0] m_axi_arsize,
    output wire [3:0][1:0] m_axi_arburst,
    output wire [3:0] m_axi_arlock,
    output wire [3:0][3:0] m_axi_arcache,
    output wire [3:0][2:0] m_axi_arprot,
    output wire [3:0][3:0] m_axi_arqos,m_axi_arregion,
    output wire [3:0] m_axi_arvalid,
    input wire [3:0] m_axi_arready,
    input wire [3:0][3:0] m_axi_rid,
    input wire [3:0][127:0] m_axi_rdata,
    input wire [3:0][1:0] m_axi_rresp,
    input wire [3:0] m_axi_rlast,m_axi_rvalid,
    output wire [3:0] m_axi_rready,
    input wire v_valid,
    output wire v_ready,
    input wire [7:0] v_pixel,
    input wire [15:0] v_id,
    input wire v_last,
    input wire a_valid,
    output wire a_ready,
    input wire signed [15:0] a_sample,
    input wire [15:0] a_id,
    input wire a_last,
    output wire mm_valid,
    input wire mm_ready,
    output wire [15:0] mm_id,
    output wire [63:0] mm_result,
    output wire [7:0] mm_error
);
    generate if (MAX_TILE_BYTES<1 || MAX_TILE_BYTES>65536 ||
        RING_DEPTH<1 || RING_DEPTH>16 || FUSION_DEPTH<1 || FUSION_DEPTH>16 ||
        IN_WIDTH<1 || IN_WIDTH>64 || IN_HEIGHT<1 || IN_HEIGHT>64 ||
        OUT_WIDTH<1 || OUT_WIDTH>64 || OUT_HEIGHT<1 || OUT_HEIGHT>64 ||
        (FFT_N!=8 && FFT_N!=16 && FFT_N!=32 && FFT_N!=64)) begin: bad_parameter
        initial $fatal(1,"PARAMETER ERROR: illegal FURNACE-X2 configuration");
        assign irq=0; assign s_axil_awready=0; assign s_axil_wready=0;
        assign s_axil_bresp=0; assign s_axil_bvalid=0; assign s_axil_arready=0;
        assign s_axil_rdata=0; assign s_axil_rresp=0; assign s_axil_rvalid=0;
        assign m_axi_awaddr=0; assign m_axi_awid=0; assign m_axi_awlen=0;
        assign m_axi_awsize=0; assign m_axi_awburst=0; assign m_axi_awlock=0;
        assign m_axi_awcache=0; assign m_axi_awprot=0; assign m_axi_awqos=0;
        assign m_axi_awregion=0; assign m_axi_awvalid=0; assign m_axi_wdata=0;
        assign m_axi_wstrb=0; assign m_axi_wlast=0; assign m_axi_wvalid=0;
        assign m_axi_bready=0; assign m_axi_araddr=0; assign m_axi_arid=0;
        assign m_axi_arlen=0; assign m_axi_arsize=0; assign m_axi_arburst=0;
        assign m_axi_arlock=0; assign m_axi_arcache=0; assign m_axi_arprot=0;
        assign m_axi_arqos=0; assign m_axi_arregion=0; assign m_axi_arvalid=0;
        assign m_axi_rready=0;
        assign v_ready=0; assign a_ready=0; assign mm_valid=0;
        assign mm_id=0; assign mm_result=0; assign mm_error=0;
    end else begin: soc
        localparam [5:0] IDLE=0, CLEAR=1, DESC_REQ=2, DESC_DATA=3,
            DESC_WAIT=4, VALIDATE=5, START_PIPE=6, FRAME_REQ=7, INGEST=8,
            PLAIN_START=9, PLAIN=10, WEIGHT_REQ=11, WEIGHT_DATA=12,
            WEIGHT_WAIT=13, ACT_REQ=14, ACT_DATA=15, ACT_WAIT=16,
            VECTOR=17, VECTOR_WAIT=18, RESULT_REQ=19, RESULT_DATA=20,
            RESULT_WAIT=21, CMP_REQ=22, CMP_DATA=23, CMP_WAIT=24,
            RETIRE=25, ABORT_PIPE=26;
        reg enabled;
        reg [5:0] state;
        wire busy=state!=IDLE;
        wire engine_rst_n=rst_n && state!=CLEAR && state!=ABORT_PIPE;
        wire run_enable,key_valid,queued,ring_full,tail_valid,tail_error;
        wire [127:0] committed_key;
        wire [31:0] ring_base,head,tail,tail_value;
        wire [3:0] head_slot;
        wire tail_ready;
        reg [1023:0] descriptor;
        reg [31:0] descriptor_address,frame_address,frame_length,plain_address;
        reg [31:0] activation_address,result_address,weight_length,vector_count;
        reg [31:0] tile_id,completion_address,authenticated_bytes,vector_index;
        reg [95:0] tile_nonce;
        reg [127:0] tile_tag,weight_buffer,activation_buffer;
        reg mm_weight_commit,mm_weights_valid;
        reg [31:0] mm_weights,candidate_weights;
        reg [2:0] candidate_bytes;
        reg [415:0] tile_aad;
        reg [63:0] tile_result;
        reg [1:0] tile_mode;
        reg request_irq,completion_safe;
        reg [7:0] status,byte_index;
        reg frame_read_seen,crypto_seen,plain_seen,lz_seen;
        reg [7:0] frame_read_error,crypto_error,plain_error;
        wire [32:0] next_descriptor_address={1'b0,ring_base}+{22'b0,head_slot,7'b0};
        wire [33:0] descriptor_limit={1'b0,next_descriptor_address}+34'd128;
        wire active_pipeline=state==INGEST || state==PLAIN_START || state==PLAIN;

        reg [3:0] rd_command,wr_command,read_byte_ready,write_byte_valid;
        reg [3:0] read_done_ready,write_done_ready;
        reg [3:0][31:0] rd_address,rd_length,wr_address,wr_length;
        reg [3:0][7:0] write_byte;
        reg [3:0] write_last;
        wire [3:0] rd_ready,wr_ready,read_byte_valid,read_last,write_byte_ready;
        wire [3:0] read_done,write_done;
        wire [3:0][7:0] read_byte,read_error,write_error;
        wire [3:0][31:0] i_awaddr,i_araddr;
        wire [3:0][1:0] i_awid,i_arid,i_awburst,i_arburst,i_bid,i_bresp,i_rid,i_rresp;
        wire [3:0][7:0] i_awlen,i_arlen;
        wire [3:0][2:0] i_awsize,i_arsize,i_awprot,i_arprot;
        wire [3:0][3:0] i_awcache,i_arcache,i_awqos,i_arqos,i_awregion,i_arregion;
        wire [3:0] i_awlock,i_arlock,i_awvalid,i_awready,i_arvalid,i_arready;
        wire [3:0][127:0] i_wdata,i_rdata;
        wire [3:0][15:0] i_wstrb;
        wire [3:0] i_wlast,i_wvalid,i_wready,i_bvalid,i_bready;
        wire [3:0] i_rlast,i_rvalid,i_rready;
        wire mm_enable,key_changed,mm_busy,mm_controller_busy,mm_report;
        wire [31:0] v_base,a_base,mm_result_base;
        wire [19:0] qos;
        reg vision_active,audio_active;
        wire vision_input_ready,audio_input_ready,vision_token_valid,audio_token_valid;
        wire vision_token_ready,audio_token_ready;
        wire [63:0] vision_token_data,audio_token_data;
        wire [15:0] vision_token_id,audio_token_id;
        wire [7:0] vision_token_error,audio_token_error;
        wire fv_valid,fv_ready,fa_valid,fa_ready,fusion_valid,fusion_ready;
        wire [63:0] fv_data,fa_data;
        wire [15:0] fv_id,fa_id,fusion_id;
        wire [7:0] fv_error,fa_error,fusion_error;
        wire [127:0] fusion_data;
        wire mm_tensor_valid,mm_tensor_ready,mm_tensor_result_ready;
        wire [127:0] mm_tensor_weights,mm_tensor_activations;
        wire [2:0] mm_wr_valid,mm_wr_ready,mm_byte_valid,mm_byte_ready,mm_byte_last;
        wire [2:0] mm_wr_done,mm_wr_done_ready;
        wire [2:0][31:0] mm_wr_address,mm_wr_length;
        wire [2:0][7:0] mm_byte_data,mm_wr_error;
        wire [3:0] dma_wr_command,dma_write_byte_valid,dma_write_last;
        wire [3:0] dma_wr_ready,dma_write_byte_ready,dma_write_done,dma_write_done_ready;
        wire [3:0][31:0] dma_wr_address,dma_wr_length;
        wire [3:0][7:0] dma_write_byte,dma_write_error;
        wire [3:0][3:0] dma_write_qos,dma_read_qos;
        wire [3:0][3:0] unused_dma_awqos,unused_dma_arqos;
        wire [7:0] mm_report_error=(mm_wr_error[2]!=0) ? 8'd5 : mm_error;
        assign v_ready=rst_n && enabled && mm_enable && vision_input_ready;
        assign a_ready=rst_n && enabled && mm_enable && audio_input_ready;
        assign mm_busy=vision_active || audio_active || mm_controller_busy ||
            (mm_enable && (v_valid || a_valid));

        furnace_x2_csr #(.RING_DEPTH(RING_DEPTH),.FUSION_DEPTH(FUSION_DEPTH)) control (
            .clk(clk),.rst_n(rst_n),
            .s_axil_awaddr(s_axil_awaddr),.s_axil_awprot(s_axil_awprot),
            .s_axil_awvalid(s_axil_awvalid),.s_axil_awready(s_axil_awready),
            .s_axil_wdata(s_axil_wdata),.s_axil_wstrb(s_axil_wstrb),
            .s_axil_wvalid(s_axil_wvalid),.s_axil_wready(s_axil_wready),
            .s_axil_bresp(s_axil_bresp),.s_axil_bvalid(s_axil_bvalid),
            .s_axil_bready(s_axil_bready),.s_axil_araddr(s_axil_araddr),
            .s_axil_arprot(s_axil_arprot),.s_axil_arvalid(s_axil_arvalid),
            .s_axil_arready(s_axil_arready),.s_axil_rdata(s_axil_rdata),
            .s_axil_rresp(s_axil_rresp),.s_axil_rvalid(s_axil_rvalid),
            .s_axil_rready(s_axil_rready),.busy(busy),.queued(queued),
            .ring_full(ring_full),.head(head),.tail(tail),.tail_error(tail_error),
            .completion_valid(enabled && state==RETIRE),
            .completion_error(status),.completion_tile_id(tile_id),
            .completion_irq_requested(request_irq),.enable(run_enable),
            .key_valid(key_valid),.key(committed_key),.ring_base(ring_base),
            .tail_valid(tail_valid),.tail_value(tail_value),.irq(irq),
            .mm_busy(mm_busy),.fusion_busy(mm_controller_busy),
            .vision_busy(vision_active),.audio_busy(audio_active),
            .weights_valid(mm_weights_valid),.mm_report(mm_report),
            .mm_report_id(mm_id),.mm_report_error(mm_report_error),
            .mm_enable(mm_enable),.v_base(v_base),.a_base(a_base),
            .result_base(mm_result_base),.qos(qos),.key_changed(key_changed)
        );
        furnace_command_ring #(.RING_DEPTH(RING_DEPTH)) command_ring (
            .clk(clk),.rst_n(rst_n),.tail_valid(tail_valid),.tail_ready(tail_ready),
            .tail_value(tail_value),.tail_error(tail_error),
            .retire(enabled && state==RETIRE),.head(head),.tail(tail),
            .head_slot(head_slot),.queued(queued),.full(ring_full)
        );
        genvar d;
        for (d=0;d<4;d=d+1) begin: dma_ports
            furnace_dma128 dma (
                .clk(clk),.rst_n(rst_n),.rd_valid(rd_command[d]),.rd_ready(rd_ready[d]),
                .rd_addr(rd_address[d]),.rd_bytes(rd_length[d]),
                .m_valid(read_byte_valid[d]),.m_ready(read_byte_ready[d]),
                .m_data(read_byte[d]),.m_last(read_last[d]),
                .rd_done(read_done[d]),.rd_done_ready(read_done_ready[d]),
                .rd_error(read_error[d]),.wr_valid(dma_wr_command[d]),.wr_ready(dma_wr_ready[d]),
                .wr_addr(dma_wr_address[d]),.wr_bytes(dma_wr_length[d]),
                .s_valid(dma_write_byte_valid[d]),.s_ready(dma_write_byte_ready[d]),
                .s_data(dma_write_byte[d]),.s_last(dma_write_last[d]),
                .wr_done(dma_write_done[d]),.wr_done_ready(dma_write_done_ready[d]),
                .wr_error(dma_write_error[d]),
                .m_axi_awaddr(i_awaddr[d]),.m_axi_awid(i_awid[d]),.m_axi_awlen(i_awlen[d]),
                .m_axi_awsize(i_awsize[d]),.m_axi_awburst(i_awburst[d]),
                .m_axi_awlock(i_awlock[d]),.m_axi_awcache(i_awcache[d]),
                .m_axi_awprot(i_awprot[d]),.m_axi_awqos(unused_dma_awqos[d]),
                .m_axi_awregion(i_awregion[d]),.m_axi_awvalid(i_awvalid[d]),
                .m_axi_awready(i_awready[d]),.m_axi_wdata(i_wdata[d]),
                .m_axi_wstrb(i_wstrb[d]),.m_axi_wlast(i_wlast[d]),
                .m_axi_wvalid(i_wvalid[d]),.m_axi_wready(i_wready[d]),
                .m_axi_bid(i_bid[d]),.m_axi_bresp(i_bresp[d]),
                .m_axi_bvalid(i_bvalid[d]),.m_axi_bready(i_bready[d]),
                .m_axi_araddr(i_araddr[d]),.m_axi_arid(i_arid[d]),.m_axi_arlen(i_arlen[d]),
                .m_axi_arsize(i_arsize[d]),.m_axi_arburst(i_arburst[d]),
                .m_axi_arlock(i_arlock[d]),.m_axi_arcache(i_arcache[d]),
                .m_axi_arprot(i_arprot[d]),.m_axi_arqos(unused_dma_arqos[d]),
                .m_axi_arregion(i_arregion[d]),.m_axi_arvalid(i_arvalid[d]),
                .m_axi_arready(i_arready[d]),.m_axi_rid(i_rid[d]),.m_axi_rdata(i_rdata[d]),
                .m_axi_rresp(i_rresp[d]),.m_axi_rlast(i_rlast[d]),
                .m_axi_rvalid(i_rvalid[d]),.m_axi_rready(i_rready[d])
            );
            assign i_awqos[d]=dma_write_qos[d];
            assign i_arqos[d]=dma_read_qos[d];
            if (d==0 || d==3) begin: dedicated_write
                assign dma_wr_command[d]=wr_command[d];
                assign wr_ready[d]=dma_wr_ready[d];
                assign dma_wr_address[d]=wr_address[d]; assign dma_wr_length[d]=wr_length[d];
                assign dma_write_byte_valid[d]=write_byte_valid[d];
                assign write_byte_ready[d]=dma_write_byte_ready[d];
                assign dma_write_byte[d]=write_byte[d]; assign dma_write_last[d]=write_last[d];
                assign write_done[d]=dma_write_done[d]; assign write_error[d]=dma_write_error[d];
                assign dma_write_done_ready[d]=write_done_ready[d];
                assign dma_write_qos[d]=(rst_n && enabled) ? ((d==3) ? qos[19:16] : qos[3:0]) : 4'b0;
            end else begin: shared_write
                wire [2:0] client_valid,client_ready,client_byte_valid,client_byte_ready;
                wire [2:0] client_last,client_done,client_done_ready;
                wire [2:0][31:0] client_address,client_length;
                wire [2:0][7:0] client_byte,client_error;
                wire [2:0][3:0] client_qos;
                assign client_valid[0]=wr_command[d];
                assign wr_ready[d]=client_ready[0];
                assign client_address[0]=wr_address[d]; assign client_length[0]=wr_length[d];
                assign client_byte_valid[0]=write_byte_valid[d];
                assign write_byte_ready[d]=client_byte_ready[0];
                assign client_byte[0]=write_byte[d]; assign client_last[0]=write_last[d];
                assign write_done[d]=client_done[0]; assign write_error[d]=client_error[0];
                assign client_done_ready[0]=write_done_ready[d];
                assign client_qos[0]=(d==1) ? qos[3:0] : qos[15:12];
                assign client_valid[1]=mm_wr_valid[d-1];
                assign mm_wr_ready[d-1]=client_ready[1];
                assign client_address[1]=mm_wr_address[d-1]; assign client_length[1]=mm_wr_length[d-1];
                assign client_byte_valid[1]=mm_byte_valid[d-1];
                assign mm_byte_ready[d-1]=client_byte_ready[1];
                assign client_byte[1]=mm_byte_data[d-1]; assign client_last[1]=mm_byte_last[d-1];
                assign mm_wr_done[d-1]=client_done[1]; assign mm_wr_error[d-1]=client_error[1];
                assign client_done_ready[1]=mm_wr_done_ready[d-1];
                assign client_qos[1]=(d==1) ? qos[7:4] : qos[11:8];
                if (d==2) begin: result_client
                    assign client_valid[2]=mm_wr_valid[2]; assign mm_wr_ready[2]=client_ready[2];
                    assign client_address[2]=mm_wr_address[2]; assign client_length[2]=mm_wr_length[2];
                    assign client_byte_valid[2]=mm_byte_valid[2]; assign mm_byte_ready[2]=client_byte_ready[2];
                    assign client_byte[2]=mm_byte_data[2]; assign client_last[2]=mm_byte_last[2];
                    assign mm_wr_done[2]=client_done[2]; assign mm_wr_error[2]=client_error[2];
                    assign client_done_ready[2]=mm_wr_done_ready[2]; assign client_qos[2]=qos[15:12];
                end else begin: unused_client
                    assign client_valid[2]=0; assign client_address[2]=0; assign client_length[2]=0;
                    assign client_byte_valid[2]=0; assign client_byte[2]=0; assign client_last[2]=0;
                    assign client_done_ready[2]=0; assign client_qos[2]=0;
                end
                furnace_dma_write_arb write_scheduler (
                    .clk(clk),.rst_n(rst_n),.c_valid(client_valid),.c_ready(client_ready),
                    .c_address(client_address),.c_length(client_length),.c_qos(client_qos),
                    .c_data_valid(client_byte_valid),.c_data_ready(client_byte_ready),
                    .c_data(client_byte),.c_last(client_last),.c_done(client_done),
                    .c_done_ready(client_done_ready),.c_error(client_error),
                    .d_valid(dma_wr_command[d]),.d_ready(dma_wr_ready[d]),
                    .d_address(dma_wr_address[d]),.d_length(dma_wr_length[d]),.d_qos(dma_write_qos[d]),
                    .d_data_valid(dma_write_byte_valid[d]),.d_data_ready(dma_write_byte_ready[d]),
                    .d_data(dma_write_byte[d]),.d_last(dma_write_last[d]),
                    .d_done(dma_write_done[d]),.d_done_ready(dma_write_done_ready[d]),
                    .d_error(dma_write_error[d])
                );
            end
            assign dma_read_qos[d]=(rst_n && enabled) ?
                ((d==0) ? qos[3:0] : (d==3) ? qos[19:16] : qos[15:12]) : 4'b0;
        end
        furnace_axi4_qos_xbar axi_crossbar (
            .clk(clk),.rst_n(rst_n),
            .s_axi_awaddr(i_awaddr),.s_axi_awid(i_awid),.s_axi_awlen(i_awlen),
            .s_axi_awsize(i_awsize),.s_axi_awburst(i_awburst),.s_axi_awlock(i_awlock),
            .s_axi_awcache(i_awcache),.s_axi_awprot(i_awprot),.s_axi_awqos(i_awqos),
            .s_axi_awregion(i_awregion),.s_axi_awvalid(i_awvalid),.s_axi_awready(i_awready),
            .s_axi_wdata(i_wdata),.s_axi_wstrb(i_wstrb),.s_axi_wlast(i_wlast),
            .s_axi_wvalid(i_wvalid),.s_axi_wready(i_wready),.s_axi_bid(i_bid),
            .s_axi_bresp(i_bresp),.s_axi_bvalid(i_bvalid),.s_axi_bready(i_bready),
            .s_axi_araddr(i_araddr),.s_axi_arid(i_arid),.s_axi_arlen(i_arlen),
            .s_axi_arsize(i_arsize),.s_axi_arburst(i_arburst),.s_axi_arlock(i_arlock),
            .s_axi_arcache(i_arcache),.s_axi_arprot(i_arprot),.s_axi_arqos(i_arqos),
            .s_axi_arregion(i_arregion),.s_axi_arvalid(i_arvalid),.s_axi_arready(i_arready),
            .s_axi_rid(i_rid),.s_axi_rdata(i_rdata),.s_axi_rresp(i_rresp),
            .s_axi_rlast(i_rlast),.s_axi_rvalid(i_rvalid),.s_axi_rready(i_rready),
            .m_axi_awaddr(m_axi_awaddr),.m_axi_awid(m_axi_awid),.m_axi_awlen(m_axi_awlen),
            .m_axi_awsize(m_axi_awsize),.m_axi_awburst(m_axi_awburst),
            .m_axi_awlock(m_axi_awlock),.m_axi_awcache(m_axi_awcache),
            .m_axi_awprot(m_axi_awprot),.m_axi_awqos(m_axi_awqos),
            .m_axi_awregion(m_axi_awregion),.m_axi_awvalid(m_axi_awvalid),
            .m_axi_awready(m_axi_awready),.m_axi_wdata(m_axi_wdata),.m_axi_wstrb(m_axi_wstrb),
            .m_axi_wlast(m_axi_wlast),.m_axi_wvalid(m_axi_wvalid),.m_axi_wready(m_axi_wready),
            .m_axi_bid(m_axi_bid),.m_axi_bresp(m_axi_bresp),.m_axi_bvalid(m_axi_bvalid),
            .m_axi_bready(m_axi_bready),.m_axi_araddr(m_axi_araddr),.m_axi_arid(m_axi_arid),
            .m_axi_arlen(m_axi_arlen),.m_axi_arsize(m_axi_arsize),.m_axi_arburst(m_axi_arburst),
            .m_axi_arlock(m_axi_arlock),.m_axi_arcache(m_axi_arcache),
            .m_axi_arprot(m_axi_arprot),.m_axi_arqos(m_axi_arqos),
            .m_axi_arregion(m_axi_arregion),.m_axi_arvalid(m_axi_arvalid),
            .m_axi_arready(m_axi_arready),.m_axi_rid(m_axi_rid),.m_axi_rdata(m_axi_rdata),
            .m_axi_rresp(m_axi_rresp),.m_axi_rlast(m_axi_rlast),.m_axi_rvalid(m_axi_rvalid),
            .m_axi_rready(m_axi_rready)
        );

        wire lz_start_ready,lz_s_ready,lz_m_valid,lz_m_ready,lz_m_last,lz_done,lz_done_ready;
        wire [7:0] lz_m_data,lz_error;
        wire crypto_start_ready,crypto_s_ready,crypto_m_valid,crypto_m_ready,crypto_m_last;
        wire crypto_done,crypto_done_ready;
        wire [7:0] crypto_m_data,crypto_status;
        wire start_engines=enabled && state==START_PIPE && lz_start_ready && crypto_start_ready;
        furnace_lz4_frontend #(.MAX_DECODED_BYTES(MAX_TILE_BYTES)) decompressor (
            .clk(clk),.rst_n(engine_rst_n),.start_valid(start_engines),
            .start_ready(lz_start_ready),.start_frame_bytes(frame_length),
            .start_decoded_bytes(weight_length),
            .s_valid(read_byte_valid[0] && !lz_seen),.s_ready(lz_s_ready),
            .s_data(read_byte[0]),.s_last(read_last[0]),
            .m_valid(lz_m_valid),.m_ready(lz_m_ready),.m_data(lz_m_data),
            .m_last(lz_m_last),.done_valid(lz_done),.done_ready(lz_done_ready),.error(lz_error)
        );
        furnace_aes128_gcm #(.MAX_TILE_BYTES(MAX_TILE_BYTES)) decryptor (
            .clk(clk),.rst_n(engine_rst_n),.start_valid(start_engines),
            .start_ready(crypto_start_ready),.key(committed_key),.nonce(tile_nonce),
            .tag(tile_tag),.aad(tile_aad),.data_bytes(weight_length),
            .s_valid(lz_m_valid),.s_ready(crypto_s_ready),.s_data(lz_m_data),.s_last(lz_m_last),
            .m_valid(crypto_m_valid),.m_ready(crypto_m_ready),.m_data(crypto_m_data),
            .m_last(crypto_m_last),.frame_done_valid(lz_done),
            .frame_done_ready(lz_done_ready),.frame_error(lz_error),
            .done_valid(crypto_done),.done_ready(crypto_done_ready),.error(crypto_status)
        );
        assign lz_m_ready=crypto_s_ready;
        assign crypto_done_ready=active_pipeline && !crypto_seen;
        assign crypto_m_ready=enabled && state==PLAIN &&
            ((plain_seen && plain_error!=0) || write_byte_ready[1]);
        wire tensor_ready,tensor_result_valid,unified_ready,unified_result_valid;
        wire [63:0] tensor_result;
        wire [7:0] tensor_error;
        reg tensor_owned,tensor_owner_mm,last_tensor_was_mm;
        wire legacy_tensor_request=enabled && state==VECTOR;
        wire legacy_tensor_selected=tensor_owned ? !tensor_owner_mm :
            (legacy_tensor_request && (!mm_tensor_valid || last_tensor_was_mm));
        wire mm_tensor_selected=tensor_owned ? tensor_owner_mm :
            (mm_tensor_valid && (!legacy_tensor_request || !last_tensor_was_mm));
        wire unified_vector_valid=(legacy_tensor_selected && legacy_tensor_request) ||
            (mm_tensor_selected && mm_tensor_valid);
        wire unified_result_ready=tensor_owned && (tensor_owner_mm ?
            mm_tensor_result_ready : enabled && state==VECTOR_WAIT);
        wire mm_result_valid=unified_result_valid && tensor_owned && tensor_owner_mm;
        assign tensor_ready=unified_ready && legacy_tensor_selected;
        assign mm_tensor_ready=unified_ready && mm_tensor_selected;
        assign tensor_result_valid=unified_result_valid && tensor_owned && !tensor_owner_mm;
        wire [127:0] shifted_weights=weight_buffer >> {vector_index[1:0],5'b0};
        wire [127:0] tensor_weights=(tile_mode==1) ? weight_buffer :
            {96'b0,shifted_weights[31:0]};
        furnace_tensor8 unified_tensor (
            .clk(clk),.rst_n(rst_n),.vector_valid(unified_vector_valid),
            .vector_ready(unified_ready),.mode(mm_tensor_selected ? 2'b0 : tile_mode),
            .first(mm_tensor_selected ? 1'b1 : vector_index==0),
            .last(mm_tensor_selected ? 1'b1 : vector_index+1'b1==vector_count),
            .weight_data(mm_tensor_selected ? mm_tensor_weights : tensor_weights),
            .activation_data(mm_tensor_selected ? mm_tensor_activations : activation_buffer),
            .result_valid(unified_result_valid),.result_ready(unified_result_ready),
            .result(tensor_result),.error(tensor_error)
        );
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                tensor_owned<=0; tensor_owner_mm<=0; last_tensor_was_mm<=1;
                vision_active<=0; audio_active<=0;
            end else begin
                if (unified_vector_valid && unified_ready && !tensor_owned) begin
                    tensor_owned<=1; tensor_owner_mm<=mm_tensor_selected;
                end
                if (unified_result_valid && unified_result_ready) begin
                    tensor_owned<=0; last_tensor_was_mm<=tensor_owner_mm;
                end
                if (vision_token_valid && vision_token_ready) vision_active<=0;
                if (audio_token_valid && audio_token_ready) audio_active<=0;
                if (v_valid && v_ready) vision_active<=1;
                if (a_valid && a_ready) audio_active<=1;
            end
        end
        furnace_x2_vision #(.IN_WIDTH(IN_WIDTH),.IN_HEIGHT(IN_HEIGHT),
            .OUT_WIDTH(OUT_WIDTH),.OUT_HEIGHT(OUT_HEIGHT)) vision_frontend (
            .clk(clk),.rst_n(rst_n),.s_valid(v_valid && mm_enable && enabled),
            .s_ready(vision_input_ready),.s_data(v_pixel),.s_id(v_id),.s_last(v_last),
            .m_valid(vision_token_valid),.m_ready(vision_token_ready),
            .m_data(vision_token_data),.m_id(vision_token_id),.m_error(vision_token_error)
        );
        furnace_x2_audio #(.FFT_N(FFT_N)) audio_frontend (
            .clk(clk),.rst_n(rst_n),.s_valid(a_valid && mm_enable && enabled),
            .s_ready(audio_input_ready),.s_data(a_sample),.s_id(a_id),.s_last(a_last),
            .m_valid(audio_token_valid),.m_ready(audio_token_ready),
            .m_data(audio_token_data),.m_id(audio_token_id),.m_error(audio_token_error)
        );
        furnace_fusion_buffer #(.FUSION_DEPTH(FUSION_DEPTH)) fusion_buffer (
            .clk(clk),.rst_n(rst_n),.v_valid(fv_valid),.v_ready(fv_ready),.v_data(fv_data),
            .v_id(fv_id),.v_error(fv_error),.a_valid(fa_valid),.a_ready(fa_ready),.a_data(fa_data),
            .a_id(fa_id),.a_error(fa_error),.m_valid(fusion_valid),.m_ready(fusion_ready),
            .m_data(fusion_data),.m_id(fusion_id),.m_error(fusion_error)
        );
        furnace_x2_mm_control #(.FUSION_DEPTH(FUSION_DEPTH)) multimodal_control (
            .clk(clk),.rst_n(rst_n),.v_base(v_base),.a_base(a_base),.result_base(mm_result_base),
            .weights_valid(mm_weights_valid),.committed_weights(mm_weights),
            .v_valid(vision_token_valid),.v_ready(vision_token_ready),.v_data(vision_token_data),
            .v_id(vision_token_id),.v_error(vision_token_error),
            .a_valid(audio_token_valid),.a_ready(audio_token_ready),.a_data(audio_token_data),
            .a_id(audio_token_id),.a_error(audio_token_error),
            .fv_valid(fv_valid),.fv_ready(fv_ready),.fv_data(fv_data),.fv_id(fv_id),.fv_error(fv_error),
            .fa_valid(fa_valid),.fa_ready(fa_ready),.fa_data(fa_data),.fa_id(fa_id),.fa_error(fa_error),
            .f_valid(fusion_valid),.f_ready(fusion_ready),.f_data(fusion_data),
            .f_id(fusion_id),.f_error(fusion_error),
            .tensor_valid(mm_tensor_valid),.tensor_ready(mm_tensor_ready),
            .tensor_weights(mm_tensor_weights),.tensor_activations(mm_tensor_activations),
            .tensor_result_valid(mm_result_valid),.tensor_result_ready(mm_tensor_result_ready),
            .tensor_result(tensor_result),.tensor_error(tensor_error),
            .wr_valid(mm_wr_valid),.wr_ready(mm_wr_ready),.wr_address(mm_wr_address),.wr_length(mm_wr_length),
            .byte_valid(mm_byte_valid),.byte_ready(mm_byte_ready),.byte_data(mm_byte_data),.byte_last(mm_byte_last),
            .wr_done(mm_wr_done),.wr_done_ready(mm_wr_done_ready),.wr_error(mm_wr_error),
            .mm_valid(mm_valid),.mm_ready(mm_ready),.mm_id(mm_id),.mm_result(mm_result),.mm_error(mm_error),
            .report_pulse(mm_report),.busy(mm_controller_busy)
        );

        wire [31:0] descriptor_flags=descriptor[63:32];
        wire [31:0] descriptor_vectors=descriptor[287:256];
        wire [31:0] descriptor_weight_bytes=descriptor[255:224];
        wire [64:0] activation_allocation={33'b0,descriptor_vectors} << 4;
        wire [64:0] weight_allocation=({33'b0,descriptor_weight_bytes}+65'd15) &
            65'h1fffffffffffffff0;
        wire [64:0] frame_allocation=({33'b0,descriptor[127:96]}+65'd15) &
            65'h1fffffffffffffff0;
        wire [64:0] required_weights=(descriptor_flags[1:0]==1) ?
            ({33'b0,descriptor_vectors} << 4) : ({33'b0,descriptor_vectors} << 2);
        reg [64:0] range_start [0:5],range_end [0:5];
        reg descriptor_bad,completion_ok;
        integer a,b;
        always @* begin
            range_start[0]={33'b0,descriptor_address};
            range_start[1]={33'b0,descriptor[95:64]};
            range_start[2]={33'b0,descriptor[159:128]};
            range_start[3]={33'b0,descriptor[191:160]};
            range_start[4]={33'b0,descriptor[223:192]};
            range_start[5]={33'b0,descriptor[575:544]};
            range_end[0]=range_start[0]+65'd128;
            range_end[1]=range_start[1]+frame_allocation;
            range_end[2]=range_start[2]+weight_allocation;
            range_end[3]=range_start[3]+activation_allocation;
            range_end[4]=range_start[4]+65'd16;
            range_end[5]=range_start[5]+65'd16;
            descriptor_bad=descriptor[31:0]!=1 ||
                (descriptor_flags & 32'hfffffcfc)!=0 || descriptor_flags[1:0]==3 ||
                (descriptor_flags[9] && (descriptor_flags[1:0]!=0 ||
                    descriptor_vectors!=1 || descriptor_weight_bytes!=4)) ||
                descriptor[1023:576]!=0 || !key_valid ||
                descriptor[127:96]==0 || descriptor[127:96]>2*MAX_TILE_BYTES+256 ||
                descriptor_weight_bytes==0 || descriptor_weight_bytes>MAX_TILE_BYTES ||
                descriptor_vectors==0 || required_weights!={33'b0,descriptor_weight_bytes};
            completion_ok=range_start[5][3:0]==0 && range_end[5]<=65'h100000000;
            for (a=0;a<6;a=a+1) begin
                if (range_start[a][3:0]!=0 || range_end[a]>65'h100000000)
                    descriptor_bad=1;
                for (b=a+1;b<6;b=b+1)
                    if (range_start[a]<range_end[b] && range_start[b]<range_end[a])
                        descriptor_bad=1;
                if (a<5 && range_start[5]<range_end[a] && range_start[a]<range_end[5])
                    completion_ok=0;
            end
        end
        wire [31:0] weight_offset=(tile_mode==1) ? (vector_index << 4) :
            ((vector_index << 2) & 32'hfffffff0);
        wire [127:0] result_record={32'b0,tile_id,tile_result};
        wire [127:0] completion_record={32'b0,authenticated_bytes,tile_id,24'b0,status};
        always @* begin
            rd_command=0; wr_command=0; read_byte_ready=0; write_byte_valid=0;
            read_done_ready=0; write_done_ready=0; rd_address=0; rd_length=0;
            wr_address=0; wr_length=0; write_byte=0; write_last=0;
            if (rst_n && enabled) begin
                rd_address[0]=frame_address; rd_length[0]=frame_length;
                rd_address[3]=descriptor_address; rd_length[3]=128;
                wr_address[1]=plain_address; wr_length[1]=weight_length;
                wr_address[2]=result_address; wr_length[2]=16;
                wr_address[3]=completion_address; wr_length[3]=16;
                rd_address[2]=plain_address+weight_offset; rd_length[2]=16;
                case (state)
                    DESC_REQ:rd_command[3]=1;
                    DESC_DATA:read_byte_ready[3]=1;
                    DESC_WAIT:read_done_ready[3]=1;
                    FRAME_REQ:rd_command[0]=1;
                    PLAIN_START:wr_command[1]=1;
                    PLAIN:begin
                        write_byte_valid[1]=crypto_m_valid && !plain_seen;
                        write_byte[1]=crypto_m_data; write_last[1]=crypto_m_last;
                        write_done_ready[1]=!plain_seen;
                    end
                    WEIGHT_REQ:rd_command[2]=1;
                    WEIGHT_DATA:read_byte_ready[2]=1;
                    WEIGHT_WAIT:read_done_ready[2]=1;
                    ACT_REQ:begin
                        rd_address[2]=activation_address+(vector_index << 4); rd_command[2]=1;
                    end
                    ACT_DATA:read_byte_ready[2]=1;
                    ACT_WAIT:read_done_ready[2]=1;
                    RESULT_REQ:wr_command[2]=1;
                    RESULT_DATA:begin
                        write_byte_valid[2]=1; write_byte[2]=result_record[{byte_index[3:0],3'b0}+:8];
                        write_last[2]=byte_index==15;
                    end
                    RESULT_WAIT:write_done_ready[2]=1;
                    CMP_REQ:wr_command[3]=completion_safe;
                    CMP_DATA:begin
                        write_byte_valid[3]=1;
                        write_byte[3]=completion_record[{byte_index[3:0],3'b0}+:8];
                        write_last[3]=byte_index==15;
                    end
                    CMP_WAIT:write_done_ready[3]=1;
                    default:begin end
                endcase
                if (active_pipeline) begin
                    read_byte_ready[0]=lz_seen || lz_s_ready;
                    read_done_ready[0]=!frame_read_seen;
                end
            end
        end
        integer n;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                enabled<=0; state<=IDLE; descriptor<=0; descriptor_address<=0;
                frame_address<=0; frame_length<=0; plain_address<=0;
                activation_address<=0; result_address<=0; weight_length<=0;
                vector_count<=0; tile_id<=0; completion_address<=0;
                authenticated_bytes<=0; vector_index<=0; tile_nonce<=0;
                tile_tag<=0; tile_aad<=0; tile_result<=0; tile_mode<=0;
                request_irq<=0; completion_safe<=0; status<=0; byte_index<=0;
                frame_read_seen<=0; crypto_seen<=0; plain_seen<=0; lz_seen<=0;
                frame_read_error<=0; crypto_error<=0; plain_error<=0;
                weight_buffer<=0; activation_buffer<=0;
                mm_weight_commit<=0; mm_weights_valid<=0; mm_weights<=0;
                candidate_weights<=0; candidate_bytes<=0;
            end else begin
                enabled<=1;
                if (mm_weight_commit && crypto_m_valid && crypto_m_ready && candidate_bytes<4) begin
                    candidate_weights[8*candidate_bytes+:8]<=crypto_m_data;
                    candidate_bytes<=candidate_bytes+1'b1;
                end
                if (enabled && state==RETIRE && status==0 && mm_weight_commit && candidate_bytes==4) begin
                    mm_weights<=candidate_weights; mm_weights_valid<=1;
                end
                if (key_changed) begin mm_weights<=0; mm_weights_valid<=0; end
                if (active_pipeline) begin
                    if (read_done[0] && read_done_ready[0]) begin
                        frame_read_seen<=1; frame_read_error<=read_error[0];
                    end
                    if (lz_done && lz_done_ready) lz_seen<=1;
                    if (crypto_done && crypto_done_ready) begin
                        crypto_seen<=1; crypto_error<=crypto_status;
                    end
                    if (write_done[1] && write_done_ready[1]) begin
                        plain_seen<=1; plain_error<=write_error[1];
                    end
                end
                case (state)
                    IDLE:if (enabled && run_enable && queued) state<=CLEAR;
                    CLEAR:begin
                        descriptor<=0; byte_index<=0; status<=0; tile_id<=0;
                        request_irq<=0; authenticated_bytes<=0; completion_safe<=0;
                        frame_read_seen<=0; crypto_seen<=0; plain_seen<=0; lz_seen<=0;
                        frame_read_error<=0; crypto_error<=0; plain_error<=0; vector_index<=0;
                        mm_weight_commit<=0; candidate_weights<=0; candidate_bytes<=0;
                        if (descriptor_limit>34'h100000000) begin status<=1; state<=RETIRE; end
                        else begin descriptor_address<=next_descriptor_address[31:0]; state<=DESC_REQ; end
                    end
                    DESC_REQ:if (rd_ready[3]) begin byte_index<=0; state<=DESC_DATA; end
                    DESC_DATA:begin
                        if (read_byte_valid[3]) begin
                            descriptor[{byte_index[6:0],3'b0}+:8]<=read_byte[3];
                            if (byte_index==127) state<=DESC_WAIT;
                            else byte_index<=byte_index+1'b1;
                        end
                        if (read_done[3] && read_error[3]!=0) state<=DESC_WAIT;
                    end
                    DESC_WAIT:if (read_done[3]) begin
                        if (read_error[3]!=0) begin status<=5; state<=RETIRE; end
                        else state<=VALIDATE;
                    end
                    VALIDATE:begin
                        frame_address<=descriptor[95:64]; frame_length<=descriptor[127:96];
                        plain_address<=descriptor[159:128]; activation_address<=descriptor[191:160];
                        result_address<=descriptor[223:192]; weight_length<=descriptor[255:224];
                        vector_count<=descriptor[287:256]; tile_id<=descriptor[319:288];
                        tile_mode<=descriptor_flags[1:0]; request_irq<=descriptor_flags[8];
                        mm_weight_commit<=descriptor_flags[9];
                        completion_address<=descriptor[575:544]; tile_aad<=descriptor[415:0];
                        completion_safe<=completion_ok;
                        for (n=0;n<12;n=n+1) tile_nonce[95-8*n-:8]<=descriptor[320+8*n+:8];
                        for (n=0;n<16;n=n+1) tile_tag[127-8*n-:8]<=descriptor[416+8*n+:8];
                        if (descriptor_bad) begin
                            status<=1;
                            if (completion_ok) state<=CMP_REQ; else state<=RETIRE;
                        end else state<=START_PIPE;
                    end
                    START_PIPE:if (start_engines) state<=FRAME_REQ;
                    FRAME_REQ:if (rd_ready[0]) state<=INGEST;
                    INGEST:begin
                        if (frame_read_seen && frame_read_error!=0) begin status<=5; state<=ABORT_PIPE; end
                        else if (frame_read_seen && crypto_seen) begin
                            if (crypto_error!=0) status<=crypto_error; else status<=6;
                            state<=CMP_REQ;
                        end else if (frame_read_seen && crypto_m_valid) begin
                            authenticated_bytes<=weight_length; state<=PLAIN_START;
                        end
                    end
                    PLAIN_START:if (wr_ready[1]) state<=PLAIN;
                    PLAIN:if (plain_seen && crypto_seen) begin
                        if (plain_error!=0) begin status<=5; state<=CMP_REQ; end
                        else if (crypto_error!=0) begin status<=crypto_error; state<=CMP_REQ; end
                        else begin vector_index<=0; state<=WEIGHT_REQ; end
                    end
                    WEIGHT_REQ:if (rd_ready[2]) begin byte_index<=0; weight_buffer<=0; state<=WEIGHT_DATA; end
                    WEIGHT_DATA:begin
                        if (read_byte_valid[2]) begin
                            weight_buffer[{byte_index[3:0],3'b0}+:8]<=read_byte[2];
                            if (byte_index==15) state<=WEIGHT_WAIT; else byte_index<=byte_index+1'b1;
                        end
                        if (read_done[2] && read_error[2]!=0) state<=WEIGHT_WAIT;
                    end
                    WEIGHT_WAIT:if (read_done[2]) begin
                        if (read_error[2]!=0) begin status<=5; state<=CMP_REQ; end
                        else state<=ACT_REQ;
                    end
                    ACT_REQ:if (rd_ready[2]) begin byte_index<=0; activation_buffer<=0; state<=ACT_DATA; end
                    ACT_DATA:begin
                        if (read_byte_valid[2]) begin
                            activation_buffer[{byte_index[3:0],3'b0}+:8]<=read_byte[2];
                            if (byte_index==15) state<=ACT_WAIT; else byte_index<=byte_index+1'b1;
                        end
                        if (read_done[2] && read_error[2]!=0) state<=ACT_WAIT;
                    end
                    ACT_WAIT:if (read_done[2]) begin
                        if (read_error[2]!=0) begin status<=5; state<=CMP_REQ; end else state<=VECTOR;
                    end
                    VECTOR:if (tensor_ready) state<=VECTOR_WAIT;
                    VECTOR_WAIT:begin
                        if (tensor_result_valid) begin
                            if (tensor_error!=0 || vector_index+1'b1!=vector_count) begin
                                status<=6; state<=CMP_REQ;
                            end else begin tile_result<=tensor_result; state<=RESULT_REQ; end
                        end else if (tensor_ready && vector_index+1'b1!=vector_count) begin
                            vector_index<=vector_index+1'b1; state<=WEIGHT_REQ;
                        end
                    end
                    RESULT_REQ:if (wr_ready[2]) begin byte_index<=0; state<=RESULT_DATA; end
                    RESULT_DATA:if (write_byte_ready[2]) begin
                        if (byte_index==15) state<=RESULT_WAIT; else byte_index<=byte_index+1'b1;
                    end
                    RESULT_WAIT:if (write_done[2]) begin
                        if (write_error[2]!=0) status<=5;
                        state<=CMP_REQ;
                    end
                    CMP_REQ:begin
                        if (!completion_safe) state<=RETIRE;
                        else if (wr_ready[3]) begin byte_index<=0; state<=CMP_DATA; end
                    end
                    CMP_DATA:if (write_byte_ready[3]) begin
                        if (byte_index==15) state<=CMP_WAIT; else byte_index<=byte_index+1'b1;
                    end
                    CMP_WAIT:if (write_done[3]) begin
                        if (write_error[3]!=0) status<=5;
                        state<=RETIRE;
                    end
                    ABORT_PIPE:state<=CMP_REQ;
                    RETIRE:state<=IDLE;
                    default:begin status<=1; state<=RETIRE; end
                endcase
            end
        end
    end endgenerate
endmodule
