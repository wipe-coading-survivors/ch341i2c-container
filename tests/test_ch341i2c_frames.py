import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "ch341i2c", ROOT / "scripts" / "ch341i2c.py")
ch341i2c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ch341i2c)


def chunk_qdr():
    """Реальный чанк write-задачи (build/s7-a2h-chunk-qdr.bin, 34 байта):
    222=00, 223=64, далее 0xff x31, 255=e7. Файл живёт на Mellanox-сервере —
    на хосте байты синтезируются те же самые."""
    f = ROOT / "build" / "s7-a2h-chunk-qdr.bin"
    if f.exists():
        return f.read_bytes()
    return bytes([0x00, 0x64]) + b"\xff" * 31 + bytes([0xE7])


def test_write_frame_1b_token_counts_addr_mem_data():
    frames = ch341i2c.build_write_frames(0x50, 124, bytes([0x9E]))
    assert frames == [bytes.fromhex("aa7483a07c9e7500")]


def test_write_frames_34b_chunk_qdr():
    data = chunk_qdr()
    assert len(data) == 34
    frames = ch341i2c.build_write_frames(0x51, 222, data)
    assert len(frames) == 4
    assert [len(f) for f in frames] == [16, 16, 16, 14]
    assert [f[2] for f in frames] == [0x8B, 0x8B, 0x8B, 0x89]
    assert frames[0] == bytes.fromhex("aa748ba2de0064ffffffffffffff7500")
    assert frames[1][:5] == bytes.fromhex("aa748ba2e7")
    assert frames[1][5:-2] == b"\xff" * 9
    assert frames[2][:5] == bytes.fromhex("aa748ba2f0")
    assert frames[2][5:-2] == b"\xff" * 9
    assert frames[3] == bytes.fromhex("aa7489a2f9ffffffffffffe77500")


def test_write_frame_boundary_9_single_10_two():
    frames9 = ch341i2c.build_write_frames(0x50, 0, b"\x11" * 9)
    assert len(frames9) == 1
    assert len(frames9[0]) == 16
    assert frames9[0][2] == 0x8B
    frames10 = ch341i2c.build_write_frames(0x50, 0, b"\x11" * 10)
    assert len(frames10) == 2
    assert frames10[0][2] == 0x8B
    assert frames10[1][2] == 0x83
