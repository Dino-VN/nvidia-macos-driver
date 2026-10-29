/* SPDX-License-Identifier: MIT */
#ifndef DINO_CGL_H
#define DINO_CGL_H
#include <OpenGL/OpenGL.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Experimental native CGL dispatch bridge, bound to the OS build used to
 * generate it. Attach before the application creates GL objects. CGL contexts
 * retain their identity and drawable; public GL core calls then use Zink.
 * The caller must serialize access with CGLLockContext and detach before
 * destroying the context. Serialize attachment/detachment in a share group.
 * No injection or Apple binary patching is involved. */
int dino_cgl_attach(CGLContextObj context, unsigned width, unsigned height);
int dino_cgl_detach(CGLContextObj context);
int dino_cgl_resize(CGLContextObj context, unsigned width, unsigned height);
/* Prefer a GPU copy into shared IOSurface pages, then the Apple drawable's
 * normal swap. CPU readback is the fallback when surface import is unavailable.
 * DINO_ZINK_PRESENT=cpu selects that fallback; =gpu requires GPU presentation. */
int dino_cgl_present(CGLContextObj context);
const char *dino_cgl_last_error(void);
#ifdef __cplusplus
}
#endif
#endif
