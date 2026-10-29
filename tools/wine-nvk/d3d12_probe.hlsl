RWByteAddressBuffer outputBuffer : register(u0);
cbuffer Parameters : register(b0) { uint seed; }

[numthreads(64, 1, 1)]
void cs(uint3 id : SV_DispatchThreadID) {
    outputBuffer.Store(id.x * 4, (id.x * 1664525u + seed) ^ 0x5a5aa5a5u);
}

float4 vs(uint id : SV_VertexID) : SV_Position {
    float2 positions[3] = {float2(-1, -1), float2(0, 1), float2(1, -1)};
    return float4(positions[id], 0.5, 1);
}

float4 ps() : SV_Target { return float4(0.2, 0.8, 0.4, 1); }
