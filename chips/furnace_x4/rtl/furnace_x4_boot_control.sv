module furnace_x4_boot_control (
    input wire clk, rst_n,
    input wire app_boot_ready, app_boot_error, app_halted,
    output wire app_start,
    output wire startup_error
);
    reg launched, start_q, error_q;
    assign app_start = rst_n && start_q && !error_q && !app_boot_error;
    assign startup_error = rst_n && error_q;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            launched <= 1'b0;
            start_q <= 1'b0;
            error_q <= 1'b0;
        end else begin
            start_q <= 1'b0;
            if (app_boot_error) begin
                error_q <= 1'b1;
                launched <= 1'b1;
            end else if (!launched && !error_q && app_boot_ready && app_halted) begin
                start_q <= 1'b1;
                launched <= 1'b1;
            end
        end
    end
endmodule
