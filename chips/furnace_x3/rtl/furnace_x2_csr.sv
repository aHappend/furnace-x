module furnace_x2_csr #(
    parameter integer RING_DEPTH=8,
    parameter integer FUSION_DEPTH=4
) (
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
    input wire busy,queued,ring_full,
    input wire [31:0] head,tail,
    input wire tail_error,
    input wire completion_valid,
    input wire [7:0] completion_error,
    input wire [31:0] completion_tile_id,
    input wire completion_irq_requested,
    output wire enable,key_valid,
    output wire [127:0] key,
    output wire [31:0] ring_base,
    output wire tail_valid,
    output wire [31:0] tail_value,
    output wire irq,
    input wire mm_busy,fusion_busy,vision_busy,audio_busy,weights_valid,
    input wire mm_report,
    input wire [15:0] mm_report_id,
    input wire [7:0] mm_report_error,
    output wire mm_enable,
    output wire [31:0] v_base,a_base,result_base,
    output wire [19:0] qos,
    output wire key_changed
);
    generate if (RING_DEPTH<1 || RING_DEPTH>16 || FUSION_DEPTH<1 || FUSION_DEPTH>16) begin: bad_parameter
        initial $fatal(1,"PARAMETER ERROR: RING_DEPTH and FUSION_DEPTH must be 1..16");
        assign s_axil_awready=0; assign s_axil_wready=0;
        assign s_axil_bresp=0; assign s_axil_bvalid=0;
        assign s_axil_arready=0; assign s_axil_rdata=0;
        assign s_axil_rresp=0; assign s_axil_rvalid=0;
        assign enable=0; assign key_valid=0; assign key=0;
        assign ring_base=0; assign tail_valid=0; assign tail_value=0; assign irq=0;
        assign mm_enable=0; assign v_base=0; assign a_base=0; assign result_base=0;
        assign qos=0; assign key_changed=0;
    end else begin: registers
        reg enabled,run_enable,committed,fault;
        reg aw_held,w_held,b_valid,r_valid;
        reg [15:0] aw_address;
        reg [31:0] w_data,base,read_data,last_error,last_tile,count;
        reg [3:0] w_strobe;
        reg [1:0] b_response,r_response,irq_status,irq_enable;
        reg [127:0] key_shadow,key_committed;
        reg [15:0] key_written;
        reg multimodal_enable,multimodal_fault;
        reg [31:0] vision_base,audio_base,mm_result_base,mm_count;
        reg [15:0] mm_last_id;
        reg [7:0] mm_last_error;
        reg [19:0] qos_value;
        wire write_execute=enabled && aw_held && w_held && !b_valid;
        wire locked=busy || queued || mm_busy;
        localparam [32:0] BUFFER_BYTES=16*FUSION_DEPTH;
        function automatic buffers_legal(input [31:0] vb,ab,rb);
            reg [32:0] ve,ae,re;
            begin
                ve={1'b0,vb}+BUFFER_BYTES; ae={1'b0,ab}+BUFFER_BYTES;
                re={1'b0,rb}+BUFFER_BYTES;
                buffers_legal=vb[3:0]==0 && ab[3:0]==0 && rb[3:0]==0 &&
                    ve<=33'h100000000 && ae<=33'h100000000 && re<=33'h100000000 &&
                    !({1'b0,vb}<ae && {1'b0,ab}<ve) &&
                    !({1'b0,vb}<re && {1'b0,rb}<ve) &&
                    !({1'b0,ab}<re && {1'b0,rb}<ae);
            end
        endfunction
        wire buffers_valid=buffers_legal(vision_base,audio_base,mm_result_base);
        wire [31:0] write_mask={{8{w_strobe[3]}},{8{w_strobe[2]}},
            {8{w_strobe[1]}},{8{w_strobe[0]}}};
        wire [31:0] strobed=w_data & write_mask;
        reg [31:0] old_value,merged,read_value;
        reg write_fault,read_fault;
        integer j;
        always @* begin
            old_value=0;
            case (aw_address)
                16'h004:old_value={31'b0,run_enable};
                16'h010:old_value={30'b0,irq_enable};
                16'h018:old_value=base;
                16'h024:old_value=tail;
                16'h1004:old_value={31'b0,multimodal_enable};
                16'h1010:old_value=vision_base;
                16'h1014:old_value=audio_base;
                16'h1018:old_value=mm_result_base;
                16'h1030:old_value={12'b0,qos_value};
                default:old_value=0;
            endcase
            merged=(old_value & ~write_mask) | strobed;
            write_fault=0;
            if (aw_address[1:0]!=0) write_fault=1;
            else case (aw_address)
                16'h004:if (merged[31:1]!=0) write_fault=1;
                16'h00c:if (strobed[31:2]!=0) write_fault=1;
                16'h010:if (merged[31:2]!=0) write_fault=1;
                16'h018:if (locked || merged[6:0]!=0) write_fault=1;
                16'h024:if (tail_error) write_fault=1;
                16'h030,16'h034,16'h038,16'h03c:if (locked) write_fault=1;
                16'h040:begin
                    if (locked || strobed[31:2]!=0 || strobed[1:0]==3 ||
                        (strobed[0] && key_written!=16'hffff)) write_fault=1;
                end
                16'h1004:if (locked || strobed[31:2]!=0 ||
                    (merged[0] && !buffers_valid)) write_fault=1;
                16'h1010,16'h1014,16'h1018:begin
                    if (locked || merged[3:0]!=0 ||
                        (multimodal_enable && !buffers_legal(
                            aw_address==16'h1010 ? merged : vision_base,
                            aw_address==16'h1014 ? merged : audio_base,
                            aw_address==16'h1018 ? merged : mm_result_base))) write_fault=1;
                end
                16'h1030:if (locked || merged[31:20]!=0) write_fault=1;
                default:write_fault=1;
            endcase
        end
        always @* begin
            read_value=0; read_fault=0;
            if (s_axil_araddr[1:0]!=0) read_fault=1;
            else case (s_axil_araddr)
                16'h000:read_value=32'h01000000;
                16'h004:read_value={31'b0,run_enable};
                16'h008:read_value={28'b0,fault,ring_full,committed,busy};
                16'h00c:read_value={30'b0,irq_status};
                16'h010:read_value={30'b0,irq_enable};
                16'h014:read_value=last_error;
                16'h018:read_value=base;
                16'h01c:read_value=RING_DEPTH;
                16'h020:read_value=head;
                16'h024:read_value=tail;
                16'h028:read_value=last_tile;
                16'h02c:read_value=count;
                16'h030,16'h034,16'h038,16'h03c,16'h040:read_value=0;
                16'h1000:read_value=32'h02000000;
                16'h1004:read_value={31'b0,multimodal_enable};
                16'h1008:read_value={27'b0,fusion_busy,audio_busy,vision_busy,
                    multimodal_fault,weights_valid};
                16'h1010:read_value=vision_base;
                16'h1014:read_value=audio_base;
                16'h1018:read_value=mm_result_base;
                16'h101c:read_value=FUSION_DEPTH;
                16'h1020:read_value=mm_count;
                16'h1024:read_value={24'b0,mm_last_error};
                16'h1028:read_value={16'b0,mm_last_id};
                16'h1030:read_value={12'b0,qos_value};
                default:read_fault=1;
            endcase
        end
        assign s_axil_awready=rst_n && enabled && !aw_held && !b_valid;
        assign s_axil_wready=rst_n && enabled && !w_held && !b_valid;
        assign s_axil_bvalid=rst_n && enabled && b_valid;
        assign s_axil_bresp=(rst_n && enabled) ? b_response : 2'b0;
        assign s_axil_arready=rst_n && enabled && !r_valid;
        assign s_axil_rvalid=rst_n && enabled && r_valid;
        assign s_axil_rdata=(rst_n && enabled) ? read_data : 32'b0;
        assign s_axil_rresp=(rst_n && enabled) ? r_response : 2'b0;
        assign enable=rst_n && enabled && run_enable;
        assign key_valid=rst_n && enabled && committed;
        assign key=(rst_n && enabled) ? key_committed : 128'b0;
        assign ring_base=(rst_n && enabled) ? base : 32'b0;
        assign tail_value=(rst_n && enabled) ? merged : 32'b0;
        assign tail_valid=rst_n && write_execute && aw_address==16'h024 && !write_fault;
        assign irq=rst_n && enabled && ((|(irq_status & irq_enable)) || multimodal_fault);
        assign mm_enable=rst_n && enabled && multimodal_enable;
        assign v_base=(rst_n && enabled) ? vision_base : 32'b0;
        assign a_base=(rst_n && enabled) ? audio_base : 32'b0;
        assign result_base=(rst_n && enabled) ? mm_result_base : 32'b0;
        assign qos=(rst_n && enabled) ? qos_value : 20'b0;
        assign key_changed=rst_n && write_execute && !write_fault &&
            aw_address==16'h0040 && (|strobed[1:0]);
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                enabled<=0; run_enable<=0; committed<=0; fault<=0;
                aw_held<=0; w_held<=0; b_valid<=0; r_valid<=0;
                aw_address<=0; w_data<=0; base<=0; read_data<=0;
                last_error<=0; last_tile<=0; count<=0; w_strobe<=0;
                b_response<=0; r_response<=0; irq_status<=0; irq_enable<=0;
                key_shadow<=0; key_committed<=0; key_written<=0;
                multimodal_enable<=0; multimodal_fault<=0; vision_base<=0;
                audio_base<=0; mm_result_base<=0; mm_count<=0;
                mm_last_id<=0; mm_last_error<=0; qos_value<=20'hf4c8f;
            end else begin
                enabled<=1;
                if (s_axil_awvalid && s_axil_awready) begin
                    aw_held<=1; aw_address<=s_axil_awaddr;
                end
                if (s_axil_wvalid && s_axil_wready) begin
                    w_held<=1; w_data<=s_axil_wdata; w_strobe<=s_axil_wstrb;
                end
                if (b_valid && s_axil_bready) b_valid<=0;
                if (r_valid && s_axil_rready) r_valid<=0;
                if (s_axil_arvalid && s_axil_arready) begin
                    read_data<=read_value; r_valid<=1;
                    if (read_fault) r_response<=2'b10; else r_response<=0;
                end
                if (write_execute) begin
                    aw_held<=0; w_held<=0; b_valid<=1;
                    if (write_fault) b_response<=2'b10;
                    else begin
                        b_response<=0;
                        case (aw_address)
                            16'h004:run_enable<=merged[0];
                            16'h00c:irq_status<=irq_status & ~strobed[1:0];
                            16'h010:irq_enable<=merged[1:0];
                            16'h018:base<=merged;
                            16'h030,16'h034,16'h038,16'h03c:begin
                                for (j=0;j<4;j=j+1)
                                    if (w_strobe[j]) begin
                                        key_shadow[{aw_address[3:2],5'b0}+8*j+:8]
                                            <=w_data[8*j+:8];
                                        key_written[{aw_address[3:2],2'b0}+j]<=1;
                                    end
                            end
                            16'h040:begin
                                if (strobed[1]) begin
                                    committed<=0; key_written<=0;
                                    key_shadow<=0; key_committed<=0;
                                end else if (strobed[0]) begin
                                    committed<=1; key_written<=0;
                                    for (j=0;j<16;j=j+1)
                                        key_committed[127-8*j-:8]<=key_shadow[8*j+:8];
                                end
                            end
                            16'h1004:begin
                                multimodal_enable<=merged[0];
                                if (strobed[1]) multimodal_fault<=0;
                            end
                            16'h1010:vision_base<=merged;
                            16'h1014:audio_base<=merged;
                            16'h1018:mm_result_base<=merged;
                            16'h1030:qos_value<=merged[19:0];
                            default:begin end
                        endcase
                    end
                end
                if (completion_valid) begin
                    count<=count+1'b1; last_tile<=completion_tile_id;
                    last_error<={24'b0,completion_error};
                    if (completion_error!=0) begin fault<=1; irq_status[1]<=1; end
                    else if (completion_irq_requested) irq_status[0]<=1;
                end
                if (mm_report) begin
                    mm_count<=mm_count+1'b1; mm_last_id<=mm_report_id;
                    mm_last_error<=mm_report_error;
                    if (mm_report_error!=0) multimodal_fault<=1;
                end
            end
        end
    end endgenerate
endmodule
