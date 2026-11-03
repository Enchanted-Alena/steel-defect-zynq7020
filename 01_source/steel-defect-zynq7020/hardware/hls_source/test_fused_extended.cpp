// Deterministic synthetic regression. No NEU images, weights or private golden.
#include "int8_conv3x3.h"
#include <cstdint>
#include <iostream>
#include <vector>
#include <algorithm>

static int8_value x[MAX_INPUT_VALUES],w[MAX_WEIGHT_VALUES],y[MAX_OUTPUT_VALUES];
static int32_value b[MAX_OUTPUT_CHANNELS],m[MAX_OUTPUT_CHANNELS],a[MAX_OUTPUT_VALUES];
static shift_value s[MAX_OUTPUT_CHANNELS];
struct Case {const char *name; int n,ci,co,h,wi,p,z,mode,variant;};

static int32_t signed32(uint32_t v) {
    return v <= 0x7fffffffU ? int32_t(v) : int32_t(int64_t(v)-0x100000000LL);
}
static int ref_quant(int32_t acc,int32_t mul,unsigned shift,int zp) {
    const int64_t product=int64_t(acc)*int64_t(mul);
    int64_t q=product;
    if(shift) {
        const int64_t divisor=int64_t(1)<<shift;
        q=product/divisor;
        int64_t remainder=product%divisor;
        if(remainder<0) remainder=-remainder;
        if(remainder>divisor/2 || (remainder==divisor/2 && (q%2)!=0))
            q+=product<0?-1:1;
    }
    q+=zp;
    return int(std::max<int64_t>(-128,std::min<int64_t>(127,q)));
}

static int run(const Case &c) {
    const int ho=c.h+2*c.p-2,wo=c.wi+2*c.p-2;
    const int count=c.n*c.co*ho*wo;
    for(int i=0;i<MAX_INPUT_VALUES;i++) x[i]=int((i*17+13)%255)-127;
    for(int i=0;i<MAX_WEIGHT_VALUES;i++) w[i]=int((i*5+7)%7)-3;
    for(int i=0;i<MAX_OUTPUT_CHANNELS;i++) {
        b[i]=c.variant==2 ? signed32(0x7fffffe0U+unsigned(i)*47U) : i*7-15;
        m[i]=c.variant==1 ? ((i&1)?-1:1) : ((i&1)?3:1);
        s[i]=c.variant==2 ? 24 : (c.variant==1 ? 1 : (i%3+3));
    }
    if(c.variant==1) {
        for(int i=0;i<MAX_WEIGHT_VALUES;i++) w[i]=0;
        for(int oc=0;oc<c.co;oc++) w[(oc*c.ci)*9+4]=1;
        for(int oc=0;oc<c.co;oc++) b[oc]=0;
    }
    std::vector<int32_t> expected_acc(count);
    std::vector<int> full(count);
    for(int n=0;n<c.n;n++) for(int oc=0;oc<c.co;oc++)
    for(int oy=0;oy<ho;oy++) for(int ox=0;ox<wo;ox++) {
        uint32_t sum=uint32_t(b[oc].to_int());
        for(int ic=0;ic<c.ci;ic++) for(int ky=0;ky<3;ky++) for(int kx=0;kx<3;kx++) {
            int iy=oy+ky-c.p,ix=ox+kx-c.p;
            if(iy>=0 && iy<c.h && ix>=0 && ix<c.wi) {
                int input=x[((n*c.ci+ic)*c.h+iy)*c.wi+ix].to_int();
                int weight=w[((oc*c.ci+ic)*3+ky)*3+kx].to_int();
                sum+=uint32_t(input*weight);
            }
        }
        const int j=((n*c.co+oc)*ho+oy)*wo+ox;
        expected_acc[j]=signed32(sum);
        int value=ref_quant(expected_acc[j],m[oc].to_int(),s[oc].to_uint(),c.z);
        full[j]=c.mode ? std::max(0,value) : value;
    }
    std::vector<int> expected;
    if(c.mode==2) {
        for(int n=0;n<c.n;n++) for(int oc=0;oc<c.co;oc++)
        for(int oy=0;oy<ho;oy+=2) for(int ox=0;ox<wo;ox+=2) {
            int value=0;
            for(int dy=0;dy<2;dy++) for(int dx=0;dx<2;dx++)
                value=std::max(value,full[((n*c.co+oc)*ho+oy+dy)*wo+ox+dx]);
            expected.push_back(value);
        }
    } else expected=full;
    int status=int8_conv3x3(x,w,b,m,s,y,a,c.n,c.ci,c.co,c.h,c.wi,c.p,c.z,c.mode);
    if(status) {std::cerr<<c.name<<" status="<<status<<std::endl; return 1;}
    for(unsigned i=0;i<expected.size();i++) if(y[i].to_int()!=expected[i]) {
        std::cerr<<c.name<<" output "<<i<<": "<<y[i]<<" expected "<<expected[i]<<std::endl;
        return 1;
    }
    for(int i=0;i<count;i++) if(a[i].to_int()!=expected_acc[i]) {
        std::cerr<<c.name<<" accumulator "<<i<<std::endl; return 1;
    }
    std::cout<<"SYNTHETIC_PASS "<<c.name<<" outputs="<<expected.size()<<" accumulators="<<count<<std::endl;
    return 0;
}

int main() {
    const Case cases[]={
        {"conv1_32_mode0",1,1,4,32,32,1,0,0,0},
        {"conv1_32_mode1",1,1,4,32,32,1,0,1,0},
        {"conv2_32_mode0",1,4,8,32,32,1,0,0,0},
        {"conv2_32_mode2",1,4,8,32,32,1,0,2,0},
        {"non_square_pad0_pool",1,2,3,6,8,0,0,2,0},
        {"two_batches_hls_only",2,2,3,4,6,1,0,2,0},
        {"positive_negative_ties",1,1,4,5,7,1,-7,0,1},
        {"relu_ties",1,1,4,6,6,1,0,1,1},
        {"int32_wrap_pool",1,4,4,4,4,1,0,2,2}
    };
    for(const Case &c:cases) if(run(c)) return 1;
    s[0]=63;
    if(int8_conv3x3(x,w,b,m,s,y,a,1,1,1,4,4,1,0,0)!=2) return 2;
    s[0]=0;
    if(int8_conv3x3(x,w,b,m,s,y,a,1,1,1,4,4,1,0,3)!=1) return 3;
    if(int8_conv3x3(x,w,b,m,s,y,a,1,1,1,5,4,1,0,2)!=1) return 4;
    if(int8_conv3x3(x,w,b,m,s,y,a,1,1,1,4,4,1,1,1)!=1) return 5;
    std::cout<<"PASS: 9 synthetic valid cases + 4 invalid cases; not private-model qualification"<<std::endl;
    return 0;
}
