/* SPDX-License-Identifier: MIT
 * Capture raw x86_64 integer arguments without guessing object layouts.
 * Unknown stack and floating-point arguments are not read or forwarded.
 */
.macro GLD_ENTRY name
.section __TEXT,__cstring,cstring_literals
L_\name:
  .asciz "\name"
.text
.globl _\name
_\name:
  pushq %rbp
  movq %rsp, %rbp
  subq $16, %rsp
  movq %r9, (%rsp)
  movq %r8, %r9
  movq %rcx, %r8
  movq %rdx, %rcx
  movq %rsi, %rdx
  movq %rdi, %rsi
  leaq L_\name(%rip), %rdi
  callq _dino_gld_trace
  addq $16, %rsp
  popq %rbp
  retq
.endm
GLD_ENTRY gldInitializeLibrary
GLD_ENTRY gldTerminateLibrary
GLD_ENTRY gldCreateDevice
GLD_ENTRY gldChoosePixelFormat
GLD_ENTRY gldDestroyPixelFormat
GLD_ENTRY gldPopulateContextDispatch
GLD_ENTRY gldUpdateDispatch
GLD_ENTRY gldPresentFramebufferData
GLD_ENTRY gldFlushQueue
GLD_ENTRY gldFinishQueue
