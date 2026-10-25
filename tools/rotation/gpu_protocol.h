/* Per-display rotation metadata over the existing WindowServer surface escape. */
#pragma once
#include <stdint.h>
#define NM_ROTATION_GPU_PROTOCOL 12u
#define NM_ROTATION_GPU_SLOTS 3u
#define NM_ROTATION_GPU_HEADS 5u
#define NM_ROTATION_GPU_SOURCES 8u
#define NM_ROTATION_GPU_PAYLOAD 0x0fffffffu
#define NM_ROTATION_GPU_BEGIN  0x10000000u
#define NM_ROTATION_GPU_BIND   0x20000000u
#define NM_ROTATION_GPU_DONE   0x30000000u
#define NM_ROTATION_GPU_CANCEL 0x50000000u
#define NM_ROTATION_GPU_FLIP "nvRotationGPUFlip"
static inline int nmRotationGPUTicketHead(uint32_t ticket)
{
    unsigned encoded=ticket&15u;
    return ticket && !(ticket&~NM_ROTATION_GPU_PAYLOAD) && encoded>=1 && encoded<=NM_ROTATION_GPU_HEADS ? (int)encoded-1 : -1;
}

// BEGIN carries a display selector, not a ticket. The kernel rechecks its mode.
static inline uint32_t nmRotationGPUBegin(unsigned head)
{
    return head < NM_ROTATION_GPU_HEADS ? NM_ROTATION_GPU_BEGIN | (head + 1u) : 0;
}
