#define CNN 0x40000000U
#define DMA 0x40400000U
#define ALIGN64(x) (((x)+63U)&~63U)
#define TX_CAP ALIGN64(MAX_TX_BYTES)
#define RX_CAP ALIGN64(MAX_RX_BYTES)
static u8 tx_storage[TX_CAP+128U] __attribute__((aligned(64)));
static u8 rx_storage[RX_CAP+128U] __attribute__((aligned(64)));
static u8 *const tx=tx_storage+64U;
static u8 *const rx=rx_storage+64U;
static int previous_job=-1;
static u32 current_job;
static u32 guard_errors;
static u32 dma_status[2][3],dma_completed;
volatile u32 board_result;
static u32 fnv(const u8 *p,u32 n){u32 h=2166136261U;for(u32 i=0;i<n;i++)h=(h^p[i])*16777619U;return h;}
static int fail(const char *reason){ timed_active=0;
 putstr("FAIL: ");putstr(reason);putstr(" JOB=0x");puthex(current_job);
 putstr(" CNN_ERRORS=0x");puthex(Xil_In32(CNN+8));
 putstr(" MM2S=0x");puthex(Xil_In32(DMA+4));
 putstr(" S2MM=0x");puthex(Xil_In32(DMA+0x34));putstr("\r\n");
 board_result=0xBAD00002U;return XST_FAILURE;
}
static u32 job_output_bytes(const Job *c,u32 post_op){
 if(post_op>2U)return 0;
 u32 h_out=(u32)c->h+2U*(u32)c->p-2U;
 u32 w_out=(u32)c->w+2U*(u32)c->p-2U;
 if(!h_out||!w_out||(post_op==2U&&((h_out|w_out)&1U)))return 0;
 return (u32)c->n*(u32)c->co*h_out*w_out/(post_op==2U?4U:1U);
}
static int run_job(u32 index,const int8_t *actual_input,u32 post_op){
 const Job *c=&jobs[index];current_job=index;
 u32 expected_rx_bytes=job_output_bytes(c,post_op);
 if(!expected_rx_bytes||c->tx_bytes>16383U||expected_rx_bytes>16383U||
    c->tx_bytes>TX_CAP||expected_rx_bytes>RX_CAP||
    c->input_offset+c->input_bytes>c->tx_bytes)return fail("buffer bounds");
 memset(tx_storage,0xA5,sizeof(tx_storage));memcpy(tx,c->payload,c->tx_bytes);
 if(c->parent>=0&&previous_job!=c->parent)return fail("chain order");
 if(!actual_input)return fail("missing runtime input");
 memcpy(tx+c->input_offset,actual_input,c->input_bytes);

 memset(rx_storage,0xCD,sizeof(rx_storage));
 Xil_DCacheFlushRange((INTPTR)tx_storage,sizeof(tx_storage));
 Xil_DCacheFlushRange((INTPTR)rx_storage,sizeof(rx_storage));
 Xil_Out32(DMA,4);

 uint64_t deadline=timer_now()+2U*timer_hz();
 while(Xil_In32(DMA)&4U){if(timer_now()>=deadline)return fail("DMA reset timeout");}
 Xil_Out32(DMA+4,0x7000);Xil_Out32(DMA+0x34,0x7000);
 Xil_Out32(CNN,12);Xil_Out32(CNN+0x0c,0);
 Xil_Out32(CNN+0x10,(u32)c->n);Xil_Out32(CNN+0x14,(u32)c->ci);Xil_Out32(CNN+0x18,(u32)c->co);
 Xil_Out32(CNN+0x1c,(u32)c->h);Xil_Out32(CNN+0x20,(u32)c->w);Xil_Out32(CNN+0x24,(u32)c->p);
 Xil_Out32(CNN+0x28,(u32)c->z);Xil_Out32(CNN+0x34,200000000U);
 Xil_Out32(CNN+0x94,post_op);
 if(Xil_In32(CNN+0x94)!=post_op||Xil_In32(CNN+0x2c)!=c->tx_bytes||
    Xil_In32(CNN+0x30)!=expected_rx_bytes)return fail("stream lengths/post-op");
 Xil_Out32(DMA+0x30,1);Xil_Out32(DMA+0x48,(u32)(UINTPTR)rx);Xil_Out32(DMA+0x58,expected_rx_bytes);
 Xil_Out32(CNN,1);Xil_Out32(DMA,1);Xil_Out32(DMA+0x18,(u32)(UINTPTR)tx);Xil_Out32(DMA+0x28,c->tx_bytes);
 deadline=timer_now()+5U*timer_hz();
 for(;;){
  u32 txs=Xil_In32(DMA+4),rxs=Xil_In32(DMA+0x34);
  if((txs|rxs)&0x770U)return fail("DMA bus error");
  if(Xil_In32(CNN+8))return fail("CNN error");
  if((txs&2U)&&(rxs&2U)&&(Xil_In32(CNN+4)&0x20U))break;
  if(timer_now()>=deadline)return fail("completion timeout");
 }

 Xil_DCacheInvalidateRange((INTPTR)rx_storage,sizeof(rx_storage));
 Xil_DCacheInvalidateRange((INTPTR)tx_storage,sizeof(tx_storage));
 if(Xil_In32(CNN+8)||((Xil_In32(DMA+4)|Xil_In32(DMA+0x34))&0x770U))return fail("post-completion error");

 /* Retain layer 0 guards before layer 1 clears the buffers; report after timer. */
 for(u32 i=0;i<64U;i++)if(rx_storage[i]!=0xCD||tx_storage[i]!=0xA5)guard_errors++;
 for(u32 i=expected_rx_bytes;i<RX_CAP+64U;i++)if(rx[i]!=0xCD)guard_errors++;
 for(u32 i=c->tx_bytes;i<TX_CAP+64U;i++)if(tx[i]!=0xA5)guard_errors++;
 if(Xil_In32(DMA+0x58)!=expected_rx_bytes)return fail("S2MM byte count");
 if(Xil_In32(CNN+0x38))return fail("HLS return status");
 dma_status[index][0]=Xil_In32(CNN+8);dma_status[index][1]=Xil_In32(DMA+4);dma_status[index][2]=Xil_In32(DMA+0x34);dma_completed++;
 previous_job=(int)index;return XST_SUCCESS;
}
