/* A real port reset, restricted to the sole BE-300 at the recorded location.
 * WinUSB's libusb_reset_device only cycles pipes and reports success. */
#include "windows_usb.h"
#include "transport.h"
#include <stdio.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#include <libusbk.h>

static int target(KLST_HANDLE *list, KLST_DEVINFO_HANDLE *chosen)
{
    KLST_DEVINFO_HANDLE item; unsigned matches=0;
    *list=NULL; *chosen=NULL;
    if (!LstK_Init(list,0)) return LIBUSB_ERROR_OTHER;
    while (LstK_MoveNext(*list,&item)) {
        if (!item->Connected || item->Common.Vid!=0x07cf || item->Common.Pid!=0x2002) continue;
        *chosen=item; matches++;
    }
    if (matches!=1) {
        fprintf(stderr,"Windows USB: connect exactly one BE-300 (found %u)\n",matches);
        return matches ? LIBUSB_ERROR_INVALID_PARAM : LIBUSB_ERROR_NO_DEVICE;
    }
    const char *driver=(*chosen)->DriverID==KUSB_DRVID_LIBUSBK ? "libusbK" :
                       (*chosen)->DriverID==KUSB_DRVID_WINUSB ? "WinUSB" : "unsupported";
    printf("{\"event\":\"usb-driver\",\"driver\":\"%s\",\"automatic_reset\":%s}\n",
           driver,(*chosen)->DriverID==KUSB_DRVID_LIBUSBK ? "true" : "false");
    if ((*chosen)->DriverID!=KUSB_DRVID_LIBUSBK) {
        fputs("Install libusbK for BE-300 (07CF:2002) using USB driver setup. WinUSB cannot reset this device.\n",stderr);
        return LIBUSB_ERROR_NOT_SUPPORTED;
    }
    return 0;
}
int installer_usb_driver(void)
{
    KLST_HANDLE list=NULL; KLST_DEVINFO_HANDLE chosen;
    int r=target(&list,&chosen);
    if (list) LstK_Free(list);
    return r;
}
static int same_port(const char *location)
{
    libusb_context *ctx=NULL; libusb_device **devices=NULL;
    int matches=0, selected=0;
    if (libusb_init(&ctx)) return 0;
    ssize_t count=libusb_get_device_list(ctx,&devices);
    for (ssize_t i=0;i<count;i++) {
        struct libusb_device_descriptor d;
        if (libusb_get_device_descriptor(devices[i],&d) || d.idVendor!=0x07cf || d.idProduct!=0x2002) continue;
        matches++;
        uint8_t ports[8]; int n=libusb_get_port_numbers(devices[i],ports,sizeof(ports));
        char path[64]; int used=snprintf(path,sizeof(path),"%u",libusb_get_bus_number(devices[i]));
        for (int j=0;j<n;j++) used+=snprintf(path+used,sizeof(path)-(size_t)used,".%u",ports[j]);
        if (!location || !strcmp(location,path)) selected++;
    }
    if (devices) libusb_free_device_list(devices,1);
    libusb_exit(ctx);
    return matches==1 && selected==1;
}
int installer_usb_reset(const char *location)
{
    if (!same_port(location)) {
        fputs("Windows USB reset: recorded port is absent or ambiguous; no device reset\n",stderr);
        return -1;
    }
    KLST_HANDLE list=NULL; KLST_DEVINFO_HANDLE chosen; KUSB_HANDLE handle=NULL;
    int r=target(&list,&chosen); DWORD error=0;
    if (!r) {
        if (!UsbK_Init(&handle,chosen)) { error=GetLastError(); r=-1; }
        else if (!UsbK_ResetDevice(handle)) { error=GetLastError(); r=-1; }
    }
    if (handle) UsbK_Free(handle);
    if (list) LstK_Free(list);
    printf("{\"event\":\"usb-reset\",\"kind\":\"port\",\"ok\":%s,\"windows_error\":%lu}\n",
           r ? "false" : "true",(unsigned long)error);
    return r;
}
#else
int installer_usb_driver(void) { return 0; }
int installer_usb_reset(const char *location) { return usb_reset_link(location,0); }
#endif
