module furnace_lz4_frontend #(
    parameter integer MAX_DECODED_BYTES=65536
) (
    input wire clk, rst_n,
    input wire start_valid,
    output wire start_ready,
    input wire [31:0] start_frame_bytes, start_decoded_bytes,
    input wire s_valid,
    output wire s_ready,
    input wire [7:0] s_data,
    input wire s_last,
    output wire m_valid,
    input wire m_ready,
    output wire [7:0] m_data,
    output wire m_last,
    output wire done_valid,
    input wire done_ready,
    output wire [7:0] error
);
    generate if (MAX_DECODED_BYTES<1 || MAX_DECODED_BYTES>131072) begin: bad_parameter
        initial $fatal(1,"PARAMETER ERROR: MAX_DECODED_BYTES must be 1..131072");
        assign start_ready=0; assign s_ready=0; assign m_valid=0;
        assign m_data=0; assign m_last=0; assign done_valid=0; assign error=0;
    end else begin: decoder
        localparam [5:0] IDLE=0, HASH_START=1, MAGIC=2, FLG=3, BD=4,
            CSIZE=5, HFIN=6, HWAIT=7, HC=8, BLEN=9, BSTART=10,
            RAW=11, TOKEN=12, LEXT=13, LITERAL=14, AFTER_LIT=15,
            OFF0=16, OFF1=17, MEXT=18, MREAD=19, MOUT=20,
            BEND=21, BFIN=22, BWAIT=23, BCHECK=24, CFIN=25,
            CWAIT=26, CCHECK=27, FINISH=28, ERROR_DRAIN=29, DONE=30;
        reg enabled;
        reg [5:0] state;
        reg [31:0] frame_len, decoded_len, input_count, output_count;
        reg [31:0] block_left, block_decoded, literal_left, literal_total;
        reg [31:0] match_left, last_match_start;
        reg [31:0] word, header_hash, block_hash, content_hash;
        reg [63:0] content_size;
        reg [7:0] flags, token, offset_low, status;
        reg [2:0] index;
        reg [15:0] history_pointer, offset;
        reg [16:0] available;
        reg raw_block, had_match;
        reg out_valid, out_last;
        reg [7:0] out_data;
        (* ramstyle="M20K", nomem2reg *) reg [7:0] history [0:65535];
        reg [7:0] history_q;
        wire [15:0] history_address=history_pointer-offset;
        wire h_start_ready,h_ready,h_finish_ready,h_done;
        wire b_start_ready,b_ready,b_finish_ready,b_done;
        wire c_start_ready,c_ready,c_finish_ready,c_done;
        wire [31:0] h_digest,b_digest,c_digest;
        wire cancel_hash=state==IDLE || state==ERROR_DRAIN || state==DONE;
        wire all_hash_start=state==HASH_START && h_start_ready && c_start_ready;
        wire slot_free=!out_valid || m_ready;
        wire output_fits=output_count<decoded_len && block_decoded<65536;
        wire can_emit=slot_free && c_ready && output_fits;
        wire header_byte=state==FLG || state==BD || state==CSIZE;
        wire block_byte=state==RAW || state==TOKEN || state==LEXT ||
            state==LITERAL || state==OFF0 || state==OFF1 || state==MEXT;
        wire wants_input=state==MAGIC || header_byte || state==HC ||
            state==BLEN || block_byte || state==BCHECK || state==CCHECK;
        wire input_room=input_count<frame_len;
        wire output_input=state==RAW || state==LITERAL;
        wire input_enable=(!header_byte || h_ready) &&
            (!block_byte || b_ready) && (!output_input || can_emit);
        wire take=s_valid && s_ready;
        wire emit=(take && output_input) ||
            (rst_n && enabled && state==MOUT && can_emit);
        wire [7:0] emit_data=(state==MOUT) ? history_q : s_data;
        wire [31:0] assembled_word={s_data,word[23:0]};
        wire [15:0] assembled_offset={s_data,offset_low};
        wire [31:0] literal_extended=literal_left+{24'b0,s_data};
        wire [31:0] match_extended=match_left+{24'b0,s_data};
        wire [7:0] magic_byte=(index==0) ? 8'h04 :
            (index==1) ? 8'h22 : (index==2) ? 8'h4d : 8'h18;

        assign start_ready=rst_n && enabled && state==IDLE;
        assign s_ready=rst_n && enabled && wants_input && input_room && input_enable;
        assign m_valid=rst_n && enabled && out_valid;
        assign m_data=(rst_n && enabled) ? out_data : 8'b0;
        assign m_last=rst_n && enabled && out_last;
        assign done_valid=rst_n && enabled && state==DONE;
        assign error=(rst_n && enabled) ? status : 8'b0;

        furnace_xxh32 header_checksum (
            .clk(clk),.rst_n(rst_n),.cancel(cancel_hash),.start_valid(all_hash_start),
            .start_ready(h_start_ready),.s_valid(take && header_byte),
            .s_ready(h_ready),.s_data(s_data),.finish_valid(state==HFIN),
            .finish_ready(h_finish_ready),.done_valid(h_done),
            .done_ready(state==HWAIT),.digest(h_digest)
        );
        furnace_xxh32 block_checksum (
            .clk(clk),.rst_n(rst_n),.cancel(cancel_hash),.start_valid(state==BSTART),
            .start_ready(b_start_ready),.s_valid(take && block_byte),
            .s_ready(b_ready),.s_data(s_data),.finish_valid(state==BFIN),
            .finish_ready(b_finish_ready),.done_valid(b_done),
            .done_ready(state==BWAIT),.digest(b_digest)
        );
        furnace_xxh32 content_checksum (
            .clk(clk),.rst_n(rst_n),.cancel(cancel_hash),.start_valid(all_hash_start),
            .start_ready(c_start_ready),.s_valid(emit),.s_ready(c_ready),
            .s_data(emit_data),.finish_valid(state==CFIN),
            .finish_ready(c_finish_ready),.done_valid(c_done),
            .done_ready(state==CWAIT),.digest(c_digest)
        );
        always @(posedge clk) begin
            if (emit) history[history_pointer]<=emit_data;
            history_q<=history[history_address];
        end
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                enabled<=0; state<=IDLE; frame_len<=0; decoded_len<=0;
                input_count<=0; output_count<=0; block_left<=0;
                block_decoded<=0; literal_left<=0; literal_total<=0;
                match_left<=0; last_match_start<=0; word<=0;
                header_hash<=0; block_hash<=0; content_hash<=0;
                content_size<=0; flags<=0; token<=0; offset_low<=0;
                status<=0; index<=0; history_pointer<=0; offset<=0;
                available<=0; raw_block<=0; had_match<=0;
                out_valid<=0; out_last<=0; out_data<=0;
            end else begin
                enabled<=1;
                if (out_valid && m_ready) out_valid<=0;
                if (take) input_count<=input_count+1'b1;
                if (take && block_byte) block_left<=block_left-1'b1;
                if (emit) begin
                    out_valid<=1; out_data<=emit_data;
                    out_last<=output_count+1'b1==decoded_len;
                    output_count<=output_count+1'b1;
                    block_decoded<=block_decoded+1'b1;
                    history_pointer<=history_pointer+1'b1;
                    if (available<65536) available<=available+1'b1;
                end
                case (state)
                    IDLE: if (start_valid && start_ready) begin
                        frame_len<=start_frame_bytes;
                        decoded_len<=start_decoded_bytes;
                        input_count<=0; output_count<=0; history_pointer<=0;
                        available<=0; status<=0; out_valid<=0; out_last<=0;
                        out_data<=0; index<=0; content_size<=0; flags<=0;
                        if (start_frame_bytes==0 ||
                            start_frame_bytes>2*MAX_DECODED_BYTES+256 ||
                            start_decoded_bytes>MAX_DECODED_BYTES) begin
                            status<=2; state<=ERROR_DRAIN;
                        end else state<=HASH_START;
                    end
                    HASH_START: if (all_hash_start) state<=MAGIC;
                    MAGIC: if (take) begin
                        if (s_data!=magic_byte) begin status<=2; state<=ERROR_DRAIN; end
                        else if (index==3) begin index<=0; state<=FLG; end
                        else index<=index+1'b1;
                    end
                    FLG: if (take) begin
                        flags<=s_data;
                        if (s_data[7:6]!=2'b01 || s_data[1] || s_data[0]) begin
                            status<=2; state<=ERROR_DRAIN;
                        end else state<=BD;
                    end
                    BD: if (take) begin
                        if (s_data!=8'h40) begin status<=2; state<=ERROR_DRAIN; end
                        else if (flags[3]) begin index<=0; state<=CSIZE; end
                        else state<=HFIN;
                    end
                    CSIZE: if (take) begin
                        content_size[{index,3'b000}+:8]<=s_data;
                        if (index==7) begin
                            if ({s_data,content_size[55:0]}!={32'b0,decoded_len}) begin
                                status<=2; state<=ERROR_DRAIN;
                            end else state<=HFIN;
                        end else index<=index+1'b1;
                    end
                    HFIN: if (h_finish_ready) state<=HWAIT;
                    HWAIT: if (h_done) begin header_hash<=h_digest; state<=HC; end
                    HC: if (take) begin
                        if (s_data!=header_hash[15:8]) begin status<=2; state<=ERROR_DRAIN; end
                        else begin word<=0; index<=0; state<=BLEN; end
                    end
                    BLEN: if (take) begin
                        word[{index[1:0],3'b000}+:8]<=s_data;
                        if (index==3) begin
                            index<=0;
                            if (assembled_word==0) state<=CFIN;
                            else if (assembled_word[30:0]==0 ||
                                assembled_word[30:0]>65536) begin
                                status<=2; state<=ERROR_DRAIN;
                            end else begin
                                raw_block<=assembled_word[31];
                                block_left<={1'b0,assembled_word[30:0]};
                                state<=BSTART;
                            end
                        end else index<=index+1'b1;
                    end
                    BSTART: if (b_start_ready) begin
                        block_decoded<=0; had_match<=0; literal_total<=0;
                        last_match_start<=0;
                        if (flags[5]) available<=0;
                        if (raw_block) state<=RAW; else state<=TOKEN;
                    end
                    RAW: begin
                        if (!output_fits) begin status<=2; state<=ERROR_DRAIN; end
                        else if (take && block_left==1) state<=BEND;
                    end
                    TOKEN: if (take) begin
                        token<=s_data;
                        literal_left<={28'b0,s_data[7:4]};
                        literal_total<={28'b0,s_data[7:4]};
                        if (s_data[7:4]==15) state<=LEXT;
                        else if (s_data[7:4]==0) state<=AFTER_LIT;
                        else state<=LITERAL;
                    end
                    LEXT: if (take) begin
                        if (literal_extended>65536) begin status<=2; state<=ERROR_DRAIN; end
                        else begin
                            literal_left<=literal_extended;
                            literal_total<=literal_extended;
                            if (s_data!=255) begin
                                if (literal_extended==0) state<=AFTER_LIT;
                                else state<=LITERAL;
                            end
                        end
                    end
                    LITERAL: begin
                        if (!output_fits || literal_left>block_left) begin
                            status<=2; state<=ERROR_DRAIN;
                        end else if (take) begin
                            literal_left<=literal_left-1'b1;
                            if (literal_left==1) state<=AFTER_LIT;
                        end
                    end
                    AFTER_LIT: begin
                        if (block_left==0) begin
                            if (had_match && (literal_total<5 ||
                                block_decoded-last_match_start<12)) begin
                                status<=2; state<=ERROR_DRAIN;
                            end else state<=BEND;
                        end else state<=OFF0;
                    end
                    OFF0: if (take) begin offset_low<=s_data; state<=OFF1; end
                    OFF1: if (take) begin
                        if (assembled_offset==0 || {1'b0,assembled_offset}>available) begin
                            status<=3; state<=ERROR_DRAIN;
                        end else begin
                            offset<=assembled_offset; had_match<=1;
                            last_match_start<=block_decoded;
                            match_left<={28'b0,token[3:0]}+32'd4;
                            if (token[3:0]==15) state<=MEXT; else state<=MREAD;
                        end
                    end
                    MEXT: if (take) begin
                        if (match_extended>65536) begin status<=2; state<=ERROR_DRAIN; end
                        else begin
                            match_left<=match_extended;
                            if (s_data!=255) state<=MREAD;
                        end
                    end
                    MREAD: state<=MOUT;
                    MOUT: begin
                        if (!output_fits) begin status<=2; state<=ERROR_DRAIN; end
                        else if (emit) begin
                            match_left<=match_left-1'b1;
                            if (match_left==1) begin
                                if (block_left==0) begin status<=2; state<=ERROR_DRAIN; end
                                else state<=TOKEN;
                            end else state<=MREAD;
                        end
                    end
                    BEND: state<=BFIN;
                    BFIN: if (b_finish_ready) state<=BWAIT;
                    BWAIT: if (b_done) begin
                        block_hash<=b_digest; index<=0; word<=0;
                        if (flags[4]) state<=BCHECK; else state<=BLEN;
                    end
                    BCHECK: if (take) begin
                        word[{index[1:0],3'b000}+:8]<=s_data;
                        if (index==3) begin
                            if (assembled_word!=block_hash) begin status<=2; state<=ERROR_DRAIN; end
                            else begin index<=0; word<=0; state<=BLEN; end
                        end else index<=index+1'b1;
                    end
                    CFIN: if (c_finish_ready) state<=CWAIT;
                    CWAIT: if (c_done) begin
                        content_hash<=c_digest; index<=0; word<=0;
                        if (flags[2]) state<=CCHECK; else state<=FINISH;
                    end
                    CCHECK: if (take) begin
                        word[{index[1:0],3'b000}+:8]<=s_data;
                        if (index==3) begin
                            if (assembled_word!=content_hash) begin status<=2; state<=ERROR_DRAIN; end
                            else state<=FINISH;
                        end else index<=index+1'b1;
                    end
                    FINISH: begin
                        if (input_count!=frame_len || output_count!=decoded_len) begin
                            status<=2; state<=ERROR_DRAIN;
                        end else if (!out_valid) begin status<=0; state<=DONE; end
                    end
                    ERROR_DRAIN: if (!out_valid) state<=DONE;
                    DONE: if (done_ready) state<=IDLE;
                    default: begin status<=2; state<=ERROR_DRAIN; end
                endcase
                if (wants_input && !input_room) begin status<=2; state<=ERROR_DRAIN; end
                if (block_byte && block_left==0) begin status<=2; state<=ERROR_DRAIN; end
                if (take && (s_last!=(input_count+1'b1==frame_len))) begin
                    status<=2; state<=ERROR_DRAIN;
                end
            end
        end
    end endgenerate
endmodule
