"""Small real CUDA kernel; no model, host mount, or third-party Python package."""
import ctypes as c
import json
import os
import time


def emit(event, **fields):
    print(json.dumps({"event": event, "pod": os.environ["HOSTNAME"],
                      "time": time.time(), **fields}), flush=True)


cuda = c.CDLL("libcuda.so.1")


def call(name, *args):
    result = getattr(cuda, name)(*args)
    if result:
        raise RuntimeError(f"{name}: CUDA error {result}")


call("cuInit", c.c_uint(0))
device = c.c_int()
call("cuDeviceGet", c.byref(device), c.c_int(0))
name = c.create_string_buffer(128)
call("cuDeviceGetName", name, c.c_int(len(name)), device)
uuid = c.create_string_buffer(16)
call("cuDeviceGetUuid", c.byref(uuid), device)
context = c.c_void_p()
call("cuDevicePrimaryCtxRetain", c.byref(context), device)
call("cuCtxSetCurrent", context)

ptx = b""".version 8.0
.target sm_87
.address_size 64
.visible .entry increment(.param .u64 data) {
  .reg .b64 %rd<3>;
  .reg .b32 %r<3>;
  ld.param.u64 %rd0, [data];
  mov.u32 %r0, %tid.x;
  mul.wide.u32 %rd1, %r0, 4;
  add.u64 %rd2, %rd0, %rd1;
  ld.global.u32 %r1, [%rd2];
  add.u32 %r2, %r1, 1;
  st.global.u32 [%rd2], %r2;
  ret;
}
"""
module = c.c_void_p()
function = c.c_void_p()
call("cuModuleLoadData", c.byref(module), c.c_char_p(ptx))
call("cuModuleGetFunction", c.byref(function), module, c.c_char_p(b"increment"))
buffer = c.c_uint64()
host = (c.c_uint32 * 256)(*range(256))
call("cuMemAlloc_v2", c.byref(buffer), c.c_size_t(c.sizeof(host)))
args = (c.c_void_p * 1)(c.cast(c.byref(buffer), c.c_void_p))
emit("started", gpu=name.value.decode(), uuid=uuid.raw.hex(),
     visible_devices=os.environ.get("NVIDIA_VISIBLE_DEVICES"))
deadline = time.monotonic() + int(os.environ.get("PROBE_SECONDS", "60"))
iterations = 0
try:
    while time.monotonic() < deadline:
        call("cuMemcpyHtoD_v2", buffer, c.byref(host), c.c_size_t(c.sizeof(host)))
        call("cuLaunchKernel", function, c.c_uint(1), c.c_uint(1), c.c_uint(1),
             c.c_uint(256), c.c_uint(1), c.c_uint(1), c.c_uint(0),
             c.c_void_p(), args, c.c_void_p())
        call("cuCtxSynchronize")
        result = (c.c_uint32 * 256)()
        call("cuMemcpyDtoH_v2", c.byref(result), buffer, c.c_size_t(c.sizeof(result)))
        assert list(result) == list(range(1, 257)), "GPU result mismatch"
        iterations += 1
        if iterations == 1 or iterations % 25 == 0:
            emit("kernel_ok", iterations=iterations, checksum=sum(result))
        time.sleep(0.2)
    emit("passed", iterations=iterations, checksum=sum(result))
finally:
    call("cuMemFree_v2", buffer)
    call("cuModuleUnload", module)
    call("cuDevicePrimaryCtxRelease_v2", device)
