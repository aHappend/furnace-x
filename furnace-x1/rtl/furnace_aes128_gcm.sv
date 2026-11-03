module furnace_aes128_gcm #(
    parameter integer MAX_TILE_BYTES=4096
) (
    input wire clk, rst_n,
    input wire start_valid,
    output wire start_ready,
    input wire [127:0] key,
    input wire [95:0] nonce,
    input wire [127:0] tag,
    input wire [415:0] aad,
    input wire [31:0] data_bytes,
    input wire s_valid,
    output wire s_ready,
    input wire [7:0] s_data,
    input wire s_last,
    output wire m_valid,
    input wire m_ready,
    output wire [7:0] m_data,
    output wire m_last,
    input wire frame_done_valid,
    output wire frame_done_ready,
    input wire [7:0] frame_error,
    output wire done_valid,
    input wire done_ready,
    output wire [7:0] error
);
    generate if (MAX_TILE_BYTES<1 || MAX_TILE_BYTES>65536) begin: bad_parameter
        initial $fatal(1,"PARAMETER ERROR: MAX_TILE_BYTES must be 1..65536");
        assign start_ready=0; assign s_ready=0; assign m_valid=0;
        assign m_data=0; assign m_last=0; assign frame_done_ready=0;
        assign done_valid=0; assign error=0;
    end else begin: decryptor
        localparam [5:0] IDLE=0, KEY_SEND=1, KEY_WAIT=2, HREQ=3,
            HWAIT=4, JREQ=5, JWAIT=6, AAD_REQ=7, AAD_WAIT=8,
            RX=9, CTR_REQ=10, CTR_WAIT=11, STORE=12, DATA_REQ=13,
            DATA_WAIT=14, LEN_REQ=15, LEN_WAIT=16, TAG_CHECK=17,
            FENCE=18, READ_REQ=19, READ_WAIT=20, OUTPUT_BYTE=21,
            ABORT=22, DONE=23;
        reg enabled;
        reg [5:0] state;
        reg [127:0] key_latched,tag_latched,h,y,ej,cipher_block,plain_block;
        reg [95:0] nonce_latched;
        reg [415:0] aad_latched;
        reg [31:0] length,received,stored,read_index,counter;
        reg [4:0] block_count,block_size,store_index;
        reg [1:0] aad_index;
        reg frame_seen,need_fence;
        reg [7:0] status,output_data;
        reg output_last;
        (* ramstyle="M20K", nomem2reg *) reg [7:0] quarantine [0:MAX_TILE_BYTES-1];
        reg [7:0] quarantine_q;
        wire aes_key_ready,aes_keys_ready,aes_s_ready,aes_m_valid;
        wire [127:0] aes_m_data;
        wire gh_start_ready,gh_done;
        wire [127:0] gh_product;
        wire cancel=state==ABORT;
        wire aes_request=state==HREQ || state==JREQ || state==CTR_REQ;
        wire [127:0] aes_input=(state==HREQ) ? 128'b0 :
            (state==JREQ) ? {nonce_latched,32'd1} : {nonce_latched,counter};
        wire aes_output_ready=state==HWAIT || state==JWAIT || state==CTR_WAIT;
        wire [511:0] aad_padded={96'b0,aad_latched};
        wire [127:0] aad_word=aad_padded >> {aad_index,7'b0000000};
        wire [127:0] aad_crypto;
        genvar b;
        for (b=0;b<16;b=b+1) begin: aad_byte_order
            assign aad_crypto[127-8*b-:8]=aad_word[8*b+:8];
        end
        wire [127:0] length_block={64'd416,29'b0,length,3'b000};
        wire [127:0] gh_input=y^((state==AAD_REQ) ? aad_crypto :
            (state==LEN_REQ) ? length_block : cipher_block);
        wire gh_request=state==AAD_REQ || state==DATA_REQ || state==LEN_REQ;
        wire gh_retire=state==AAD_WAIT || state==DATA_WAIT || state==LEN_WAIT;
        wire take=s_valid && s_ready;
        wire frame_take=frame_done_valid && frame_done_ready;
        wire [127:0] computed_tag=ej^y;
        wire [127:0] tag_difference=computed_tag^tag_latched;
        assign start_ready=rst_n && enabled && state==IDLE;
        assign s_ready=rst_n && enabled &&
            ((state==RX && received<length) || (state==ABORT && !frame_seen && need_fence));
        assign frame_done_ready=rst_n && enabled && state!=IDLE &&
            state!=DONE && !frame_seen && need_fence;
        assign m_valid=rst_n && enabled && state==OUTPUT_BYTE;
        assign m_data=m_valid ? output_data : 8'b0;
        assign m_last=m_valid && output_last;
        assign done_valid=rst_n && enabled && state==DONE;
        assign error=(rst_n && enabled) ? status : 8'b0;

        furnace_aes128_block aes (
            .clk(clk),.rst_n(rst_n),.cancel(cancel),
            .key_valid(state==KEY_SEND),.key_ready(aes_key_ready),
            .key(key_latched),.keys_ready(aes_keys_ready),
            .s_valid(aes_request),.s_ready(aes_s_ready),.s_data(aes_input),
            .m_valid(aes_m_valid),.m_ready(aes_output_ready),.m_data(aes_m_data)
        );
        furnace_ghash_mul ghash (
            .clk(clk),.rst_n(rst_n),.cancel(cancel),
            .start_valid(gh_request),.start_ready(gh_start_ready),
            .x(gh_input),.h(h),.done_valid(gh_done),
            .done_ready(gh_retire),.product(gh_product)
        );
        always @(posedge clk) begin
            if (rst_n && enabled && state==STORE)
                quarantine[stored]<=plain_block[127-{store_index[3:0],3'b000}-:8];
            quarantine_q<=quarantine[read_index];
        end
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                enabled<=0; state<=IDLE; key_latched<=0; tag_latched<=0;
                h<=0; y<=0; ej<=0; cipher_block<=0; plain_block<=0;
                nonce_latched<=0; aad_latched<=0; length<=0; received<=0;
                stored<=0; read_index<=0; counter<=0; block_count<=0;
                block_size<=0; store_index<=0; aad_index<=0; frame_seen<=0;
                need_fence<=0; status<=0; output_data<=0; output_last<=0;
            end else begin
                enabled<=1;
                case (state)
                    IDLE: if (start_valid && start_ready) begin
                        key_latched<=key; tag_latched<=tag; nonce_latched<=nonce;
                        aad_latched<=aad; length<=data_bytes; received<=0;
                        stored<=0; read_index<=0; counter<=2; block_count<=0;
                        block_size<=0; store_index<=0; aad_index<=0; frame_seen<=0;
                        need_fence<=1; status<=0; output_data<=0; output_last<=0;
                        cipher_block<=0; plain_block<=0; h<=0; y<=0; ej<=0;
                        if (data_bytes>MAX_TILE_BYTES) begin
                            need_fence<=0; status<=2; state<=ABORT;
                        end else state<=KEY_SEND;
                    end
                    KEY_SEND: if (aes_key_ready) state<=KEY_WAIT;
                    KEY_WAIT: if (aes_keys_ready) state<=HREQ;
                    HREQ: if (aes_s_ready) state<=HWAIT;
                    HWAIT: if (aes_m_valid) begin h<=aes_m_data; state<=JREQ; end
                    JREQ: if (aes_s_ready) state<=JWAIT;
                    JWAIT: if (aes_m_valid) begin ej<=aes_m_data; state<=AAD_REQ; end
                    AAD_REQ: if (gh_start_ready) state<=AAD_WAIT;
                    AAD_WAIT: if (gh_done) begin
                        y<=gh_product;
                        if (aad_index==3) begin
                            if (length==0) state<=LEN_REQ; else state<=RX;
                        end else begin aad_index<=aad_index+1'b1; state<=AAD_REQ; end
                    end
                    RX: if (take) begin
                        cipher_block[127-{block_count[3:0],3'b000}-:8]<=s_data;
                        received<=received+1'b1;
                        if (block_count==15 || received+1'b1==length) begin
                            block_size<=block_count+1'b1; block_count<=0; state<=CTR_REQ;
                        end else block_count<=block_count+1'b1;
                        if (s_last!=(received+1'b1==length)) begin status<=2; state<=ABORT; end
                    end
                    CTR_REQ: if (aes_s_ready) state<=CTR_WAIT;
                    CTR_WAIT: if (aes_m_valid) begin
                        plain_block<=cipher_block^aes_m_data; store_index<=0; state<=STORE;
                    end
                    STORE: begin
                        stored<=stored+1'b1;
                        if (store_index+1'b1==block_size) state<=DATA_REQ;
                        else store_index<=store_index+1'b1;
                    end
                    DATA_REQ: if (gh_start_ready) state<=DATA_WAIT;
                    DATA_WAIT: if (gh_done) begin
                        y<=gh_product; cipher_block<=0;
                        if (received==length) state<=LEN_REQ;
                        else if (counter==32'hffffffff) begin status<=2; state<=ABORT; end
                        else begin counter<=counter+1'b1; state<=RX; end
                    end
                    LEN_REQ: if (gh_start_ready) state<=LEN_WAIT;
                    LEN_WAIT: if (gh_done) begin y<=gh_product; state<=TAG_CHECK; end
                    TAG_CHECK: begin
                        if (|tag_difference) begin status<=4; state<=ABORT; end
                        else state<=FENCE;
                    end
                    FENCE: if (frame_seen) begin
                        read_index<=0;
                        if (length==0) state<=DONE; else state<=READ_REQ;
                    end
                    READ_REQ: state<=READ_WAIT;
                    READ_WAIT: begin
                        output_data<=quarantine_q;
                        output_last<=read_index+1'b1==length;
                        state<=OUTPUT_BYTE;
                    end
                    OUTPUT_BYTE: if (m_ready) begin
                        if (output_last) state<=DONE;
                        else begin read_index<=read_index+1'b1; state<=READ_REQ; end
                    end
                    ABORT: if (frame_seen || !need_fence) state<=DONE;
                    DONE: if (done_ready) state<=IDLE;
                    default: begin status<=2; state<=ABORT; end
                endcase
                if (frame_take) begin
                    frame_seen<=1;
                    if (frame_error!=0) begin status<=frame_error; state<=ABORT; end
                    else if (received!=length) begin status<=2; state<=ABORT; end
                end
            end
        end
    end endgenerate
endmodule
