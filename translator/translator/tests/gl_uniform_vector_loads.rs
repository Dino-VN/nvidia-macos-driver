//! Apple's GL compiles a uniform block member as a GEP over float slots of the block's byte buffer and loads the
//! member's own type through it: an ivec3 at offset 0 is `getelementptr float, ptr %ubo, i32 0` then
//! `load <3 x i32>`. Minecraft's chunk vertex shaders read their chunk offset (ivec3) this way; the translator took
//! the zero-offset GEP for the buffer itself and failed "reinterpret load bit width mismatch Float (32) vs
//! Vector(Int(32), 3) (96)", so Apple's GL ran those shaders on the CPU.
//!
//! The same shaders sample the lightmap through a GLSL function taking a sampler2D: Apple's GL passes every
//! texture/sampler pair with the index of the one meant, a constant the caller stores, and picks with a switch whose
//! phis have pointer type over loaded images and samplers ("sampler operand is a pointer whose exact sampler state
//! was not recovered").
use metal2vulkan::passes::Stage;
use metal2vulkan::{disassemble, translate_sanitized_native};
use std::collections::HashSet;
use std::path::PathBuf;

fn tmp() -> PathBuf {
    let d = std::env::temp_dir().join(format!("m2v_gl_uniform_vector_loads_{}", std::process::id()));
    let _ = std::fs::create_dir_all(&d);
    d
}

fn spirv_val(spv: &[u8]) {
    let out = std::process::Command::new("spirv-val").args(["--target-env", "vulkan1.2", "-"]).stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped()).stderr(std::process::Stdio::piped()).spawn().and_then(|mut c| {
            use std::io::Write; c.stdin.take().unwrap().write_all(spv)?; c.wait_with_output() });
    if let Ok(out) = out { assert!(out.status.success(), "spirv-val: {}{}", String::from_utf8_lossy(&out.stdout), String::from_utf8_lossy(&out.stderr)); }
}

#[test]
fn an_ivec3_uniform_at_offset_zero_of_a_float_gep_translates() {
    let ll = include_str!("fixtures/gl/ivec3_uniform_through_float_gep.ll");
    let spv = translate_sanitized_native(ll, Stage::Vertex, &tmp()).expect("the ivec3 uniform load must translate");
    let asm = disassemble(&spv).expect("disassemble");
    assert!(asm.contains("OpConvertSToF"), "the ivec3 difference is converted to float:\n{asm}");
    spirv_val(&spv);
}

#[test]
fn an_ivec2_uniform_in_a_vec4_slot_translates() {
    // BSL reads eyeBrightnessSmooth (ivec2) as `load <2 x i32>` through a GEP over the block's vec4 slots; it failed
    // "reinterpret load bit width mismatch Vector(Float, 4) (128) vs Vector(Int(32), 2) (64)".
    let ll = include_str!("fixtures/gl/ivec2_uniform_through_vec4_gep.ll");
    let spv = translate_sanitized_native(ll, Stage::Vertex, &tmp()).expect("the ivec2 uniform load must translate");
    let asm = disassemble(&spv).expect("disassemble");
    assert!(asm.contains("OpBitcast") && asm.contains("OpConvertSToF"), "the lanes are reinterpreted as int:\n{asm}");
    spirv_val(&spv);
}

fn assert_prefix_load_width(spv: &[u8], lanes: usize) {
    let words: Vec<u32> = spv.chunks_exact(4)
        .map(|b| u32::from_le_bytes(b.try_into().unwrap())).collect();
    let mut instructions = Vec::new();
    let mut at = 5;
    while at < words.len() {
        let count = (words[at] >> 16) as usize;
        assert!(count > 0 && at + count <= words.len());
        instructions.push((words[at] & 0xffff, &words[at + 1..at + count]));
        at += count;
    }
    let scalars: HashSet<_> = instructions.iter().filter_map(|(op, args)|
        (matches!(*op, 21 | 22) && args.get(1) == Some(&32)).then(|| args[0])).collect();
    let vec4: HashSet<_> = instructions.iter().filter_map(|(op, args)|
        (*op == 23 && args.get(2) == Some(&4)).then(|| args[0])).collect();
    assert!(!instructions.iter().any(|(op, args)| *op == 61 && vec4.contains(&args[0])),
        "an 8/12-byte prefix must not load a full 16-byte vec4");
    let loads: HashSet<_> = instructions.iter().filter_map(|(op, args)|
        (*op == 61 && scalars.contains(&args[0])).then(|| args[1])).collect();
    assert_eq!(loads.len(), lanes);
    assert_eq!(instructions.iter().filter(|(op, args)| *op == 124 && loads.contains(&args[2])).count(), lanes,
        "each loaded lane keeps its bits, rather than being numerically converted");
}

#[test]
fn vector_prefix_loads_do_not_read_past_the_buffer_tail() {
    let fixture = include_str!("fixtures/gl/ivec2_uniform_through_vec4_gep.ll");
    for lanes in [2, 3] {
        // The GEP starts at byte 16. Only the 8/12 bytes requested by the LLVM
        // load remain; reading the source vector's last lanes would over-read.
        let ll = fixture.replace("<2 x i32>", &format!("<{lanes} x i32>"))
            .replace("!\"air.buffer_size\", i32 32,", &format!("!\"air.buffer_size\", i32 {},", 16 + lanes * 4));
        let spv = translate_sanitized_native(&ll, Stage::Vertex, &tmp()).expect("bounded prefix load");
        assert_prefix_load_width(&spv, lanes);
        spirv_val(&spv);
    }
}

#[test]
fn integer_vector_prefixes_can_be_reinterpreted_as_float_lanes() {
    let fixture = include_str!("fixtures/gl/ivec2_uniform_through_vec4_gep.ll");
    let ll = fixture.replace("getelementptr <4 x float>", "getelementptr <4 x i32>")
        .replace("<2 x i32>", "<2 x float>")
        .replace("%7 = call reassoc nsz arcp contract afn float @air.convert.f.f32.s.i32(i32 %6)",
            "%7 = fadd float %6, 0.000000e+00")
        .replace("!\"air.buffer_size\", i32 32,", "!\"air.buffer_size\", i32 24,");
    let spv = translate_sanitized_native(&ll, Stage::Vertex, &tmp()).expect("integer prefix as floats");
    assert_prefix_load_width(&spv, 2);
    spirv_val(&spv);
}

#[test]
fn a_sampler2d_parameter_chosen_by_a_constant_index_samples_that_pair() {
    let ll = include_str!("fixtures/gl/sampler2d_param_chosen_by_constant.ll");
    let spv = translate_sanitized_native(ll, Stage::Vertex, &tmp()).expect("the lightmap lookup must translate");
    let asm = disassemble(&spv).expect("disassemble");
    if std::env::var_os("M2V_SHOW_ASM").is_some() { eprintln!("{asm}"); }
    assert!(asm.contains("OpImageSampleExplicitLod"), "{asm}");
    assert!(!asm.lines().any(|l| l.contains("OpPhi") && (l.contains("Image") || l.contains("Sampler"))), "no image/sampler phi left:\n{asm}");
    spirv_val(&spv);
}

