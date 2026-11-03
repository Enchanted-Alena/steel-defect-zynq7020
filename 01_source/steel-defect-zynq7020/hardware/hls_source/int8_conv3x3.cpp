#include "int8_conv3x3.h"

int8_value requantize_half_to_even(
    int32_value accumulator, int32_value multiplier,
    shift_value shift, int8_value zero_point) {
    // Inline so an unrolled TM lane receives an independent requant datapath.
#pragma HLS INLINE
    int64_value product = accumulator * multiplier;
    int64_value rounded = product;
    if (shift != 0) {
        int64_value denominator = int64_value(1) << shift;
        int64_value quotient = product >> shift;
        // Low bits equal the nonnegative remainder after arithmetic right shift.
        // A mask avoids a second wide multiplier; this is exact for negative values too.
        ap_uint<64> mask = ap_uint<64>(denominator) - 1;
        int64_value remainder = int64_value(ap_uint<64>(product) & mask);
        int64_value halfway = denominator >> 1;
        if (remainder > halfway || (remainder == halfway && quotient[0])) {
            quotient = quotient + 1;
        }
        rounded = quotient;
    }
    int64_value shifted = rounded + int64_value(zero_point);
    if (shifted > 127) {
        return int8_value(127);
    }
    if (shifted < -128) {
        return int8_value(-128);
    }
    return int8_value(shifted);
}

