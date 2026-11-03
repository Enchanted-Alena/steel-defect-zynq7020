`timescale 1ns / 1ps
module clock_heartbeat #(
    parameter integer CLK_HZ = 100000000
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 clk CLK", X_INTERFACE_PARAMETER = "ASSOCIATED_RESET reset_n, FREQ_HZ 100000000" *)
    input wire clk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 reset_n RST", X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input wire reset_n,
    output reg led
);
    (* ASYNC_REG = "TRUE" *) reg [1:0] reset_release;
    reg [25:0] count;
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) reset_release <= 2'b00;
        else reset_release <= {reset_release[0], 1'b1};
    end
    always @(posedge clk) begin
        if (!reset_release[1]) begin count <= 0; led <= 0; end
        else if (count == CLK_HZ/2-1) begin count <= 0; led <= ~led; end
        else count <= count + 1'b1;
    end
endmodule