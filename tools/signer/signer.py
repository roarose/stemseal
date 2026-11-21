# -*- coding: utf-8 -*-
"""stemseal release signer. Runs only on the release owner's own PC, with the key on a USB stick. Not part of the package.

  python signer.py make-keys       make the main and the spare release key (each on its own USB stick)
  python signer.py sign [file]     sign release.json (downloaded from the main branch, or the given file)

Needs Python 3.9+ and the `cryptography` package (pip install cryptography). Sends nothing anywhere: `sign` only
downloads the public release.json. The secret keys are written only to the folders you name, encrypted with your
passphrase, and are never printed."""
import getpass, hashlib, json, os, sys, urllib.request

RELEASE_URL = "https://raw.githubusercontent.com/roarose/stemseal/main/stemseal/cells/release.json"
MAIN_NAME, SPARE_NAME = "stemseal-release-key-main.pem", "stemseal-release-key-spare.pem"

def say(text): print(text, flush=True)

def _crypto():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        return Ed25519PrivateKey, serialization
    except ImportError:
        say("이 도구에는 cryptography 꾸러미가 필요합니다. 명령 창에서 한 번만 실행하세요:  pip install cryptography")
        sys.exit(2)

def _removable(path):
    """True on Windows when the folder is on a removable drive (USB stick). Elsewhere it is not checked."""
    if os.name != "nt": return True
    import ctypes
    drive = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
    return ctypes.windll.kernel32.GetDriveTypeW(drive) == 2       # DRIVE_REMOVABLE

def _folder(question, allow_fixed=False):
    while True:
        a = input(question).strip().strip('"')
        if len(a) == 1 and a.isalpha(): a = a.upper() + ":\\"
        if not a or not os.path.isdir(a): say("  그 폴더(드라이브)를 찾지 못했습니다. USB가 꽂혀 있는지 확인하고 다시 입력하세요."); continue
        if not allow_fixed and not _removable(a): say("  USB 같은 이동식 드라이브가 아닙니다. 열쇠는 USB에만 둡니다. 다시 입력하세요."); continue
        return a

def _passphrase(twice):
    while True:
        p = getpass.getpass("  암호 (화면에 보이지 않습니다): ")
        if len(p) < 12: say("  12자 이상으로 정해 주세요."); continue
        if twice and getpass.getpass("  같은 암호를 한 번 더: ") != p: say("  두 번 입력한 암호가 다릅니다. 다시 해 주세요."); continue
        return p.encode("utf-8")

def _warn():
    say("")
    say("확인: Claude 원격 세션(Remote Control)이 이 PC에서 켜져 있으면 지금 끄고 다시 실행하세요.")
    say("      암호는 키보드로만 입력하고, 채팅이나 파일 어디에도 적지 마세요.")
    say("")

def make_keys(main_dir=None, spare_dir=None, passphrase=None, allow_fixed=False):
    Key, ser = _crypto()
    if main_dir is None:
        _warn()
        main_dir = _folder("주 열쇠를 넣을 USB의 드라이브 문자 (예: E): ", allow_fixed)
        spare_dir = _folder("예비 열쇠를 넣을 다른 USB의 드라이브 문자 (예: F): ", allow_fixed)
    if os.path.realpath(main_dir) == os.path.realpath(spare_dir): say("주 열쇠와 예비 열쇠는 서로 다른 USB에 둡니다."); return 1
    paths = [os.path.join(main_dir, MAIN_NAME), os.path.join(spare_dir, SPARE_NAME)]
    for p in paths:
        if os.path.exists(p): say("이미 열쇠가 있습니다: %s  (덮어쓰지 않습니다)" % p); return 1
    if passphrase is None:
        say("열쇠를 잠글 암호를 정합니다. 종이에 적어 예비 USB와 같은 곳에 보관하세요.")
        passphrase = _passphrase(twice=True)
    publics = []
    for p in paths:
        k = Key.generate()
        pem = k.private_bytes(ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.BestAvailableEncryption(passphrase))
        with open(p, "xb") as f: f.write(pem)
        publics.append(k.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw).hex())
    say("")
    say("열쇠를 만들었습니다. 아래 두 줄은 공개 열쇠입니다(비밀이 아닙니다). 이 두 줄만 작업 스레드에 붙여 주세요.")
    say("  주   %s" % publics[0])
    say("  예비 %s" % publics[1])
    say("USB 두 개는 뽑아서 서로 다른 곳에 보관하세요.")
    return publics

def _load(path, passphrase):
    _, ser = _crypto()
    with open(path, "rb") as f: data = f.read()
    return ser.load_pem_private_key(data, password=passphrase)

def summary(raw):
    rel = json.loads(raw.decode("utf-8"))
    cells = ["%s %s" % (n, v) for n, vs in sorted(rel["cells"].items()) for v in sorted(vs)]
    return rel.get("release"), cells, hashlib.sha256(raw).hexdigest()

def sign(source=None, key_path=None, passphrase=None, out_dir=None, confirm=True, allow_fixed=False):
    _crypto()
    if source and os.path.isfile(source):
        with open(source, "rb") as f: raw = f.read()
    else:
        say("공개된 release.json을 내려받습니다(받기만 하고 아무것도 보내지 않습니다).")
        with urllib.request.urlopen(urllib.request.Request(source or RELEASE_URL, headers={"User-Agent": "stemseal-signer"}), timeout=30) as r:
            raw = r.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024: say("release.json이 너무 큽니다. 서명하지 않습니다."); return 1
    n, cells, digest = summary(raw)
    say("")
    say("출시 번호: cells-%s" % n)
    say("세포 %d개:" % len(cells))
    for c in cells: say("  " + c)
    say("지문: %s" % digest[:8])
    say("")
    if confirm:
        _warn()
        if input("작업 스레드 메시지의 지문과 같으면 y 를 입력하세요: ").strip().lower() != "y": say("서명하지 않았습니다."); return 1
    if key_path is None:
        d = _folder("주 열쇠 USB의 드라이브 문자 (예: E): ", allow_fixed)
        key_path = os.path.join(d, MAIN_NAME)
        if not os.path.exists(key_path):
            spare = os.path.join(d, SPARE_NAME)
            if os.path.exists(spare): key_path = spare
            else: say("그 USB에 열쇠 파일이 없습니다."); return 1
    for _ in range(3):
        try:
            k = _load(key_path, passphrase if passphrase is not None else _passphrase(twice=False)); break
        except (ValueError, TypeError):
            if passphrase is not None: say("암호가 맞지 않습니다."); return 1
            say("  암호가 맞지 않습니다. 다시 입력하세요.")
    else: return 1
    sig = k.sign(raw).hex()
    out_dir = out_dir or os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(out_dir): out_dir = os.path.expanduser("~")
    out = os.path.join(out_dir, "release.json.sig")
    with open(out, "w", encoding="ascii") as f: f.write(sig + "\n")
    say("")
    say("서명했습니다: %s" % out)
    say("이 파일을 GitHub의 Release 초안 화면에 끌어다 놓고 Publish release를 누르세요. 그다음 USB를 뽑으세요.")
    return out

def main(argv):
    if not argv or argv[0] not in ("make-keys", "sign"): say(__doc__); return 2
    if argv[0] == "make-keys": r = make_keys()
    else: r = sign(argv[1] if len(argv) > 1 else None)
    return 0 if isinstance(r, (str, list)) else 1

if __name__ == "__main__":
    try: sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt: say("\n멈췄습니다. 아무것도 쓰지 않았습니다."); sys.exit(1)
