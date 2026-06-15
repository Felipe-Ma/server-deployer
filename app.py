import customtkinter as ctk
import paramiko
import threading
import queue
import time
import io
from tkinter import filedialog

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

DOCKER_INSTALL = {
    "Ubuntu": (
        "apt-get update -y && apt-get install -y ca-certificates curl gnupg && "
        "install -m 0755 -d /etc/apt/keyrings && "
        "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && "
        "chmod a+r /etc/apt/keyrings/docker.gpg && "
        "echo \"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] "
        "https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo \\\"$VERSION_CODENAME\\\") stable\" "
        "| tee /etc/apt/sources.list.d/docker.list > /dev/null && "
        "apt-get update -y && "
        "apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin && "
        "systemctl enable docker && systemctl start docker"
    ),
    "CentOS": (
        "yum install -y yum-utils && "
        "yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo && "
        "yum install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin && "
        "systemctl enable docker && systemctl start docker"
    ),
    "Rocky Linux": (
        "yum install -y yum-utils && "
        "yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo && "
        "yum install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin && "
        "systemctl enable docker && systemctl start docker"
    ),
    "Fedora": (
        "dnf -y install dnf-plugins-core && "
        "dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo && "
        "dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin && "
        "systemctl enable docker && systemctl start docker"
    ),
}

