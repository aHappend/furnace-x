`default_nettype none
module furnace_header_parser #(
    parameter integer DATA_WIDTH = 512
) (
    input wire clk, rst_n,
    input wire in_fire,
    input wire [((DATA_WIDTH > 0) ? DATA_WIDTH : 1)-1:0] in_data,
    input wire [((DATA_WIDTH >= 8) ? (DATA_WIDTH>>3) : 1)-1:0] in_keep,
    input wire in_last,
    output reg out_valid,
    output reg [511:0] out_header,
    output reg [295:0] out_tuple,
    output reg [8:0] out_tuple_bits,
    output reg [31:0] out_packet_bytes
);
    generate if (DATA_WIDTH == 64 || DATA_WIDTH == 512) begin : g_legal
        localparam integer LANES = DATA_WIDTH >> 3;
        localparam integer BANK_BITS = (DATA_WIDTH == 64) ? 3 : 6;
        localparam integer ROWS = 256 >> BANK_BITS;
        localparam [3:0] ETH=0, VLAN=1, IP4=2, IP6=3, EXT=4,
                         TCP=5, UDP=6, DONE=7;
        reg packet_open;
        reg [31:0] packet_bytes;
        reg [8:0] capture_base;
        reg packet_bad;
        wire [6:0] count_tree [0:126];
        wire [LANES-1:0] violations;
        genvar lane;
        for (lane=0; lane<64; lane=lane+1) begin : g_count
            if (lane<LANES) begin : g_used
                assign count_tree[63+lane] = {6'b0,in_keep[lane]};
            end else begin : g_unused
                assign count_tree[63+lane] = 0;
            end
        end
        for (lane=0; lane<63; lane=lane+1) begin : g_sum
            assign count_tree[lane] = count_tree[2*lane+1] + count_tree[2*lane+2];
        end
        assign violations[0] = 0;
        for (lane=1; lane<LANES; lane=lane+1) begin : g_prefix
            assign violations[lane] = in_keep[lane] && !in_keep[lane-1];
        end
        wire bad_keep = in_last ? (|violations) : !(&in_keep);
        wire [31:0] byte_base = packet_open ? packet_bytes : 32'b0;
        wire [32:0] byte_sum = {1'b0,byte_base} + {26'b0,count_tree[0]};
        wire [31:0] byte_next = byte_sum[32] ? 32'hffffffff : byte_sum[31:0];
        wire [8:0] write_base = packet_open ? capture_base : 9'b0;
        reg [1:0] engine;
        reg [8:0] read_index, scan_index;
        reg scan_valid;
        wire [7:0] bank_q [0:LANES-1];
        for (lane=0; lane<LANES; lane=lane+1) begin : g_capture
            (* nomem2reg *) reg [7:0] bytes [0:ROWS-1];
            reg [7:0] read_q;
            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    read_q <= 0;
                end else begin
                    if (in_fire && write_base < 256)
                        bytes[write_base[7:BANK_BITS]] <=
                            in_keep[lane] ? in_data[8*lane +: 8] : 8'b0;
                    if (engine == 1 && read_index < 256) begin
                        if (({24'b0,read_index[7:BANK_BITS],
                              {BANK_BITS{1'b0}}}+lane) < packet_bytes)
                            read_q <= bytes[read_index[7:BANK_BITS]];
                        else read_q <= 0;
                    end
                end
            end
            assign bank_q[lane] = read_q;
        end
        wire [7:0] octet = (scan_index < packet_bytes) ?
                           bank_q[scan_index[BANK_BITS-1:0]] : 8'b0;

        reg [3:0] state, ns;
        reg [511:0] header, nh;
        reg error_flag, ne, unsupported_flag, nu;
        reg [16:0] rel, nr, ip_end, ni_end, ip_start, ni_start;
        reg [16:0] header_len, nl, ext_len, nx_len;
        reg [7:0] high_byte, n_high, protocol, n_protocol;
        reg [7:0] ext_type, n_ext_type, ext_next, n_ext_next;
        reg [3:0] ext_count, n_ext_count;
        reg fragment_seen, n_fragment_seen, noninitial, n_noninitial;
        reg more_fragments, n_more;
        reg [31:0] ports, n_ports;
        reg [15:0] udp_length, n_udp_length;
        reg [7:0] dispatch_protocol;
        reg dispatch, type_done;
        reg [15:0] ether_type;
        reg [16:0] next_position, calculated_length;
        reg [511:0] final_header;
        reg eligible;
        wire [16:0] absolute_position = {8'b0,scan_index};

        always @* begin
            ns=state; nh=header; ne=error_flag; nu=unsupported_flag;
            nr=rel; ni_end=ip_end; ni_start=ip_start; nl=header_len;
            nx_len=ext_len; n_high=high_byte; n_protocol=protocol;
            n_ext_type=ext_type; n_ext_next=ext_next; n_ext_count=ext_count;
            n_fragment_seen=fragment_seen; n_noninitial=noninitial;
            n_more=more_fragments; n_ports=ports; n_udp_length=udp_length;
            dispatch=0; dispatch_protocol=protocol; type_done=0;
            ether_type={high_byte,octet};
            next_position=absolute_position+17'd1;
            calculated_length=0;
            if (scan_valid && scan_index < packet_bytes) begin
                nr=rel+17'd1;
                case (state)
                    ETH: begin
                        if (rel<6) nh[440:393]={header[432:393],octet};
                        else if (rel<12) nh[392:345]={header[384:345],octet};
                        if (rel==12) n_high=octet;
                        if (rel==13) type_done=1;
                    end
                    VLAN: begin
                        if (rel==0) n_high=octet;
                        if (rel==1) begin
                            if (header[304:303]==1)
                                nh[316:305]={high_byte[3:0],octet};
                            else nh[328:317]={high_byte[3:0],octet};
                        end
                        if (rel==2) n_high=octet;
                        if (rel==3) type_done=1;
                    end
                    IP4: begin
                        if (rel==0) begin
                            nh[299:296]=4;
                            if (octet[7:4]!=4 || octet[3:0]<5) ne=1;
                            nl={11'b0,octet[3:0],2'b0};
                        end
                        if (rel==2) n_high=octet;
                        if (rel==3) begin
                            ni_end=ip_start+{1'b0,high_byte,octet};
                            if ({1'b0,high_byte,octet}<header_len) ne=1;
                            if ({15'b0,ip_start}+{16'b0,high_byte,octet}>
                                packet_bytes) ne=1;
                        end
                        if (rel==6) begin
                            n_high=octet;
                            n_more=octet[5];
                            if (octet[7]) ne=1;
                        end
                        if (rel==7) begin
                            n_noninitial=(high_byte[4:0]!=0 || octet!=0);
                            nh[302]=more_fragments || n_noninitial;
                        end
                        if (rel==9) begin
                            n_protocol=octet;
                            nh[295:288]=octet;
                        end
                        if (rel>=12 && rel<16)
                            nh[31:0]={header[23:0],octet};
                        if (rel>=16 && rel<20)
                            nh[159:128]={header[151:128],octet};
                        if (rel+17'd1==header_len) begin
                            nh[300]=1;
                            nr=0;
                            if (noninitial) begin
                                ns=DONE;
                                if (protocol!=6 && protocol!=17) nu=1;
                            end else begin
                                dispatch=1;
                                dispatch_protocol=protocol;
                            end
                        end
                        if (scan_valid && scan_index >= packet_bytes && state != DONE) begin
                            ne=1;
                            ns=DONE;
                        end
                    end
                    IP6: begin
                        if (rel==0) begin
                            nh[299:296]=6;
                            if (octet[7:4]!=6) ne=1;
                        end
                        if (rel==4) n_high=octet;
                        if (rel==5) begin
                            ni_end=ip_start+17'd40+{1'b0,high_byte,octet};
                            if ({15'b0,ip_start}+32'd40+
                                {16'b0,high_byte,octet}>packet_bytes) ne=1;
                        end
                        if (rel==6) begin
                            n_protocol=octet;
                            nh[295:288]=octet;
                        end
                        if (rel>=8 && rel<24)
                            nh[127:0]={header[119:0],octet};
                        if (rel>=24 && rel<40)
                            nh[255:128]={header[247:128],octet};
                        if (rel==39) begin
                            nh[300]=1;
                            nr=0;
                            if (ip_end==ip_start+17'd40 && protocol!=59) begin
                                nu=1;
                                ns=DONE;
                            end else begin
                                dispatch=1;
                                dispatch_protocol=protocol;
                            end
                        end
                    end
                    EXT: begin
                        if (rel==0) n_ext_next=octet;
                        if (rel==1) begin
                            if (ext_type==44) calculated_length=8;
                            else if (ext_type==51)
                                calculated_length=({9'b0,octet}+17'd2)<<2;
                            else calculated_length=({9'b0,octet}+17'd1)<<3;
                            nx_len=calculated_length;
                            if ((ext_type==51 && calculated_length<12) ||
                                absolute_position-17'd1+calculated_length>ip_end)
                                ne=1;
                            if (absolute_position-17'd1+calculated_length>256) begin
                                nu=1;
                                ns=DONE;
                            end
                        end
                        if (ext_type==44 && rel==2) n_high=octet;
                        if (ext_type==44 && rel==3) begin
                            n_noninitial=(high_byte!=0 || octet[7:3]!=0);
                            n_more=octet[0];
                            nh[302]=n_noninitial || octet[0];
                        end
                        if (rel+17'd1==ext_len) begin
                            n_protocol=ext_next;
                            nh[295:288]=ext_next;
                            nr=0;
                            if (noninitial) begin
                                ns=DONE;
                                if (ext_next!=6 && ext_next!=17 && ext_next!=59)
                                    nu=1;
                            end else begin
                                dispatch=1;
                                dispatch_protocol=ext_next;
                            end
                        end
                    end
                    TCP: begin
                        if (rel<4) n_ports={ports[23:0],octet};
                        if (rel==12) begin
                            nl={11'b0,octet[7:4],2'b0};
                            if (octet[7:4]<5 ||
                                absolute_position-17'd12+
                                {11'b0,octet[7:4],2'b0}>ip_end) ne=1;
                            if (absolute_position-17'd12+
                                {11'b0,octet[7:4],2'b0}>256) begin
                                nu=1;
                                ns=DONE;
                            end
                        end
                        if (rel+17'd1==header_len) begin
                            nh[271:256]=ports[31:16];
                            nh[287:272]=ports[15:0];
                            nh[301]=1;
                            ns=DONE;
                        end
                    end
                    UDP: begin
                        if (rel<4) n_ports={ports[23:0],octet};
                        if (rel==4) n_high=octet;
                        if (rel==5) begin
                            n_udp_length={high_byte,octet};
                            if ({high_byte,octet}<8 ||
                                (!more_fragments &&
                                 absolute_position-17'd5+
                                 {1'b0,high_byte,octet}>ip_end)) ne=1;
                        end
                        if (rel==7) begin
                            nh[271:256]=ports[31:16];
                            nh[287:272]=ports[15:0];
                            nh[301]=1;
                            ns=DONE;
                        end
                    end
                    default: nr=0;
                endcase
                if (type_done) begin
                    nh[344:329]=ether_type;
                    nr=0;
                    if (ether_type==16'h8100 || ether_type==16'h88a8) begin
                        if (header[304:303]==2) begin
                            nu=1;
                            ns=DONE;
                        end else begin
                            nh[304:303]=header[304:303]+2'd1;
                            ns=VLAN;
                        end
                    end else if (ether_type==16'h0800) begin
                        ns=IP4; ni_start=next_position; nl=20;
                    end else if (ether_type==16'h86dd) begin
                        ns=IP6; ni_start=next_position; nl=40;
                    end else begin
                        nu=1; ns=DONE;
                    end
                end
                if (dispatch) begin
                    nr=0;
                    if (dispatch_protocol==6 || dispatch_protocol==17) begin
                        if (dispatch_protocol==6) begin ns=TCP; nl=20; end
                        else begin ns=UDP; nl=8; end
                        if (next_position+nl>ip_end) ne=1;
                        if (next_position+nl>256) begin nu=1; ns=DONE; end
                    end else if (header[299:296]==6 &&
                        (dispatch_protocol==0 || dispatch_protocol==43 ||
                         dispatch_protocol==60 || dispatch_protocol==44 ||
                         dispatch_protocol==51)) begin
                        if (ext_count==8) begin nu=1; ns=DONE; end
                        else begin
                            ns=EXT;
                            n_ext_type=dispatch_protocol;
                            n_ext_count=ext_count+1'b1;
                            nx_len=8;
                            if (dispatch_protocol==44) begin
                                if (fragment_seen) ne=1;
                                n_fragment_seen=1;
                            end
                            if (next_position+17'd8>ip_end) ne=1;
                            if (next_position+17'd8>256) begin nu=1; ns=DONE; end
                        end
                    end else begin
                        ns=DONE;
                        if (!(header[299:296]==6 && dispatch_protocol==59)) nu=1;
                    end
                end
            end
            final_header=header;
            final_header[442]=unsupported_flag;
            final_header[441]=error_flag || packet_bad ||
                packet_bytes<14 || packet_bytes>9216 || state!=DONE;
            if (final_header[441]) begin
                final_header=0;
                final_header[441]=1;
                final_header[442]=unsupported_flag;
            end
            eligible=final_header[300] && final_header[301] &&
                     !final_header[302] && !final_header[441] &&
                     !final_header[442] &&
                     (final_header[295:288]==6 || final_header[295:288]==17);
        end

        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                packet_open<=0; packet_bytes<=0; capture_base<=0; packet_bad<=0;
                engine<=0; read_index<=0; scan_index<=0; scan_valid<=0;
                state<=ETH; header<=0; error_flag<=0; unsupported_flag<=0;
                rel<=0; ip_end<=0; ip_start<=0; header_len<=0; ext_len<=0;
                high_byte<=0; protocol<=0; ext_type<=0; ext_next<=0;
                ext_count<=0; fragment_seen<=0; noninitial<=0;
                more_fragments<=0; ports<=0; udp_length<=0;
                out_valid<=0; out_header<=0; out_tuple<=0;
                out_tuple_bits<=0; out_packet_bytes<=0;
            end else begin
                out_valid<=0;
                if (in_fire) begin
                    packet_open<=!in_last;
                    packet_bytes<=byte_next;
                    packet_bad<=bad_keep || (packet_open && packet_bad);
                    if (write_base<256) capture_base<=write_base+LANES;
                    else capture_base<=256;
                    if (in_last) begin
                        engine<=1; read_index<=0; scan_valid<=0;
                        state<=ETH; header<=0; error_flag<=0; unsupported_flag<=0;
                        rel<=0; ip_end<=0; ip_start<=0; header_len<=0; ext_len<=0;
                        high_byte<=0; protocol<=0; ext_type<=0; ext_next<=0;
                        ext_count<=0; fragment_seen<=0; noninitial<=0;
                        more_fragments<=0; ports<=0; udp_length<=0;
                    end
                end
                if (engine==1) begin
                    if (read_index<256) begin
                        scan_index<=read_index; scan_valid<=1;
                        read_index<=read_index+1'b1;
                    end else scan_valid<=0;
                    if (scan_valid) begin
                        state<=ns; header<=nh; error_flag<=ne; unsupported_flag<=nu;
                        rel<=nr; ip_end<=ni_end; ip_start<=ni_start;
                        header_len<=nl; ext_len<=nx_len; high_byte<=n_high;
                        protocol<=n_protocol; ext_type<=n_ext_type;
                        ext_next<=n_ext_next; ext_count<=n_ext_count;
                        fragment_seen<=n_fragment_seen; noninitial<=n_noninitial;
                        more_fragments<=n_more; ports<=n_ports; udp_length<=n_udp_length;
                        if (scan_index==255) engine<=2;
                    end
                end else if (engine==2) begin
                    engine<=0; out_valid<=1; out_header<=final_header;
                    out_packet_bytes<=packet_bytes;
                    out_tuple<=0; out_tuple_bits<=0;
                    if (eligible) begin
                        if (final_header[299:296]==4) begin
                            out_tuple<={final_header[31:0],final_header[159:128],
                                final_header[271:256],final_header[287:272],
                                final_header[295:288],192'b0};
                            out_tuple_bits<=104;
                        end else begin
                            out_tuple<={final_header[127:0],final_header[255:128],
                                final_header[271:256],final_header[287:272],
                                final_header[295:288]};
                            out_tuple_bits<=296;
                        end
                    end
                end
            end
        end
    end else begin : g_illegal
        initial $fatal(1,"PARAMETER ERROR: DATA_WIDTH must be 64 or 512");
        always @* begin
            out_valid=1'b0 & rst_n; out_header=0; out_tuple=0;
            out_tuple_bits=0; out_packet_bytes=0;
        end
    end endgenerate
endmodule
`default_nettype wire
