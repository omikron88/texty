// Generates a 3.5MHz clock-enable pulse from the 28MHz system clock.

module zx_clock_enable (
    input  wire clk_28mhz,
    input  wire reset_n,
    output reg  cpu_ce
);
    reg [2:0] div_cnt;

    always @(posedge clk_28mhz or negedge reset_n) begin
        if (!reset_n) begin
            div_cnt <= 3'd0;
            cpu_ce <= 1'b0;
        end else begin
            cpu_ce <= (div_cnt == 3'd7);
            div_cnt <= div_cnt + 3'd1;
        end
    end
endmodule
