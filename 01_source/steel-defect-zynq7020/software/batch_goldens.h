#ifndef BATCH_GOLDENS_H
#define BATCH_GOLDENS_H
#include <stdint.h>
#ifdef HOST_TEST
extern const int8_t *batch_conv1_golden;
extern const int8_t *batch_conv2_golden;
extern const int8_t *batch_fused_conv1_relu_golden;
extern const int8_t *batch_fused_conv2_relu_pool_golden;
extern const uint32_t *batch_fused_stage_fnv;
#else
extern const int8_t _binary_conv1_golden_int8_bin_start[];
extern const int8_t _binary_conv2_golden_int8_bin_start[];
extern const int8_t _binary_fused_conv1_relu_golden_int8_bin_start[];
extern const int8_t _binary_fused_conv2_relu_pool_golden_int8_bin_start[];
extern const uint32_t _binary_batch_fused_stage_fnv_start[];
#define batch_conv1_golden _binary_conv1_golden_int8_bin_start
#define batch_conv2_golden _binary_conv2_golden_int8_bin_start
#define batch_fused_conv1_relu_golden _binary_fused_conv1_relu_golden_int8_bin_start
#define batch_fused_conv2_relu_pool_golden _binary_fused_conv2_relu_pool_golden_int8_bin_start
#define batch_fused_stage_fnv _binary_batch_fused_stage_fnv_start
#endif
#endif
