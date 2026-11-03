module furnace_x2_vision #(
    parameter integer IN_WIDTH=8, IN_HEIGHT=8,
    parameter integer OUT_WIDTH=8, OUT_HEIGHT=8
) (
    input wire clk, rst_n,
    input wire s_valid,
    output wire s_ready,
    input wire [7:0] s_data,
    input wire [15:0] s_id,
    input wire s_last,
    output wire m_valid,
    input wire m_ready,
    output wire [63:0] m_data,
    output wire [15:0] m_id,
    output wire [7:0] m_error
);
    function automatic [15:0] coordinate(
        input integer index, input integer input_size, input integer output_size
    );
        reg [31:0] numerator,denominator,quotient;
        reg [32:0] remainder;
        integer b;
        begin
            numerator=256*index*(input_size-1);
            denominator=output_size-1; quotient=0; remainder=0;
            if (output_size==1) coordinate=0;
            else begin
                for (b=31;b>=0;b=b-1) begin
                    remainder={remainder[31:0],numerator[b]};
                    if (remainder>={1'b0,denominator}) begin
                        remainder=remainder-{1'b0,denominator}; quotient[b]=1;
                    end
                end
                coordinate=quotient[15:0];
            end
        end
    endfunction
    function automatic [1:0] constant_slot(input integer row);
        integer r;
        reg [1:0] slot;
        begin
            slot=0;
            for (r=0;r<row;r=r+1) begin
                if (slot==2) slot=0; else slot=slot+1'b1;
            end
            constant_slot=slot;
        end
    endfunction
    generate if (IN_WIDTH<1 || IN_WIDTH>64 || IN_HEIGHT<1 || IN_HEIGHT>64 ||
        OUT_WIDTH<1 || OUT_WIDTH>64 || OUT_HEIGHT<1 || OUT_HEIGHT>64) begin: bad_parameter
        initial $fatal(1,"PARAMETER ERROR: image dimensions must be 1..64");
        assign s_ready=0; assign m_valid=0; assign m_data=0;
        assign m_id=0; assign m_error=0;
    end else begin: frontend
        function automatic [16:0] abs16(input signed [15:0] value);
            reg signed [16:0] wide;
            begin
                wide={value[15],value};
                if (value[15]) abs16=-wide; else abs16=wide;
            end
        endfunction
        localparam [4:0] COLLECT=0, B_READ=1, B_CAPTURE=2, B_SEND=3, B_WAIT=4,
            S_READ=5, S_CAPTURE=6, S_SEND=7, S_WAIT=8, TAIL=9,
            DIV_START=10, DIV_RUN=11, DRAIN=12, ERROR_TOKEN=13, OUTPUT_TOKEN=14,
            ROW_CHECK=15;
        reg enabled,output_valid,input_complete;
        reg [4:0] state,divide_step;
        reg [5:0] input_x,input_y,output_x,output_y,spatial_x,spatial_y;
        reg [6:0] loaded_rows;
        reg [12:0] input_count;
        reg [3:0] tap;
        reg [1:0] write_row_slot;
        reg [15:0] packet_id;
        reg [7:0] status;
        reg [63:0] answer;
        reg [31:0] bilinear_samples;
        reg [71:0] spatial_window;
        (* ramstyle="M20K", nomem2reg *) reg [7:0] input_lines [0:2*IN_WIDTH-1];
        (* ramstyle="M20K", nomem2reg *) reg [7:0] resized_lines [0:3*OUT_WIDTH-1];
        reg [7:0] input_q,resized_q;
        reg [31:0] accumulator [0:3];
        reg [31:0] numerator [0:3],quotient [0:3];
        reg [32:0] remainder [0:3];
        wire [32:0] shifted_remainder [0:3],next_remainder [0:3];
        wire [31:0] next_quotient [0:3];
        wire [15:0] x_coordinates [0:OUT_WIDTH-1];
        wire [15:0] y_coordinates [0:OUT_HEIGHT-1];
        wire [1:0] row_slots [0:OUT_HEIGHT-1];
        genvar g;
        for (g=0;g<OUT_WIDTH;g=g+1) begin: x_mapping
            localparam [15:0] Q=coordinate(g,IN_WIDTH,OUT_WIDTH);
            assign x_coordinates[g]=Q;
        end
        for (g=0;g<OUT_HEIGHT;g=g+1) begin: y_mapping
            localparam [15:0] Q=coordinate(g,IN_HEIGHT,OUT_HEIGHT);
            localparam [1:0] SLOT=constant_slot(g);
            assign y_coordinates[g]=Q;
            assign row_slots[g]=SLOT;
        end
        for (g=0;g<4;g=g+1) begin: dividers
            assign shifted_remainder[g]={remainder[g][31:0],numerator[g][31]};
            assign next_remainder[g]=(shifted_remainder[g]>=OUT_WIDTH*OUT_HEIGHT) ?
                shifted_remainder[g]-OUT_WIDTH*OUT_HEIGHT : shifted_remainder[g];
            assign next_quotient[g]={quotient[g][30:0],
                shifted_remainder[g]>=OUT_WIDTH*OUT_HEIGHT};
        end
        wire active=rst_n && enabled;
        wire take=s_valid && s_ready;
        wire [15:0] qx=x_coordinates[output_x],qy=y_coordinates[output_y];
        wire [7:0] x0=qx[15:8],y0=qy[15:8];
        wire [7:0] x1=(x0==IN_WIDTH-1) ? x0 : x0+1'b1;
        wire [7:0] y1=(y0==IN_HEIGHT-1) ? y0 : y0+1'b1;
        wire [7:0] line_write_address=(input_y[0] ? IN_WIDTH : 0)+input_x;
        wire [7:0] line_read_address=((tap[1] ? y1[0] : y0[0]) ? IN_WIDTH : 0)+
            (tap[0] ? x1 : x0);
        wire [7:0] resized_write_address=write_row_slot*OUT_WIDTH+output_x;
        reg [5:0] neighbor_x,neighbor_y;
        wire [7:0] resized_read_address=row_slots[neighbor_y]*OUT_WIDTH+neighbor_x;
        wire bilinear_ready,bilinear_valid,spatial_ready,spatial_valid;
        wire [7:0] bilinear_data;
        wire [63:0] spatial_data;
        wire [16:0] spatial_abs_x=abs16($signed(spatial_data[31:16]));
        wire [16:0] spatial_abs_y=abs16($signed(spatial_data[47:32]));
        wire [16:0] spatial_abs_l=abs16($signed(spatial_data[63:48]));
        assign s_ready=active && (state==COLLECT || state==TAIL || state==DRAIN);
        assign m_valid=active && output_valid;
        assign m_data=active ? answer : 64'b0;
        assign m_id=active ? packet_id : 16'b0;
        assign m_error=active ? status : 8'b0;
        always @* begin
            neighbor_y=spatial_y;
            neighbor_x=spatial_x;
            if (tap<3) begin
                if (spatial_y!=0) neighbor_y=spatial_y-1'b1;
            end else if (tap>=6) begin
                if (spatial_y!=OUT_HEIGHT-1) neighbor_y=spatial_y+1'b1;
            end
            if (tap==0 || tap==3 || tap==6) begin
                if (spatial_x!=0) neighbor_x=spatial_x-1'b1;
            end else if (tap==2 || tap==5 || tap==8) begin
                if (spatial_x!=OUT_WIDTH-1) neighbor_x=spatial_x+1'b1;
            end
        end
        furnace_bilinear_pipe bilinear_kernel (
            .clk(clk),.rst_n(rst_n),.s_valid(active && state==B_SEND),
            .s_ready(bilinear_ready),.s_samples(bilinear_samples),
            .s_xfrac(qx[7:0]),.s_yfrac(qy[7:0]),
            .m_valid(bilinear_valid),.m_ready(active && state==B_WAIT),.m_data(bilinear_data)
        );
        furnace_spatial3x3_pipe spatial_kernel (
            .clk(clk),.rst_n(rst_n),.s_valid(active && state==S_SEND),
            .s_ready(spatial_ready),.s_window(spatial_window),
            .m_valid(spatial_valid),.m_ready(active && state==S_WAIT),.m_data(spatial_data)
        );
        always @(posedge clk) begin
            if (take && state==COLLECT) input_lines[line_write_address]<=s_data;
            if (active && state==B_READ) input_q<=input_lines[line_read_address];
            if (active && state==B_WAIT && bilinear_valid)
                resized_lines[resized_write_address]<=bilinear_data;
            if (active && state==S_READ) resized_q<=resized_lines[resized_read_address];
        end
        integer i;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                enabled<=0; output_valid<=0; input_complete<=0;
                state<=COLLECT; divide_step<=0; input_x<=0; input_y<=0;
                output_x<=0; output_y<=0; spatial_x<=0; spatial_y<=0;
                loaded_rows<=0; input_count<=0; tap<=0; write_row_slot<=0;
                packet_id<=0; status<=0; answer<=0;
                bilinear_samples<=0; spatial_window<=0;
                for (i=0;i<4;i=i+1) begin
                    accumulator[i]<=0; numerator[i]<=0; quotient[i]<=0; remainder[i]<=0;
                end
            end else begin
                enabled<=1;
                case (state)
                    COLLECT:if (take) begin
                        if (input_x==IN_WIDTH-1) begin
                            input_x<=0; loaded_rows<=loaded_rows+1'b1;
                            if (input_y!=IN_HEIGHT-1) input_y<=input_y+1'b1;
                            if ({2'b0,input_y}==y1) begin tap<=0; state<=B_READ; end
                        end else input_x<=input_x+1'b1;
                    end
                    B_READ:state<=B_CAPTURE;
                    B_CAPTURE:begin
                        bilinear_samples[8*tap[1:0]+:8]<=input_q;
                        if (tap==3) state<=B_SEND;
                        else begin tap<=tap+1'b1; state<=B_READ; end
                    end
                    B_SEND:if (bilinear_ready) state<=B_WAIT;
                    B_WAIT:if (bilinear_valid) begin
                        if (output_x==OUT_WIDTH-1) begin
                            output_x<=0; spatial_x<=0; tap<=0;
                            if (output_y==0 && OUT_HEIGHT!=1) begin
                                output_y<=1; write_row_slot<=1;
                                state<=ROW_CHECK;
                            end else begin
                                if (output_y==0) spatial_y<=0;
                                else spatial_y<=output_y-1'b1;
                                state<=S_READ;
                            end
                        end else begin output_x<=output_x+1'b1; tap<=0; state<=B_READ; end
                    end
                    S_READ:state<=S_CAPTURE;
                    S_CAPTURE:begin
                        spatial_window[8*tap+:8]<=resized_q;
                        if (tap==8) state<=S_SEND;
                        else begin tap<=tap+1'b1; state<=S_READ; end
                    end
                    S_SEND:if (spatial_ready) state<=S_WAIT;
                    S_WAIT:if (spatial_valid) begin
                        accumulator[0]<=accumulator[0]+{16'b0,spatial_data[15:0]};
                        accumulator[1]<=accumulator[1]+{15'b0,spatial_abs_x};
                        accumulator[2]<=accumulator[2]+{15'b0,spatial_abs_y};
                        accumulator[3]<=accumulator[3]+{15'b0,spatial_abs_l};
                        tap<=0;
                        if (spatial_x==OUT_WIDTH-1) begin
                            spatial_x<=0;
                            if (output_y==OUT_HEIGHT-1) begin
                                if (spatial_y==OUT_HEIGHT-1) begin
                                    if (input_complete) state<=DIV_START; else state<=TAIL;
                                end else begin spatial_y<=output_y; state<=S_READ; end
                            end else begin
                                output_y<=output_y+1'b1;
                                if (write_row_slot==2) write_row_slot<=0;
                                else write_row_slot<=write_row_slot+1'b1;
                                state<=ROW_CHECK;
                            end
                        end else begin spatial_x<=spatial_x+1'b1; state<=S_READ; end
                    end
                    TAIL:if (take && s_last) state<=DIV_START;
                    ROW_CHECK:begin
                        tap<=0;
                        if ({1'b0,loaded_rows}>y1) state<=B_READ;
                        else state<=COLLECT;
                    end
                    DIV_START:begin
                        divide_step<=0;
                        for (i=0;i<4;i=i+1) begin
                            numerator[i]<=accumulator[i]; quotient[i]<=0; remainder[i]<=0;
                        end
                        state<=DIV_RUN;
                    end
                    DIV_RUN:begin
                        for (i=0;i<4;i=i+1) begin
                            numerator[i]<={numerator[i][30:0],1'b0};
                            quotient[i]<=next_quotient[i]; remainder[i]<=next_remainder[i];
                        end
                        if (divide_step==31) begin
                            answer<={next_quotient[3][15:0],next_quotient[2][15:0],
                                next_quotient[1][15:0],next_quotient[0][15:0]};
                            output_valid<=1; state<=OUTPUT_TOKEN;
                        end else divide_step<=divide_step+1'b1;
                    end
                    DRAIN:if (take && s_last) state<=ERROR_TOKEN;
                    ERROR_TOKEN:begin
                        answer<=0; status<=7; output_valid<=1; state<=OUTPUT_TOKEN;
                    end
                    OUTPUT_TOKEN:if (output_valid && m_ready) begin
                        output_valid<=0; input_complete<=0; input_count<=0;
                        input_x<=0; input_y<=0; output_x<=0; output_y<=0;
                        spatial_x<=0; spatial_y<=0; loaded_rows<=0; write_row_slot<=0;
                        status<=0; state<=COLLECT;
                        for (i=0;i<4;i=i+1) accumulator[i]<=0;
                    end
                    default:begin answer<=0; status<=7; state<=ERROR_TOKEN; end
                endcase
                if (take && (state==COLLECT || state==TAIL)) begin
                    input_count<=input_count+1'b1;
                    if (input_count==0) begin packet_id<=s_id; answer<=0; status<=0; end
                    if ((input_count!=0 && s_id!=packet_id) ||
                        s_last!=(input_count==IN_WIDTH*IN_HEIGHT-1)) begin
                        status<=7; answer<=0;
                        if (s_last) state<=ERROR_TOKEN; else state<=DRAIN;
                    end else if (s_last) input_complete<=1;
                end
            end
        end
    end endgenerate
endmodule
