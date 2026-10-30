module furnace_fusion_buffer #(
    parameter integer FUSION_DEPTH=4
) (
    input wire clk, rst_n,
    input wire v_valid,
    output wire v_ready,
    input wire [63:0] v_data,
    input wire [15:0] v_id,
    input wire [7:0] v_error,
    input wire a_valid,
    output wire a_ready,
    input wire [63:0] a_data,
    input wire [15:0] a_id,
    input wire [7:0] a_error,
    output wire m_valid,
    input wire m_ready,
    output wire [127:0] m_data,
    output wire [15:0] m_id,
    output wire [7:0] m_error
);
    generate if (FUSION_DEPTH<1 || FUSION_DEPTH>16) begin: bad_parameter
        initial $fatal(1,"PARAMETER ERROR: FUSION_DEPTH must be 1..16");
        assign v_ready=0; assign a_ready=0; assign m_valid=0;
        assign m_data=0; assign m_id=0; assign m_error=0;
    end else begin: queues
        localparam integer PW=(FUSION_DEPTH==1) ? 1 : $clog2(FUSION_DEPTH);
        localparam integer CW=$clog2(FUSION_DEPTH+1);
        reg enabled,output_valid;
        reg [PW-1:0] vr,vw,ar,aw;
        reg [CW-1:0] vc,ac;
        (* nomem2reg *) reg [87:0] vision [0:FUSION_DEPTH-1];
        (* nomem2reg *) reg [87:0] audio [0:FUSION_DEPTH-1];
        reg [127:0] output_data;
        reg [15:0] output_id;
        reg [7:0] output_error;
        wire active=rst_n && enabled;
        wire pair_pop=active && vc!=0 && ac!=0 && (!output_valid || m_ready);
        wire v_push=v_valid && v_ready;
        wire a_push=a_valid && a_ready;
        wire [87:0] vh=vision[vr],ah=audio[ar];
        wire [7:0] pair_error=(vh[79:64]!=ah[79:64]) ? 8'd8 :
            (vh[87:80]!=0) ? vh[87:80] : ah[87:80];
        assign v_ready=active && (vc<FUSION_DEPTH || pair_pop);
        assign a_ready=active && (ac<FUSION_DEPTH || pair_pop);
        assign m_valid=active && output_valid;
        assign m_data=active ? output_data : 128'b0;
        assign m_id=active ? output_id : 16'b0;
        assign m_error=active ? output_error : 8'b0;
        always @(posedge clk) begin
            if (v_push) vision[vw]<={v_error,v_id,v_data};
            if (a_push) audio[aw]<={a_error,a_id,a_data};
        end
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                enabled<=0; output_valid<=0; vr<=0; vw<=0; ar<=0; aw<=0;
                vc<=0; ac<=0; output_data<=0; output_id<=0; output_error<=0;
            end else begin
                enabled<=1;
                if (output_valid && m_ready) output_valid<=0;
                if (v_push) begin
                    if (vw==FUSION_DEPTH-1) vw<=0; else vw<=vw+1'b1;
                end
                if (a_push) begin
                    if (aw==FUSION_DEPTH-1) aw<=0; else aw<=aw+1'b1;
                end
                case ({v_push,pair_pop})
                    2'b10:vc<=vc+1'b1;
                    2'b01:vc<=vc-1'b1;
                    default:begin end
                endcase
                case ({a_push,pair_pop})
                    2'b10:ac<=ac+1'b1;
                    2'b01:ac<=ac-1'b1;
                    default:begin end
                endcase
                if (pair_pop) begin
                    if (vr==FUSION_DEPTH-1) vr<=0; else vr<=vr+1'b1;
                    if (ar==FUSION_DEPTH-1) ar<=0; else ar<=ar+1'b1;
                    output_valid<=1; output_id<=vh[79:64]; output_error<=pair_error;
                    if (pair_error!=0) output_data<=0;
                    else output_data<={ah[63:0],vh[63:0]};
                end
            end
        end
    end endgenerate
endmodule
