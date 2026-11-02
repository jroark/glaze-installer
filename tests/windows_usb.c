/* Production Windows reset adapter with fake enumeration and libusbK APIs.
 * No physical device handle is opened by this fixture. */
#include <windows.h>
#include <libusbk.h>
#include <libusb.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../installer/windows_usb.h"
static KLST_DEVINFO info;
static unsigned cursor, devices=1, resets, frees;
static int init_ok=1, reset_ok=1;
BOOL KUSB_API LstK_Init(KLST_HANDLE *list,KLST_FLAG flags)
{ (void)flags; cursor=0;*list=(KLST_HANDLE)(uintptr_t)1;return TRUE; }
BOOL KUSB_API LstK_MoveNext(KLST_HANDLE list,KLST_DEVINFO_HANDLE *item)
{ (void)list;if(cursor++)return FALSE;*item=&info;return TRUE; }
BOOL KUSB_API LstK_Free(KLST_HANDLE list) { (void)list; return TRUE; }
BOOL KUSB_API UsbK_Init(KUSB_HANDLE *handle,KLST_DEVINFO_HANDLE item)
{ assert(item==&info);if(!init_ok){SetLastError(ERROR_ACCESS_DENIED);return FALSE;}*handle=(KUSB_HANDLE)(uintptr_t)1;return TRUE; }
BOOL KUSB_API UsbK_ResetDevice(KUSB_HANDLE handle)
{ assert(handle);resets++;if(!reset_ok)SetLastError(ERROR_ACCESS_DENIED);return reset_ok; }
BOOL KUSB_API UsbK_Free(KUSB_HANDLE handle) { assert(handle);frees++;return TRUE; }
int LIBUSB_CALL libusb_init(libusb_context **ctx) { *ctx=(libusb_context *)(uintptr_t)1;return 0; }
void LIBUSB_CALL libusb_exit(libusb_context *ctx) { assert(ctx); }
ssize_t LIBUSB_CALL libusb_get_device_list(libusb_context *ctx,libusb_device ***out)
{ (void)ctx;static libusb_device *list[3]={(libusb_device *)(uintptr_t)1,(libusb_device *)(uintptr_t)2,NULL};*out=list;return devices; }
void LIBUSB_CALL libusb_free_device_list(libusb_device **list,int unref) { (void)list;(void)unref; }
int LIBUSB_CALL libusb_get_device_descriptor(libusb_device *dev,struct libusb_device_descriptor *d)
{ (void)dev;memset(d,0,sizeof(*d));d->idVendor=0x07cf;d->idProduct=0x2002;return 0; }
uint8_t LIBUSB_CALL libusb_get_bus_number(libusb_device *dev) { (void)dev;return 1; }
int LIBUSB_CALL libusb_get_port_numbers(libusb_device *dev,uint8_t *ports,int count)
{ assert(count);ports[0]=(uint8_t)(uintptr_t)dev;return 1; }
int main(void)
{
    info.Common.Vid=0x07cf;info.Common.Pid=0x2002;info.Connected=TRUE;
    info.DriverID=KUSB_DRVID_WINUSB;
    assert(installer_usb_driver()==LIBUSB_ERROR_NOT_SUPPORTED && !resets);
    info.Connected=FALSE;
    assert(installer_usb_driver()==LIBUSB_ERROR_NO_DEVICE && !resets);
    info.Connected=TRUE;
    info.DriverID=KUSB_DRVID_LIBUSBK;
    assert(!installer_usb_driver());
    assert(installer_usb_reset("1.2")<0 && !resets);
    devices=2;assert(installer_usb_reset("1.1")<0 && !resets);devices=1;
    init_ok=0;assert(installer_usb_reset("1.1")<0 && !resets && !frees);init_ok=1;
    reset_ok=0;assert(installer_usb_reset("1.1")<0 && resets==1 && frees==1);
    reset_ok=1;assert(!installer_usb_reset("1.1") && resets==2 && frees==2);
    puts("windows-usb: driver gating, exact port, ambiguity, initialization/reset failure, handle cleanup PASS");
}
