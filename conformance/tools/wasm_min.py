"""A minimal WebAssembly binary writer for the kit's program cases (SREPs 66 and 69). Standard library only.

It writes the binary format of the WebAssembly core specification (section 5, "Binary Format"): the magic and version,
then the type, import, function, memory, export, code and data sections, in that order. Instructions are given as raw
bytes; the helpers below encode the LEB128 integers and the IEEE 754 constants the instructions take.
"""
import struct

I32, I64, F32, F64, V128 = 0x7F, 0x7E, 0x7D, 0x7C, 0x7B


def uleb(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def sleb(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if (n == 0 and not b & 0x40) or (n == -1 and b & 0x40):
            out.append(b)
            return bytes(out)
        out.append(b | 0x80)


def name(s: str) -> bytes:
    b = s.encode()
    return uleb(len(b)) + b


def vec(items) -> bytes:
    items = list(items)
    return uleb(len(items)) + b"".join(items)


def section(sid: int, body: bytes) -> bytes:
    return bytes([sid]) + uleb(len(body)) + body


# instructions
def i32_const(n): return b"\x41" + sleb(n)
def i64_const(n): return b"\x42" + sleb(n if n < 1 << 63 else n - (1 << 64))
def f64_const(x): return b"\x44" + struct.pack("<d", x)
def call(i): return b"\x10" + uleb(i)
def local_get(i): return b"\x20" + uleb(i)
def local_set(i): return b"\x21" + uleb(i)
def local_tee(i): return b"\x22" + uleb(i)
def global_get(i): return b"\x23" + uleb(i)
def global_set(i): return b"\x24" + uleb(i)
def i32_store(offset): return b"\x36\x02" + uleb(offset)
def br_if(depth): return b"\x0D" + uleb(depth)


END, ELSE, UNREACHABLE, DROP = b"\x0B", b"\x05", b"\x00", b"\x1A"
I64_AND, I64_EQZ, I64_EQ, I32_EQ = b"\x83", b"\x50", b"\x51", b"\x46"
F64_GT, F64_DIV, I64_REINTERPRET_F64 = b"\x64", b"\xA3", b"\xBD"
MEMORY_GROW = b"\x40\x00"
I64_ADD, I64_XOR, I64_NE, I32_ADD, I32_LT_U = b"\x7C", b"\x85", b"\x52", b"\x6A", b"\x49"
F64_GE, F64_CONVERT_I64_S = b"\x66", b"\xB9"


def if_(result: int) -> bytes:
    return b"\x04" + bytes([result])


def loop_empty() -> bytes:
    return b"\x03\x40"


def br(depth: int) -> bytes:
    return b"\x0C" + uleb(depth)


def packed(ptr: int, length: int) -> int:
    """The value generate() returns: the output's address in the high 32 bits, its length in the low 32 bits."""
    return (ptr << 32) | length


def module(*, types, imports=(), funcs, memory=(1, None, False), globals_=(), exports, codes, data=()) -> bytes:
    """types: [(params, results)]; imports: [(module, field, typeidx)]; funcs: [typeidx] of the defined functions;
    memory: (min pages, max pages or None, shared); globals_: [(valtype, initial i64 or i32 value)], all mutable;
    exports: [(name, kind, index)] with kind 0 function, 2 memory; codes: [body] or [(locals, body)] with locals
    [(count, valtype)]; data: [(offset, bytes)]."""
    out = b"\x00asm" + b"\x01\x00\x00\x00"
    out += section(1, vec(b"\x60" + vec(bytes([p]) for p in ps) + vec(bytes([r]) for r in rs) for ps, rs in types))
    if imports:
        out += section(2, vec(name(m) + name(f) + b"\x00" + uleb(t) for m, f, t in imports))
    out += section(3, vec(uleb(t) for t in funcs))
    lo, hi, shared = memory
    if shared:
        lim = b"\x03" + uleb(lo) + uleb(hi)
    elif hi is None:
        lim = b"\x00" + uleb(lo)
    else:
        lim = b"\x01" + uleb(lo) + uleb(hi)
    out += section(5, vec([lim]))
    if globals_:
        out += section(6, vec(bytes([t, 1]) + (i64_const(v) if t == I64 else i32_const(v)) + END for t, v in globals_))
    out += section(7, vec(name(n) + bytes([k]) + uleb(i) for n, k, i in exports))
    def entry(c):
        locals_, body = c if isinstance(c, tuple) else ([], c)
        b = vec(uleb(n) + bytes([t]) for n, t in locals_) + body
        return uleb(len(b)) + b
    out += section(10, vec(entry(c) for c in codes))
    if data:
        out += section(11, vec(b"\x00" + i32_const(off) + END + uleb(len(d)) + d for off, d in data))
    return out


# SplitMix64 (Vigna, https://prng.di.unimi.it/splitmix64.c), as SREP 66 seeds it
GAMMA = 0x9E3779B97F4A7C15
M64 = (1 << 64) - 1


def mix64(z: int) -> int:
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & M64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & M64
    return z ^ (z >> 31)


def program_rng(project_seed: int, program_seed: int):
    """The values sr.rand_u64 returns, in order (SREP 66, Semantics 4)."""
    x = mix64((project_seed ^ mix64(program_seed)) & M64)
    while True:
        x = (x + GAMMA) & M64
        yield mix64(x)
