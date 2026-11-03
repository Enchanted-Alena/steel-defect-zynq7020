#ifndef MODEL_OPS_H
#define MODEL_OPS_H
#include <stdint.h>
#include <stddef.h>
int32_t model_signed32(uint32_t v);
/* Caller supplies shift 0..62. model_conv validates exported shifts. */
int8_t model_requant(int32_t acc,int32_t mult,uint8_t shift,int8_t zp);
void model_relu(const int8_t *in,int8_t *out,size_t count);
int model_pool2(const int8_t *in,int8_t *out,unsigned n,unsigned c,unsigned h,unsigned w);
void model_fc(const int8_t *in,const int8_t *weights,const int32_t *bias,int32_t *out,unsigned features,unsigned classes);
unsigned model_argmax(const int32_t *in,unsigned classes);
int model_conv(const int8_t *in,const int8_t *weights,const int32_t *bias,const int32_t *mult,const uint8_t *shifts,int8_t *out,int32_t *accum,unsigned n,unsigned ci,unsigned co,unsigned h,unsigned w,unsigned pad,int8_t zp);
#endif
