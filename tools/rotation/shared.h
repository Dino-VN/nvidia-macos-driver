/* Resolution checks for the timed CoreDisplay rotation controller. */
#pragma once
#include <stdint.h>
#define NM_ROTATION_MAX_DIM 16384u
static inline int nmRotationValid(uint32_t degrees)
{
    return degrees == 0 || degrees == 90 || degrees == 180 || degrees == 270;
}
static inline int nmRotationSwaps(uint32_t degrees)
{
    return degrees == 90 || degrees == 270;
}
