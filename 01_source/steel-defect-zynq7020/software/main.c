#ifdef HOST_TEST
#include "host_platform.h"
#else
#include "platform.h"
#endif
#include <stdint.h>
#include <string.h>
#include "timing.h"
#include "model_ops.h"
#include "model_params.h"
#include "board_vectors.h"
#include "batch_data.h"
#include "batch_goldens.h"
#if !BATCH_DATA_FORMAL && !defined(HOST_TEST) && !defined(OFFLINE_FIXTURE_BUILD)
#error "No formal C dataset; fixture firmware must never be downloaded"
#endif
#define REPEATS 3U
enum { MODE_ARM_REFERENCE=0U, MODE_PL_BASELINE=1U, MODE_PL_FUSED_POSTOP=2U, MODE_COUNT=3U };
static volatile unsigned timed_active;
#include "dma_driver.inc"
static int8_t input_copy[1024],c1[4096],r1[4096],c2[8192],r2[8192],pool[2048];
static int32_t accum[8192],logits[6];
static void put64(uint64_t value){puthex((u32)(value>>32));puthex((u32)value);}
static int infer(unsigned mode,const int8_t *input){
 memcpy(input_copy,input,sizeof(input_copy));previous_job=-1;guard_errors=0;dma_completed=0;memset(dma_status,0,sizeof dma_status);
 if(mode==MODE_ARM_REFERENCE){
  if(model_conv(input_copy,model_weights_0,model_bias_0,model_mult_0,model_shifts_0,c1,accum,1,1,4,32,32,1,0))return fail("ARM conv1");
  model_relu(c1,r1,sizeof r1);
 }else if(mode==MODE_PL_BASELINE){
  if(run_job(0,input_copy,0U)){return XST_FAILURE;}
  memcpy(c1,rx,sizeof c1);model_relu(c1,r1,sizeof r1);
 }else if(mode==MODE_PL_FUSED_POSTOP){
  if(run_job(0,input_copy,1U)){return XST_FAILURE;}
  memcpy(r1,rx,sizeof r1);memset(c1,0,sizeof c1);
 }else return fail("invalid mode");
 if(mode==MODE_PL_FUSED_POSTOP){
  if(run_job(1,r1,2U)){return XST_FAILURE;}
  memcpy(pool,rx,sizeof pool);
  memset(c2,0,sizeof c2);memset(r2,0,sizeof r2);
 }else{
  if(mode==MODE_PL_BASELINE){if(run_job(1,r1,0U))return XST_FAILURE;memcpy(c2,rx,sizeof c2);}
  else if(model_conv(r1,model_weights_1,model_bias_1,model_mult_1,model_shifts_1,c2,accum,1,4,8,32,32,1,0))return fail("ARM conv2");
  model_relu(c2,r2,sizeof r2);
  if(model_pool2(r2,pool,1,8,32,32))return fail("pool");
 }
 model_fc(pool,fc_weights,fc_bias,logits,2048,6);
 /* argmax is intentionally inside the timed inference boundary. */
 return (int)model_argmax(logits,6);
}
static int evaluate(unsigned mode,unsigned phase,unsigned index,unsigned repeat){
 current_job=0;
 board_uart_drain(); /* Drain preceding UART output BEFORE starting the timer. */
 timed_active=1;uint64_t start=timer_now();
 if(phase==0)cold_cache_prepare();
 int pred=infer(mode,batch_inputs[index]);
 uint64_t end=timer_now();timed_active=0;
 if(board_result==0xBAD00002U)return XST_FAILURE;
 if(end<=start)return fail("timer did not advance");
 if(guard_errors)return fail("DMA guard");
 if(pred<0||(unsigned)pred!=batch_predictions[index]||memcmp(logits,batch_logits[index],sizeof logits))return fail("reference logits/prediction mismatch");
 u32 hashes[3]={fnv((u8*)r1,sizeof r1),fnv((u8*)pool,sizeof pool),fnv((u8*)logits,sizeof logits)};
 if(memcmp(hashes,batch_fused_stage_fnv+index*3U,sizeof hashes))return fail("C golden output-stage hash mismatch");
 if(phase==2&&(memcmp(r1,batch_fused_conv1_relu_golden+index*4096U,sizeof r1)||
                memcmp(pool,batch_fused_conv2_relu_pool_golden+index*2048U,sizeof pool)))
  return fail("accuracy pass fused-stage byte mismatch");
 if(phase==2&&mode!=MODE_PL_FUSED_POSTOP&&
    (memcmp(c1,batch_conv1_golden+index*4096U,sizeof c1)||
     memcmp(c2,batch_conv2_golden+index*8192U,sizeof c2)))
  return fail("accuracy pass baseline conv byte mismatch");
 putstr("R,");puthex(mode);putstr(",");puthex(phase);putstr(",");puthex(index);putstr(",");puthex(repeat);putstr(",");put64(end-start);putstr(",");puthex((u32)pred);
 for(unsigned i=0;i<6;i++){putstr(",");puthex((u32)logits[i]);}
 for(unsigned i=0;i<3;i++){putstr(",");puthex(hashes[i]);}
 putstr(",");puthex(guard_errors);
 for(unsigned layer=0;layer<2;layer++)for(unsigned field=0;field<3;field++){putstr(",");puthex(dma_status[layer][field]);}
 putstr(",");puthex(dma_completed);putstr("\r\n");
 return XST_SUCCESS;
}
static int suite_main(void){
 board_result=1;uint64_t begin=timer_now();
 if(init_board()!=XST_SUCCESS)return fail("board init");
 if(Xil_In32(CNN+0x88)!=0x20000U||Xil_In32(CNN+0x8c)!=0x30102U||Xil_In32(CNN+0x90)!=1U)return fail("protocol/capability");
 uint64_t initialized=timer_now();
 putstr("\r\nBUILD=SMART_SL_COUNTER_PREDICT_20261017_FUSED_POSTOP_CANDIDATE SUITE=NEU_FULL270_FUSED_POSTOP_V2\r\n");
 putstr("DATA_FORMAL=");puthex(BATCH_DATA_FORMAL);putstr(" DATA_SHA256=");putstr(BATCH_MANIFEST_SHA256);putstr("\r\n");
 putstr("META,");puthex(BATCH_COUNT);putstr(",");puthex(REPEATS);putstr(",");put64(timer_hz());putstr("\r\n");
 putstr("INIT_TICKS,");put64(initialized-begin);putstr("\r\n");
 /* Three cache-cold first uses, each preceded by explicit cache maintenance.
    This is not a board power-on-to-result measurement. */
 for(unsigned mode=0;mode<MODE_COUNT;mode++)if(evaluate(mode,0,0,0))return XST_FAILURE;
 for(unsigned mode=0;mode<MODE_COUNT;mode++)if(evaluate(mode,1,0,0))return XST_FAILURE;
 /* One ascending-index accuracy pass per path, separate from performance. */
 for(unsigned mode=0;mode<MODE_COUNT;mode++)for(unsigned index=0;index<BATCH_COUNT;index++)
  if(evaluate(mode,2,index,0))return XST_FAILURE;
 /* At most three full ascending-index performance sweeps, rotating all paths. */
 for(unsigned repeat=0;repeat<REPEATS;repeat++)for(unsigned index=0;index<BATCH_COUNT;index++)
  for(unsigned offset=0;offset<MODE_COUNT;offset++){
   unsigned mode=(index+repeat+offset)%MODE_COUNT;
   if(evaluate(mode,3,index,repeat))return XST_FAILURE;
  }
 board_result=0x600D0270U;putstr("PASS: NEU_FULL270_FUSED_POSTOP_V2\r\n");return XST_SUCCESS;
}
#ifndef HOST_TEST
int main(void){int result=suite_main();board_led(result==XST_SUCCESS);for(;;)usleep(1000000);}
#endif
