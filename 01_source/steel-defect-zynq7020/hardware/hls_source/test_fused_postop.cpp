#include "int8_conv3x3.h"

#include <iostream>

static int8_value inputs[MAX_INPUT_VALUES];
static int8_value weights[MAX_WEIGHT_VALUES];
static int32_value bias[MAX_OUTPUT_CHANNELS];
static int32_value multipliers[MAX_OUTPUT_CHANNELS];
static shift_value shifts[MAX_OUTPUT_CHANNELS];
static int8_value outputs[MAX_OUTPUT_VALUES];
static int32_value accumulators[MAX_OUTPUT_VALUES];

static int check_equal(int actual, int expected, const char *label, int index) {
    if (actual == expected) return 0;
    std::cerr << label << " mismatch at " << index << ": "
              << actual << " != " << expected << std::endl;
    return 1;
}

int main() {
    const int source[16] = {
        -1, 2, -3, 4,
         5,-6,  7,-8,
         9,10,-11,12,
       -13,14, 15,-16
    };
    const int relu_expected[16] = {
         0, 2, 0, 4,
         5, 0, 7, 0,
         9,10, 0,12,
         0,14,15, 0
    };
    const int pool_expected[4] = {5, 7, 14, 15};

    for (int i = 0; i < 16; ++i) inputs[i] = source[i];
    weights[4] = 1;
    multipliers[0] = 1;
    shifts[0] = 0;

    int failures = 0;
    int status = int8_conv3x3(inputs, weights, bias, multipliers, shifts,
                              outputs, accumulators, 1, 1, 1, 4, 4, 1, 0, 0);
    failures += check_equal(status, 0, "passthrough status", 0);
    for (int i = 0; i < 16; ++i) {
        failures += check_equal(outputs[i].to_int(), source[i], "passthrough", i);
        failures += check_equal(accumulators[i].to_int(), source[i], "accumulator", i);
    }

    status = int8_conv3x3(inputs, weights, bias, multipliers, shifts,
                          outputs, accumulators, 1, 1, 1, 4, 4, 1, 0, 1);
    failures += check_equal(status, 0, "relu status", 0);
    for (int i = 0; i < 16; ++i)
        failures += check_equal(outputs[i].to_int(), relu_expected[i], "relu", i);

    status = int8_conv3x3(inputs, weights, bias, multipliers, shifts,
                          outputs, accumulators, 1, 1, 1, 4, 4, 1, 0, 2);
    failures += check_equal(status, 0, "pool status", 0);
    for (int i = 0; i < 4; ++i)
        failures += check_equal(outputs[i].to_int(), pool_expected[i], "relu_pool", i);
    for (int i = 0; i < 16; ++i)
        failures += check_equal(accumulators[i].to_int(), source[i], "pool accumulator", i);

    failures += check_equal(
        int8_conv3x3(inputs, weights, bias, multipliers, shifts, outputs, accumulators,
                     1, 1, 1, 4, 4, 1, 0, 3),
        1, "invalid mode", 0);
    failures += check_equal(
        int8_conv3x3(inputs, weights, bias, multipliers, shifts, outputs, accumulators,
                     1, 1, 1, 5, 4, 1, 0, 2),
        1, "odd pool shape", 0);
    failures += check_equal(
        int8_conv3x3(inputs, weights, bias, multipliers, shifts, outputs, accumulators,
                     1, 1, 1, 4, 4, 1, 1, 1),
        1, "fused nonzero zero-point", 0);

    if (failures) return 1;
    std::cout << "PASS: fused post-op CSim smoke" << std::endl;
    return 0;
}
