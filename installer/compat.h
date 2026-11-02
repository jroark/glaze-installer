#pragma once
#ifdef _WIN32
#include <windows.h>
#include <io.h>
#include <fcntl.h>
#include <stdio.h>
#include <errno.h>
#define fsync _commit
/* POSIX link semantics: fail if destination exists. */
static inline int link(const char *a,const char *b) {
    if (CreateHardLinkA(b,a,NULL)) return 0;
    DWORD error=GetLastError();
    errno=error==ERROR_ALREADY_EXISTS || error==ERROR_FILE_EXISTS ? EEXIST :
          error==ERROR_ACCESS_DENIED ? EACCES : error==ERROR_NOT_SAME_DEVICE ? EXDEV : EIO;
    fprintf(stderr,"CreateHardLink failed (Windows error %lu)\n",(unsigned long)error);
    return -1;
}
static inline void installer_binary(void) { _setmode(_fileno(stdin),_O_BINARY); _setmode(_fileno(stdout),_O_BINARY); _set_fmode(_O_BINARY); }
#else
static inline void installer_binary(void) {}
#endif
