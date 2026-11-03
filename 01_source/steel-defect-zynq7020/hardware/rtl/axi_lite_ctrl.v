`timescale 1ns / 1ps

// Protocol 2.0 control register bank. AW and W can arrive independently.
// One write response and one read response may be outstanding.
module axi_lite_ctrl (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [11:0] s_axi_awaddr,
    input  wire        s_axi_awvalid,
    output wire        s_axi_awready,
    input  wire [31:0] s_axi_wdata,
    input  wire [3:0]  s_axi_wstrb,
    input  wire        s_axi_wvalid,
    output wire        s_axi_wready,
    output reg  [1:0]  s_axi_bresp,
    output reg         s_axi_bvalid,
    input  wire        s_axi_bready,
    input  wire [11:0] s_axi_araddr,
    input  wire        s_axi_arvalid,
    output wire        s_axi_arready,
    output reg  [31:0] s_axi_rdata,
    output reg  [1:0]  s_axi_rresp,
    output reg         s_axi_rvalid,
    input  wire        s_axi_rready,

    input  wire [3:0]  current_state,
    input  wire        done_sticky,
    input  wire [12:0] error_status,
    input  wire [31:0] expected_input_bytes,
    input  wire [31:0] expected_output_bytes,
    input  wire        lengths_ready,
    input  wire [31:0] core_return,
    input  wire [63:0] start_cycle,
    input  wire [63:0] first_in_cycle,
    input  wire [63:0] last_in_cycle,
    input  wire [63:0] core_done_cycle,
    input  wire [63:0] first_out_cycle,
    input  wire [63:0] last_out_cycle,
    input  wire [63:0] input_stall_cycles,
    input  wire [63:0] output_stall_cycles,
    input  wire [63:0] active_cycles,
    output wire        irq,

    output reg  [31:0] cfg_batch,
    output reg  [31:0] cfg_input_channels,
    output reg  [31:0] cfg_output_channels,
    output reg  [31:0] cfg_height,
    output reg  [31:0] cfg_width,
    output reg  [31:0] cfg_padding,
    output reg  [31:0] cfg_zero_point,
    output reg  [31:0] cfg_post_op,
    output reg  [31:0] cfg_watchdog_limit,
    output reg  [1:0]  irq_enable,
    output reg         cmd_start,
    output reg         cmd_abort,
    output reg         cmd_clear_done,
    output reg         cmd_clear_error,
    output reg         cfg_write_busy,
    output reg         cfg_updated,
    output reg         bad_command,
    output reg  [12:0] error_w1c_mask
);
    reg aw_held, w_held;
    reg [11:0] held_awaddr;
    reg [31:0] held_wdata;
    reg [3:0] held_wstrb;
    wire busy = (current_state != 4'd0);
    wire [7:0] status_bits = {
        irq, (|error_status), done_sticky,
        (current_state == 4'd5),
        (current_state == 4'd3 || current_state == 4'd4),
        (current_state == 4'd2), (current_state == 4'd1),
        (current_state == 4'd0)
    };
    wire [31:0] control_word = held_wstrb[0] ? held_wdata : 32'd0;

    assign s_axi_awready = !aw_held && !s_axi_bvalid;
    assign s_axi_wready = !w_held && !s_axi_bvalid;
    assign s_axi_arready = !s_axi_rvalid &&
        ((s_axi_araddr != 12'h02C && s_axi_araddr != 12'h030) || lengths_ready);
    assign irq = (irq_enable[0] && done_sticky) ||
                 (irq_enable[1] && (|error_status));

    function [31:0] merge_bytes;
        input [31:0] old_value, new_value;
        input [3:0] strobes;
        integer byte_no;
        begin
            merge_bytes = old_value;
            for (byte_no = 0; byte_no < 4; byte_no = byte_no + 1)
                if (strobes[byte_no])
                    merge_bytes[8*byte_no +: 8] = new_value[8*byte_no +: 8];
        end
    endfunction

    function [31:0] masked_bytes;
        input [31:0] value;
        input [3:0] strobes;
        integer byte_no;
        begin
            masked_bytes = 32'd0;
            for (byte_no = 0; byte_no < 4; byte_no = byte_no + 1)
                if (strobes[byte_no])
                    masked_bytes[8*byte_no +: 8] = value[8*byte_no +: 8];
        end
    endfunction

    always @(posedge clk) begin
        if (!rst_n) begin
            aw_held <= 0; w_held <= 0;
            held_awaddr <= 0; held_wdata <= 0; held_wstrb <= 0;
            s_axi_bresp <= 0; s_axi_bvalid <= 0;
            s_axi_rdata <= 0; s_axi_rresp <= 0; s_axi_rvalid <= 0;
            cfg_batch <= 0; cfg_input_channels <= 0;
            cfg_output_channels <= 0; cfg_height <= 0;
            cfg_width <= 0; cfg_padding <= 0; cfg_zero_point <= 0;
            cfg_post_op <= 0;
            cfg_watchdog_limit <= 0; irq_enable <= 0;
            cmd_start <= 0; cmd_abort <= 0;
            cmd_clear_done <= 0; cmd_clear_error <= 0;
            cfg_write_busy <= 0; cfg_updated <= 0; bad_command <= 0;
            error_w1c_mask <= 0;
        end else begin
            cmd_start <= 0; cmd_abort <= 0;
            cmd_clear_done <= 0; cmd_clear_error <= 0;
            cfg_write_busy <= 0; cfg_updated <= 0; bad_command <= 0;
            error_w1c_mask <= 0;
            if (s_axi_awvalid && s_axi_awready) begin
                held_awaddr <= s_axi_awaddr;
                aw_held <= 1;
            end
            if (s_axi_wvalid && s_axi_wready) begin
                held_wdata <= s_axi_wdata;
                held_wstrb <= s_axi_wstrb;
                w_held <= 1;
            end
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 0;
            if (aw_held && w_held && !s_axi_bvalid) begin
                aw_held <= 0; w_held <= 0;
                s_axi_bvalid <= 1;
                s_axi_bresp <= 2'b00;
                if (!busy && |held_wstrb &&
                    (held_awaddr == 12'h010 || held_awaddr == 12'h014 ||
                     held_awaddr == 12'h018 || held_awaddr == 12'h01C ||
                     held_awaddr == 12'h020 || held_awaddr == 12'h024 ||
                     held_awaddr == 12'h028 ||
                     held_awaddr == 12'h094))
                    cfg_updated <= 1;
                case (held_awaddr)
                    12'h000: begin
                        if (control_word != 32'd0 && control_word != 32'd1 &&
                            control_word != 32'd2 && control_word != 32'd4 &&
                            control_word != 32'd8 && control_word != 32'd12) begin
                            bad_command <= 1;
                            s_axi_bresp <= 2'b10;
                        end else begin
                            cmd_start <= control_word[0];
                            cmd_abort <= control_word[1];
                            cmd_clear_done <= control_word[2];
                            cmd_clear_error <= control_word[3];
                        end
                    end
                    12'h008: begin
                        if (current_state == 4'd0 || current_state == 4'd6)
                            error_w1c_mask <= masked_bytes(held_wdata, held_wstrb);
                        else
                            s_axi_bresp <= 2'b10;
                    end
                    12'h00C: irq_enable <= merge_bytes({30'd0, irq_enable},
                                                       held_wdata, held_wstrb);
                    12'h010: if (busy) cfg_write_busy <= 1;
                             else cfg_batch <= merge_bytes(cfg_batch, held_wdata, held_wstrb);
                    12'h014: if (busy) cfg_write_busy <= 1;
                             else cfg_input_channels <= merge_bytes(cfg_input_channels, held_wdata, held_wstrb);
                    12'h018: if (busy) cfg_write_busy <= 1;
                             else cfg_output_channels <= merge_bytes(cfg_output_channels, held_wdata, held_wstrb);
                    12'h01C: if (busy) cfg_write_busy <= 1;
                             else cfg_height <= merge_bytes(cfg_height, held_wdata, held_wstrb);
                    12'h020: if (busy) cfg_write_busy <= 1;
                             else cfg_width <= merge_bytes(cfg_width, held_wdata, held_wstrb);
                    12'h024: if (busy) cfg_write_busy <= 1;
                             else cfg_padding <= merge_bytes(cfg_padding, held_wdata, held_wstrb);
                    12'h028: if (busy) cfg_write_busy <= 1;
                             else cfg_zero_point <= merge_bytes(cfg_zero_point, held_wdata, held_wstrb);
                    12'h094: if (busy) cfg_write_busy <= 1;
                             else cfg_post_op <= merge_bytes(cfg_post_op, held_wdata, held_wstrb);
                    12'h034: if (busy) cfg_write_busy <= 1;
                             else cfg_watchdog_limit <= merge_bytes(cfg_watchdog_limit, held_wdata, held_wstrb);
                    default: s_axi_bresp <= 2'b10;
                endcase
            end
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 0;
            if (s_axi_arvalid && s_axi_arready) begin
                s_axi_rvalid <= 1;
                s_axi_rresp <= 2'b00;
                case (s_axi_araddr)
                    12'h004: s_axi_rdata <= {24'd0, status_bits};
                    12'h008: s_axi_rdata <= {19'd0, error_status};
                    12'h00C: s_axi_rdata <= {30'd0, irq_enable};
                    12'h010: s_axi_rdata <= cfg_batch;
                    12'h014: s_axi_rdata <= cfg_input_channels;
                    12'h018: s_axi_rdata <= cfg_output_channels;
                    12'h01C: s_axi_rdata <= cfg_height;
                    12'h020: s_axi_rdata <= cfg_width;
                    12'h024: s_axi_rdata <= cfg_padding;
                    12'h028: s_axi_rdata <= cfg_zero_point;
                    12'h094: s_axi_rdata <= cfg_post_op;
                    12'h02C: s_axi_rdata <= expected_input_bytes;
                    12'h030: s_axi_rdata <= expected_output_bytes;
                    12'h034: s_axi_rdata <= cfg_watchdog_limit;
                    12'h038: s_axi_rdata <= core_return;
                    12'h03C: s_axi_rdata <= {28'd0, current_state};
                    12'h040: s_axi_rdata <= start_cycle[31:0];
                    12'h044: s_axi_rdata <= start_cycle[63:32];
                    12'h048: s_axi_rdata <= first_in_cycle[31:0];
                    12'h04C: s_axi_rdata <= first_in_cycle[63:32];
                    12'h050: s_axi_rdata <= last_in_cycle[31:0];
                    12'h054: s_axi_rdata <= last_in_cycle[63:32];
                    12'h058: s_axi_rdata <= core_done_cycle[31:0];
                    12'h05C: s_axi_rdata <= core_done_cycle[63:32];
                    12'h060: s_axi_rdata <= first_out_cycle[31:0];
                    12'h064: s_axi_rdata <= first_out_cycle[63:32];
                    12'h068: s_axi_rdata <= last_out_cycle[31:0];
                    12'h06C: s_axi_rdata <= last_out_cycle[63:32];
                    12'h070: s_axi_rdata <= input_stall_cycles[31:0];
                    12'h074: s_axi_rdata <= input_stall_cycles[63:32];
                    12'h078: s_axi_rdata <= output_stall_cycles[31:0];
                    12'h07C: s_axi_rdata <= output_stall_cycles[63:32];
                    12'h080: s_axi_rdata <= active_cycles[31:0];
                    12'h084: s_axi_rdata <= active_cycles[63:32];
                    12'h088: s_axi_rdata <= 32'h00020000;
                    12'h08C: s_axi_rdata <= 32'h00030102;
                    12'h090: s_axi_rdata <= 32'h00000001;
                    default: begin
                        s_axi_rdata <= 32'd0;
                        s_axi_rresp <= 2'b10;
                    end
                endcase
            end
        end
    end
endmodule
