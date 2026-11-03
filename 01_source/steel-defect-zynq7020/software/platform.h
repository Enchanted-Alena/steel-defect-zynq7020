#ifndef BOARD_PLATFORM_H
#define BOARD_PLATFORM_H
#include "xil_types.h"
#include "xil_io.h"
#include "xil_cache.h"
#include "xstatus.h"
#include "sleep.h"
int init_board(void);
void putstr(const char *s);
void puthex(u32 v);
void board_led(int value);
void board_uart_drain(void);
#endif
