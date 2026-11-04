#pragma once
#ifdef _WIN32
#include <windows.h>
#include <io.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <errno.h>
#define fsync _commit
/* The shared NAND capture publishes with link/unlink before fclose. CRT open
 * omits FILE_SHARE_DELETE, so Windows otherwise rejects that final unlink even
 * after a complete read. Keep exclusive creation and binary I/O, but allow the
 * POSIX publication sequence for these read/write capture files. */
static inline int installer_open(const char *path,int flags,...) {
    int mode=0;
    if(flags&_O_CREAT) {
        va_list args;va_start(args,flags);mode=va_arg(args,int);va_end(args);
    }
    if(flags!=(_O_RDWR|_O_CREAT|_O_EXCL))return _open(path,flags,mode);
    HANDLE handle=CreateFileA(path,GENERIC_READ|GENERIC_WRITE,
        FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
    if(handle==INVALID_HANDLE_VALUE) {
        DWORD error=GetLastError();
        fprintf(stderr,"Could not create snapshot file %s (Windows file error %lu).\n",path,(unsigned long)error);
        errno=(error==ERROR_FILE_EXISTS || error==ERROR_ALREADY_EXISTS) ? EEXIST :
              error==ERROR_PATH_NOT_FOUND ? ENOENT :
              (error==ERROR_ACCESS_DENIED || error==ERROR_SHARING_VIOLATION) ? EACCES : EIO;
        return -1;
    }
    int fd=_open_osfhandle((intptr_t)handle,_O_RDWR|_O_BINARY);
    if(fd<0)CloseHandle(handle);
    return fd;
}
#define open installer_open
/* POSIX link semantics: fail if destination exists. */
static inline int link(const char *a,const char *b) {
    if(CreateHardLinkA(b,a,NULL))return 0;
    DWORD error=GetLastError();
    errno=error==ERROR_ALREADY_EXISTS || error==ERROR_FILE_EXISTS ? EEXIST :
          error==ERROR_ACCESS_DENIED ? EACCES : error==ERROR_NOT_SAME_DEVICE ? EXDEV : EIO;
    fprintf(stderr,"Could not publish snapshot %s (Windows file error %lu). Use a writable local NTFS backup folder.\n",b,(unsigned long)error);
    return -1;
}
static inline void installer_binary(void) { _setmode(_fileno(stdin),_O_BINARY); _setmode(_fileno(stdout),_O_BINARY); _set_fmode(_O_BINARY); }
#else
static inline void installer_binary(void) {}
#endif
