#ifndef INT8_CONV3X3_H
#define INT8_CONV3X3_H

#include <ap_int.h>

#define TM 2

typedef ap_int<8> int8_value;
typedef ap_int<16> int16_product;
typedef ap_int<32> int32_value;
typedef ap_int<64> int64_value;
typedef ap_uint<6> shift_value;

static const int MAX_BATCH = 2;
static const int MAX_INPUT_CHANNELS = 16;
static const int MAX_OUTPUT_CHANNELS = 16;
static const int MAX_HEIGHT = 32;
static const int MAX_WIDTH = 32;
static const int KERNEL_SIZE = 3;
static const int LINE_BUFFER_ROWS = KERNEL_SIZE - 1;
static const int MAX_PADDED_HEIGHT = MAX_HEIGHT + 2;
static const int MAX_PADDED_WIDTH = MAX_WIDTH + 2;
static const int WINDOW_CHANNEL_BANKS = 4;
static const int MAX_INPUT_VALUES = MAX_BATCH * MAX_INPUT_CHANNELS * MAX_HEIGHT * MAX_WIDTH;
static const int MAX_WEIGHT_VALUES = MAX_OUTPUT_CHANNELS * MAX_INPUT_CHANNELS * 9;
static const int MAX_OUTPUT_VALUES = MAX_BATCH * MAX_OUTPUT_CHANNELS * MAX_HEIGHT * MAX_WIDTH;
static_assert(TM >= 1 && TM <= MAX_OUTPUT_CHANNELS, "TM must be within output-channel capacity");
static_assert(MAX_OUTPUT_CHANNELS % TM == 0, "MAX_OUTPUT_CHANNELS must be divisible by TM");

int8_value requantize_half_to_even(
    int32_value accumulator, int32_value multiplier,
    shift_value shift, int8_value zero_point);

// Flat external storage remains NCHW/OIHW; banking is applied to local tiles.
// Each batch is staged once. Two rows and a 3x3 window are kept per input channel.
// TM output lanes share each activation; Cin and taps stay serial with MAC II=1.
// INT32 overflow wraps; requant uses arithmetic shift, ties-to-even and INT8 clipping.
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
    int post_op);

#endif
