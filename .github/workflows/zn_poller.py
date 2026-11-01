#!/usr/bin/env python3
"""
ZN Server Poller (mit FTP-Upload)
Fragt per UDP (getinfo) mehrere CoD2-Server ab und laedt das Ergebnis per FTP
in deinen CoD2-Serverordner hoch. Das GSC-Modul _serverlist.gsc liest die Datei.

Der Poller laeuft NICHT auf dem Gameserver, sondern auf irgendeinem Rechner,
der dauerhaft an ist (eigener PC, Raspberry Pi, kleiner VPS ...).
Nur Python 3, keine Zusatzpakete.

Start:  python3 zn_poller.py
(FTP-Daten oben in der Konfiguration eintragen)

Ohne FTP (Poller laeuft auf dem Gameserver): FTP_HOST leer lassen und
        python3 zn_poller.py /pfad/zum/server/zn_servers.cfg
"""
import ftplib, io, os, re, socket, sys, time

# --- FTP-Zugang zu deinem CoD2-Serverordner -------------------------------
FTP_HOST = os.environ.get("FTP_HOST", "")                 # z.B. "ftp.meinhoster.de"  (leer = kein FTP)
FTP_PORT = int(os.environ.get("FTP_PORT", "21"))
FTP_USER = os.environ.get("FTP_USER", "")
FTP_PASS = os.environ.get("FTP_PASS", "")
FTP_TLS  = os.environ.get("FTP_TLS", "") == "1"               # True, falls dein Hoster FTPS verlangt
FTP_DIR  = os.environ.get("FTP_DIR", "server")           # Ordner im FTP, in dem uptime.cfg liegt
FTP_FILE = "zn_servers.cfg"
# ---------------------------------------------------------------------------

INTERVAL = 15          # Sekunden zwischen den Abfragen
TIMEOUT  = 2.0
MAXNAME  = 26          # sichtbare Zeichen (Farbcodes zaehlen nicht)

# Reihenfolge = Zeile 1 / Zeile 2 im Menue.
# (Anzeigename falls offline, IP, Port)
SERVERS = [
    ("^4Zombie^8Nation ^7Zombie Server", "213.199.49.8", 28960),
    ("^4[^7ZN^4]B^7otzombie Server",     "213.199.49.8", 28965),
]

HDR = b"\xff\xff\xff\xff"


def clean(s):
    """Zeichen entfernen, die das Dateiformat oder cvars stoeren."""
    s = s.replace("|", "").replace("~", "").replace('"', "").replace(";", "")
    s = s.replace("\\", "").replace("\r", "").replace("\n", "")
    return s.strip()


def cut_colored(s, maxvisible):
    """Auf maxvisible sichtbare Zeichen kuerzen, ^x-Codes bleiben erhalten."""
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
    # Format: name|map|clients|max|gametype|online     (Leerzeichen -> ~)
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
            # Hoster erlaubt kein rename: direkt hochladen
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
            print(__doc__)
            sys.exit(1)
        out = args[0]
    once = "--once" in sys.argv
    while True:
        lines = [line_for(*s) for s in SERVERS]
        # 3. Zeile: Heartbeat (aendert sich bei jedem Durchlauf). Das GSC erkennt
        # daran, ob der Poller noch laeuft, und zeigt sonst "keine Daten".
        lines.append(str(int(time.time())))
        payload = ("\n".join(lines) + "\n").encode("latin1", errors="replace")
        try:
            if use_ftp:
                upload_ftp(payload)
            else:
                tmp = out + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(payload)
                os.replace(tmp, out)
            print(time.strftime("%H:%M:%S"), "ok:", " || ".join(lines[:-1]))
        except Exception as e:
            print(time.strftime("%H:%M:%S"), "Upload-Fehler:", e)
        if once:
            break
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
