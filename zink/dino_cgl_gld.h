/* SPDX-License-Identifier: MIT */
#ifndef DINO_CGL_GLD_H
#define DINO_CGL_GLD_H
/* Private GLD lifecycle interface. These arguments are observed GLI and GLD
 * contexts on x86_64 macOS 25G241, not application CGL handles. */
int dino_cgl_prepare_gld(void *engine, void *driver);
void dino_cgl_destroy_gld(void *driver);
#endif
