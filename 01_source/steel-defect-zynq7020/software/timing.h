#ifndef BATCH_TIMING_H
#define BATCH_TIMING_H
#include <stdint.h>
#ifdef HOST_TEST
uint64_t timer_now(void);
uint64_t timer_hz(void);
void cold_cache_prepare(void);
#else
#include "xiltimer.h"
static uint64_t timer_now(void){XTime value;__asm__ volatile("dsb sy\nisb sy" ::: "memory");XTime_GetTime(&value);__asm__ volatile("dsb sy\nisb sy" ::: "memory");return (uint64_t)value;}
static uint64_t timer_hz(void){return (uint64_t)COUNTS_PER_SECOND;}
static void cold_cache_prepare(void){Xil_DCacheFlush();Xil_DCacheInvalidate();Xil_ICacheInvalidate();}
#endif
#endif
