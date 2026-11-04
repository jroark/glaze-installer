/* Real shared NAND capture against a synthetic, read-only RPC peer. On Windows,
 * build with installer/compat.h and run with a scratch output path argument. */
#include "client.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static unsigned calls;
static int mismatch, fail;

int gu_call(struct gu_client *c,uint32_t op,const void *req,uint32_t n)
{
    assert(op==GU_NAND_READ && n==8);
    unsigned page=gu_get32(req), count=gu_get32((const uint8_t *)req+4);
    assert(count && count<=7 && page+count<=32768);
    if(fail)return -1;
    for(unsigned i=0;i<count*528;i++)c->frame[GU_HEADER+i]=(uint8_t)(page+i/528+i%528);
    calls++;
    if(mismatch && calls>4682)c->frame[GU_HEADER]^=1;
    return (int)(count*528);
}

static void check_file(const char *path)
{
    FILE *f=fopen(path,"rb");assert(f);
    for(unsigned page=0;page<32768;page++)
        for(unsigned i=0;i<528;i++)assert(fgetc(f)==(int)(uint8_t)(page+i));
    assert(fgetc(f)==EOF && !ferror(f));assert(!fclose(f));
}

int main(int argc,char **argv)
{
    installer_binary();
    if(argc!=2)return 2;
    const char *path=argv[1];
    char *partial=malloc(strlen(path)+9);assert(partial);
    sprintf(partial,"%s.partial",path);
    assert(access(path,F_OK) && access(partial,F_OK));
    struct gu_client c={.caps=GU_CAP_NAND_BACKUP};
    if(gu_nand_snapshot(&c,path)) {
        fprintf(stderr,"snapshot returned failure after %u read requests\n",calls);
        free(partial);return 1;
    }
    assert(calls==4682 && access(partial,F_OK));check_file(path);
    assert(gu_nand_snapshot(&c,path)<0 && calls==4682);check_file(path);
    assert(!unlink(path));
    calls=0;
    assert(!gu_nand_backup(&c,path) && calls==9364 && access(partial,F_OK));
    check_file(path);assert(!unlink(path));
    calls=0;mismatch=1;
    assert(gu_nand_backup(&c,path)<0 && access(path,F_OK) && !access(partial,F_OK));
    assert(!unlink(partial));
    calls=0;mismatch=0;fail=1;
    assert(gu_nand_snapshot(&c,path)<0 && access(path,F_OK) && !access(partial,F_OK));
    assert(!unlink(partial));
    free(partial);
    puts("snapshot/backup: exact binary data, publication, cleanup, no overwrite, mismatch and read failure PASS");
    return 0;
}
