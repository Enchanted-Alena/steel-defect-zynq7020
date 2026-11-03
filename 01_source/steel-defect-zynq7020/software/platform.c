#include "xparameters.h"
#include "xuartps.h"
#include "xuartps_hw.h"
#include "xgpiops.h"
#include "xstatus.h"
#include "sleep.h"

#define BOARD_UART_BASE 0xE0000000U
#define BOARD_GPIO_BASE 0xE000A000U
#define BOARD_LED2_PIN 54U /* EMIO GPIO bit 0: PL pin P21 */
static XUartPs uart;
static XGpioPs gpio;
void putstr(const char *s) {
    while (*s) XUartPs_SendByte(BOARD_UART_BASE, (u8)*s++);
}
void puthex(u32 v) {
    const char *hex = "0123456789ABCDEF";
    for (int shift=28; shift>=0; shift-=4)
        XUartPs_SendByte(BOARD_UART_BASE, (u8)hex[(v >> shift) & 15U]);
}
int init_board(void) {
    XUartPs_Config *uc;
    XGpioPs_Config *gc;
#ifdef SDT
    uc=XUartPs_LookupConfig(BOARD_UART_BASE);
    gc=XGpioPs_LookupConfig(BOARD_GPIO_BASE);
#else
    uc=XUartPs_LookupConfig(XPAR_XUARTPS_0_DEVICE_ID);
    gc=XGpioPs_LookupConfig(XPAR_XGPIOPS_0_DEVICE_ID);
#endif
    if (!uc || !gc) return XST_FAILURE;
    if (XUartPs_CfgInitialize(&uart,uc,uc->BaseAddress)!=XST_SUCCESS) return XST_FAILURE;
    if (XUartPs_SetBaudRate(&uart,115200U)!=XST_SUCCESS) return XST_FAILURE;
    if (XGpioPs_CfgInitialize(&gpio,gc,gc->BaseAddr)!=XST_SUCCESS) return XST_FAILURE;
    XGpioPs_SetDirectionPin(&gpio,BOARD_LED2_PIN,1);
    XGpioPs_SetOutputEnablePin(&gpio,BOARD_LED2_PIN,1);
    XGpioPs_WritePin(&gpio,BOARD_LED2_PIN,0);
    return XST_SUCCESS;
}



void board_led(int value){XGpioPs_WritePin(&gpio,BOARD_LED2_PIN,(u32)value);}
void board_uart_drain(void){while(!(XUartPs_ReadReg(BOARD_UART_BASE,XUARTPS_SR_OFFSET)&XUARTPS_SR_TXEMPTY)){} }

