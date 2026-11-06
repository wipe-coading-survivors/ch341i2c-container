#!/usr/bin/env python3
"""ch341i2c.py — userspace I2C master для PACBTECH SFP Programmer (CH341A 1a86:5512), pyusb.

Протокол (подтверждён двумя независимыми опорниками — ch341eeprom и драйвером
frank-zago i2c-ch341 + вендорским CH341DLL):
- I2C-стрим идёт как bulk OUT (EP 0x02), первый байт пакета — 0xAA (I2C_STREAM);
  0x1A НЕ работает для I2C на этой микросхеме.
- 0x74=STA 0x75=STO 0x80|N=OUT N байт (N>=1), 0xC0|N=IN N байт,
  0xC0|0 (голый IN) = 1 байт с NAK, 0x60|speed=SET (0=20k 1=100k 2=400k 3=750k),
  0x00=END. OUT|0 + байт-адрес = проба: на bulk IN приходит status, бит 0x80 = NAK.
- Читаемые данные приходят на bulk IN (EP 0x82), по 32 байта на пакет.

Запись в A0h SFP-модуля защищена от записи until level переключён — смотри
docs/42-transceiver-programming.md; поведение verify учитывает это.
"""
import argparse
import sys

VID, PID = 0x1A86, 0x5512
EP_OUT, EP_IN = 0x02, 0x82
CMD_STREAM = 0xAA
STM_STA, STM_STO, STM_OUT, STM_IN, STM_SET, STM_END = 0x74, 0x75, 0x80, 0xC0, 0x60, 0x00
PKT = 32
TIMEOUT = 2000


def open_dev():
    import usb.core
    import usb.util
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        sys.exit("CH341 (1a86:5512) не найден в USB")
    if dev.is_kernel_driver_active(0):
        dev.detach_kernel_driver(0)
        dev.set_configuration()
        usb.util.claim_interface(dev, 0)
    try:
        ver = dev.ctrl_transfer(0xC0, 0x5F, 0, 0, 2)
        print(f"CH341 version: {ver[0]}.{ver[1]:02d}", file=sys.stderr)
    except usb.core.USBError as e:
        print(f"GET_VER warning: {e}", file=sys.stderr)
    return dev


def set_speed(dev, speed=1):
    dev.write(EP_OUT, bytes([CMD_STREAM, STM_SET | (speed & 3), STM_END]), TIMEOUT)


def probe_ack(dev, dev_addr):
    """True если устройство ACK'нуло свой адрес (write direction)."""
    dev.write(EP_OUT, bytes([CMD_STREAM, STM_STA, STM_OUT, (dev_addr << 1) & 0xFE,
                             STM_STO, STM_END]), TIMEOUT)
    st = bytes(dev.read(EP_IN, 8, TIMEOUT))
    return not (st[0] & 0x80), st[0]


def build_read_frames(dev_addr, mem_addr, n):
    """Кадры чтения n байт, формат ch341eeprom (каждый кадр — отдельный bulk OUT,
    первый кадр содержит адресацию; нули-END добивают кадр не нужны — передаём
    короткие пакеты, CH341 это принимает). Возвращает (frames, takes): takes[i]
    — сколько IN-байт ответит кадр i (перестройка хвоста последнего кадра
    (k-1)+1 не меняет суммарное число IN-байт — оно равно take)."""
    frames = []
    takes = []
    head = [CMD_STREAM, STM_STA, STM_OUT | 2, (dev_addr << 1) & 0xFE, mem_addr & 0xFF,
            STM_STA, STM_OUT | 1, (dev_addr << 1) | 1]
    remaining = n
    first = True
    while remaining > 0:
        if first:
            room = PKT - len(head) - 1  # -1 под END
            take = min(remaining, room)
            frames.append(bytes(head + [STM_IN | take, STM_END]))
            takes.append(take)
            first = False
        else:
            take = min(remaining, PKT - 2)
            frames.append(bytes([CMD_STREAM, STM_IN | take, STM_END]))
            takes.append(take)
        remaining -= take
    # последний кадр: заменить хвост на (k-1 с ACK) + 1 с NAK + STO
    last = list(frames[-1])
    assert last[-1] == STM_END
    last.pop()
    k = last[-1] & 0x3F
    assert (last[-1] & 0xC0) == STM_IN and k >= 1
    if k > 1:
        last = last[:-1] + [STM_IN | (k - 1), STM_IN, STM_STO, STM_END]
    else:
        last = last[:-1] + [STM_IN, STM_STO, STM_END]
    frames[-1] = bytes(last)
    return frames, takes


