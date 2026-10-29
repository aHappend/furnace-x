module furnace_aes128_block (
    input wire clk, rst_n, cancel,
    input wire key_valid,
    output wire key_ready,
    input wire [127:0] key,
    output wire keys_ready,
    input wire s_valid,
    output wire s_ready,
    input wire [127:0] s_data,
    output wire m_valid,
    input wire m_ready,
    output wire [127:0] m_data
);
    function automatic [7:0] sbox(input [7:0] x);
        reg [127:0] row;
        begin
            case (x[7:4])
                4'h0: row=128'h637c777bf26b6fc53001672bfed7ab76;
                4'h1: row=128'hca82c97dfa5947f0add4a2af9ca472c0;
                4'h2: row=128'hb7fd9326363ff7cc34a5e5f171d83115;
                4'h3: row=128'h04c723c31896059a071280e2eb27b275;
                4'h4: row=128'h09832c1a1b6e5aa0523bd6b329e32f84;
                4'h5: row=128'h53d100ed20fcb15b6acbbe394a4c58cf;
                4'h6: row=128'hd0efaafb434d338545f9027f503c9fa8;
                4'h7: row=128'h51a3408f929d38f5bcb6da2110fff3d2;
                4'h8: row=128'hcd0c13ec5f974417c4a77e3d645d1973;
                4'h9: row=128'h60814fdc222a908846eeb814de5e0bdb;
                4'ha: row=128'he0323a0a4906245cc2d3ac629195e479;
                4'hb: row=128'he7c8376d8dd54ea96c56f4ea657aae08;
                4'hc: row=128'hba78252e1ca6b4c6e8dd741f4bbd8b8a;
                4'hd: row=128'h703eb5664803f60e613557b986c11d9e;
                4'he: row=128'he1f8981169d98e949b1e87e9ce5528df;
                default: row=128'h8ca1890dbfe6426841992d0fb054bb16;
            endcase
            sbox=row[127-{x[3:0],3'b000}-:8];
        end
    endfunction
    function automatic [7:0] xtime(input [7:0] x);
        xtime={x[6:0],1'b0}^{8'h1b & {8{x[7]}}};
    endfunction
    function automatic [127:0] sub_shift(input [127:0] x);
        integer c,r;
        begin
            for (c=0;c<4;c=c+1)
                for (r=0;r<4;r=r+1)
                    sub_shift[127-8*(4*c+r)-:8]=
                        sbox(x[127-8*(4*((c+r)&3)+r)-:8]);
        end
    endfunction
    function automatic [127:0] mix_columns(input [127:0] x);
        integer c;
        reg [7:0] a,b,d,e,t;
        begin
            for (c=0;c<4;c=c+1) begin
                a=x[127-32*c-:8]; b=x[119-32*c-:8];
                d=x[111-32*c-:8]; e=x[103-32*c-:8];
                t=a^b^d^e;
                mix_columns[127-32*c-:8]=a^t^xtime(a^b);
                mix_columns[119-32*c-:8]=b^t^xtime(b^d);
                mix_columns[111-32*c-:8]=d^t^xtime(d^e);
                mix_columns[103-32*c-:8]=e^t^xtime(e^a);
            end
        end
    endfunction
    reg enabled, expanding, expanded;
    reg [3:0] key_round;
    reg [1:0] key_phase;
    reg [7:0] rcon;
    reg [127:0] current_key;
    reg [31:0] key_temp,kw0,kw1,kw2,kw3;
    reg [127:0] round_key [0:10];
    reg [127:0] data_pipe [0:21];
    reg [21:0] valid_pipe;
    wire [31:0] sub_rot={sbox(current_key[23:16]),
        sbox(current_key[15:8]),sbox(current_key[7:0]),
        sbox(current_key[31:24])}^{rcon,24'b0};
    wire [7:0] next_rcon=xtime(rcon);
    wire advance=!valid_pipe[21] || m_ready;
    wire empty_pipe=!(|valid_pipe);
    wire [127:0] stage_data [1:21];
    assign stage_data[1]=data_pipe[0]^round_key[0];
    genvar g;
    generate for (g=2;g<20;g=g+1) begin: rounds
        if ((g & 1)==0) begin: substage
            assign stage_data[g]=sub_shift(data_pipe[g-1]);
        end else begin: mixstage
            assign stage_data[g]=mix_columns(data_pipe[g-1])^round_key[(g-1)>>1];
        end
    end endgenerate
    assign stage_data[20]=sub_shift(data_pipe[19]);
    assign stage_data[21]=data_pipe[20]^round_key[10];
    assign key_ready=rst_n && enabled && !expanding && empty_pipe;
    assign keys_ready=rst_n && enabled && expanded && !expanding;
    assign s_ready=keys_ready && advance && !key_valid;
    assign m_valid=rst_n && enabled && valid_pipe[21];
    assign m_data=(rst_n && enabled) ? data_pipe[21] : 128'b0;
    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enabled<=0; expanding<=0; expanded<=0; key_round<=0;
            key_phase<=0; rcon<=0; current_key<=0; key_temp<=0;
            kw0<=0; kw1<=0; kw2<=0; kw3<=0; valid_pipe<=0;
            for (i=0;i<22;i=i+1) data_pipe[i]<=0;
        end else begin
            enabled<=1;
            if (cancel) begin
                expanding<=0; expanded<=0; valid_pipe<=0;
            end else begin
            if (key_valid && key_ready) begin
                round_key[0]<=key; current_key<=key; key_round<=1;
                key_phase<=0; rcon<=1; expanded<=0; expanding<=1;
            end else if (expanding) begin
                case (key_phase)
                    0: begin key_temp<=sub_rot; key_phase<=1; end
                    1: begin
                        kw0<=current_key[127:96]^key_temp;
                        kw1<=current_key[95:64]^current_key[127:96]^key_temp;
                        key_phase<=2;
                    end
                    2: begin
                        kw2<=current_key[63:32]^kw1;
                        kw3<=current_key[31:0]^current_key[63:32]^kw1;
                        key_phase<=3;
                    end
                    3: begin
                        current_key<={kw0,kw1,kw2,kw3};
                        round_key[key_round]<={kw0,kw1,kw2,kw3};
                        key_phase<=0; rcon<=next_rcon;
                        if (key_round==10) begin expanding<=0; expanded<=1; end
                        else key_round<=key_round+1'b1;
                    end
                endcase
            end
            if (advance) begin
                valid_pipe[0]<=s_valid && s_ready;
                if (s_valid && s_ready) data_pipe[0]<=s_data;
                for (i=1;i<22;i=i+1) begin
                    valid_pipe[i]<=valid_pipe[i-1];
                    if (valid_pipe[i-1]) data_pipe[i]<=stage_data[i];
                end
            end
            end
        end
    end
endmodule
