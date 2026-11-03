#include "model_ops.h"
#include <limits.h>
int32_t model_signed32(uint32_t v){return v<=INT32_MAX?(int32_t)v:(int32_t)((int64_t)v-INT64_C(4294967296));}
int8_t model_requant(int32_t acc,int32_t mult,uint8_t shift,int8_t zp){
 int64_t product=(int64_t)acc*mult,q=product;
 if(shift){int64_t den=INT64_C(1)<<shift,rem; q=product/den;rem=product%den;if(rem<0){rem+=den;q--;}if(rem>den/2||(rem==den/2&&q%2!=0))q++;}
 q+=zp;if(q>127)q=127;if(q< -128)q= -128;return (int8_t)q;
}
void model_relu(const int8_t *in,int8_t *out,size_t count){for(size_t i=0;i<count;i++)out[i]=in[i]<0?0:in[i];}
int model_pool2(const int8_t *in,int8_t *out,unsigned n,unsigned c,unsigned h,unsigned w){
 if(!in||!out||!n||!c||!h||!w||(h&1)||(w&1))return 1;
 for(unsigned bn=0;bn<n;bn++)for(unsigned ch=0;ch<c;ch++)for(unsigned y=0;y<h/2;y++)for(unsigned x=0;x<w/2;x++){
  size_t base=((size_t)bn*c+ch)*h*w+2*y*w+2*x;int8_t v=in[base];if(in[base+1]>v)v=in[base+1];if(in[base+w]>v)v=in[base+w];if(in[base+w+1]>v)v=in[base+w+1];out[((size_t)bn*c+ch)*(h/2)*(w/2)+y*(w/2)+x]=v;
 }return 0;
}
void model_fc(const int8_t *in,const int8_t *weights,const int32_t *bias,int32_t *out,unsigned features,unsigned classes){
 for(unsigned oc=0;oc<classes;oc++){uint32_t bits=(uint32_t)bias[oc];for(unsigned f=0;f<features;f++)bits+=(uint32_t)((int32_t)in[f]*weights[(size_t)oc*features+f]);out[oc]=model_signed32(bits);}
}
unsigned model_argmax(const int32_t *in,unsigned classes){unsigned selected=0;for(unsigned i=1;i<classes;i++)if(in[i]>in[selected])selected=i;return selected;}
int model_conv(const int8_t *in,const int8_t *weights,const int32_t *bias,const int32_t *mult,const uint8_t *shifts,int8_t *out,int32_t *accum,unsigned n,unsigned ci,unsigned co,unsigned h,unsigned w,unsigned pad,int8_t zp){
 if(!in||!weights||!bias||!mult||!shifts||!out||!accum||!n||n>2||!ci||ci>16||!co||co>16||!h||h>32||!w||w>32||pad>1||(pad==0&&(h<3||w<3)))return 1;
 for(unsigned oc=0;oc<co;oc++)if(shifts[oc]>62)return 1;
 unsigned ho=h+2*pad-2,wo=w+2*pad-2;
 for(unsigned bn=0;bn<n;bn++)for(unsigned oc=0;oc<co;oc++)for(unsigned y=0;y<ho;y++)for(unsigned x=0;x<wo;x++){
  uint32_t bits=(uint32_t)bias[oc];for(unsigned ic=0;ic<ci;ic++)for(unsigned ky=0;ky<3;ky++)for(unsigned kx=0;kx<3;kx++){
   int iy=(int)(y+ky)-(int)pad,ix=(int)(x+kx)-(int)pad;
   if(iy>=0&&iy<(int)h&&ix>=0&&ix<(int)w){int32_t product=(int32_t)in[(((size_t)bn*ci+ic)*h+(unsigned)iy)*w+(unsigned)ix]*weights[((size_t)oc*ci+ic)*9+ky*3+kx];bits+=(uint32_t)product;}
  }
  size_t at=(((size_t)bn*co+oc)*ho+y)*wo+x;accum[at]=model_signed32(bits);out[at]=model_requant(accum[at],mult[oc],shifts[oc],zp);
 }return 0;
}