int int8_conv3x3(
    const int8_value inputs[MAX_INPUT_VALUES],
    const int8_value weights[MAX_WEIGHT_VALUES],
    const int32_value bias[MAX_OUTPUT_CHANNELS],
    const int32_value multipliers[MAX_OUTPUT_CHANNELS],
    const shift_value shifts[MAX_OUTPUT_CHANNELS],
    int8_value outputs[MAX_OUTPUT_VALUES],
    int32_value accumulators[MAX_OUTPUT_VALUES],
    int batch, int input_channels, int output_channels,
    int height, int width, int padding, int8_value zero_point,
    int post_op) {
    if (batch < 1 || batch > MAX_BATCH || input_channels < 1 ||
        input_channels > MAX_INPUT_CHANNELS || output_channels < 1 ||
        output_channels > MAX_OUTPUT_CHANNELS || height < 1 || height > MAX_HEIGHT ||
        width < 1 || width > MAX_WIDTH || (padding != 0 && padding != 1) ||
        post_op < 0 || post_op > 2 || (post_op != 0 && zero_point != 0)) {
        return 1;
    }
    int convolution_height = height + 2 * padding - 2;
    int convolution_width = width + 2 * padding - 2;
    if (convolution_height < 1 || convolution_width < 1 ||
        (post_op == 2 && ((convolution_height & 1) || (convolution_width & 1)))) {
        return 1;
    }
    int output_height = post_op == 2 ? convolution_height / 2 : convolution_height;
    int output_width = post_op == 2 ? convolution_width / 2 : convolution_width;
    validate_shifts:
    for (int channel = 0; channel < output_channels; ++channel) {
        if (shifts[channel] > 62) {
            return 2;
        }
    }
    int8_value input_tile[MAX_INPUT_CHANNELS][MAX_HEIGHT][MAX_WIDTH];
    int8_value weight_tile[MAX_OUTPUT_CHANNELS][MAX_INPUT_CHANNELS][KERNEL_SIZE][KERNEL_SIZE];
    int8_value line_buffer[MAX_INPUT_CHANNELS][LINE_BUFFER_ROWS][MAX_PADDED_WIDTH];
    int8_value window[MAX_INPUT_CHANNELS][KERNEL_SIZE][KERNEL_SIZE];
    int8_value output_tile[MAX_OUTPUT_CHANNELS][MAX_HEIGHT][MAX_WIDTH];
    int32_value accumulator_tile[MAX_OUTPUT_CHANNELS][MAX_HEIGHT][MAX_WIDTH];
    int32_value bias_tile[MAX_OUTPUT_CHANNELS];
    int32_value multiplier_tile[MAX_OUTPUT_CHANNELS];
    shift_value shift_tile[MAX_OUTPUT_CHANNELS];

    // Two alternating column banks keep feature storage in BRAM, not a huge register file.
    // Banking adds BRAM/mux overhead; one read/cycle already fits, and no parallel MAC
    // is implied. It leaves two independent banks for adjacent-column accesses.
#pragma HLS ARRAY_PARTITION variable=input_tile cyclic factor=2 dim=3
    // Simple dual-port BRAM supplies separate read/write ports without LUTRAM expansion.
#pragma HLS BIND_STORAGE variable=input_tile type=ram_s2p impl=bram
    // Nine spatial weight banks remove shared tap-port conflicts. LUTRAM avoids nine
    // mostly empty BRAMs; expect more LUTs but no additional DSPs unless MACs are unrolled.
#pragma HLS ARRAY_PARTITION variable=weight_tile complete dim=3
#pragma HLS ARRAY_PARTITION variable=weight_tile complete dim=4
#pragma HLS ARRAY_PARTITION variable=weight_tile cyclic factor=TM dim=1
#pragma HLS BIND_STORAGE variable=weight_tile type=ram_1p impl=lutram
    // Each historical row needs one read and one write on every window update.
    // Two row banks of simple dual-port BRAM avoid those four accesses sharing one RAM.
#pragma HLS ARRAY_PARTITION variable=line_buffer complete dim=2
#pragma HLS BIND_STORAGE variable=line_buffer type=ram_s2p impl=bram
    // Four Tn-style channel banks replace scalarizing all 16 channels.
    // The 3x3 tap dimensions stay independent so the unrolled shift still has nine ports.
    // Expected effect: each local bank/control cone drives at most four channels, reducing
    // the single FSM-enable fanout. LUTRAM stores the shallow banks instead of 1152 FF bits.
#pragma HLS ARRAY_PARTITION variable=window cyclic factor=WINDOW_CHANNEL_BANKS dim=1
#pragma HLS ARRAY_PARTITION variable=window complete dim=2
#pragma HLS ARRAY_PARTITION variable=window complete dim=3
#pragma HLS BIND_STORAGE variable=window type=ram_s2p impl=lutram
    // TM output-channel banks accept TM simultaneous convolution results. Results
    // are copied to the single external output memories after the spatial scan.
#pragma HLS ARRAY_PARTITION variable=output_tile cyclic factor=TM dim=1
#pragma HLS ARRAY_PARTITION variable=accumulator_tile cyclic factor=TM dim=1
#pragma HLS BIND_STORAGE variable=output_tile type=ram_s2p impl=bram
#pragma HLS BIND_STORAGE variable=accumulator_tile type=ram_s2p impl=bram
    // Small per-channel parameter registers avoid extra RAM-port scheduling constraints.
#pragma HLS ARRAY_PARTITION variable=bias_tile cyclic factor=TM dim=1
#pragma HLS ARRAY_PARTITION variable=multiplier_tile cyclic factor=TM dim=1
#pragma HLS ARRAY_PARTITION variable=shift_tile cyclic factor=TM dim=1

    load_output_channels:
    for (int output_channel = 0; output_channel < output_channels; ++output_channel) {
        bias_tile[output_channel] = bias[output_channel];
        multiplier_tile[output_channel] = multipliers[output_channel];
        shift_tile[output_channel] = shifts[output_channel];
        load_weight_channels:
        for (int input_channel = 0; input_channel < input_channels; ++input_channel) {
            load_weight_rows:
            for (int kernel_y = 0; kernel_y < KERNEL_SIZE; ++kernel_y) {
                load_weight_columns:
                for (int kernel_x = 0; kernel_x < KERNEL_SIZE; ++kernel_x) {
                    // One external weight/cycle; pipeline adds FF/control, not parallel DSPs.
#pragma HLS PIPELINE II=1
                    int weight_index = ((output_channel * input_channels + input_channel) * KERNEL_SIZE + kernel_y) * KERNEL_SIZE + kernel_x;
                    weight_tile[output_channel][input_channel][kernel_y][kernel_x] = weights[weight_index];
                }
            }
        }
    }

    int padded_height = height + 2 * padding;
    int padded_width = width + 2 * padding;
    int input_linear_index = 0;
    int output_linear_index = 0;
    int accumulator_linear_index = 0;
    batches:
    for (int batch_index = 0; batch_index < batch; ++batch_index) {
        load_input_channels:
        for (int input_channel = 0; input_channel < input_channels; ++input_channel) {
            load_input_rows:
            for (int input_y = 0; input_y < height; ++input_y) {
                load_input_columns:
                for (int input_x = 0; input_x < width; ++input_x) {
                    // Stage one pixel/cycle into BRAM; input is read once per batch.
#pragma HLS PIPELINE II=1
                    // The nested loops already visit flat NCHW order. A monotonic index
                    // removes four runtime multiplies from the pipelined address path.
                    input_tile[input_channel][input_y][input_x] = inputs[input_linear_index];
                    ++input_linear_index;
                }
            }
        }

        clear_line_channels:
        for (int input_channel = 0; input_channel < input_channels; ++input_channel) {
            clear_line_columns:
            for (int column = 0; column < padded_width; ++column) {
                // Two independent row banks permit two zero writes/cycle, no DSP cost.
#pragma HLS PIPELINE II=1
                clear_line_rows:
                for (int row = 0; row < LINE_BUFFER_ROWS; ++row) {
                    // Only the fixed two-row reset is unrolled; BRAM banks already exist.
#pragma HLS UNROLL
                    line_buffer[input_channel][row][column] = 0;
                }
            }
        }
        clear_window_channels:
        for (int input_channel = 0; input_channel < input_channels; ++input_channel) {
            clear_window_rows:
            for (int row = 0; row < KERNEL_SIZE; ++row) {
                // Unroll the fixed register reset; increases reset fanout, not DSP/BRAM use.
#pragma HLS UNROLL
                clear_window_columns:
                for (int column = 0; column < KERNEL_SIZE; ++column) {
#pragma HLS UNROLL
                    window[input_channel][row][column] = 0;
                }
            }
        }

        scan_rows:
        for (int padded_y = 0; padded_y < padded_height; ++padded_y) {
            scan_columns:
            for (int padded_x = 0; padded_x < padded_width; ++padded_x) {
                update_window_channels:
                for (int input_channel = 0; input_channel < input_channels; ++input_channel) {
                    // One channel window update/cycle; channels remain serial to share RAMs.
                    // This is not a whole-output-pixel II=1 claim. True recurrences are retained.
#pragma HLS PIPELINE II=1
                    int8_value activation = 0;
                    int input_y = padded_y - padding;
                    int input_x = padded_x - padding;
                    if (input_y >= 0 && input_y < height && input_x >= 0 && input_x < width) {
                        activation = input_tile[input_channel][input_y][input_x];
                    }
                    int8_value row_values[KERNEL_SIZE];
                    // Three scalar row taps become registers: simultaneous reads, no extra DSPs.
#pragma HLS ARRAY_PARTITION variable=row_values complete dim=1
                    row_values[0] = line_buffer[input_channel][0][padded_x];
                    row_values[1] = line_buffer[input_channel][1][padded_x];
                    row_values[2] = activation;
                    line_buffer[input_channel][0][padded_x] = row_values[1];
                    line_buffer[input_channel][1][padded_x] = activation;
                    shift_window_rows:
                    for (int row = 0; row < KERNEL_SIZE; ++row) {
                        // Three rows shift in parallel using only register wiring/mux LUTs.
#pragma HLS UNROLL
                        shift_window_columns:
                        for (int column = 0; column < KERNEL_SIZE - 1; ++column) {
                            // Two register moves per row: no extra feature reads or MAC units.
#pragma HLS UNROLL
                            window[input_channel][row][column] = window[input_channel][row][column + 1];
                        }
                        window[input_channel][row][KERNEL_SIZE - 1] = row_values[row];
                    }
                }

                if (padded_y >= KERNEL_SIZE - 1 && padded_x >= KERNEL_SIZE - 1) {
                    int output_y = padded_y - (KERNEL_SIZE - 1);
                    int output_x = padded_x - (KERNEL_SIZE - 1);
                    output_channel_blocks:
                    for (int output_channel_base = 0; output_channel_base < output_channels; output_channel_base += TM) {
                        int32_value lane_accumulator[TM];
#pragma HLS ARRAY_PARTITION variable=lane_accumulator complete dim=1
                        initialize_output_lanes:
                        for (int lane = 0; lane < TM; ++lane) {
#pragma HLS UNROLL
                            int output_channel = output_channel_base + lane;
                            lane_accumulator[lane] = output_channel < output_channels
                                ? bias_tile[output_channel] : int32_value(0);
                        }
                        mac_input_channels:
                        for (int input_channel = 0; input_channel < input_channels; ++input_channel) {
                            // Keep Cin serial: each tap broadcasts to TM MACs. Preserve channel order.
#pragma HLS LOOP_FLATTEN off
                            mac_rows:
                            for (int kernel_y = 0; kernel_y < KERNEL_SIZE; ++kernel_y) {
                                mac_columns:
                                for (int kernel_x = 0; kernel_x < KERNEL_SIZE; ++kernel_x) {
                                    // Target TM INT8 MACs/cycle. Pipeline uses extra FFs/control;
                                    // the INT32 feedback adder must fit the clock for actual II=1.
                                    // Spatial loops are NOT unrolled: no nine-DSP replication.
#pragma HLS PIPELINE II=1
                                    int8_value activation = window[input_channel][kernel_y][kernel_x];
                                    int16_product lane_product[TM];
#pragma HLS ARRAY_PARTITION variable=lane_product complete dim=1
                                    // TM output channels share one activation read. Cout banking
                                    // supplies one independent weight and one DSP MAC per lane.
                                    compute_output_channels:
                                    for (int lane = 0; lane < TM; ++lane) {
#pragma HLS UNROLL factor=TM
                                        int output_channel = output_channel_base + lane;
                                        if (output_channel < output_channels) {
                                            lane_product[lane] = activation * weight_tile[output_channel][input_channel][kernel_y][kernel_x];
#pragma HLS BIND_OP variable=lane_product op=mul impl=dsp
                                            // Explicit 32-bit assignment preserves modulo-2^32 wrap.
                                            lane_accumulator[lane] = int32_value(
                                                lane_accumulator[lane] + int32_value(lane_product[lane]));
                                        }
                                    }
                                }
                            }
                        }
                        store_output_lanes:
                        for (int lane = 0; lane < TM; ++lane) {
#pragma HLS UNROLL
                            int output_channel = output_channel_base + lane;
                            if (output_channel < output_channels) {
                                accumulator_tile[output_channel][output_y][output_x] = lane_accumulator[lane];
                                int8_value quantized = requantize_half_to_even(
                                    lane_accumulator[lane], multiplier_tile[output_channel],
                                    shift_tile[output_channel], zero_point);
                                // ReLU is monotonic and operates on the post-requant INT8 value.
                                // For mode 2, MaxPool is applied later to these ReLU values.
                                if (post_op != 0 && quantized < 0) quantized = 0;
                                output_tile[output_channel][output_y][output_x] = quantized;
                            }
                        }
                    }
                }
            }
        }

        // Keep the full-resolution INT32 accumulator stream unchanged for diagnostics.
        // The integrated wrapper currently discards this port; preserving it also
        // keeps the C/HLS reference interface useful in non-fused modes.
        if (post_op == 2) {
            copy_accumulator_channels:
            for (int output_channel = 0; output_channel < output_channels; ++output_channel) {
                copy_accumulator_rows:
                for (int output_y = 0; output_y < convolution_height; ++output_y) {
                    copy_accumulator_columns:
                    for (int output_x = 0; output_x < convolution_width; ++output_x) {
#pragma HLS PIPELINE II=1
                        accumulators[accumulator_linear_index] =
                            accumulator_tile[output_channel][output_y][output_x];
                        ++accumulator_linear_index;
                    }
                }
            }

            // Read each non-overlapping 2x2 window from the existing output BRAM.
            // Pooling is per channel, with no padding and stride 2. This adds no DSPs;
            // BRAM read scheduling/resource impact must still be measured after HLS.
            pool_output_channels:
            for (int output_channel = 0; output_channel < output_channels; ++output_channel) {
                pool_output_rows:
                for (int output_y = 0; output_y < output_height; ++output_y) {
                    pool_output_columns:
                    for (int output_x = 0; output_x < output_width; ++output_x) {
                        int source_y = output_y * 2;
                        int source_x = output_x * 2;
                        int8_value maximum = output_tile[output_channel][source_y][source_x];
                        int8_value candidate = output_tile[output_channel][source_y][source_x + 1];
                        if (candidate > maximum) maximum = candidate;
                        candidate = output_tile[output_channel][source_y + 1][source_x];
                        if (candidate > maximum) maximum = candidate;
                        candidate = output_tile[output_channel][source_y + 1][source_x + 1];
                        if (candidate > maximum) maximum = candidate;
                        outputs[output_linear_index] = maximum;
                        ++output_linear_index;
                    }
                }
            }
        } else {
            // Non-pool modes retain the frozen full-resolution output order.
            copy_output_channels:
            for (int output_channel = 0; output_channel < output_channels; ++output_channel) {
                copy_output_rows:
                for (int output_y = 0; output_y < output_height; ++output_y) {
                    copy_output_columns:
                    for (int output_x = 0; output_x < output_width; ++output_x) {
#pragma HLS PIPELINE II=1
                        outputs[output_linear_index] = output_tile[output_channel][output_y][output_x];
                        accumulators[accumulator_linear_index] = accumulator_tile[output_channel][output_y][output_x];
                        ++output_linear_index;
                        ++accumulator_linear_index;
                    }
                }
            }
        }
    }
    return 0;
}
