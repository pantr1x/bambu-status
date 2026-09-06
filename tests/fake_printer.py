"""A stand-in Bambu Lab printer: MQTT over TLS on 8883 plus the camera stream
on 6000. Speaks enough of both to drive the real monitor, and records every
command it is sent, so a test can assert that the buttons reach it.

Needs openssl on PATH for a throwaway certificate — the printer serves a
self-signed one too, which is why the monitor does not verify it."""
import json, os, ssl, socket, struct, subprocess, tempfile, threading, time

CERT_DIR = os.path.join(tempfile.gettempdir(), "bambu-fake-printer")
CERT = os.path.join(CERT_DIR, "cert.pem")
KEY = os.path.join(CERT_DIR, "key.pem")


def ensure_cert():
    """Returns False when openssl is missing, so callers can skip."""
    if os.path.exists(CERT) and os.path.exists(KEY):
        return True
    os.makedirs(CERT_DIR, exist_ok=True)
    try:
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048",
                        "-keyout", KEY, "-out", CERT, "-days", "2", "-nodes",
                        "-subj", "/CN=bambu-fake"],
                       check=True, capture_output=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def rlen(n):
    out = b""
    while True:
        b = n % 128
        n //= 128
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def read_rlen(sock):
    mult, value = 1, 0
    while True:
        b = sock.recv(1)
        if not b:
            raise ConnectionError
        value += (b[0] & 127) * mult
        if not (b[0] & 128):
            return value
        mult *= 128


def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError
        buf += chunk
    return buf


class FakePrinter:
    def __init__(self, serial="01P00C612903019", frame=b"", access_code="12345678"):
        self.serial = serial
        self.access_code = access_code
        self.frame = frame
        self.commands = []           # what the widget asked the printer to do
        self.percent = 63
        self.state = "RUNNING"
        self.stop = threading.Event()
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(CERT, KEY)
        self.mqtt = socket.socket(); self.mqtt.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.mqtt.bind(("127.0.0.1", 8883)); self.mqtt.listen(2)
        self.cam = socket.socket(); self.cam.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.cam.bind(("127.0.0.1", 6000)); self.cam.listen(2)

    def start(self):
        for target in (self.serve_mqtt, self.serve_cam):
            threading.Thread(target=target, daemon=True).start()

    def report(self):
        return json.dumps({"print": {
            "gcode_state": self.state, "mc_percent": self.percent,
            "mc_remaining_time": 97, "subtask_name": "bearing_block_v3.gcode.3mf",
            "gcode_file": "/sdcard/bearing_block_v3.3mf",
            "layer_num": 184, "total_layer_num": 312,
            "nozzle_temper": 219.7, "bed_temper": 60.0}})

    def publish(self, sock, topic, payload):
        body = struct.pack(">H", len(topic)) + topic.encode() + payload.encode()
        sock.sendall(bytes([0x30]) + rlen(len(body)) + body)

    def serve_mqtt(self):
        while not self.stop.is_set():
            try:
                raw, _ = self.mqtt.accept()
                threading.Thread(target=self.session, args=(raw,), daemon=True).start()
            except OSError:
                return

    @staticmethod
    def connect_password(body):
        """Pull the password out of a CONNECT: 10 bytes of variable header,
        then client id, username and password, each length-prefixed."""
        pos = 10
        fields = []
        for _ in range(3):
            if pos + 2 > len(body):
                return ""
            n = struct.unpack(">H", body[pos:pos + 2])[0]
            fields.append(body[pos + 2:pos + 2 + n].decode("utf-8", "replace"))
            pos += 2 + n
        return fields[2] if len(fields) == 3 else ""

    def session(self, raw):
        sock = self.ctx.wrap_socket(raw, server_side=True)
        hdr = recv_exact(sock, 1); n = read_rlen(sock)
        body = recv_exact(sock, n)                                             # CONNECT
        if self.connect_password(body) != self.access_code:
            sock.sendall(bytes([0x20, 0x02, 0x00, 0x04]))     # bad credentials
            sock.close()
            return
        sock.sendall(bytes([0x20, 0x02, 0x00, 0x00]))                          # CONNACK ok
        threading.Thread(target=self.push_loop, args=(sock,), daemon=True).start()
        while not self.stop.is_set():
            try:
                hdr = recv_exact(sock, 1)
                n = read_rlen(sock)
                body = recv_exact(sock, n) if n else b""
            except (ConnectionError, OSError):
                return
            kind = hdr[0] >> 4
            if kind == 8:                                                      # SUBSCRIBE
                pid = body[:2]
                sock.sendall(bytes([0x90, 0x03]) + pid + bytes([0x00]))
            elif kind == 3:                                                    # PUBLISH
                tlen = struct.unpack(">H", body[:2])[0]
                payload = body[2 + tlen:]
                try:
                    msg = json.loads(payload.decode())
                except ValueError:
                    continue
                if "print" in msg:
                    self.commands.append(msg["print"])
                    cmd = msg["print"].get("command")
                    if cmd == "pause":
                        self.state = "PAUSE"
                    elif cmd == "resume":
                        self.state = "RUNNING"
                    elif cmd == "stop":
                        self.state = "FAILED"
                    elif cmd == "project_file":
                        self.state, self.percent = "RUNNING", 0

    def push_loop(self, sock):
        while not self.stop.is_set():
            try:
                self.publish(sock, f"device/{self.serial}/report", self.report())
            except OSError:
                return
            time.sleep(0.5)

    def serve_cam(self):
        while not self.stop.is_set():
            try:
                raw, _ = self.cam.accept()
            except OSError:
                return
            try:
                sock = self.ctx.wrap_socket(raw, server_side=True)
                recv_exact(sock, 80)                      # the auth blob
                while not self.stop.is_set():
                    sock.sendall(struct.pack("<IIII", len(self.frame), 0, 0, 0)
                                 + self.frame)
                    time.sleep(0.5)
            except (OSError, ConnectionError):
                continue

    def shutdown(self):
        self.stop.set()
        for s in (self.mqtt, self.cam):
            try:
                s.close()
            except OSError:
                pass