def build_write_frames(dev_addr, mem_addr, data):
    """Кадры записи: [STA OUT|(2+len) addr mem data... STO END] — OUT|N считает
    ВСЕ байты на шине после токена (адрес+mem+data); до 9 байт данных на кадр:
    кадр = 2+1+1+1+9+2 = 16 байт максимум — эмпирически безопасный размер
    USB-пакета (32-Б пакеты без ZLP не доезжают до I2C, sessions 7/10)."""
    frames = []
    pos = 0
    while pos < len(data):
        chunk = data[pos:pos + 9]
        fr = [CMD_STREAM, STM_STA, STM_OUT | (len(chunk) + 2), (dev_addr << 1) & 0xFE,
              (mem_addr + pos) & 0xFF] + list(chunk) + [STM_STO, STM_END]
        frames.append(bytes(fr))
        pos += len(chunk)
    return frames


def do_read(dev, dev_addr, mem_addr, n, speed=1):
    # Кадры запроса и чтение IN ЧЕРЕДУЮТСЯ: если сначала записать все кадры в
    # bulk OUT, не читая ответы, внутренний буфер CH341 переполняется и чип
    # встаёт (USBTimeoutError 110, спасает только USB-reset) — зависание
    # воспроизводилось уже на read 128 (см. journal 2026-10-06-qsfp28-edr-task-01).
    set_speed(dev, speed)
    frames, takes = build_read_frames(dev_addr, mem_addr, n)
    data = b""
    for fr, take in zip(frames, takes):
        dev.write(EP_OUT, fr, TIMEOUT)
        got = b""
        while len(got) < take:
            pkt = dev.read(EP_IN, PKT, TIMEOUT)
            got += bytes(pkt)
        data += got[:take]
    return data


def do_write(dev, dev_addr, mem_addr, data, speed=1, verify=True):
    import usb.core
    set_speed(dev, speed)
    ack, st = probe_ack(dev, dev_addr)
    if not ack:
        sys.exit(f"устройство 0x{dev_addr:02x} не отвечает (probe status=0x{st:02x}) — запись отменена")
    frames = build_write_frames(dev_addr, mem_addr, data)
    for fr in frames:
        dev.write(EP_OUT, fr, TIMEOUT)
        try:
            st = bytes(dev.read(EP_IN, 8, TIMEOUT))
            print(f"frame status: 0x{st[0]:02x}", file=sys.stderr)
        except usb.core.USBError:
            pass
    if verify:
        back = do_read(dev, dev_addr, mem_addr, len(data))
        if back != bytes(data):
            bad = sum(1 for a, b in zip(back, data) if a != b)
            print(f"verify: {bad}/{len(data)} байт не сошлись "
                  f"(модуль может игнорировать запись — A0h write-protected?)", file=sys.stderr)
            sys.exit(2)
        print(f"verify OK: {len(data)} bytes", file=sys.stderr)


