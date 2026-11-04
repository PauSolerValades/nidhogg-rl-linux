#import <Foundation/Foundation.h>
#include <mach-o/dyld.h>
#include <mach-o/loader.h>
#include <stdio.h>
#include <string.h>
static FILE*L; 
#define LOG(...) do{ if(!L)L=fopen("/tmp/nid_diag.log","a"); fprintf(L,__VA_ARGS__); fflush(L);}while(0)
__attribute__((constructor)) static void go(void){
  LOG("[diag] pid %d\n", getpid());
  uint32_t n = _dyld_image_count();
  const struct mach_header_64 *h0 = (const struct mach_header_64*)_dyld_get_image_header(0);
  LOG("[diag] images=%u image0=%s header=%p slide=%llx magic=%x cputype=%d\n",
      n, _dyld_get_image_name(0), (void*)h0, (unsigned long long)_dyld_get_image_vmaddr_slide(0),
      h0->magic, h0->cputype);
  // walk segments
  const uint8_t *p = (const uint8_t*)h0 + sizeof(struct mach_header_64);
  uint64_t text_vmaddr = 0;
  for (uint32_t i=0;i<h0->ncmds;i++){
    const struct load_command *lc = (const struct load_command*)p;
    if (lc->cmd == LC_SEGMENT_64){
      const struct segment_command_64 *sg = (const struct segment_command_64*)lc;
      if (!strcmp(sg->segname,"__TEXT")) text_vmaddr = sg->vmaddr;
      LOG("[diag] seg %-16s vmaddr=%llx fileoff=%llu filesize=%llu\n", sg->segname,
          (unsigned long long)sg->vmaddr, (unsigned long long)sg->fileoff, (unsigned long long)sg->filesize);
    }
    p += lc->cmdsize;
  }
  uint64_t base = (uint64_t)(uintptr_t)h0 - text_vmaddr;
  LOG("[diag] text_vmaddr=%llx -> runtime_base=%llx\n", (unsigned long long)text_vmaddr,(unsigned long long)base);
  const char *names[4] = {"GetInstanceList","InternalGetYYVar","Ref","FindVal"};
  uint64_t addrs[4] = {0x100ca0b18ULL,0x100c23a38ULL,0x100c23d44ULL,0x100c24c60ULL};
  for (int i=0;i<4;i++){
    const uint8_t *a = (const uint8_t*)(uintptr_t)(base + (addrs[i]-text_vmaddr));
    LOG("[diag] %s runtime=%p bytes=%02x%02x%02x%02x\n", names[i], a, a[0],a[1],a[2],a[3]);
  }
}
