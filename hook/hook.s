// Minimal arm64 inline hook: replaces a function's first 16 bytes with
//   ldr x16, #8 ; br x16 ; .quad hook
// and runs the original 4 instructions from a trampoline that jumps back.
    .text
    .globl _nid_hook_entry
    .align 4
_nid_hook_entry:
    stp x29, x30, [sp, #-16]!
    stp x0, x1, [sp, #-16]!
    stp x2, x3, [sp, #-16]!
    stp x4, x5, [sp, #-16]!
    stp x6, x7, [sp, #-16]!
    stp x8, x9, [sp, #-16]!
    stp d0, d1, [sp, #-16]!
    stp d2, d3, [sp, #-16]!
    stp d4, d5, [sp, #-16]!
    stp d6, d7, [sp, #-16]!
    bl _nid_hook_c
    ldp d6, d7, [sp], #16
    ldp d4, d5, [sp], #16
    ldp d2, d3, [sp], #16
    ldp d0, d1, [sp], #16
    ldp x8, x9, [sp], #16
    ldp x6, x7, [sp], #16
    ldp x4, x5, [sp], #16
    ldp x2, x3, [sp], #16
    ldp x0, x1, [sp], #16
    ldp x29, x30, [sp], #16
    adrp x16, _nid_tramp@PAGE
    ldr x16, [x16, _nid_tramp@PAGEOFF]
    br x16
