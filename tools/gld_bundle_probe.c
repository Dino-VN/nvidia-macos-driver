/* SPDX-License-Identifier: MIT */
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv)
{
   if (argc != 2) { fprintf(stderr, "usage: %s BUNDLE_NAME\n", argv[0]); return 2; }
   void *sandbox = dlopen("/usr/lib/system/libsystem_sandbox.dylib", RTLD_NOW | RTLD_LOCAL);
   int (*find)(const char *, char *, size_t) = sandbox ? dlsym(sandbox, "gpu_bundle_find_trusted") : NULL;
   if (!find) { fprintf(stderr, "GPU bundle lookup is unavailable\n"); return 1; }
   char path[1024] = {0};
   int result = find(argv[1], path, sizeof(path));
   if (result || !*path) { fprintf(stderr, "GPU bundle lookup failed (%d): %s\n", result, argv[1]); return 1; }
   printf("Trusted GPU bundle: %s\n", path);
   return 0;
}
