`timescale 1ns / 1ps

// RAM side of the frozen TM=2 / effective-TN=1 HLS interface.
// The packet parser drives load_* during LOADING. The HLS core owns RAMs
// only while core_active=1. The output packer drives drain_* afterward.
module hls_memory_bank (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        core_active,

    input  wire        load_inputs_we,
    input  wire [14:0] load_inputs_addr,
    input  wire [7:0]  load_inputs_data,
    input  wire        load_weights_we,
    input  wire [11:0] load_weights_addr,
    input  wire [7:0]  load_weights_data,
    input  wire        load_bias_we,
    input  wire [3:0]  load_bias_addr,
    input  wire [31:0] load_bias_data,
    input  wire        load_multipliers_we,
    input  wire [3:0]  load_multipliers_addr,
    input  wire [31:0] load_multipliers_data,
    input  wire        load_shifts_we,
    input  wire [3:0]  load_shifts_addr,
    input  wire [5:0]  load_shifts_data,

    input  wire [14:0] inputs_address0,
    input  wire        inputs_ce0,
    output wire [7:0]  inputs_q0,
    input  wire [11:0] weights_address0,
    input  wire        weights_ce0,
    output wire [7:0]  weights_q0,
    input  wire [3:0]  bias_address0,
    input  wire        bias_ce0,
    output wire [31:0] bias_q0,
    input  wire [3:0]  multipliers_address0,
    input  wire        multipliers_ce0,
    output wire [31:0] multipliers_q0,
    input  wire [3:0]  shifts_address0,
    input  wire        shifts_ce0,
    output wire [5:0]  shifts_q0,

    input  wire [14:0] outputs_address0,
    input  wire        outputs_ce0,
    input  wire        outputs_we0,
    input  wire [7:0]  outputs_d0,
    input  wire        drain_ce,
    input  wire [14:0] drain_addr,
    output wire [7:0]  drain_q,

    input  wire        accumulators_ce0,
    input  wire        accumulators_we0,
    output reg  [31:0] accumulator_write_count
);
    // The accumulator address and data from HLS are intentionally discarded.
    // They are not needed for the integrated INT8 result stream.
    hls_input_ram #(.DATA_WIDTH(8), .ADDR_WIDTH(15), .DEPTH(32768)) inputs_ram (
        .clk(clk), .rst_n(rst_n), .core_active(core_active),
        .load_we(load_inputs_we), .load_addr(load_inputs_addr), .load_data(load_inputs_data),
        .hls_ce(inputs_ce0), .hls_addr(inputs_address0), .hls_q(inputs_q0)
    );
    hls_input_ram #(.DATA_WIDTH(8), .ADDR_WIDTH(12), .DEPTH(2304)) weights_ram (
        .clk(clk), .rst_n(rst_n), .core_active(core_active),
        .load_we(load_weights_we), .load_addr(load_weights_addr), .load_data(load_weights_data),
        .hls_ce(weights_ce0), .hls_addr(weights_address0), .hls_q(weights_q0)
    );
    hls_input_ram #(.DATA_WIDTH(32), .ADDR_WIDTH(4), .DEPTH(16)) bias_ram (
        .clk(clk), .rst_n(rst_n), .core_active(core_active),
        .load_we(load_bias_we), .load_addr(load_bias_addr), .load_data(load_bias_data),
        .hls_ce(bias_ce0), .hls_addr(bias_address0), .hls_q(bias_q0)
    );
    hls_input_ram #(.DATA_WIDTH(32), .ADDR_WIDTH(4), .DEPTH(16)) multipliers_ram (
        .clk(clk), .rst_n(rst_n), .core_active(core_active),
        .load_we(load_multipliers_we), .load_addr(load_multipliers_addr),
        .load_data(load_multipliers_data),
        .hls_ce(multipliers_ce0), .hls_addr(multipliers_address0), .hls_q(multipliers_q0)
    );
    hls_input_ram #(.DATA_WIDTH(6), .ADDR_WIDTH(4), .DEPTH(16)) shifts_ram (
        .clk(clk), .rst_n(rst_n), .core_active(core_active),
        .load_we(load_shifts_we), .load_addr(load_shifts_addr), .load_data(load_shifts_data),
        .hls_ce(shifts_ce0), .hls_addr(shifts_address0), .hls_q(shifts_q0)
    );
    hls_output_ram #(.DATA_WIDTH(8), .ADDR_WIDTH(15), .DEPTH(32768)) outputs_ram (
        .clk(clk), .rst_n(rst_n), .core_active(core_active),
        .hls_ce(outputs_ce0), .hls_we(outputs_we0),
        .hls_addr(outputs_address0), .hls_data(outputs_d0),
        .drain_ce(drain_ce), .drain_addr(drain_addr), .drain_q(drain_q)
    );

    always @(posedge clk) begin
        if (!rst_n)
            accumulator_write_count <= 32'd0;
        else if (core_active && accumulators_ce0 && accumulators_we0)
            accumulator_write_count <= accumulator_write_count + 32'd1;
    end
endmodule
