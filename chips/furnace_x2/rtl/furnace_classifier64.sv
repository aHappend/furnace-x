`default_nettype none
module furnace_classifier64 (
    input wire clk, rst_n,
    input wire cfg_write, cfg_clear,
    input wire [5:0] cfg_index,
    input wire [511:0] cfg_value, cfg_mask,
    input wire [31:0] cfg_action,
    input wire cfg_enable,
    input wire in_valid,
    input wire [511:0] in_key,
    input wire [31:0] in_default_action,
    output reg out_valid, out_hit,
    output reg [5:0] out_index,
    output reg [31:0] out_action
);
    (* nomem2reg *) reg [511:0] values [0:63];
    (* nomem2reg *) reg [511:0] masks [0:63];
    (* nomem2reg *) reg [31:0] actions [0:63];
    reg [63:0] enabled;
    reg [511:0] value_q, mask_q, key_q, packet_key;
    reg [31:0] action_q, winner_action;
    reg enable_q, equal_q, found, busy;
    reg [5:0] rule_number, winner_index;
    reg [3:0] phase;
    wire chunk_equal = (((key_q[63:0] ^ value_q[63:0]) &
                         mask_q[63:0]) == 64'b0);
    wire current_wins = !found && enable_q && equal_q;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enabled <= 0;
        end else if (cfg_clear) begin
            enabled <= 0;
        end else if (cfg_write) begin
            enabled[cfg_index] <= cfg_enable;
        end
    end
    // Contents are protected by resettable enable bits, not reset RAM writes.
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            value_q <= 0;
            mask_q <= 0;
            action_q <= 0;
        end else begin
            if (cfg_write) begin
                values[cfg_index] <= cfg_value;
                masks[cfg_index] <= cfg_mask;
                actions[cfg_index] <= cfg_action;
            end
            if (in_valid && !busy) begin
                value_q <= values[0];
                mask_q <= masks[0];
                action_q <= actions[0];
            end else if (busy && phase == 9) begin
                value_q <= values[rule_number];
                mask_q <= masks[rule_number];
                action_q <= actions[rule_number];
            end else if (busy && phase < 8) begin
                value_q <= {64'b0,value_q[511:64]};
                mask_q <= {64'b0,mask_q[511:64]};
            end
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            key_q <= 0;
            packet_key <= 0;
            winner_action <= 0;
            enable_q <= 0;
            equal_q <= 0;
            found <= 0;
            busy <= 0;
            rule_number <= 0;
            winner_index <= 0;
            phase <= 0;
            out_valid <= 0;
            out_hit <= 0;
            out_index <= 0;
            out_action <= 0;
        end else begin
            out_valid <= 0;
            if (in_valid && !busy) begin
                packet_key <= in_key;
                key_q <= in_key;
                winner_action <= in_default_action;
                winner_index <= 0;
                found <= 0;
                busy <= 1;
                rule_number <= 0;
                phase <= 0;
                equal_q <= 1;
                enable_q <= enabled[0];
            end else if (busy) begin
                if (phase < 8) begin
                    equal_q <= equal_q && chunk_equal;
                    key_q <= {64'b0,key_q[511:64]};
                    phase <= phase + 1'b1;
                end else if (phase == 8) begin
                    if (current_wins) begin
                        found <= 1;
                        winner_action <= action_q;
                        winner_index <= rule_number;
                    end
                    if (rule_number == 63) begin
                        out_valid <= 1;
                        out_hit <= found || current_wins;
                        out_index <= current_wins ? rule_number : winner_index;
                        out_action <= current_wins ? action_q : winner_action;
                        busy <= 0;
                    end else begin
                        rule_number <= rule_number + 1'b1;
                        phase <= 9;
                    end
                end else begin
                    key_q <= packet_key;
                    equal_q <= 1;
                    enable_q <= enabled[rule_number];
                    phase <= 0;
                end
            end
        end
    end
endmodule
`default_nettype wire
