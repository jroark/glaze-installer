/* Use the shared transport with error diagnostics even when packet tracing is
 * disabled. Never log NAND contents or entropy; report only transfer errors. */
#define usb_read installer_transport_read
#define usb_write installer_transport_write
#include "transport.c"
#undef usb_read
#undef usb_write

int usb_read(struct usb_link *l, void *p, size_t n, unsigned timeout)
{
    int r = installer_transport_read(l, p, n, timeout);
    if (r < 0 && r != LIBUSB_ERROR_TIMEOUT)
        fprintf(stderr, "USB bulk IN failed: %s\n", libusb_error_name(r));
    return r;
}

int usb_write(struct usb_link *l, const void *p, size_t n, unsigned timeout)
{
    int r = installer_transport_write(l, p, n, timeout);
    if (r < 0)
        fprintf(stderr, "USB bulk OUT failed: %s\n", libusb_error_name(r));
    return r;
}