SYSTEMD_SERVICE = """\
[Unit]
Description=Docker Compose Application Service
Requires=docker.service
After=docker.service

[Service]
WorkingDirectory=/opt
ExecStart=/bin/bash -c "/usr/bin/docker compose up -d"
ExecStop=/bin/bash -c "/usr/bin/docker compose down"
User=root
Group=root
TimeoutStartSec=0
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Server Data Collector — Deployment Tool")
        self.geometry("1280x800")
        self.minsize(1000, 640)

        self._ssh: paramiko.SSHClient | None = None
        self._shell: paramiko.Channel | None = None
        self._q: queue.Queue = queue.Queue()

        self._build_layout()
        self._poll()

    # ─── layout ───────────────────────────────────────────────────────────────

    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._left = ctk.CTkScrollableFrame(self, width=330)
        self._left.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)

        self._right = ctk.CTkFrame(self)
        self._right.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=10)
        self._right.grid_rowconfigure(1, weight=1)
        self._right.grid_columnconfigure(0, weight=1)

        self._bar = ctk.CTkFrame(self, height=64)
        self._bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))

        self._build_left()
        self._build_terminal()
        self._build_bar()

    def _section(self, parent, title):
        ctk.CTkLabel(parent, text=title,
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(12, 2))
        ctk.CTkFrame(parent, height=1, fg_color="gray35").pack(fill="x", pady=(0, 6))

    def _field(self, parent, label, default="", show=None):
        ctk.CTkLabel(parent, text=label, font=ctk.CTkFont(size=11)).pack(anchor="w")
        e = ctk.CTkEntry(parent, show=show)
        e.pack(fill="x", pady=(0, 5))
        if default:
            e.insert(0, default)
        return e

    def _build_left(self):
        p = self._left

        # ── SSH Connection ────────────────────────────────────────────────────
        self._section(p, "SSH Connection")
        self._e_host = self._field(p, "Host / IP")
        self._e_port = self._field(p, "Port", "22")
        self._e_user = self._field(p, "Username", "root")

        ctk.CTkLabel(p, text="Auth Method", font=ctk.CTkFont(size=11)).pack(anchor="w")
        self._auth_var = ctk.StringVar(value="Password")
        ctk.CTkOptionMenu(p, values=["Password", "SSH Key"],
                          variable=self._auth_var,
                          command=self._toggle_auth).pack(fill="x", pady=(0, 5))

        # password widget
        self._pw_frame = ctk.CTkFrame(p, fg_color="transparent")
        self._pw_frame.pack(fill="x")
        ctk.CTkLabel(self._pw_frame, text="Password", font=ctk.CTkFont(size=11)).pack(anchor="w")
        self._e_pass = ctk.CTkEntry(self._pw_frame, show="*")
        self._e_pass.pack(fill="x", pady=(0, 5))

        # key widget (hidden by default)
        self._key_frame = ctk.CTkFrame(p, fg_color="transparent")
        ctk.CTkLabel(self._key_frame, text="Key File", font=ctk.CTkFont(size=11)).pack(anchor="w")
        row = ctk.CTkFrame(self._key_frame, fg_color="transparent")
        row.pack(fill="x", pady=(0, 5))
        self._e_key = ctk.CTkEntry(row)
        self._e_key.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(row, text="Browse", width=72, command=self._browse_key).pack(side="right")
        ctk.CTkLabel(self._key_frame, text="Passphrase (optional)", font=ctk.CTkFont(size=11)).pack(anchor="w")
        self._e_phrase = ctk.CTkEntry(self._key_frame, show="*")
        self._e_phrase.pack(fill="x", pady=(0, 5))

        # ── Server Config ─────────────────────────────────────────────────────
        self._section(p, "Server Configuration")
        self._e_server_id   = self._field(p, "Server ID")
        self._e_rack        = self._field(p, "Rack Location")
        self._e_conn        = self._field(p, "Connection Type", "U.2")
        self._e_bays        = self._field(p, "Drive Bays", "8")
        self._e_region      = self._field(p, "Region", "Rancho Cordova")
        self._e_api         = self._field(p, "API Endpoint",
                                          "https://serverdashboard.elements.local/update")

        # ── Deployment ───────────────────────────────────────────────────────
        self._section(p, "Deployment")

        ctk.CTkLabel(p, text="Target OS", font=ctk.CTkFont(size=11)).pack(anchor="w")
        self._os_var = ctk.StringVar(value="Ubuntu")
        ctk.CTkOptionMenu(p, values=["Ubuntu", "CentOS", "Rocky Linux", "Fedora"],
                          variable=self._os_var).pack(fill="x", pady=(0, 5))

        ctk.CTkLabel(p, text="Registry", font=ctk.CTkFont(size=11)).pack(anchor="w")
        self._reg_var = ctk.StringVar(value="Docker Hub (Standard)")
        ctk.CTkOptionMenu(p, values=["Docker Hub (Standard)", "PRC Local Registry"],
                          variable=self._reg_var,
                          command=self._toggle_registry).pack(fill="x", pady=(0, 5))

        self._prc_frame = ctk.CTkFrame(p, fg_color="transparent")
        ctk.CTkLabel(self._prc_frame, text="Registry Address", font=ctk.CTkFont(size=11)).pack(anchor="w")
        self._e_prc = ctk.CTkEntry(self._prc_frame, placeholder_text="e.g. 10.74.26.9:5050")
        self._e_prc.pack(fill="x", pady=(0, 5))

        # ── Upload cert ──────────────────────────────────────────────────────
        self._section(p, "Certificate (optional)")
        ctk.CTkLabel(p, text="Root Certificate (.crt)", font=ctk.CTkFont(size=11)).pack(anchor="w")
        cert_row = ctk.CTkFrame(p, fg_color="transparent")
        cert_row.pack(fill="x", pady=(0, 5))
        self._e_cert = ctk.CTkEntry(cert_row, placeholder_text="Local path to root.crt")
        self._e_cert.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(cert_row, text="Browse", width=72, command=self._browse_cert).pack(side="right")

        self._cert_upload_btn = ctk.CTkButton(p, text="Upload Certificate to /opt/certs/",
                                               command=self._action_upload_cert)
        self._cert_upload_btn.pack(fill="x", pady=(0, 5))

    def _build_terminal(self):
        p = self._right

        hdr = ctk.CTkFrame(p, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 2))
        ctk.CTkLabel(hdr, text="Terminal Output",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
        ctk.CTkButton(hdr, text="Clear", width=60, height=26,
                      command=self._clear).pack(side="right")

        self._term = ctk.CTkTextbox(p, font=ctk.CTkFont(family="Courier New", size=11),
                                    wrap="word", state="disabled")
        self._term.grid(row=1, column=0, sticky="nsew", padx=8, pady=2)

        shell_row = ctk.CTkFrame(p, fg_color="transparent")
        shell_row.grid(row=2, column=0, sticky="ew", padx=8, pady=(2, 8))
        ctk.CTkLabel(shell_row, text="$",
                     font=ctk.CTkFont(family="Courier New", size=13)).pack(side="left", padx=(0, 4))
        self._e_cmd = ctk.CTkEntry(shell_row,
                                   placeholder_text='Type a command and press Enter (needs "Open Shell")')
        self._e_cmd.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._e_cmd.bind("<Return>", self._send_cmd)
        ctk.CTkButton(shell_row, text="Send", width=60,
                      command=self._send_cmd).pack(side="right")

    def _build_bar(self):
        buttons = [
            ("Test SSH",       self._act_test,       None,       None),
            ("Install Docker", self._act_install,     None,       None),
            ("Full Deploy",    self._act_deploy,      "#1a7a1a",  "#1a5e1a"),
            ("Check Status",   self._act_status,      None,       None),
            ("View Logs",      self._act_logs,        None,       None),
            ("Open Shell",     self._act_shell,       None,       None),
            ("Disconnect",     self._act_disconnect,  "#7a1a1a",  "#5e1a1a"),
        ]
        for text, cmd, fg, hover in buttons:
            kw = {}
            if fg:
                kw["fg_color"] = fg
            if hover:
                kw["hover_color"] = hover
            ctk.CTkButton(self._bar, text=text, command=cmd,
                          width=128, **kw).pack(side="left", padx=6, pady=12)

    # ─── toggle helpers ────────────────────────────────────────────────────────

    def _toggle_auth(self, val):
        if val == "SSH Key":
            self._pw_frame.pack_forget()
            self._key_frame.pack(fill="x")
        else:
            self._key_frame.pack_forget()
            self._pw_frame.pack(fill="x")

    def _toggle_registry(self, val):
        if val == "PRC Local Registry":
            self._prc_frame.pack(fill="x")
        else:
            self._prc_frame.pack_forget()

    def _browse_key(self):
        p = filedialog.askopenfilename(title="Select SSH Key",
                                       filetypes=[("All files", "*.*"), ("PEM", "*.pem")])
        if p:
            self._e_key.delete(0, "end")
            self._e_key.insert(0, p)

    def _browse_cert(self):
        p = filedialog.askopenfilename(title="Select Root Certificate",
                                       filetypes=[("CRT files", "*.crt"), ("All files", "*.*")])
        if p:
            self._e_cert.delete(0, "end")
            self._e_cert.insert(0, p)

    # ─── terminal helpers ──────────────────────────────────────────────────────

    def _log(self, text: str):
        self._q.put(text)

    def _poll(self):
        try:
            while True:
                msg = self._q.get_nowait()
                self._term.configure(state="normal")
                self._term.insert("end", msg + "\n")
                self._term.see("end")
                self._term.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _clear(self):
        self._term.configure(state="normal")
        self._term.delete("1.0", "end")
        self._term.configure(state="disabled")

    # ─── SSH helpers ──────────────────────────────────────────────────────────

    def _connect(self) -> paramiko.SSHClient:
        if self._ssh and self._ssh.get_transport() and self._ssh.get_transport().is_active():
            return self._ssh

        host = self._e_host.get().strip()
        port = int(self._e_port.get().strip() or 22)
        user = self._e_user.get().strip()
        if not host:
            raise ValueError("Host / IP is required")

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        kw: dict = dict(hostname=host, port=port, username=user, timeout=15)
        if self._auth_var.get() == "SSH Key":
            key_path = self._e_key.get().strip()
            if not key_path:
                raise ValueError("SSH key file is required")
            phrase = self._e_phrase.get().strip() or None
            kw.update(key_filename=key_path, passphrase=phrase,
                      look_for_keys=False, allow_agent=False)
        else:
            pw = self._e_pass.get()
            if not pw:
                raise ValueError("Password is required")
            kw.update(password=pw, look_for_keys=False, allow_agent=False)

        client.connect(**kw)
        self._ssh = client
        self._log(f"[OK] Connected to {host}:{port} as {user}")
        return client

    def _run(self, client: paramiko.SSHClient, cmd: str) -> tuple[int, str]:
        self._log(f"\n$ {cmd}")
        _, stdout, stderr = client.exec_command(cmd, get_pty=True)
        buf = []
        for line in iter(lambda: stdout.readline(), ""):
            stripped = line.rstrip("\n")
            buf.append(stripped)
            self._log(stripped)
        rc = stdout.channel.recv_exit_status()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        if err and rc != 0:
            for ln in err.splitlines():
                self._log(f"  {ln}")
        return rc, "\n".join(buf)

    def _sftp_write(self, client: paramiko.SSHClient, remote_path: str, content: str):
        sftp = client.open_sftp()
        try:
            with sftp.file(remote_path, "w") as f:
                f.write(content)
            self._log(f"[OK] Wrote {remote_path}")
        finally:
            sftp.close()

    # ─── config builders ──────────────────────────────────────────────────────

    def _cfg(self) -> dict:
        return {
            "SERVER_ID":     self._e_server_id.get().strip(),
            "RACK_LOCATION": self._e_rack.get().strip(),
            "CONNECTION":    self._e_conn.get().strip(),
            "DRIVE_BAYS":    self._e_bays.get().strip(),
            "REGION":        self._e_region.get().strip(),
            "API_ENDPOINT":  self._e_api.get().strip(),
        }

    def _image(self) -> str:
        if self._reg_var.get() == "PRC Local Registry":
            return f"{self._e_prc.get().strip()}/server-data-collector:latest"
        return "felipema/server-data-collector:latest"

    def _compose_yml(self) -> str:
        c = self._cfg()
        return f"""\
