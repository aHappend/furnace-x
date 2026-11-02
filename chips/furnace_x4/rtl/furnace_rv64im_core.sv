module furnace_rv64im_core (
    input wire clk, rst_n,
    input wire run, ext_irq,
    output wire halted,
    output wire req_valid,
    input wire req_ready,
    output wire req_write, req_instr,
    output wire [63:0] req_addr, req_wdata,
    output wire [7:0] req_wstrb,
    output wire [1:0] req_size,
    input wire rsp_valid,
    output wire rsp_ready,
    input wire [63:0] rsp_rdata,
    input wire rsp_error,
    output wire trap_valid,
    output wire [63:0] trap_cause, trap_pc,
    output wire bus_error
);
    localparam [3:0] BOUNDARY=0, FETCH_REQUEST=1, FETCH_RESPONSE=2,
        DECODE=3, EXECUTE=4, RETIRE=5, MEMORY_REQUEST=6,
        MEMORY_RESPONSE=7, M_ITERATE=8, M_NORMALIZE=9, M_SIGN=10,
        TRAP_ENTRY=11, SLEEP=12;
    reg enabled;
    reg [3:0] state;
    reg [63:0] x [0:31];
    reg [63:0] pc, operand_a, operand_b;
    reg [31:0] instruction;
    reg [63:0] next_pc_q, result_q, address_q, store_q;
    reg [4:0] destination_q;
    reg writeback_q, store_access_q, sleep_q, mret_q;
    reg [2:0] load_function_q;
    reg [1:0] size_q;
    reg [7:0] strobe_q;
    reg csr_write_q;
    reg [11:0] csr_address_q;
    reg [63:0] csr_value_q;
    reg [63:0] mstatus, mie, mtvec, mscratch, mepc, mcause, mtval;
    reg [63:0] mcycle, minstret;
    reg [63:0] fault_cause, fault_value, fault_pc;
    reg trap_pulse, bus_error_pulse;
    reg [63:0] last_trap_cause, last_trap_pc;

    reg [5:0] m_iteration;
    reg [2:0] m_function;
    reg m_word, m_negative_a, m_negative_b, m_zero_divisor;
    reg [63:0] m_dividend, m_divisor, m_quotient, m_remainder;
    reg [127:0] m_product, m_multiplicand;
    reg [63:0] m_multiplier;
    reg [127:0] m_normalized;
    wire [127:0] product_step = m_product +
        (m_multiplier[0] ? m_multiplicand : 128'b0);
    wire [64:0] remainder_shift = {m_remainder, m_dividend[63]};
    wire divide_subtract = remainder_shift >= {1'b0,m_divisor};
    wire [64:0] remainder_step = divide_subtract ?
        remainder_shift - {1'b0,m_divisor} : remainder_shift;
    wire [63:0] quotient_step = {m_quotient[62:0],divide_subtract};
    wire [127:0] signed_product = m_negative_a ^ m_negative_b ?
        (~m_normalized + 128'd1) : m_normalized;
    wire [63:0] signed_quotient = m_negative_a ^ m_negative_b ?
        (~m_normalized[63:0] + 64'd1) : m_normalized[63:0];
    wire [63:0] signed_remainder = m_negative_a ?
        (~m_normalized[127:64] + 64'd1) : m_normalized[127:64];
    wire [63:0] division_result = m_function[1] ?
        signed_remainder : (m_zero_divisor ? 64'hffffffffffffffff :
        signed_quotient);
    wire [63:0] multiplication_result = m_function==0 ?
        signed_product[63:0] : signed_product[127:64];
    wire [63:0] m_result = m_function[2] ? division_result :
        multiplication_result;

    wire active = rst_n && enabled;
    wire interrupt_pending = ext_irq && mie[11] && mstatus[3];
    assign halted = active && state==BOUNDARY && !run;
    assign req_valid = active &&
        (state==FETCH_REQUEST || state==MEMORY_REQUEST);
    assign req_instr = req_valid && state==FETCH_REQUEST;
    assign req_write = req_valid && state==MEMORY_REQUEST && store_access_q;
    assign req_addr = !req_valid ? 64'b0 :
        (state==FETCH_REQUEST ? pc : address_q);
    assign req_wdata = req_write ? store_q : 64'b0;
    assign req_wstrb = req_write ? strobe_q : 8'b0;
    assign req_size = !req_valid ? 2'b0 :
        (state==FETCH_REQUEST ? 2'd2 : size_q);
    assign rsp_ready = active &&
        (state==FETCH_RESPONSE || state==MEMORY_RESPONSE);
    assign trap_valid = active && trap_pulse;
    assign trap_cause = active ? last_trap_cause : 64'b0;
    assign trap_pc = active ? last_trap_pc : 64'b0;
    assign bus_error = active && bus_error_pulse;

    wire [6:0] opcode = instruction[6:0];
    wire [2:0] funct3 = instruction[14:12];
    wire [6:0] funct7 = instruction[31:25];
    wire [4:0] rd = instruction[11:7];
    wire [4:0] rs1 = instruction[19:15];
    wire [4:0] rs2 = instruction[24:20];
    wire [63:0] imm_i = {{52{instruction[31]}},instruction[31:20]};
    wire [63:0] imm_s = {{52{instruction[31]}},
        instruction[31:25],instruction[11:7]};
    wire [63:0] imm_b = {{51{instruction[31]}},instruction[31],
        instruction[7],instruction[30:25],instruction[11:8],1'b0};
    wire [63:0] imm_u = {{32{instruction[31]}},instruction[31:12],12'b0};
    wire [63:0] imm_j = {{43{instruction[31]}},instruction[31],
        instruction[19:12],instruction[20],instruction[30:21],1'b0};
    wire word_operation = opcode==7'h1b || opcode==7'h3b;
    wire [63:0] m_a_unsigned = word_operation ?
        {32'b0,operand_a[31:0]} : operand_a;
    wire [63:0] m_b_unsigned = word_operation ?
        {32'b0,operand_b[31:0]} : operand_b;
    wire m_a_signed = funct3==0 || funct3==1 || funct3==2 ||
        funct3==4 || funct3==6;
    wire m_b_signed = funct3==0 || funct3==1 || funct3==4 || funct3==6;
    wire m_a_sign = m_a_signed &&
        (word_operation ? operand_a[31] : operand_a[63]);
    wire m_b_sign = m_b_signed &&
        (word_operation ? operand_b[31] : operand_b[63]);
    wire [63:0] m_a_extended = word_operation && m_a_sign ?
        {32'hffffffff,operand_a[31:0]} : m_a_unsigned;
    wire [63:0] m_b_extended = word_operation && m_b_sign ?
        {32'hffffffff,operand_b[31:0]} : m_b_unsigned;
    wire [63:0] m_a_magnitude = m_a_sign ? ~m_a_extended+64'd1 : m_a_extended;
    wire [63:0] m_b_magnitude = m_b_sign ? ~m_b_extended+64'd1 : m_b_extended;

    reg [63:0] csr_read, csr_source, csr_new;
    reg csr_supported, csr_readonly, csr_do_write, csr_fault;
    always @* begin
        csr_read=0;
        csr_supported=1;
        csr_readonly=0;
        case (instruction[31:20])
            12'h300: csr_read=mstatus;
            12'h301: csr_read=64'h8000000000001100;
            12'h304: csr_read=mie;
            12'h305: csr_read=mtvec;
            12'h340: csr_read=mscratch;
            12'h341: csr_read=mepc;
            12'h342: csr_read=mcause;
            12'h343: csr_read=mtval;
            12'h344: csr_read=ext_irq ? 64'h800 : 64'b0;
            12'hb00: csr_read=mcycle;
            12'hb02: csr_read=minstret;
            12'hc00: begin csr_read=mcycle; csr_readonly=1; end
            12'hc02: begin csr_read=minstret; csr_readonly=1; end
            default: csr_supported=0;
        endcase
        csr_source=funct3[2] ? {59'b0,rs1} : operand_a;
        csr_do_write=funct3[1:0]==1 ||
            (funct3[1:0]!=0 && rs1!=0);
        case (funct3[1:0])
            2'd1: csr_new=csr_source;
            2'd2: csr_new=csr_read | csr_source;
            2'd3: csr_new=csr_read & ~csr_source;
            default: csr_new=csr_read;
        endcase
        csr_fault=!csr_supported || (csr_do_write && csr_readonly) ||
            (csr_do_write && instruction[31:20]==12'h305 && csr_new[1:0]!=0);
    end

    reg illegal, do_memory, do_m, do_sleep, do_mret, do_csr;
    reg do_writeback, do_store, take_branch, synchronous_trap;
    reg [63:0] result, next_pc, access_address, trap_code, trap_value;
    reg [31:0] word_result;
    reg [1:0] access_size;
    reg [7:0] access_strobes;
    wire signed [31:0] signed_word_operand = operand_a[31:0];
    wire [63:0] alu_rhs = opcode==7'h13 || opcode==7'h1b ? imm_i : operand_b;
    wire [2:0] access_alignment_mask = 3'b111 >> (3-access_size);
    always @* begin
        illegal=0; do_memory=0; do_m=0; do_sleep=0; do_mret=0; do_csr=0;
        do_writeback=0; do_store=0; take_branch=0; synchronous_trap=0;
        result=0; word_result=0; next_pc=pc+64'd4; access_address=0;
        trap_code=0; trap_value=0; access_size=0; access_strobes=0;
        case (opcode)
            7'h37: begin result=imm_u; do_writeback=1; end
            7'h17: begin result=pc+imm_u; do_writeback=1; end
            7'h6f: begin
                result=pc+64'd4; next_pc=pc+imm_j; do_writeback=1;
            end
            7'h67: begin
                if (funct3!=0) illegal=1;
                result=pc+64'd4;
                next_pc=(operand_a+imm_i) & ~64'd1;
                do_writeback=1;
            end
            7'h63: begin
                case (funct3)
                    0: take_branch=operand_a==operand_b;
                    1: take_branch=operand_a!=operand_b;
                    4: take_branch=$signed(operand_a)<$signed(operand_b);
                    5: take_branch=$signed(operand_a)>=$signed(operand_b);
                    6: take_branch=operand_a<operand_b;
                    7: take_branch=operand_a>=operand_b;
                    default: illegal=1;
                endcase
                if (take_branch) next_pc=pc+imm_b;
            end
            7'h03,7'h23: begin
                do_store=opcode==7'h23;
                do_memory=1; do_writeback=!do_store;
                access_size=funct3[1:0];
                access_address=operand_a+(do_store ? imm_s : imm_i);
                access_strobes=8'hff >> (8-(1<<access_size));
                if ((do_store && funct3>3) || (!do_store && funct3==7))
                    illegal=1;
                if ((access_address[2:0] & access_alignment_mask)!=0) begin
                    synchronous_trap=1;
                    trap_code=do_store ? 64'd6 : 64'd4;
                    trap_value=access_address;
                end
            end
            7'h13,7'h33: begin
                do_writeback=1;
                if (opcode==7'h33 && funct7==1) do_m=1;
                else begin
                    if (opcode==7'h33 && funct7!=0 &&
                        !(funct7==7'h20 && (funct3==0 || funct3==5)))
                        illegal=1;
                    case (funct3)
                        0: result=opcode==7'h33 && funct7==7'h20 ?
                            operand_a-alu_rhs : operand_a+alu_rhs;
                        1: begin
                            result=operand_a << alu_rhs[5:0];
                            if (opcode==7'h13 && instruction[31:26]!=0) illegal=1;
                        end
                        2: result={63'b0,$signed(operand_a)<$signed(alu_rhs)};
                        3: result={63'b0,operand_a<alu_rhs};
                        4: result=operand_a ^ alu_rhs;
                        5: begin
                            if (instruction[30]) result=$signed(operand_a) >>> alu_rhs[5:0];
                            else result=operand_a >> alu_rhs[5:0];
                            if (opcode==7'h13 && instruction[31:26]!=0 &&
                                instruction[31:26]!=6'h10) illegal=1;
                        end
                        6: result=operand_a | alu_rhs;
                        7: result=operand_a & alu_rhs;
                    endcase
                end
            end
            7'h1b,7'h3b: begin
                do_writeback=1;
                if (opcode==7'h3b && funct7==1) begin
                    do_m=1;
                    if (funct3!=0 && funct3<4) illegal=1;
                end else begin
                    if (opcode==7'h3b && funct7!=0 &&
                        !(funct7==7'h20 && (funct3==0 || funct3==5)))
                        illegal=1;
                    case (funct3)
                        0: word_result=opcode==7'h3b && funct7==7'h20 ?
                            operand_a[31:0]-alu_rhs[31:0] :
                            operand_a[31:0]+alu_rhs[31:0];
                        1: begin
                            word_result=operand_a[31:0] << alu_rhs[4:0];
                            if (opcode==7'h1b && funct7!=0) illegal=1;
                        end
                        5: begin
                            if (instruction[30])
                                word_result=signed_word_operand >>> alu_rhs[4:0];
                            else word_result=operand_a[31:0] >> alu_rhs[4:0];
                            if (opcode==7'h1b && funct7!=0 && funct7!=7'h20)
                                illegal=1;
                        end
                        default: illegal=1;
                    endcase
                    result={{32{word_result[31]}},word_result};
                end
            end
            7'h0f: begin
                if (funct3==0) begin
                    if (instruction[31:28]!=0 || rs1!=0 || rd!=0) illegal=1;
                end else if (funct3==1) begin
                    if (instruction[31:15]!=0 || rd!=0) illegal=1;
                end else illegal=1;
            end
            7'h73: begin
                if (funct3==0) begin
                    case (instruction)
                        32'h00000073: begin
                            synchronous_trap=1; trap_code=11;
                        end
                        32'h00100073: begin
                            synchronous_trap=1; trap_code=3; trap_value=pc;
                        end
                        32'h30200073: begin do_mret=1; next_pc=mepc; end
                        32'h10500073: do_sleep=1;
                        default: illegal=1;
                    endcase
                end else if (funct3==4) illegal=1;
                else begin
                    do_csr=1; do_writeback=1; result=csr_read;
                    if (csr_fault) illegal=1;
                end
            end
            default: illegal=1;
        endcase
        if (next_pc[1:0]!=0) begin
            synchronous_trap=1; trap_code=0; trap_value=next_pc;
        end
        if (illegal) begin
            synchronous_trap=1; trap_code=2;
            trap_value={32'b0,instruction};
        end
    end

    reg [63:0] load_result;
    always @* begin
        case (load_function_q)
            0: load_result={{56{rsp_rdata[7]}},rsp_rdata[7:0]};
            1: load_result={{48{rsp_rdata[15]}},rsp_rdata[15:0]};
            2: load_result={{32{rsp_rdata[31]}},rsp_rdata[31:0]};
            3: load_result=rsp_rdata;
            4: load_result={56'b0,rsp_rdata[7:0]};
            5: load_result={48'b0,rsp_rdata[15:0]};
            6: load_result={32'b0,rsp_rdata[31:0]};
            default: load_result=0;
        endcase
    end

    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enabled<=0; state<=BOUNDARY; pc<=64'h10000;
            instruction<=0; operand_a<=0; operand_b<=0;
            next_pc_q<=0; result_q<=0; address_q<=0; store_q<=0;
            destination_q<=0; writeback_q<=0; store_access_q<=0;
            sleep_q<=0; mret_q<=0; load_function_q<=0;
            size_q<=0; strobe_q<=0; csr_write_q<=0;
            csr_address_q<=0; csr_value_q<=0;
            mstatus<=64'h1800; mie<=0; mtvec<=0; mscratch<=0;
            mepc<=0; mcause<=0; mtval<=0; mcycle<=0; minstret<=0;
            fault_cause<=0; fault_value<=0; fault_pc<=0;
            trap_pulse<=0; bus_error_pulse<=0;
            last_trap_cause<=0; last_trap_pc<=0;
            m_iteration<=0; m_function<=0; m_word<=0;
            m_negative_a<=0; m_negative_b<=0; m_zero_divisor<=0;
            m_dividend<=0; m_divisor<=0; m_quotient<=0; m_remainder<=0;
            m_product<=0; m_multiplicand<=0; m_multiplier<=0; m_normalized<=0;
            for (i=0;i<32;i=i+1) x[i]<=0;
        end else begin
            enabled<=1;
            trap_pulse<=0; bus_error_pulse<=0;
            if (enabled) mcycle<=mcycle+64'd1;
            x[0]<=0;
            case (state)
                BOUNDARY: if (enabled && run) begin
                    if (interrupt_pending) begin
                        fault_cause<=64'h800000000000000b;
                        fault_pc<=pc; fault_value<=0; state<=TRAP_ENTRY;
                    end else if (pc[1:0]!=0) begin
                        fault_cause<=0; fault_value<=pc;
                        fault_pc<=pc; state<=TRAP_ENTRY;
                    end else state<=FETCH_REQUEST;
                end
                FETCH_REQUEST: if (req_valid && req_ready) state<=FETCH_RESPONSE;
                FETCH_RESPONSE: if (rsp_valid && rsp_ready) begin
                    if (rsp_error) begin
                        fault_cause<=1; fault_value<=pc; fault_pc<=pc;
                        bus_error_pulse<=1; state<=TRAP_ENTRY;
                    end else begin
                        instruction<=rsp_rdata[31:0]; state<=DECODE;
                    end
                end
                DECODE: begin
                    operand_a<=rs1==0 ? 64'b0 : x[rs1];
                    operand_b<=rs2==0 ? 64'b0 : x[rs2];
                    state<=EXECUTE;
                end
                EXECUTE: begin
                    if (synchronous_trap) begin
                        fault_cause<=trap_code; fault_value<=trap_value;
                        fault_pc<=pc; state<=TRAP_ENTRY;
                    end else begin
                        result_q<=result; next_pc_q<=next_pc;
                        destination_q<=rd; writeback_q<=do_writeback;
                        sleep_q<=do_sleep; mret_q<=do_mret;
                        csr_write_q<=do_csr && csr_do_write;
                        csr_address_q<=instruction[31:20]; csr_value_q<=csr_new;
                        if (do_memory) begin
                            address_q<=access_address; store_q<=operand_b;
                            store_access_q<=do_store; size_q<=access_size;
                            strobe_q<=access_strobes; load_function_q<=funct3;
                            state<=MEMORY_REQUEST;
                        end else if (do_m) begin
                            m_iteration<=0; m_function<=funct3; m_word<=word_operation;
                            m_negative_a<=m_a_sign; m_negative_b<=m_b_sign;
                            m_zero_divisor<=m_b_magnitude==0;
                            m_dividend<=m_a_magnitude; m_divisor<=m_b_magnitude;
                            m_quotient<=0; m_remainder<=0; m_product<=0;
                            m_multiplicand<={64'b0,m_a_magnitude};
                            m_multiplier<=m_b_magnitude;
                            state<=M_ITERATE;
                        end else state<=RETIRE;
                    end
                end
                MEMORY_REQUEST: if (req_valid && req_ready) state<=MEMORY_RESPONSE;
                MEMORY_RESPONSE: if (rsp_valid && rsp_ready) begin
                    if (rsp_error) begin
                        fault_cause<=store_access_q ? 64'd7 : 64'd5;
                        fault_value<=address_q; fault_pc<=pc;
                        bus_error_pulse<=1; state<=TRAP_ENTRY;
                    end else begin
                        result_q<=load_result; state<=RETIRE;
                    end
                end
                M_ITERATE: begin
                    if (m_function[2]) begin
                        m_remainder<=remainder_step[63:0];
                        m_dividend<={m_dividend[62:0],1'b0};
                        m_quotient<=quotient_step;
                    end else begin
                        m_product<=product_step;
                        m_multiplicand<={m_multiplicand[126:0],1'b0};
                        m_multiplier<={1'b0,m_multiplier[63:1]};
                    end
                    m_iteration<=m_iteration+6'd1;
                    if (m_iteration==63) state<=M_NORMALIZE;
                end
                M_NORMALIZE: begin
                    if (m_function[2]) m_normalized<={m_remainder,m_quotient};
                    else m_normalized<=m_product;
                    state<=M_SIGN;
                end
                M_SIGN: begin
                    result_q<=m_word ? {{32{m_result[31]}},m_result[31:0]} : m_result;
                    state<=RETIRE;
                end
                RETIRE: begin
                    if (writeback_q && destination_q!=0) x[destination_q]<=result_q;
                    pc<=next_pc_q;
                    minstret<=minstret+64'd1;
                    if (csr_write_q) begin
                        case (csr_address_q)
                            12'h300: mstatus<=(csr_value_q & 64'h88) | 64'h1800;
                            12'h304: mie<=csr_value_q & 64'h800;
                            12'h305: mtvec<=csr_value_q;
                            12'h340: mscratch<=csr_value_q;
                            12'h341: mepc<=csr_value_q & ~64'd3;
                            12'h342: mcause<=csr_value_q;
                            12'h343: mtval<=csr_value_q;
                            12'hb00: mcycle<=csr_value_q;
                            12'hb02: minstret<=csr_value_q;
                            default: begin end
                        endcase
                    end
                    if (mret_q) begin
                        mstatus[3]<=mstatus[7]; mstatus[7]<=1;
                        mstatus[12:11]<=2'b11;
                    end
                    if (sleep_q && run) state<=SLEEP;
                    else state<=BOUNDARY;
                end
                SLEEP: if (!run || (ext_irq && mie[11])) state<=BOUNDARY;
                TRAP_ENTRY: begin
                    mepc<=fault_pc & ~64'd3;
                    mcause<=fault_cause; mtval<=fault_value;
                    mstatus[7]<=mstatus[3]; mstatus[3]<=0; mstatus[12:11]<=2'b11;
                    pc<=mtvec;
                    last_trap_cause<=fault_cause; last_trap_pc<=fault_pc;
                    trap_pulse<=1; state<=BOUNDARY;
                end
                default: begin
                    fault_cause<=2; fault_value<={32'b0,instruction};
                    fault_pc<=pc; state<=TRAP_ENTRY;
                end
            endcase
        end
    end
endmodule
