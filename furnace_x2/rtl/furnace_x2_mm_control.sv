module furnace_x2_mm_control #(
    parameter integer FUSION_DEPTH=4
) (
    input wire clk,rst_n,
    input wire [31:0] v_base,a_base,result_base,
    input wire weights_valid,
    input wire [31:0] committed_weights,
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
    output wire fv_valid,
    input wire fv_ready,
    output wire [63:0] fv_data,
    output wire [15:0] fv_id,
    output wire [7:0] fv_error,
    output wire fa_valid,
    input wire fa_ready,
    output wire [63:0] fa_data,
    output wire [15:0] fa_id,
    output wire [7:0] fa_error,
    input wire f_valid,
    output wire f_ready,
    input wire [127:0] f_data,
    input wire [15:0] f_id,
    input wire [7:0] f_error,
    output wire tensor_valid,
    input wire tensor_ready,
    output wire [127:0] tensor_weights,tensor_activations,
    input wire tensor_result_valid,
    output wire tensor_result_ready,
    input wire [63:0] tensor_result,
    input wire [7:0] tensor_error,
    output wire [2:0] wr_valid,
    input wire [2:0] wr_ready,
    output wire [2:0][31:0] wr_address,wr_length,
    output wire [2:0] byte_valid,
    input wire [2:0] byte_ready,
    output wire [2:0][7:0] byte_data,
    output wire [2:0] byte_last,
    input wire [2:0] wr_done,
    output wire [2:0] wr_done_ready,
    input wire [2:0][7:0] wr_error,
    output wire mm_valid,
    input wire mm_ready,
    output wire [15:0] mm_id,
    output wire [63:0] mm_result,
    output wire [7:0] mm_error,
    output wire report_pulse,busy
);
    generate if (FUSION_DEPTH<1 || FUSION_DEPTH>16) begin: bad_parameter
        initial $fatal(1,"PARAMETER ERROR: FUSION_DEPTH must be 1..16");
        assign v_ready=0; assign a_ready=0; assign fv_valid=0; assign fa_valid=0;
        assign fv_data=0; assign fv_id=0; assign fv_error=0;
        assign fa_data=0; assign fa_id=0; assign fa_error=0; assign f_ready=0;
        assign tensor_valid=0; assign tensor_weights=0; assign tensor_activations=0;
        assign tensor_result_ready=0; assign wr_valid=0; assign wr_address=0;
        assign wr_length=0; assign byte_valid=0; assign byte_data=0; assign byte_last=0;
        assign wr_done_ready=0; assign mm_valid=0; assign mm_id=0;
        assign mm_result=0; assign mm_error=0; assign report_pulse=0; assign busy=0;
    end else begin: control
        localparam [2:0] F_IDLE=0,F_COMMAND=1,F_BYTES=2,F_WAIT=3,F_ENQUEUE=4;
        localparam [3:0] M_IDLE=0,M_TENSOR=1,M_TWAIT=2,M_COMMAND=3,M_BYTES=4,M_WAIT=5,M_REPORT=6;
        reg enabled;
        reg [2:0] feature_state [0:1];
        reg [3:0] feature_slot [0:1],feature_write_slot [0:1],feature_byte [0:1];
        reg [4:0] credits [0:1];
        reg [63:0] feature_data [0:1];
        reg [15:0] feature_id [0:1];
        reg [7:0] feature_error [0:1];
        reg [3:0] mm_state,result_slot,result_byte;
        reg [15:0] result_id;
        reg [63:0] result_data;
        reg [7:0] result_error;
        reg [127:0] activations;
        reg [31:0] weight_snapshot;
        wire active=rst_n && enabled;
        wire completion_take=mm_valid && mm_ready;
        wire [1:0] feature_valid={a_valid,v_valid};
        wire [1:0] feature_ready={a_ready,v_ready};
        wire [1:0][63:0] incoming_data={a_data,v_data};
        wire [1:0][15:0] incoming_id={a_id,v_id};
        wire [1:0][7:0] incoming_error={a_error,v_error};
        wire [1:0] enqueue_ready={fa_ready,fv_ready};
        assign v_ready=active && feature_state[0]==F_IDLE &&
            (credits[0]<FUSION_DEPTH || completion_take);
        assign a_ready=active && feature_state[1]==F_IDLE &&
            (credits[1]<FUSION_DEPTH || completion_take);
        assign fv_valid=active && feature_state[0]==F_ENQUEUE;
        assign fa_valid=active && feature_state[1]==F_ENQUEUE;
        assign fv_data=active ? feature_data[0] : 64'b0;
        assign fa_data=active ? feature_data[1] : 64'b0;
        assign fv_id=active ? feature_id[0] : 16'b0;
        assign fa_id=active ? feature_id[1] : 16'b0;
        assign fv_error=active ? feature_error[0] : 8'b0;
        assign fa_error=active ? feature_error[1] : 8'b0;
        assign f_ready=active && mm_state==M_IDLE && weights_valid;
        assign tensor_valid=active && mm_state==M_TENSOR;
        assign tensor_weights=active ? {96'b0,weight_snapshot} : 128'b0;
        assign tensor_activations=active ? activations : 128'b0;
        assign tensor_result_ready=active && mm_state==M_TWAIT;
        assign mm_valid=active && mm_state==M_REPORT;
        assign mm_id=active ? result_id : 16'b0;
        assign mm_result=active ? result_data : 64'b0;
        assign mm_error=active ? result_error : 8'b0;
        assign report_pulse=active && mm_state==M_WAIT && wr_done[2];
        assign busy=active && (credits[0]!=0 || credits[1]!=0 || mm_state!=M_IDLE ||
            feature_state[0]!=F_IDLE || feature_state[1]!=F_IDLE);
        wire [127:0] result_record={result_error,8'b0,result_id,32'b0,result_data};
        genvar g;
        for (g=0;g<2;g=g+1) begin: feature_writes
            wire [127:0] record_data={feature_error[g],8'b0,feature_id[g],32'b0,feature_data[g]};
            assign wr_valid[g]=active && feature_state[g]==F_COMMAND;
            assign wr_address[g]=active ? ((g==0 ? v_base : a_base)+
                {24'b0,feature_write_slot[g],4'b0}) : 32'b0;
            assign wr_length[g]=active ? 32'd16 : 32'b0;
            assign byte_valid[g]=active && feature_state[g]==F_BYTES;
            assign byte_data[g]=active ? record_data[8*feature_byte[g]+:8] : 8'b0;
            assign byte_last[g]=active && feature_state[g]==F_BYTES && feature_byte[g]==15;
            assign wr_done_ready[g]=active && feature_state[g]==F_WAIT;
        end
        assign wr_valid[2]=active && mm_state==M_COMMAND;
        assign wr_address[2]=active ? result_base+{24'b0,result_slot,4'b0} : 32'b0;
        assign wr_length[2]=active ? 32'd16 : 32'b0;
        assign byte_valid[2]=active && mm_state==M_BYTES;
        assign byte_data[2]=active ? result_record[8*result_byte+:8] : 8'b0;
        assign byte_last[2]=active && mm_state==M_BYTES && result_byte==15;
        assign wr_done_ready[2]=active && mm_state==M_WAIT;
        integer i;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                enabled<=0; mm_state<=M_IDLE; result_slot<=0; result_byte<=0;
                result_id<=0; result_data<=0; result_error<=0;
                activations<=0; weight_snapshot<=0;
                for (i=0;i<2;i=i+1) begin
                    feature_state[i]<=F_IDLE; feature_slot[i]<=0; feature_write_slot[i]<=0;
                    feature_byte[i]<=0; credits[i]<=0; feature_data[i]<=0;
                    feature_id[i]<=0; feature_error[i]<=0;
                end
            end else begin
                enabled<=1;
                for (i=0;i<2;i=i+1) begin
                    case ({feature_valid[i] && feature_ready[i],completion_take})
                        2'b10:credits[i]<=credits[i]+1'b1;
                        2'b01:credits[i]<=credits[i]-1'b1;
                        default:begin end
                    endcase
                    case (feature_state[i])
                        F_IDLE:if (feature_valid[i] && feature_ready[i]) begin
                            feature_data[i]<=incoming_data[i]; feature_id[i]<=incoming_id[i];
                            feature_error[i]<=incoming_error[i];
                            feature_write_slot[i]<=feature_slot[i];
                            if (feature_slot[i]==FUSION_DEPTH-1) feature_slot[i]<=0;
                            else feature_slot[i]<=feature_slot[i]+1'b1;
                            feature_state[i]<=F_COMMAND;
                        end
                        F_COMMAND:if (wr_valid[i] && wr_ready[i]) begin
                            feature_byte[i]<=0; feature_state[i]<=F_BYTES;
                        end
                        F_BYTES:if (byte_valid[i] && byte_ready[i]) begin
                            if (feature_byte[i]==15) feature_state[i]<=F_WAIT;
                            else feature_byte[i]<=feature_byte[i]+1'b1;
                        end
                        F_WAIT:if (wr_done[i] && wr_done_ready[i]) begin
                            if (wr_error[i]!=0) feature_error[i]<=5;
                            feature_state[i]<=F_ENQUEUE;
                        end
                        F_ENQUEUE:if (enqueue_ready[i]) feature_state[i]<=F_IDLE;
                        default:begin feature_error[i]<=5; feature_state[i]<=F_ENQUEUE; end
                    endcase
                end
                case (mm_state)
                    M_IDLE:if (f_valid && f_ready) begin
                        result_id<=f_id; result_error<=f_error; result_data<=0;
                        weight_snapshot<=committed_weights; activations<=f_data;
                        if (f_error!=0) mm_state<=M_COMMAND; else mm_state<=M_TENSOR;
                    end
                    M_TENSOR:if (tensor_valid && tensor_ready) mm_state<=M_TWAIT;
                    M_TWAIT:if (tensor_result_valid && tensor_result_ready) begin
                        if (tensor_error!=0) begin result_data<=0; result_error<=tensor_error; end
                        else result_data<=tensor_result;
                        mm_state<=M_COMMAND;
                    end
                    M_COMMAND:if (wr_valid[2] && wr_ready[2]) begin result_byte<=0; mm_state<=M_BYTES; end
                    M_BYTES:if (byte_valid[2] && byte_ready[2]) begin
                        if (result_byte==15) mm_state<=M_WAIT; else result_byte<=result_byte+1'b1;
                    end
                    M_WAIT:if (wr_done[2] && wr_done_ready[2]) begin
                        if (wr_error[2]!=0) begin result_data<=0; result_error<=5; end
                        mm_state<=M_REPORT;
                    end
                    M_REPORT:if (completion_take) begin
                        if (result_slot==FUSION_DEPTH-1) result_slot<=0;
                        else result_slot<=result_slot+1'b1;
                        mm_state<=M_IDLE;
                    end
                    default:begin result_data<=0; result_error<=5; mm_state<=M_COMMAND; end
                endcase
            end
        end
    end endgenerate
endmodule
