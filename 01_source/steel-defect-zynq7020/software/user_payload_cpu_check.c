/* Host-only check of the actual firmware model_ops against all four Golden
 * files and the three-stage FNV table. No DMA/PL emulation or accuracy claim. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "model_ops.h"
#include "model_params.h"
#include "batch_data.h"
static int8_t c1[4096],r1[4096],c2[8192],r2[8192],pool[2048];
static int32_t acc[8192],scores[6];
static unsigned char expected[8192];
static uint32_t hash(const void *ptr,size_t n){const unsigned char *p=ptr;uint32_t v=0x811c9dc5U;for(size_t i=0;i<n;i++)v=(v^p[i])*0x01000193U;return v;}
static int check(FILE *f,const void *actual,size_t n){return fread(expected,1,n,f)!=n||memcmp(expected,actual,n);}
int main(int argc,char **argv){
 if(argc!=6)return 2;
 FILE *f[5];for(unsigned i=0;i<5;i++){f[i]=fopen(argv[i+1],"rb");if(!f[i])return 3;}
 for(unsigned i=0;i<BATCH_COUNT;i++){
  if(model_conv(batch_inputs[i],model_weights_0,model_bias_0,model_mult_0,model_shifts_0,c1,acc,1,1,4,32,32,1,0))return 4;
  model_relu(c1,r1,sizeof r1);
  if(model_conv(r1,model_weights_1,model_bias_1,model_mult_1,model_shifts_1,c2,acc,1,4,8,32,32,1,0))return 5;
  model_relu(c2,r2,sizeof r2);if(model_pool2(r2,pool,1,8,32,32))return 6;
  model_fc(pool,fc_weights,fc_bias,scores,2048,6);
  if(memcmp(scores,batch_logits[i],sizeof scores)||model_argmax(scores,6)!=batch_predictions[i])return 7;
  if(check(f[0],c1,sizeof c1)||check(f[1],c2,sizeof c2)||check(f[2],r1,sizeof r1)||check(f[3],pool,sizeof pool))return 8;
  unsigned char le[24];for(unsigned k=0;k<6;k++)for(unsigned b=0;b<4;b++)le[k*4+b]=(unsigned char)((uint32_t)scores[k]>>(b*8));
  uint32_t h[3]={hash(r1,sizeof r1),hash(pool,sizeof pool),hash(le,sizeof le)};
  for(unsigned k=0;k<3;k++){unsigned char bytes[4];for(unsigned b=0;b<4;b++)bytes[b]=(unsigned char)(h[k]>>(8*b));if(check(f[4],bytes,4))return 9;}
 }
 for(unsigned i=0;i<5;i++){if(fgetc(f[i])!=EOF)return 10;fclose(f[i]);}
 printf("HOST_FIRMWARE_MODEL_OPS_GOLDEN_PASS samples=%u; NOT_PL_OR_FORMAL_RESULT\n",BATCH_COUNT);return 0;
}
