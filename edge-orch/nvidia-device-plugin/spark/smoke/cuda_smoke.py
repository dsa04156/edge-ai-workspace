"""Bounded CUDA Driver API kernel test; no toolkit or Python packages required."""
import ctypes as C
import json
import platform

cuda = C.CDLL("libcuda.so.1")
def call(name, types, *args):
    fn = getattr(cuda, name)
    fn.argtypes = types
    fn.restype = C.c_int
    result = fn(*args)
    if result:
        raise RuntimeError(f"{name}: CUDA error {result}")

ptr = C.c_void_p
u64 = C.c_uint64
call("cuInit", [C.c_uint], 0)
count = C.c_int()
call("cuDeviceGetCount", [C.POINTER(C.c_int)], C.byref(count))
assert count.value == 1, count.value
device = C.c_int()
call("cuDeviceGet", [C.POINTER(C.c_int), C.c_int], C.byref(device), 0)
name = C.create_string_buffer(128)
call("cuDeviceGetName", [ptr, C.c_int, C.c_int], name, 128, device.value)
ctx = ptr()
call("cuCtxCreate_v2", [C.POINTER(ptr), C.c_uint, C.c_int], C.byref(ctx), 0, device.value)
module = ptr()
memory = u64()
try:
    ptx = b""".version 8.0
.target sm_80
.address_size 64
.visible .entry fill(.param .u64 output) {
.reg .b32 %r<3>;
.reg .b64 %rd<4>;
ld.param.u64 %rd1, [output];
mov.u32 %r1, %tid.x;
add.u32 %r2, %r1, 1;
mul.wide.u32 %rd2, %r1, 4;
add.u64 %rd3, %rd1, %rd2;
st.global.u32 [%rd3], %r2;
ret;
}
"""
    call("cuModuleLoadData", [C.POINTER(ptr), ptr], C.byref(module), C.cast(C.c_char_p(ptx), ptr))
    kernel = ptr()
    call("cuModuleGetFunction", [C.POINTER(ptr), ptr, C.c_char_p], C.byref(kernel), module, b"fill")
    call("cuMemAlloc_v2", [C.POINTER(u64), C.c_size_t], C.byref(memory), 256 * 4)
    params = (ptr * 1)(C.cast(C.byref(memory), ptr))
    call("cuLaunchKernel", [ptr] + [C.c_uint] * 7 + [ptr, ptr, ptr], kernel, 1, 1, 1, 256, 1, 1, 0, None, params, None)
    call("cuCtxSynchronize", [])
    output = (C.c_uint32 * 256)()
    call("cuMemcpyDtoH_v2", [ptr, u64, C.c_size_t], output, memory, C.sizeof(output))
    assert list(output) == list(range(1, 257))
    print(json.dumps({"result": "PASS", "architecture": platform.machine(), "gpu": name.value.decode(), "visible_gpu_count": count.value, "elements": 256, "checksum": sum(output)}))
finally:
    if memory.value:
        call("cuMemFree_v2", [u64], memory)
    if module.value:
        call("cuModuleUnload", [ptr], module)
    call("cuCtxDestroy_v2", [ptr], ctx)
