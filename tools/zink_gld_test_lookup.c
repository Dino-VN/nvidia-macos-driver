/* SPDX-License-Identifier: MIT
 * Process-local GLD test shim. It does not register or trust a system bundle.
 * Link with the tested runtime as LC_RPATH: interposed dlopen changes its caller.
 */
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <sys/sysctl.h>
#include <errno.h>
extern int gpu_bundle_find_trusted(const char *, char *, size_t);
static int lookup(const char *name, char *output, size_t bytes)
{
    const char *bundle = getenv("ZINK_TEST_GLD_BUNDLE");
    if (bundle && !strcmp(name,"AppleMetalOpenGLRenderer")) {
        char path[PATH_MAX];
        if (!realpath(bundle,path) || strlen(path)+1 > bytes) return -1;
        memcpy(output,path,strlen(path)+1);
        fprintf(stderr,"Process-local GLD test lookup: %s\n",path);
        return 0;
    }
    return gpu_bundle_find_trusted(name,output,bytes);
}
static void *open_bundle(const char *path, int mode)
{
    const char *bundle = getenv("ZINK_TEST_GLD_BUNDLE");
    char original[PATH_MAX], replacement[PATH_MAX];
    if (bundle) {
        snprintf(original,sizeof(original),"%s/Contents/MacOS/AppleMetalOpenGLRenderer",bundle);
        snprintf(replacement,sizeof(replacement),"%s/Contents/MacOS/NVKZinkGLDriver",bundle);
        if (!strcmp(path,original)) return dlopen(replacement,mode);
    }
    return dlopen(path,mode);
}

/* Simulate a later OS build in this probe process while retaining the actual
 * Apple CGL binaries/layout. This checks the version policy, not a new OS ABI. */
static int os_version(const char *name, void *value, size_t *size, void *new_value, size_t new_size)
{
    const char *build = getenv("ZINK_TEST_OS_BUILD");
    if (build && !strcmp(name,"kern.osversion") && !new_value) {
        if (!size) { errno = EFAULT; return -1; }
        size_t needed = strlen(build)+1, capacity = *size;
        *size = needed;
        if (value) {
            if (capacity<needed) { errno = ENOMEM; return -1; }
            memcpy(value,build,needed);
        }
        return 0;
    }
    return sysctlbyname(name,value,size,new_value,new_size);
}
__attribute__((used)) static struct { const void *replacement, *original; } hook
__attribute__((section("__DATA,__interpose"))) = { (const void *)lookup, (const void *)gpu_bundle_find_trusted };

__attribute__((used)) static struct { const void *replacement, *original; } open_hook
__attribute__((section("__DATA,__interpose"))) = { (const void *)open_bundle, (const void *)dlopen };

__attribute__((used)) static struct { const void *replacement, *original; } version_hook
__attribute__((section("__DATA,__interpose"))) = { (const void *)os_version, (const void *)sysctlbyname };
