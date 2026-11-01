#!/usr/bin/env python3
import ftplib, io, os, re, socket, sys, time
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

FTP_HOST = os.environ.get("FTP_HOST", "")
FTP_PORT = int(os.environ.get("FTP_PORT", "21"))
FTP_USER = os.environ.get("FTP_USER", "")
FTP_PASS = os.environ.get("FTP_PASS", "")
FTP_TLS  = os.environ.get("FTP_TLS", "") == "1"
FTP_DIR  = os.environ.get("FTP_DIR", "server")
FTP_FILE = "zn_servers.cfg"

INTERVAL = 15
TIMEOUT  = 2.0
MAXNAME  = 26

SERVERS = [
    ("^4Zombie^8Nation", "213.199.49.8", 28960),
    ("^4[^7ZN^4]B^7otzombie",     "213.199.49.8", 28965),
]

HDR = b"\xff\xff\xff\xff"


def clean(s):
    s = s.replace("|", "").replace("~", "").replace('"', "").replace(";", "")
    s = s.replace("\\", "").replace("\r", "").replace("\n", "")
    return s.strip()


def cut_colored(s, maxvisible):
    out, vis, i = "", 0, 0
    while i < len(s) and vis < maxvisible:
        if s[i] == "^" and i + 1 < len(s) and s[i + 1].isdigit():
            out += s[i:i + 2]
            i += 2
            continue
        out += s[i]
        vis += 1
        i += 1
    return out


def stamp():
    try:
        now = datetime.now(ZoneInfo("Europe/Berlin"))
    except Exception:
        now = datetime.now(timezone.utc)
    return now.strftime("%d.%m.~%H:%M~%Z")


def getinfo(ip, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(TIMEOUT)
    try:
        sock.sendto(HDR + b"getinfo znpoll", (ip, port))
        data, _ = sock.recvfrom(4096)
    finally:
        sock.close()
    text = data.decode("latin1")
    if "infoResponse" not in text:
        raise ValueError("keine infoResponse")
    body = text.split("\n", 2)[1] if "\n" in text else ""
    parts = body.strip("\\").split("\\")
    return dict(zip(parts[0::2], parts[1::2]))


def line_for(label, ip, port):
    try:
        d = getinfo(ip, port)
        name = cut_colored(clean(d.get("hostname", label)), MAXNAME) or label
        mapn = clean(d.get("mapname", "?"))
        cur  = re.sub(r"\D", "", d.get("clients", "0")) or "0"
        mx   = re.sub(r"\D", "", d.get("sv_maxclients", "0")) or "0"
        gt   = clean(d.get("gametype", ""))
        ok   = 1
    except Exception:
        name, mapn, cur, mx, gt, ok = label, "-", "0", "0", "", 0
    return "|".join([name, mapn, cur, mx, gt, str(ok)]).replace(" ", "~")


def upload_ftp(payload):
    cls = ftplib.FTP_TLS if FTP_TLS else ftplib.FTP
    ftp = cls()
    ftp.connect(FTP_HOST, FTP_PORT, timeout=15)
    ftp.login(FTP_USER, FTP_PASS)
    if FTP_TLS:
        ftp.prot_p()
    try:
        if FTP_DIR:
            ftp.cwd(FTP_DIR)
        tmp = FTP_FILE + ".tmp"
        ftp.storbinary("STOR " + tmp, io.BytesIO(payload))
        try:
            try:
                ftp.delete(FTP_FILE)
            except ftplib.error_perm:
                pass
            ftp.rename(tmp, FTP_FILE)
        except ftplib.error_perm:
            ftp.storbinary("STOR " + FTP_FILE, io.BytesIO(payload))
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()


def main():
    use_ftp = bool(FTP_HOST)
    out = None
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not use_ftp:
        if not args:
            print("Usage: python3 zn_poller.py /path/to/zn_servers.cfg")
            print("Or set FTP_HOST env var for FTP upload mode.")
            sys.exit(1)
        out = args[0]
    once = "--once" in sys.argv
    while True:
        lines = [line_for(*s) for s in SERVERS]
        lines.append(str(int(time.time())))
        lines.append(stamp())
        payload = ("\n".join(lines) + "\n").encode("latin1", errors="replace")
        try:
            if use_ftp:
                upload_ftp(payload)
            else:
                tmp = out + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(payload)
                os.replace(tmp, out)
            print(time.strftime("%H:%M:%S"), "ok:", " || ".join(lines[:len(SERVERS)]))
        except Exception as e:
            print(time.strftime("%H:%M:%S"), "Upload-Fehler:", e)
        if once:
            break
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