services:
  server-data-container:
    image: {self._image()}
    container_name: server-data-container
    privileged: true
    network_mode: "host"
    volumes:
      - /dev:/dev
      - /etc/os-release:/etc/os-release:ro
      - /opt/certs:/opt/certs
    environment:
      - API_ENDPOINT={c['API_ENDPOINT']}
      - SERVER_ID={c['SERVER_ID']}
      - RACK_LOCATION={c['RACK_LOCATION']}
      - CONNECTION={c['CONNECTION']}
      - DRIVE_BAYS={c['DRIVE_BAYS']}
      - REGION={c['REGION']}
    restart: "no"
"""

    # ─── actions (each runs in a daemon thread) ────────────────────────────────

    def _bg(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def _act_test(self):
        def run():
            self._log("\n══ Test SSH Connection ══════════════════")
            try:
                c = self._connect()
                self._run(c, "uname -a")
                self._run(c, "whoami")
                self._run(c, "df -h /")
            except Exception as e:
                self._log(f"[ERROR] {e}")
        self._bg(run)

    def _act_install(self):
        def run():
            self._log("\n══ Install Docker ═══════════════════════")
            try:
                c = self._connect()
                rc, out = self._run(c, "docker --version 2>/dev/null; echo __EXIT$?")
                if "Docker version" in out:
                    self._log("[INFO] Docker already installed — skipping.")
                else:
                    os_type = self._os_var.get()
                    cmd = DOCKER_INSTALL.get(os_type)
                    if not cmd:
                        self._log(f"[ERROR] No install recipe for {os_type}")
                        return
                    rc, _ = self._run(c, cmd)
                    if rc != 0:
                        self._log(f"[ERROR] Docker install failed (exit {rc})")
                        return
                    self._log("[OK] Docker installed.")

                if self._reg_var.get() == "PRC Local Registry":
                    reg = self._e_prc.get().strip()
                    daemon = '{' + f'"insecure-registries":["{reg}"]' + '}'
                    self._run(c, f"mkdir -p /etc/docker && "
                                 f"echo '{daemon}' > /etc/docker/daemon.json && "
                                 f"systemctl restart docker && sleep 2")
                    self._log(f"[OK] Insecure registry configured: {reg}")
            except Exception as e:
                self._log(f"[ERROR] {e}")
        self._bg(run)

    def _act_deploy(self):
        def run():
            self._log("\n══ Full Deployment ══════════════════════")
            try:
                c = self._connect()

                cfg = self._cfg()
                missing = [k for k, v in cfg.items() if not v]
                if missing:
                    self._log(f"[ERROR] Missing fields: {', '.join(missing)}")
                    return

                # 1. Docker
                self._log("\n── Docker check ─────────────────────────")
                rc, out = self._run(c, "docker --version 2>/dev/null || echo MISSING")
                if "MISSING" in out or "Docker version" not in out:
                    self._log("[INFO] Installing Docker…")
                    cmd = DOCKER_INSTALL.get(self._os_var.get(), "")
                    if not cmd:
                        self._log("[ERROR] Unknown OS type")
                        return
                    rc, _ = self._run(c, cmd)
                    if rc != 0:
                        self._log("[ERROR] Docker install failed — aborting.")
                        return

                # 2. PRC registry
                if self._reg_var.get() == "PRC Local Registry":
                    reg = self._e_prc.get().strip()
                    daemon = '{' + f'"insecure-registries":["{reg}"]' + '}'
                    self._run(c, f"mkdir -p /etc/docker && "
                                 f"echo '{daemon}' > /etc/docker/daemon.json && "
                                 f"systemctl restart docker && sleep 3")
                    self._log(f"[OK] PRC registry: {reg}")

                # 3. Cert dir
                self._log("\n── Certificate directory ────────────────")
                self._run(c, "mkdir -p /opt/certs")

                # 4. docker-compose.yml
                self._log("\n── Writing /opt/docker-compose.yml ─────")
                self._sftp_write(c, "/opt/docker-compose.yml", self._compose_yml())

                # 5. systemd service
                self._log("\n── Writing systemd service ──────────────")
                self._sftp_write(c, "/etc/systemd/system/docker-compose-app.service",
                                 SYSTEMD_SERVICE)

                # 6. Pull image
                self._log("\n── Pulling image ────────────────────────")
                self._run(c, "cd /opt && docker compose pull")

                # 7. Enable + start
                self._log("\n── Enabling service ─────────────────────")
                self._run(c, "systemctl daemon-reload")
                self._run(c, "systemctl enable docker-compose-app")
                self._run(c, "systemctl start docker-compose-app")

                # 8. Verify
                self._log("\n── Container status ─────────────────────")
                self._run(c, "docker ps --filter name=server-data-container")

                self._log("\n[SUCCESS] Deployment complete!")
            except Exception as e:
                self._log(f"[ERROR] {e}")
        self._bg(run)

    def _act_status(self):
        def run():
            self._log("\n══ Service Status ═══════════════════════")
            try:
                c = self._connect()
                self._run(c, "systemctl status docker-compose-app --no-pager -l")
                self._run(c, "docker ps -a --filter name=server-data-container")
            except Exception as e:
                self._log(f"[ERROR] {e}")
        self._bg(run)

    def _act_logs(self):
        def run():
            self._log("\n══ Container Logs ═══════════════════════")
            try:
                c = self._connect()
                self._run(c, "docker logs server-data-container --tail 80 2>&1")
            except Exception as e:
                self._log(f"[ERROR] {e}")
        self._bg(run)

    def _act_shell(self):
        def run():
            self._log("\n══ Opening Interactive Shell ════════════")
            try:
                c = self._connect()
                self._shell = c.invoke_shell(width=220, height=50)
                self._log("[OK] Shell ready — type in the command box below.\n")

                def reader():
                    while self._shell and not self._shell.closed:
                        if self._shell.recv_ready():
                            data = self._shell.recv(8192).decode("utf-8", errors="replace")
                            # strip most ANSI escapes for readability
                            import re
                            data = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", data)
                            self._log(data.rstrip())
                        time.sleep(0.05)

                threading.Thread(target=reader, daemon=True).start()
            except Exception as e:
                self._log(f"[ERROR] {e}")
        self._bg(run)

    def _act_upload_cert(self):
        def run():
            self._log("\n══ Uploading Certificate ════════════════")
            local = self._e_cert.get().strip()
            if not local:
                self._log("[ERROR] No local certificate path selected.")
                return
            try:
                c = self._connect()
                self._run(c, "mkdir -p /opt/certs")
                sftp = c.open_sftp()
                try:
                    sftp.put(local, "/opt/certs/root.crt")
                    self._log("[OK] Uploaded to /opt/certs/root.crt")
                finally:
                    sftp.close()
            except Exception as e:
                self._log(f"[ERROR] {e}")
        self._bg(run)

    # expose as method for the button in _build_left
    _action_upload_cert = _act_upload_cert

    def _send_cmd(self, _event=None):
        cmd = self._e_cmd.get().strip()
        if not cmd:
            return
        self._e_cmd.delete(0, "end")
        if self._shell and not self._shell.closed:
            self._shell.send(cmd + "\n")
        else:
            def run():
                self._log(f"\n$ {cmd}")
                try:
                    c = self._connect()
                    self._run(c, cmd)
                except Exception as e:
                    self._log(f"[ERROR] {e}")
            self._bg(run)

    def _act_disconnect(self):
        if self._shell:
            try:
                self._shell.close()
            except Exception:
                pass
            self._shell = None
        if self._ssh:
            try:
                self._ssh.close()
            except Exception:
                pass
            self._ssh = None
        self._log("\n[INFO] Disconnected.")


if __name__ == "__main__":
    App().mainloop()