def hexdump(data, base=0):
    for off in range(0, len(data), 16):
        chunk = data[off:off + 16]
        hexs = " ".join(f"{b:02x}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"{base + off:04x}: {hexs:<48} {asc}")


def decode_a0h(data):
    def s(a, b):
        return bytes(data[a:b]).decode("ascii", "replace").strip()
    cc_base = data[63]
    cc_base_calc = sum(data[0:63]) & 0xFF
    cc_ext = data[95]
    cc_ext_calc = sum(data[64:95]) & 0xFF
    print("=== SFF-8472 A0h decode ===")
    print(f"byte 0  (ID)              : 0x{data[0]:02x}")
    print(f"byte 2  (connector)       : 0x{data[2]:02x}")
    print(f"byte 3  (compliance)      : 0x{data[3]:02x}")
    print(f"byte 4-10 (ext codes)     : {' '.join(f'{b:02x}' for b in data[4:11])}")
    print(f"byte 12 (BR nominal)      : 0x{data[12]:02x} ({data[12]} x100 MBd)")
    print(f"byte 14-17 (BR ext)       : {' '.join(f'{b:02x}' for b in data[14:18])}")
    print(f"vendor (20-35)            : {s(20, 36)!r}")
    print(f"PN (40-55)                : {s(40, 56)!r}")
    print(f"rev (56-59)               : {s(56, 60)!r}")
    print(f"SN (68-83)                : {s(68, 84)!r}")
    print(f"date (84-91)              : {s(84, 92)!r}")
    print(f"CC_BASE (63)              : 0x{cc_base:02x}  calc=0x{cc_base_calc:02x} "
          f"{'OK' if cc_base == cc_base_calc else 'MISMATCH'}")
    print(f"CC_EXT (95)               : 0x{cc_ext:02x}  calc=0x{cc_ext_calc:02x} "
          f"{'OK' if cc_ext == cc_ext_calc else 'MISMATCH'}")


def main():
    ap = argparse.ArgumentParser(description="CH341 userspace I2C (PACBTECH SFP programmer)")
    ap.add_argument("--addr", type=lambda x: int(x, 0), required=True,
                    help="7-bit I2C адрес (SFP: A0h=0x50, A2h=0x51)")
    ap.add_argument("--offset", type=lambda x: int(x, 0), default=0, help="адрес в EEPROM")
    ap.add_argument("--speed", type=int, default=1, choices=[0, 1, 2, 3],
                    help="0=20k 1=100k 2=400k 3=750k")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe", help="проверить ACK по адресу")
    rp = sub.add_parser("read", help="прочитать N байт")
    rp.add_argument("n", type=lambda x: int(x, 0))
    rp.add_argument("--decode-a0", action="store_true", help="расшифровать поля SFF-8472 A0h")
    wp = sub.add_parser("write", help="записать файл в EEPROM")
    wp.add_argument("file")
    wp.add_argument("--dry-run", action="store_true",
                    help="только собрать кадры и показать, USB не трогать")
    args = ap.parse_args()

    if args.cmd == "write" and args.dry_run:
        data = open(args.file, "rb").read()
        frames = build_write_frames(args.addr, args.offset, data)
        print(f"dry-run: {len(data)} байт, {len(frames)} кадров")
        for i, fr in enumerate(frames):
            print(f"frame{i}: {' '.join(f'{b:02x}' for b in fr)}")
        return

    dev = open_dev()
    if args.cmd == "probe":
        ack, st = probe_ack(dev, args.addr)
        print(f"0x{args.addr:02x}: probe status=0x{st:02x} -> "
              f"{'ACK, устройство на шине' if ack else 'NAK, устройства нет'}")
        sys.exit(0 if ack else 1)
    if args.cmd == "read":
        ack, st = probe_ack(dev, args.addr)
        if not ack:
            print(f"0x{args.addr:02x}: NAK (status=0x{st:02x}) — модуля в клетке нет", file=sys.stderr)
            sys.exit(1)
        data = do_read(dev, args.addr, args.offset, args.n, args.speed)
        if all(b == 0xFF for b in data):
            print("ВНИМАНИЕ: все байты 0xFF — шина пустая, данным не доверять", file=sys.stderr)
        hexdump(data, args.offset)
        if args.decode_a0:
            decode_a0h(data)
    elif args.cmd == "write":
        data = open(args.file, "rb").read()
        do_write(dev, args.addr, args.offset, data, args.speed)
        print(f"written {len(data)} bytes @0x{args.offset:02x} to dev 0x{args.addr:02x}")


if __name__ == "__main__":
    main()
