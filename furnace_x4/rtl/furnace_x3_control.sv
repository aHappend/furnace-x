module furnace_x3_control (
    input wire clk, rst_n,
    input wire req_valid,
    output wire req_ready,
    input wire req_host, req_write, req_instr,
    input wire [63:0] req_addr, req_wdata,
    input wire [7:0] req_wstrb,
    input wire [1:0] req_size,
    output wire rsp_valid,
    input wire rsp_ready,
    output wire [63:0] rsp_rdata,
    output wire rsp_error,
    input wire cpu_halted, cpu_trap_valid, cpu_bus_error,
    input wire [63:0] cpu_trap_cause, cpu_trap_pc,
    output wire cpu_run, cpu_reset,
    output wire fw_mode,
    input wire legacy_v_transfer, legacy_v_last,
    input wire legacy_a_transfer, legacy_a_last,
    input wire legacy_stream_activity,
    output wire fw_v_valid,
    input wire fw_v_ready,
    output wire [7:0] fw_v_pixel,
    output wire [15:0] fw_v_id,
    output wire fw_v_last,
    output wire fw_a_valid,
    input wire fw_a_ready,
    output wire signed [15:0] fw_a_sample,
    output wire [15:0] fw_a_id,
    output wire fw_a_last,
    output wire dma_cmd_valid,
    input wire dma_cmd_ready, dma_busy,
    output wire [31:0] dma_src, dma_dst, dma_bytes,
    input wire dma_done_valid,
    output wire dma_done_ready,
    input wire [7:0] dma_done_error,
    input wire semaphore_overflow_event,
    output wire clear_semaphore_overflow,
    input wire [2:0] leaf_protocol_error,
    output wire [2:0] leaf_req_valid,
    input wire [2:0] leaf_req_ready,
    output wire leaf_req_write,
    output wire [7:0] leaf_req_addr,
    output wire [31:0] leaf_req_wdata,
    output wire [3:0] leaf_req_wstrb,
    input wire [2:0] leaf_rsp_valid,
    output wire [2:0] leaf_rsp_ready,
    input wire [2:0][31:0] leaf_rsp_rdata,
    input wire [2:0] leaf_rsp_error,
    output wire [1:0] memory_req_valid,
    input wire [1:0] memory_req_ready,
    output wire memory_req_host, memory_req_write, memory_req_instr,
    output wire [63:0] memory_req_addr, memory_req_wdata,
    output wire [7:0] memory_req_wstrb,
    output wire [1:0] memory_req_size,
    input wire [1:0] memory_rsp_valid,
    output wire [1:0] memory_rsp_ready,
    input wire [1:0][63:0] memory_rsp_rdata,
    input wire [1:0] memory_rsp_error,
    output wire [15:0] p_axil_awaddr,
    output wire [2:0] p_axil_awprot,
    output wire p_axil_awvalid,
    input wire p_axil_awready,
    output wire [31:0] p_axil_wdata,
    output wire [3:0] p_axil_wstrb,
    output wire p_axil_wvalid,
    input wire p_axil_wready,
    input wire [1:0] p_axil_bresp,
    input wire p_axil_bvalid,
    output wire p_axil_bready,
    output wire [15:0] p_axil_araddr,
    output wire [2:0] p_axil_arprot,
    output wire p_axil_arvalid,
    input wire p_axil_arready,
    input wire [31:0] p_axil_rdata,
    input wire [1:0] p_axil_rresp,
    input wire p_axil_rvalid,
    output wire p_axil_rready,
    output wire protocol_error
);
    localparam [3:0] IDLE=0, EXECUTE=1, RESPONSE=2, LEAF_REQUEST=3,
        LEAF_RESPONSE=4, MEMORY_REQUEST=5, MEMORY_RESPONSE=6,
        PARENT_WRITE=7, PARENT_B=8, PARENT_READ=9, PARENT_R=10;
    reg enabled;
    reg [3:0] state;
    reg host_q, write_q, instruction_q, response_error;
    reg [63:0] address_q, data_q, response_data;
    reg [7:0] strobe_q;
    reg [1:0] size_q, leaf_select;
    reg memory_select;
    reg run_q, reset_pulse, mode_q;
    reg [3:0] errors;
    reg [63:0] last_cause, last_pc;
    reg [31:0] source_q, destination_q, bytes_q;
    reg dma_done_q;
    reg [7:0] dma_error_q;
    reg vision_full, audio_full;
    reg [16:0] vision_meta, audio_meta, vision_slot_meta, audio_slot_meta;
    reg [7:0] vision_pixel;
    reg [15:0] audio_sample;
    reg vision_packet, audio_packet;
    reg parent_aw_sent, parent_w_sent;
    reg [15:0] parent_read_address;
    reg mode_probe, probe_activity;
    reg [1:0] probe_index;
    reg [31:0] probe_head;
    reg protocol_pulse;
    wire active=rst_n && enabled;
    wire [31:0] write_mask={{8{strobe_q[3]}},{8{strobe_q[2]}},
        {8{strobe_q[1]}},{8{strobe_q[0]}}};
    wire [31:0] strobed=data_q[31:0] & write_mask;
    wire mmio_shape_ok=!instruction_q && size_q==2 &&
        address_q[1:0]==0 && (!write_q || strobe_q[7:4]==0);
    wire in_host_local=host_q &&
        address_q>=64'h4000 && address_q<64'hc000;
    wire in_cpu_local=!host_q &&
        ((address_q>=64'h10000 && address_q<64'h14000) ||
         (address_q>=64'h20000 && address_q<64'h24000));
    wire in_cpu_ddr=!host_q && address_q>=64'h80000000 &&
        address_q<=64'hffffffff;
    wire in_registers=address_q<64'h3000;
    wire own_register=address_q>=64'h2000 && address_q<64'h2300;
    wire execute_register=active && state==EXECUTE && mmio_shape_ok && own_register;
    wire vision_capacity=!vision_full || fw_v_ready;
    wire audio_capacity=!audio_full || fw_a_ready;
    wire [31:0] merged_run=({31'b0,run_q} & ~write_mask) | strobed;
    wire [31:0] merged_mode=({31'b0,mode_q} & ~write_mask) | strobed;
    wire [31:0] merged_vmeta=({15'b0,vision_meta} & ~write_mask) | strobed;
    wire [31:0] merged_ameta=({15'b0,audio_meta} & ~write_mask) | strobed;
    wire dma_start=execute_register && write_q && address_q==64'h204c &&
        strobed==1 && !dma_busy && dma_cmd_ready;
    reg register_fault, register_wait, start_mode_probe;
    reg [31:0] register_data;
    reg [3:0] clear_errors;
    reg clear_dma;

    assign req_ready=active && state==IDLE;
    assign rsp_valid=active && state==RESPONSE;
    assign rsp_rdata=rsp_valid ? response_data : 64'b0;
    assign rsp_error=rsp_valid && response_error;
    assign cpu_run=active && run_q;
    assign cpu_reset=active && reset_pulse;
    assign fw_mode=active && mode_q;
    assign protocol_error=active && errors[0];
    assign dma_cmd_valid=dma_start;
    assign dma_src=active ? source_q : 32'b0;
    assign dma_dst=active ? destination_q : 32'b0;
    assign dma_bytes=active ? bytes_q : 32'b0;
    assign dma_done_ready=active;
    assign clear_semaphore_overflow=execute_register && !register_fault &&
        write_q && address_q==64'h2018 && strobed[1];
    assign fw_v_valid=active && mode_q && vision_full;
    assign fw_v_pixel=fw_v_valid ? vision_pixel : 8'b0;
    assign fw_v_id=fw_v_valid ? vision_slot_meta[15:0] : 16'b0;
    assign fw_v_last=fw_v_valid && vision_slot_meta[16];
    assign fw_a_valid=active && mode_q && audio_full;
    assign fw_a_sample=fw_a_valid ? audio_sample : 16'b0;
    assign fw_a_id=fw_a_valid ? audio_slot_meta[15:0] : 16'b0;
    assign fw_a_last=fw_a_valid && audio_slot_meta[16];

    assign leaf_req_valid=active && state==LEAF_REQUEST ?
        (3'b001 << leaf_select) : 3'b0;
    assign leaf_req_write=active && state==LEAF_REQUEST && write_q;
    assign leaf_req_addr=active && state==LEAF_REQUEST ? address_q[7:0] : 8'b0;
    assign leaf_req_wdata=active && state==LEAF_REQUEST ? data_q[31:0] : 32'b0;
    assign leaf_req_wstrb=active && state==LEAF_REQUEST ? strobe_q[3:0] : 4'b0;
    assign leaf_rsp_ready=active && state==LEAF_RESPONSE ?
        (3'b001 << leaf_select) : 3'b0;
    assign memory_req_valid=active && state==MEMORY_REQUEST ?
        (2'b01 << memory_select) : 2'b0;
    assign memory_req_host=active && state==MEMORY_REQUEST && host_q;
    assign memory_req_write=active && state==MEMORY_REQUEST && write_q;
    assign memory_req_instr=active && state==MEMORY_REQUEST && instruction_q;
    assign memory_req_addr=active && state==MEMORY_REQUEST ? address_q : 64'b0;
    assign memory_req_wdata=active && state==MEMORY_REQUEST ? data_q : 64'b0;
    assign memory_req_wstrb=active && state==MEMORY_REQUEST ? strobe_q : 8'b0;
    assign memory_req_size=active && state==MEMORY_REQUEST ? size_q : 2'b0;
    assign memory_rsp_ready=active && state==MEMORY_RESPONSE ?
        (2'b01 << memory_select) : 2'b0;
    assign p_axil_awvalid=active && state==PARENT_WRITE && !parent_aw_sent;
    assign p_axil_awaddr=p_axil_awvalid ? address_q[15:0] : 16'b0;
    assign p_axil_awprot=0;
    assign p_axil_wvalid=active && state==PARENT_WRITE && !parent_w_sent;
    assign p_axil_wdata=p_axil_wvalid ? data_q[31:0] : 32'b0;
    assign p_axil_wstrb=p_axil_wvalid ? strobe_q[3:0] : 4'b0;
    assign p_axil_bready=active && state==PARENT_B;
    assign p_axil_arvalid=active && state==PARENT_READ;
    assign p_axil_araddr=p_axil_arvalid ? parent_read_address : 16'b0;
    assign p_axil_arprot=0;
    assign p_axil_rready=active && state==PARENT_R;

    always @* begin
        register_data=0; register_fault=0; register_wait=0;
        start_mode_probe=0; clear_errors=0; clear_dma=0;
        case (address_q[15:0])
            16'h2000: begin register_data=32'h03000000; if (write_q) register_fault=1; end
            16'h2004: begin
                register_data={31'b0,run_q};
                if (write_q && (merged_run[31:2]!=0 ||
                    (merged_run[0] && !mode_q) || (strobed[1] && !cpu_halted)))
                    register_fault=1;
            end
            16'h2008: begin
                register_data={30'b0,cpu_halted,!cpu_halted};
                if (write_q) register_fault=1;
            end
            16'h200c: begin
                register_data={last_cause[63],last_cause[30:0]};
                if (write_q) register_fault=1;
            end
            16'h2010: begin register_data=last_pc[31:0]; if (write_q) register_fault=1; end
            16'h2014: begin register_data=last_pc[63:32]; if (write_q) register_fault=1; end
            16'h2018: begin
                register_data={28'b0,errors};
                if (write_q) begin
                    if (strobed[31:4]!=0) register_fault=1;
                    else clear_errors=strobed[3:0];
                end
            end
            16'h2020: begin
                register_data={31'b0,mode_q};
                if (write_q) begin
                    if (merged_mode[31:1]!=0 || (mode_q && !merged_mode[0]))
                        register_fault=1;
                    else if (!mode_q && merged_mode[0]) begin
                        if (!cpu_halted || vision_packet || audio_packet ||
                            legacy_stream_activity) register_fault=1;
                        else start_mode_probe=1;
                    end
                end
            end
            16'h2040: begin register_data=source_q; if (write_q && dma_busy) register_fault=1; end
            16'h2044: begin register_data=destination_q; if (write_q && dma_busy) register_fault=1; end
            16'h2048: begin register_data=bytes_q; if (write_q && dma_busy) register_fault=1; end
            16'h204c: begin
                if (!write_q || strobed[31:1]!=0 ||
                    (strobed[0] && (dma_busy || !dma_cmd_ready))) register_fault=1;
            end
            16'h2050: begin
                register_data={16'b0,dma_error_q,6'b0,dma_done_q,dma_busy};
                if (write_q) register_fault=1;
            end
            16'h2054: begin
                if (!write_q || strobed[31:2]!=0) register_fault=1;
                else clear_dma=|strobed[1:0];
            end
            16'h2200: begin
                if (!write_q || !mode_q || strobed[31:8]!=0) register_fault=1;
                else if (strobe_q!=0 && !vision_capacity) register_wait=1;
            end
            16'h2204: begin
                if (!write_q || !mode_q || strobed[31:16]!=0) register_fault=1;
                else if (strobe_q!=0 && !audio_capacity) register_wait=1;
            end
            16'h2210: begin
                register_data={15'b0,vision_meta};
                if (write_q && merged_vmeta[31:17]!=0) register_fault=1;
            end
            16'h2214: begin
                register_data={15'b0,audio_meta};
                if (write_q && merged_ameta[31:17]!=0) register_fault=1;
            end
            16'h2220: begin
                register_data={30'b0,audio_full,vision_full};
                if (write_q) register_fault=1;
            end
            default: register_fault=1;
        endcase
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enabled<=0; state<=IDLE; host_q<=0; write_q<=0; instruction_q<=0;
            response_error<=0; address_q<=0; data_q<=0; response_data<=0;
            strobe_q<=0; size_q<=0; leaf_select<=0; memory_select<=0;
            run_q<=0; reset_pulse<=0; mode_q<=0; errors<=0;
            last_cause<=0; last_pc<=0; source_q<=0; destination_q<=0; bytes_q<=0;
            dma_done_q<=0; dma_error_q<=0;
            vision_full<=0; audio_full<=0; vision_meta<=0; audio_meta<=0;
            vision_slot_meta<=0; audio_slot_meta<=0; vision_pixel<=0; audio_sample<=0;
            vision_packet<=0; audio_packet<=0; parent_aw_sent<=0; parent_w_sent<=0;
            parent_read_address<=0; mode_probe<=0; probe_activity<=0;
            probe_index<=0; probe_head<=0; protocol_pulse<=0;
        end else begin
            enabled<=1; reset_pulse<=0; protocol_pulse<=0;
            if (legacy_v_transfer) vision_packet<=!legacy_v_last;
            if (legacy_a_transfer) audio_packet<=!legacy_a_last;
            if (mode_probe && legacy_stream_activity) probe_activity<=1;
            if (fw_v_valid && fw_v_ready) vision_full<=0;
            if (fw_a_valid && fw_a_ready) audio_full<=0;
            if (cpu_trap_valid) begin
                last_cause<=cpu_trap_cause; last_pc<=cpu_trap_pc;
            end
            if (execute_register && write_q && !register_fault && !register_wait)
                errors<=errors & ~clear_errors;
            if (semaphore_overflow_event) errors[1]<=1;
            if (cpu_bus_error) errors[3]<=1;
            if (protocol_pulse || |leaf_protocol_error) errors[0]<=1;
            if (execute_register && !register_fault && clear_dma) begin
                dma_done_q<=0; dma_error_q<=0;
            end
            if (dma_done_valid && dma_done_ready) begin
                dma_done_q<=1; dma_error_q<=dma_done_error;
                if (dma_done_error!=0) errors[2]<=1;
            end
            case (state)
                IDLE: if (req_valid && req_ready) begin
                    host_q<=req_host; write_q<=req_write; instruction_q<=req_instr;
                    address_q<=req_addr; data_q<=req_wdata; strobe_q<=req_wstrb;
                    size_q<=req_size; response_data<=0; response_error<=0;
                    state<=EXECUTE;
                end
                EXECUTE: begin
                    if (in_host_local || in_cpu_local || in_cpu_ddr) begin
                        memory_select<=in_cpu_ddr;
                        state<=MEMORY_REQUEST;
                    end else if (!in_registers || !mmio_shape_ok) begin
                        response_error<=1; protocol_pulse<=1; state<=RESPONSE;
                    end else if (address_q<64'h2000) begin
                        parent_aw_sent<=0; parent_w_sent<=0; mode_probe<=0;
                        parent_read_address<=address_q[15:0];
                        if (write_q) state<=PARENT_WRITE;
                        else state<=PARENT_READ;
                    end else if (address_q>=64'h2100 && address_q<64'h2200) begin
                        leaf_select<=0; state<=LEAF_REQUEST;
                    end else if (address_q>=64'h2400 && address_q<64'h2500) begin
                        leaf_select<=1; state<=LEAF_REQUEST;
                    end else if (address_q>=64'h2600 && address_q<64'h2700) begin
                        leaf_select<=2; state<=LEAF_REQUEST;
                    end else if (!own_register || register_fault) begin
                        response_error<=1; protocol_pulse<=1; state<=RESPONSE;
                    end else if (start_mode_probe) begin
                        mode_probe<=1; probe_activity<=0; probe_index<=0;
                        parent_read_address<=16'h0008; state<=PARENT_READ;
                    end else if (!register_wait) begin
                        response_data<=write_q ? 64'b0 : {32'b0,register_data};
                        state<=RESPONSE;
                        if (write_q) begin
                            case (address_q[15:0])
                                16'h2004: begin
                                    run_q<=merged_run[0]; reset_pulse<=strobed[1];
                                end
                                16'h2040: source_q<=(source_q & ~write_mask) | strobed;
                                16'h2044: destination_q<=(destination_q & ~write_mask) | strobed;
                                16'h2048: bytes_q<=(bytes_q & ~write_mask) | strobed;
                                16'h2200: if (strobe_q!=0) begin
                                    vision_full<=1; vision_pixel<=strobed[7:0];
                                    vision_slot_meta<=vision_meta;
                                end
                                16'h2204: if (strobe_q!=0) begin
                                    audio_full<=1; audio_sample<=strobed[15:0];
                                    audio_slot_meta<=audio_meta;
                                end
                                16'h2210: vision_meta<=merged_vmeta[16:0];
                                16'h2214: audio_meta<=merged_ameta[16:0];
                                default: begin end
                            endcase
                        end
                    end
                end
                LEAF_REQUEST: if (leaf_req_valid[leaf_select] && leaf_req_ready[leaf_select])
                    state<=LEAF_RESPONSE;
                LEAF_RESPONSE: if (leaf_rsp_valid[leaf_select] && leaf_rsp_ready[leaf_select]) begin
                    response_error<=leaf_rsp_error[leaf_select];
                    response_data<=leaf_rsp_error[leaf_select] ? 64'b0 :
                        {32'b0,leaf_rsp_rdata[leaf_select]};
                    state<=RESPONSE;
                end
                MEMORY_REQUEST: if (memory_req_valid[memory_select] && memory_req_ready[memory_select])
                    state<=MEMORY_RESPONSE;
                MEMORY_RESPONSE: if (memory_rsp_valid[memory_select] && memory_rsp_ready[memory_select]) begin
                    response_error<=memory_rsp_error[memory_select];
                    response_data<=memory_rsp_error[memory_select] ? 64'b0 :
                        memory_rsp_rdata[memory_select];
                    if (host_q && memory_rsp_error[memory_select]) protocol_pulse<=1;
                    state<=RESPONSE;
                end
                PARENT_WRITE: begin
                    if (p_axil_awvalid && p_axil_awready) parent_aw_sent<=1;
                    if (p_axil_wvalid && p_axil_wready) parent_w_sent<=1;
                    if ((parent_aw_sent || (p_axil_awvalid && p_axil_awready)) &&
                        (parent_w_sent || (p_axil_wvalid && p_axil_wready))) state<=PARENT_B;
                end
                PARENT_B: if (p_axil_bvalid && p_axil_bready) begin
                    response_error<=p_axil_bresp!=0;
                    if (p_axil_bresp!=0) protocol_pulse<=1;
                    state<=RESPONSE;
                end
                PARENT_READ: if (p_axil_arvalid && p_axil_arready) state<=PARENT_R;
                PARENT_R: if (p_axil_rvalid && p_axil_rready) begin
                    if (!mode_probe) begin
                        response_error<=p_axil_rresp!=0;
                        response_data<=p_axil_rresp!=0 ? 64'b0 : {32'b0,p_axil_rdata};
                        if (p_axil_rresp!=0) protocol_pulse<=1;
                        state<=RESPONSE;
                    end else if (p_axil_rresp!=0 || probe_activity ||
                        legacy_stream_activity || !cpu_halted ||
                        (probe_index==0 && p_axil_rdata[0]) ||
                        (probe_index==2 && p_axil_rdata!=probe_head) ||
                        (probe_index==3 && p_axil_rdata[4:2]!=0)) begin
                        response_error<=1; protocol_pulse<=1;
                        mode_probe<=0; state<=RESPONSE;
                    end else if (probe_index==3) begin
                        mode_q<=1; mode_probe<=0; state<=RESPONSE;
                    end else begin
                        if (probe_index==0) parent_read_address<=16'h0020;
                        if (probe_index==1) begin
                            probe_head<=p_axil_rdata; parent_read_address<=16'h0024;
                        end
                        if (probe_index==2) parent_read_address<=16'h1008;
                        probe_index<=probe_index+2'd1; state<=PARENT_READ;
                    end
                end
                RESPONSE: if (rsp_valid && rsp_ready) state<=IDLE;
                default: begin
                    response_error<=1; response_data<=0;
                    protocol_pulse<=1; state<=RESPONSE;
                end
            endcase
        end
    end
endmodule
