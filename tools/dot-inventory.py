#!/usr/bin/env python3
"""dot-inventory — read-only snapshot of a host's shell / editor / terminal config.

Collects what is installed and configured (bash, Emacs, tmux, SSH, git, systemd
user units, cron, and on WSL the Windows Terminal settings), runs consistency
checks, and writes a REDACTED, shareable bundle:

    ~/dot-inventory/<machine>-<timestamp>/
        report.md      human-readable summary + findings
        report.json    machine-readable (feed to --compare, jq, other scripts)
        files/         redacted copies of every config file found
    ~/dot-inventory/<machine>-<timestamp>.tar.gz   the same, as one file

Nothing on the host is modified. It never starts an Emacs daemon or a tmux
server; it only queries ones that are already running. Private keys, Claude
credentials, keyrings and known_hosts are never read.

Usage:
    dot-inventory.py                         snapshot this host
    dot-inventory.py --raw-backup            also save an UNREDACTED local backup
                                             of the config files (never share it)
    dot-inventory.py --identifiers a,b,c     extra words to flag as homelab-specific
    dot-inventory.py --checks-only           print findings only, write nothing
    dot-inventory.py --compare A.json B.json ...
                                             compare snapshots from several hosts

Words to flag can also be listed one per line in ~/.config/dotfiles/denylist.txt.

Python 3.6+, standard library only.
"""

import argparse
import datetime
import glob
import hashlib
import json
import os
import platform
import re
import socket
import stat
import subprocess
import sys
import tarfile

VERSION = "1.0.0"
HOME = os.path.expanduser("~")
MAX_COPY_BYTES = 512 * 1024

# ---------------------------------------------------------------------------
# What to look at
# ---------------------------------------------------------------------------

# Paths relative to $HOME. Globs allowed; "**" recurses.
CANDIDATES = [
    # shell
    ".bashrc", ".bash_profile", ".bash_login", ".profile", ".bash_aliases",
    ".bash_logout", ".inputrc", ".bashrc.local.d/**", ".bashrc.d/**",
    # emacs
    ".emacs", ".emacs.el", ".emacs.d/init.el", ".emacs.d/early-init.el",
    ".emacs.d/custom.el", ".emacs.d/private.el", ".emacs.d/lisp/**/*.el",
    ".config/emacs/init.el", ".config/emacs/early-init.el",
    # tmux
    ".tmux.conf", ".config/tmux/tmux.conf",
    # git
    ".gitconfig", ".config/git/config", ".config/git/ignore",
    ".config/git/identity", ".gitignore_global",
    # ssh — config only, never keys
    ".ssh/config", ".ssh/config.d/**",
    # systemd user units
    ".config/systemd/user/*.service", ".config/systemd/user/*.timer",
    ".config/systemd/user/*.socket", ".config/systemd/user/*.d/*.conf",
    # claude — settings only, never credentials
    ".claude/settings.json", ".claude/CLAUDE.md",
    # dotfile tooling
    ".config/chezmoi/chezmoi.toml", ".config/dotfiles/**",
    # personal scripts (text scripts only — binaries are skipped)
    "bin/*", ".local/bin/*",
]

SHELL_RC = re.compile(
    r"^(\.bashrc|\.bash_profile|\.bash_login|\.profile|\.bash_aliases|"
    r"\.bashrc\.local\.d/.*|\.bashrc\.d/.*)$")

# Never read these, whatever a glob matches.
NEVER_READ = re.compile(
    r"(^|/)("
    r"\.ssh/(?!config$|config\.d/)"          # everything in ~/.ssh except config
    r"|\.claude/\.credentials"
    r"|\.netrc$|\.gnupg/|\.local/share/keyrings/|\.password-store/"
    r")")

TOOLS = ["bash", "emacs", "emacsclient", "tmux", "git", "ssh", "python3",
         "chezmoi", "stow", "jq", "rg", "fd", "fdfind", "socat", "rbw", "bw",
         "claude", "syncthing", "tailscale", "snap", "npiperelay.exe"]
VERSION_ARGS = {"ssh": ["-V"], "tmux": ["-V"], "socat": ["-V"],
                "npiperelay.exe": None, "snap": ["--version"]}
# Tools where every distinct binary on PATH gets its own version check.
MULTI_VERSION = {"emacs", "emacsclient", "tmux", "git"}

ELISP = [
    ("emacs_version", "emacs-version"),
    ("binary", "(expand-file-name invocation-name invocation-directory)"),
    ("user_init_file", "user-init-file"),
    ("custom_file", "custom-file"),
    ("my_machine", "(and (boundp 'my/machine) my/machine)"),
    ("my_profile", "(and (boundp 'my/profile) my/profile)"),
    ("my_online_p", "(and (boundp 'my/online-p) my/online-p)"),
    ("package_archives", "(and (boundp 'package-archives) package-archives)"),
    ("packages_activated", "(length (bound-and-true-p package-activated-list))"),
    ("treesit_available", "(and (fboundp 'treesit-available-p) (treesit-available-p))"),
    ("clipetty_loaded", "(featurep 'clipetty)"),
    ("claude_code_ide_loaded", "(featurep 'claude-code-ide)"),
    ("frames", "(length (frame-list))"),
]

# ---------------------------------------------------------------------------
# Redaction — applied to every copied file and every captured command output
# ---------------------------------------------------------------------------

_KEYWORDS = (r"TOKEN|SECRET|PASSWORD|PASSWD|PASSPHRASE|PASS|API_?KEY|ACCESS_?KEY|"
             r"PRIVATE_?KEY|BW_SESSION|CLIENT_?SECRET|AUTH_?KEY|SESSION_?KEY")
_LISP_KEYWORDS = r"password|passwd|passphrase|secret|token|api-?key|auth-?key"

# NAME=value / NAME: value / "name": "value"  (shell, gitconfig, json, yaml, toml)
# Quoted values are taken whole, so `PW='abc#def'` cannot leak its tail.
REDACT_ASSIGN = re.compile(
    r"(?i)(\b[A-Z0-9_.-]*(?:" + _KEYWORDS + r")[A-Z0-9_.-]*\b)"
    r"([\"']?\s*[=:]\s*)"
    r"(?:([\"'])(.*?)\3|([^\s\"'#;,)]+))")
# (setq my-token "…"), (setq a 1 my-token "…"), (gptel-api-key "…"), :custom (x-secret "…")
REDACT_LISP = re.compile(
    r"(?i)((?:^|[\s(])[\w/-]*(?:" + _LISP_KEYWORDS + r")[\w/-]*\s+)\"(?:[^\"\\]|\\.)*\"")
# (setenv "OPENAI_API_KEY" "…")
REDACT_SETENV = re.compile(
    r"(?i)(\(setenv\s+\"[^\"]*(?:" + _KEYWORDS + r")[^\"]*\"\s+)\"(?:[^\"\\]|\\.)*\"")
# .netrc style:  machine x login y password z
REDACT_NETRC = re.compile(r"(?i)(\bpassword\s+)(?![=:]|<REDACTED)(\S+)")
# Values that are settings, not secrets (e.g. `PasswordAuthentication no`).
SAFE_VALUES = {"no", "yes", "true", "false", "nil", "t", "none", "0", "1", "on", "off", ""}
REDACT_LITERALS = [
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"),     # Anthropic / OpenAI
    re.compile(r"\btskey-[A-Za-z0-9-]{10,}"),                   # Tailscale
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),                # GitHub
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"),                  # GitLab
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                        # AWS
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),                   # Google
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),             # Slack tokens
    re.compile(r"https://hooks\.slack\.com/services/\S+"),      # Slack webhooks
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
    re.compile(r"\$(?:1|2[aby]?|5|6|y)\$[^\s:'\"]{8,}"),        # crypt hashes
]
# Authorization: Bearer … / Basic …
REDACT_AUTH_HEADER = re.compile(r"(?i)(\b(?:bearer|basic|token)\s+)([A-Za-z0-9._~+/=-]{16,})")
# mysql -pSECRET
REDACT_MYSQL = re.compile(r"(\bmysql\S*\s(?:.*?\s)?-p)(\S+)")
# scheme://user:pass@host  and  scheme://<long-token>@host
REDACT_URL_USERINFO = re.compile(r"([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^@\s/]+@")
REDACT_URL_TOKEN = re.compile(r"([a-z][a-z0-9+.-]*://)[A-Za-z0-9_-]{20,}@")
PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.S)


def redact(text):
    """Return (redacted_text, number_of_redactions)."""
    count = 0
    text, n = PRIVATE_KEY_BLOCK.subn("<REDACTED PRIVATE KEY>", text)
    count += n
    hits = [0]

    def _assign(m):
        name = m.group(1)
        quote = m.group(3) or ""
        val = m.group(4) if m.group(3) else (m.group(5) or "")
        if (name.lower().endswith("authentication") or val.lower() in SAFE_VALUES
                or val.startswith(("$", "<REDACTED", "~", "/", "%"))):
            # settings, variable/command substitutions and file paths are not secrets
            return m.group(0)
        hits[0] += 1
        return m.group(1) + m.group(2) + quote + "<REDACTED>" + quote

    out_lines = []
    for line in text.splitlines(True):
        new = REDACT_ASSIGN.sub(_assign, line)
        for rx, repl in ((REDACT_SETENV, r'\1"<REDACTED>"'),
                         (REDACT_LISP, r'\1"<REDACTED>"'),
                         (REDACT_AUTH_HEADER, r"\1<REDACTED>"),
                         (REDACT_MYSQL, r"\1<REDACTED>"),
                         (REDACT_URL_USERINFO, r"\1<REDACTED>@"),
                         (REDACT_URL_TOKEN, r"\1<REDACTED>@")):
            new, n = rx.subn(repl, new)
            count += n
        for rx in REDACT_LITERALS:
            new, n = rx.subn("<REDACTED>", new)
            count += n
        if re.match(r"(?i)\s*(machine|default|login|password)\b", new):
            new, n = REDACT_NETRC.subn(r"\1<REDACTED>", new)
            count += n
        out_lines.append(new)
    return "".join(out_lines), count + hits[0]


# ---------------------------------------------------------------------------
# Homelab / personal identifier scan
# ---------------------------------------------------------------------------

GENERIC_IDENTIFIERS = [
    ("private-ip", re.compile(
        r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b")),
    ("tailnet-ip", re.compile(
        r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b")),
    ("tailnet-dns", re.compile(r"\b[\w-]+\.ts\.net\b")),
    ("lan-dns", re.compile(r"\b[\w-]+\.(?:lan|home\.arpa|internal)\b")),
    # not git@host, and not the userinfo part of a URL (scheme://token@host)
    ("email", re.compile(r"(?<![\w/:.+-])(?!git@)[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
]


def load_identifiers(extra):
    words = []
    path = os.path.join(HOME, ".config/dotfiles/denylist.txt")
    if os.path.isfile(path):
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.split("#", 1)[0].strip()
                if line:
                    words.append(line)
    if extra:
        words.extend(w.strip() for w in extra.split(",") if w.strip())
    pats = list(GENERIC_IDENTIFIERS)
    for w in sorted(set(words), key=str.lower):
        # Letters-only boundaries: with "oak" listed, OAK_IP, oak-nas, sync-oak and
        # oak2 all match, while "cloak" and "oaken" do not.
        pats.append(("word:" + w, re.compile(
            r"(?i)(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])")))
    return pats, path if os.path.isfile(path) else None


def scan_identifiers(text, patterns):
    hits = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        for name, rx in patterns:
            if rx.search(line):
                hits.setdefault(name, []).append(lineno)
    return hits


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(cmd, timeout=10, env=None):
    """Run a command, return (rc, stdout, stderr). Never raises."""
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           stdin=subprocess.DEVNULL, timeout=timeout, env=env)
        return (p.returncode,
                p.stdout.decode("utf-8", "replace"),
                p.stderr.decode("utf-8", "replace"))
    except FileNotFoundError:
        return 127, "", "not found"
    except subprocess.TimeoutExpired:
        return 124, "", "timed out after %ss" % timeout
    except OSError as exc:
        return 126, "", str(exc)


def tilde(path):
    if path == HOME:
        return "~"
    if path.startswith(HOME + os.sep):
        return "~/" + path[len(HOME) + 1:]
    return path


def ascii_safe(s):
    """Console output stays ASCII so a C/POSIX locale (Python 3.6) cannot crash it."""
    s = str(s)
    for a, b in ((u"\u2014", "-"), (u"\u2013", "-"), (u"\u2192", "->"), (u"\u2018", "'"),
                 (u"\u2019", "'"), (u"\u201c", '"'), (u"\u201d", '"'), (u"\u2026", "...")):
        s = s.replace(a, b)
    return s.encode("ascii", "backslashreplace").decode("ascii")


def first_line(*texts):
    for t in texts:
        for line in (t or "").splitlines():
            if line.strip():
                return line.strip()
    return ""


def read_text(path):
    """Return file text, or None if binary/unreadable/too large/not a regular file."""
    try:
        st = os.stat(path)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_COPY_BYTES:
            return None     # opening a FIFO would block forever
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    if b"\x00" in raw[:8192]:
        return None
    return raw.decode("utf-8", "replace")


def which_all(name):
    """Every executable called NAME on PATH, in PATH order: [(path, realpath)]."""
    seen, out = set(), []
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        p = os.path.join(d, name)
        if p in seen:
            continue
        seen.add(p)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            out.append((p, os.path.realpath(p)))
    return out


class Findings(object):
    def __init__(self):
        self.items = []

    def add(self, level, area, message, where=""):
        self.items.append({"level": level, "area": area,
                           "message": message, "where": where})

    def sorted(self):
        order = {"WARN": 0, "INFO": 1, "OK": 2}
        return sorted(self.items, key=lambda f: (order.get(f["level"], 9), f["area"]))


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------

def collect_identity():
    wsl_distro = os.environ.get("WSL_DISTRO_NAME")
    release = platform.release()
    is_wsl = bool(wsl_distro) or "microsoft" in release.lower()
    os_release = {}
    try:
        with open("/etc/os-release") as fh:
            for line in fh:
                if "=" in line:
                    k, v = line.rstrip("\n").split("=", 1)
                    os_release[k] = v.strip('"')
    except OSError:
        pass
    profile_file = os.path.join(HOME, ".config/dotfiles/profile")
    profile = None
    if os.path.isfile(profile_file):
        profile = (read_text(profile_file) or "").strip() or None
    return {
        # Machine id = short hostname, lowercase. Not WSL_DISTRO_NAME: every
        # stock WSL install is called "Ubuntu", so it can't tell machines apart.
        "machine": socket.gethostname().split(".")[0].lower(),
        "hostname": socket.gethostname(),
        "wsl_distro": wsl_distro,
        "is_wsl": is_wsl,
        "user": os.environ.get("USER") or os.environ.get("LOGNAME") or "",
        "uid": os.getuid(),
        "home": HOME,
        "login_shell": os.environ.get("SHELL", ""),
        "os": os_release.get("PRETTY_NAME", platform.system()),
        "kernel": release,
        "in_tmux": bool(os.environ.get("TMUX")),
        "over_ssh": bool(os.environ.get("SSH_CONNECTION")),
        "ssh_tty": os.environ.get("SSH_TTY"),
        "editor": os.environ.get("EDITOR"),
        "visual": os.environ.get("VISUAL"),
        "dot_profile_env": os.environ.get("DOT_PROFILE"),
        "dot_profile_file": profile,
        "python": platform.python_version(),
    }


def collect_tools(findings):
    tools = {}
    for name in TOOLS:
        found = which_all(name)
        if not found:
            continue
        groups = []                      # one entry per distinct real binary
        for path, real in found:
            for g in groups:
                if g["realpath"] == real:
                    g["aliases"].append(path)
                    break
            else:
                groups.append({"path": path, "realpath": real, "aliases": []})
        args = VERSION_ARGS.get(name, ["--version"])
        targets = groups if name in MULTI_VERSION else groups[:1]
        for g in targets:
            if args is None:
                g["version"] = ""
                continue
            rc, out, err = run([g["path"]] + args, timeout=15)
            if name == "socat":
                line = next((l for l in (out + err).splitlines() if "version" in l), "")
            else:
                line = first_line(out, err)
            g["version"] = line[:160]
        tools[name] = groups

    emacs = tools.get("emacs", [])
    if len(emacs) > 1:
        findings.add("WARN", "emacs",
                     "%d different Emacs binaries on PATH — pick one per host and remove the rest"
                     % len(emacs),
                     "; ".join("%s (%s)" % (g["path"], g.get("version", "")) for g in emacs))
    if "snap" in tools:
        rc, out, _ = run(["snap", "list"], timeout=20)
        if rc == 0:
            tools["_snaps"] = [l for l in out.splitlines()[1:]
                               if re.match(r"^(emacs|tmux|chezmoi|code)\s", l)]
    if os.path.isfile("/usr/bin/dpkg-query"):
        rc, out, _ = run(["dpkg-query", "-W", "-f", "${db:Status-Abbrev}${Package} ${Version}\n",
                          "emacs*", "tmux", "libtree-sitter0"], timeout=20)
        tools["_dpkg"] = [l[3:].strip() for l in out.splitlines() if l.startswith("ii")]
    return tools


def collect_processes():
    rc, out, _ = run(["ps", "-u", str(os.getuid()), "-o", "pid=,args="])
    procs = {"emacs_daemons": [], "emacs_other": [], "tmux_processes": [], "other": []}
    if rc != 0:
        return procs
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        pid, _, args = line.partition(" ")
        args = args.strip()
        prog = os.path.basename(args.split(" ", 1)[0])
        entry = {"pid": int(pid), "args": redact(args)[0][:200]}
        if "emacs" in prog and "emacsclient" not in prog:
            if re.search(r"--(fg-|bg-)?daemon", args):
                procs["emacs_daemons"].append(entry)
            else:
                procs["emacs_other"].append(entry)
        elif prog == "tmux" or prog.startswith("tmux:"):
            procs["tmux_processes"].append(entry)
        elif prog in ("syncthing", "socat", "ssh-agent", "rbw-agent"):
            procs["other"].append(entry)
    return procs


def collect_emacs(procs, findings):
    info = {"daemon_running": bool(procs["emacs_daemons"]), "query": {}}
    sockets = []
    for d in [os.path.join(os.environ.get("XDG_RUNTIME_DIR", ""), "emacs"),
              "/tmp/emacs%d" % os.getuid()]:
        if d and os.path.isdir(d):
            sockets.extend(os.path.join(d, n) for n in sorted(os.listdir(d)))
    info["server_sockets"] = sockets

    if len(procs["emacs_daemons"]) > 1:
        findings.add("WARN", "emacs", "%d Emacs daemons running — usually one is an orphan"
                     % len(procs["emacs_daemons"]),
                     "; ".join("pid %d: %s" % (p["pid"], p["args"]) for p in procs["emacs_daemons"]))
    if procs["emacs_other"]:
        findings.add("INFO", "emacs",
                     "standalone (non-daemon) Emacs running — `C-x 5 0` cannot close its only frame",
                     "; ".join("pid %d: %s" % (p["pid"], p["args"]) for p in procs["emacs_other"]))

    clients = which_all("emacsclient")
    if info["daemon_running"] and clients:
        client = clients[0][0]
        info["client_used"] = client
        for key, expr in ELISP:
            # -a false: if no server answers, run `false` instead of starting one.
            rc, out, err = run([client, "-a", "false", "-e", expr], timeout=6)
            info["query"][key] = redact(out.strip())[0] if rc == 0 else "ERR(%d): %s" % (rc, first_line(err))
        archives = info["query"].get("package_archives", "")
        if "elpa.nongnu.org/packages" in archives:
            findings.add("WARN", "emacs", "running daemon uses the wrong NonGNU ELPA URL "
                         "(…/packages/) — should be https://elpa.nongnu.org/nongnu/",
                         "package-archives")
    return info


def collect_tmux(findings):
    info = {"server_running": False}
    rc, out, _ = run(["tmux", "ls"], timeout=5)
    if rc != 0:
        return info
    info["server_running"] = True
    info["sessions"] = [l for l in out.splitlines() if l.strip()]
    queries = [
        ("version", ["tmux", "-V"]),
        ("prefix", ["tmux", "show", "-gv", "prefix"]),
        ("set_clipboard", ["tmux", "show", "-sv", "set-clipboard"]),
        ("escape_time", ["tmux", "show", "-sv", "escape-time"]),
        ("default_terminal", ["tmux", "show", "-gv", "default-terminal"]),
        ("mode_keys", ["tmux", "show", "-gwv", "mode-keys"]),
        ("allow_passthrough", ["tmux", "show", "-gwv", "allow-passthrough"]),
        ("update_environment", ["tmux", "show", "-gv", "update-environment"]),
        ("terminal_features", ["tmux", "show", "-sv", "terminal-features"]),
    ]
    for key, cmd in queries:
        rc, out, err = run(cmd, timeout=5)
        info[key] = out.strip() if rc == 0 else "ERR: " + first_line(err)
    rc, out, _ = run(["tmux", "list-keys", "-T", "root"], timeout=5)
    keys = []
    for line in out.splitlines():
        m = re.match(r"bind-key\s+(?:-r\s+)?-T\s+root\s+(\S+)\s+(.*)", line)
        if m and not re.search(r"Mouse|Wheel|Drag|Click", m.group(1)):
            keys.append("%s → %s" % (m.group(1), m.group(2)[:80]))
    info["root_bindings"] = keys
    stolen = [k for k in keys if re.match(r"C-[hjkl] ", k)]
    if stolen:
        findings.add("WARN", "tmux", "prefix-free bindings steal plain C-h/j/k/l from Emacs",
                     "; ".join(stolen))
    rc, out, _ = run(["tmux", "info"], timeout=5)
    m = re.search(r"\bMs: (.*)", out)
    info["Ms_capability"] = m.group(1).strip() if m else "(no attached client to inspect)"
    return info


def parse_ssh_config(text):
    hosts, current, includes = [], None, []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = re.split(r"\s+|=", line, maxsplit=1)
        key = parts[0].lower()
        val = parts[1].strip() if len(parts) > 1 else ""
        if key == "include":
            includes.append(val)
        elif key in ("host", "match"):
            current = {"block": "%s %s" % (parts[0], val)}
            hosts.append(current)
        elif current is not None and key in ("hostname", "user", "port", "identityfile",
                                             "identityagent", "proxyjump", "identitiesonly",
                                             "setenv", "forwardagent", "remotecommand",
                                             "requesttty"):
            # SetEnv / RemoteCommand can carry tokens — redact before it reaches the report
            current.setdefault(key, []).append(redact(val)[0])
    return hosts, includes


def collect_ssh(findings):
    info = {}
    sshdir = os.path.join(HOME, ".ssh")
    if os.path.isdir(sshdir):
        mode = stat.S_IMODE(os.stat(sshdir).st_mode)
        info["dir_mode"] = oct(mode)
        if mode & 0o077:
            findings.add("WARN", "ssh", "~/.ssh is %s — should be 0700" % oct(mode), "~/.ssh")
        listing = []
        for name in sorted(os.listdir(sshdir)):
            p = os.path.join(sshdir, name)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            kind = "link" if stat.S_ISLNK(st.st_mode) else "dir" if stat.S_ISDIR(st.st_mode) else "file"
            listing.append("%s %s %s" % (oct(stat.S_IMODE(st.st_mode)), kind, name))
        info["listing"] = listing       # names and modes only — contents never read
        cfg = os.path.join(sshdir, "config")
        if os.path.isfile(cfg):
            mode = stat.S_IMODE(os.stat(cfg).st_mode)
            if mode & 0o022:
                findings.add("WARN", "ssh", "~/.ssh/config is %s — group/world writable, ssh may refuse it"
                             % oct(mode), "~/.ssh/config")
            text = read_text(cfg) or ""
            for extra in sorted(glob.glob(os.path.join(sshdir, "config.d", "*"))):
                text += "\n" + (read_text(extra) or "")
            hosts, includes = parse_ssh_config(text)
            info["hosts"] = hosts
            info["includes"] = includes
            for h in hosts:
                for agent in h.get("identityagent", []):
                    p = agent.strip('"').replace("%d", HOME).replace("%u", os.environ.get("USER", ""))
                    p = os.path.expanduser(p)
                    if agent.lower() not in ("none", "ssh_auth_sock") and "$" not in p \
                            and "%" not in p and not os.path.exists(p):
                        findings.add("WARN", "ssh", "IdentityAgent socket does not exist right now",
                                     "%s → %s" % (h["block"], agent))
    sock = os.environ.get("SSH_AUTH_SOCK")
    info["SSH_AUTH_SOCK"] = sock
    if sock:
        rc, out, err = run(["ssh-add", "-l"], timeout=8)
        info["agent_rc"] = rc
        # fingerprints only — "256 SHA256:... comment (ED25519)"
        info["agent_keys"] = [l for l in out.splitlines() if l.strip()] or [first_line(err, out)]
    return info


def collect_git():
    rc, out, _ = run(["git", "config", "--global", "--list", "--show-origin"], timeout=5)
    return [redact(l)[0] for l in out.splitlines()] if rc == 0 else []


def collect_services(findings, identity, procs):
    info = {}
    rc, out, _ = run(["systemctl", "--user", "list-unit-files", "--state=enabled",
                      "--no-pager", "--no-legend"], timeout=10)
    if rc == 0:
        info["enabled_user_units"] = [l.split()[0] for l in out.splitlines() if l.strip()]
    else:
        info["enabled_user_units"] = None
    rc, out, _ = run(["systemctl", "--user", "show", "emacs.service", "--no-pager",
                      "-p", "FragmentPath", "-p", "ExecStart", "-p", "ActiveState",
                      "-p", "UnitFileState"], timeout=10)
    if rc == 0:
        info["emacs_service"] = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
        exec_start = info["emacs_service"].get("ExecStart", "")
        daemons = " ".join(p["args"] for p in procs["emacs_daemons"])
        if info["emacs_service"].get("UnitFileState") == "enabled" and daemons and \
                ("/snap/" in daemons) != ("/snap/" in exec_start):
            findings.add("WARN", "emacs", "emacs.service is enabled but starts a different Emacs "
                         "(snap vs apt) than the daemon that is running", exec_start[:160])
    rc, out, _ = run(["loginctl", "show-user", identity["user"], "-p", "Linger"], timeout=5)
    if rc == 0:
        info["linger"] = out.strip()
    rc, out, err = run(["crontab", "-l"], timeout=5)
    info["crontab"] = redact(out)[0].splitlines() if rc == 0 else [first_line(err) or "(none)"]
    return info


def collect_windows(identity, copy_file):
    """WSL only: Windows Terminal settings, .wslconfig, wsl.conf, Windows ssh-agent service."""
    info = {}
    if not identity["is_wsl"]:
        return info
    patterns = [
        "/mnt/c/Users/*/AppData/Local/Packages/Microsoft.WindowsTerminal_*/LocalState/settings.json",
        "/mnt/c/Users/*/AppData/Local/Packages/Microsoft.WindowsTerminalPreview_*/LocalState/settings.json",
        "/mnt/c/Users/*/AppData/Local/Microsoft/Windows Terminal/settings.json",
        "/mnt/c/Users/*/.wslconfig",
    ]
    found = []
    for pat in patterns:
        for p in sorted(glob.glob(pat)):
            if re.search(r"/Users/(Public|Default|All Users|Default User)/", p):
                continue
            user = p.split("/Users/", 1)[1].split("/", 1)[0]
            if "WindowsTerminalPreview_" in p:
                name = "WindowsTerminalPreview-settings.json"
            elif "/Packages/" in p:
                name = "WindowsTerminal-settings.json"
            elif p.endswith("settings.json"):
                name = "WindowsTerminal-unpackaged-settings.json"
            else:
                name = os.path.basename(p)
            label = "_windows/%s/%s" % (user, name)
            rec = copy_file(p, label)
            found.append(rec)
            if p.endswith("settings.json"):
                text = read_text(p) or ""
                unbound = []
                for m in re.finditer(r"\{[^{}]*\"unbound\"[^{}]*\}", text):
                    k = re.search(r"\"keys\"\s*:\s*\"([^\"]+)\"", m.group(0))
                    if k:
                        unbound.append(k.group(1))
                info.setdefault("terminal_unbound_keys", []).extend(unbound)
    if os.path.isfile("/etc/wsl.conf"):
        found.append(copy_file("/etc/wsl.conf", "_system/etc/wsl.conf"))
    info["files"] = found
    if which_all("powershell.exe"):
        rc, out, err = run(["powershell.exe", "-NoProfile", "-Command",
                            "(Get-Service ssh-agent).Status; (Get-Service ssh-agent).StartType"],
                           timeout=20)
        info["windows_ssh_agent_service"] = " / ".join(
            l.strip() for l in out.splitlines() if l.strip()) or first_line(err)
    return info


# ---------------------------------------------------------------------------
# File collection + static checks
# ---------------------------------------------------------------------------

REAL_HOME = os.path.realpath(HOME)


def is_forbidden(path):
    """True if PATH, or whatever it resolves to, is a key/credential location.

    Checking the resolved target closes the symlink route, e.g.
    ~/.config/dotfiles/x -> ~/.ssh/id_ed25519.
    """
    for candidate in (os.path.abspath(path), os.path.realpath(path)):
        for home in (HOME, REAL_HOME):
            if candidate.startswith(home + os.sep):
                if NEVER_READ.search(os.path.relpath(candidate, home)):
                    return True
        if re.search(r"/\.ssh/(?!config$|config\.d/)|/\.gnupg/|/\.netrc$|/\.claude/\.credentials",
                     candidate):
            return True
    return False


def expand_candidates():
    paths = []
    for pat in CANDIDATES:
        full = os.path.join(HOME, pat)
        matches = glob.glob(full, recursive=True) if any(c in pat for c in "*?[") else [full]
        for m in sorted(matches):
            if is_forbidden(m):
                continue
            if os.path.isdir(m):
                continue
            if m not in paths:
                paths.append(m)
    return paths


def file_record(path, label):
    rec = {"path": tilde(path), "copied_as": None}
    try:
        lst = os.lstat(path)
    except OSError:
        rec["status"] = "missing"
        return rec, None
    if stat.S_ISLNK(lst.st_mode):
        rec["symlink_to"] = os.readlink(path)
        rec["resolves_to"] = tilde(os.path.realpath(path))
        if not os.path.exists(path):
            rec["status"] = "broken-symlink"
            return rec, None
    try:
        st = os.stat(path)
    except OSError:
        rec["status"] = "unreadable"
        return rec, None
    if not stat.S_ISREG(st.st_mode):
        # FIFOs, sockets and devices would block or make no sense to read
        rec["status"] = "skipped-not-a-regular-file"
        return rec, None
    if is_forbidden(path):
        rec["status"] = "skipped-sensitive-target"
        return rec, None
    rec["status"] = "present"
    rec["size"] = st.st_size
    rec["mode"] = oct(stat.S_IMODE(st.st_mode))
    rec["mtime"] = datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
    try:
        with open(path, "rb") as fh:
            rec["sha256"] = hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        rec["status"] = "unreadable"
        return rec, None
    text = read_text(path)
    if text is None:
        rec["skipped"] = "binary or larger than %d KB" % (MAX_COPY_BYTES // 1024)
        return rec, None
    rec["lines"] = text.count("\n")
    rec["crlf"] = text.count("\r\n")
    return rec, text


def static_checks(files, texts, findings, identifier_patterns):
    defs = {}          # name -> [(kind, where)]
    editor_lines = []
    for rec in files:
        rel = rec["path"][2:] if rec["path"].startswith("~/") else rec["path"]
        text = texts.get(rec["path"])
        if text is None:
            continue
        if rec.get("crlf") and not rec["path"].startswith("/mnt/"):
            findings.add("WARN", "files", "Windows (CRLF) line endings — bash/tmux will misread this file",
                         "%s (%d lines)" % (rec["path"], rec["crlf"]))
        if SHELL_RC.match(rel):
            for n, line in enumerate(text.splitlines(), 1):
                code = line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
                if not code.strip():
                    continue
                indented = code[:1].isspace()      # inside an if/case block, e.g. per-profile variants
                m = re.match(r"^\s*alias\s+([A-Za-z0-9_.:+-]+)=", code)
                if m:
                    defs.setdefault(m.group(1), []).append(("alias", "%s:%d" % (rec["path"], n), indented))
                m = re.match(r"^\s*(?:function\s+([A-Za-z0-9_.:+-]+)|([A-Za-z0-9_.:+-]+)\s*\(\s*\))", code)
                if m:
                    defs.setdefault(m.group(1) or m.group(2), []).append(
                        ("function", "%s:%d" % (rec["path"], n), indented))
                m = re.search(r"\b(?:export\s+)?(EDITOR|VISUAL)=(\S+.*)$", code)
                if m:
                    editor_lines.append((m.group(1), m.group(2).strip(), "%s:%d" % (rec["path"], n)))
                if re.search(r"\bemacs\b[^|;&]*--(?:bg-|fg-)?daemon", code):
                    findings.add("INFO", "shell", "shell startup references `emacs --daemon` — if this is "
                                 "outside a function it runs on every new shell",
                                 "%s:%d" % (rec["path"], n))
                # a bare `tmux new`/`attach` at startup — not tmux new-window, and not inside
                # an alias or a one-line function definition
                if re.search(r"\btmux\s+(?:new-session|new|attach-session|attach|a)(?=\s|;|$)", code) and \
                        not re.match(r"^\s*(?:alias\b|function\b|[A-Za-z0-9_.:+-]+\s*\(\s*\))", code):
                    findings.add("INFO", "shell", "tmux auto-start/attach in shell startup",
                                 "%s:%d" % (rec["path"], n))
        if rel.endswith("init.el") and "emacs" in rel:
            first = text.splitlines()[0] if text else ""
            if "lexical-binding: t" not in first:
                findings.add("WARN", "emacs", "first line lacks `-*- lexical-binding: t; -*-` "
                             "(closures in loops will misbehave)", rec["path"])
            if "elpa.nongnu.org/packages" in text:
                findings.add("WARN", "emacs", "NonGNU ELPA URL is wrong — use https://elpa.nongnu.org/nongnu/",
                             rec["path"])
            for n, line in enumerate(text.splitlines(), 1):
                if re.search(r"package-check-signature\s+nil", line) and not line.lstrip().startswith(";"):
                    findings.add("WARN", "emacs", "package signature checking is disabled",
                                 "%s:%d" % (rec["path"], n))
        hits = scan_identifiers(text, identifier_patterns)
        if hits:
            rec["identifiers"] = {k: v[:12] for k, v in hits.items()}

    for name, entries in sorted(defs.items()):
        kinds = {k for k, _, _ in entries}
        where = "; ".join("%s %s" % e[:2] for e in entries)
        if {"alias", "function"} <= kinds:
            findings.add("WARN", "shell", "`%s` is both an alias and a function — bash expands the alias "
                         "first, so the function never runs (and its definition can be a syntax error)"
                         % name, where)
        elif len(entries) > 1:
            files = {w.rsplit(":", 1)[0] for _, w, _ in entries}
            if len(files) == 1 and any(ind for _, _, ind in entries):
                continue        # alternatives in one file's if/case branches — only one runs
            findings.add("INFO", "shell", "`%s` is defined %d times" % (name, len(entries)), where)
    for var, val, where in editor_lines:
        if "emacs" in val and "emacsclient" not in val:
            findings.add("INFO", "shell", "%s starts a standalone Emacs; `emacsclient -nw -a emacs` "
                         "reuses the daemon" % var, "%s  (%s)" % (where, val))
    return defs


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def md_escape(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def write_markdown(data, path):
    L = []
    idn = data["identity"]
    L.append("# dot-inventory — %s" % idn["machine"])
    L.append("")
    L.append("Generated %s by dot-inventory %s. Read-only snapshot; secrets redacted."
             % (data["generated"], VERSION))
    L.append("")
    L.append("## Identity")
    L.append("")
    for k in ("machine", "hostname", "wsl_distro", "user", "home", "os", "kernel", "login_shell",
              "over_ssh", "in_tmux", "ssh_tty", "editor", "visual", "dot_profile_env",
              "dot_profile_file", "python"):
        L.append("- **%s:** `%s`" % (k, idn.get(k)))
    L.append("")

    L.append("## Findings")
    L.append("")
    if not data["findings"]:
        L.append("No problems detected.")
    for f in data["findings"]:
        L.append("- **%s** [%s] %s" % (f["level"], f["area"], f["message"]))
        if f["where"]:
            L.append("  - `%s`" % f["where"])
    L.append("")

    L.append("## Binaries on PATH")
    L.append("")
    L.append("| tool | path | real binary | version | same binary also at |")
    L.append("|---|---|---|---|---|")
    for name, groups in data["tools"].items():
        if name.startswith("_"):
            continue
        for g in groups:
            L.append("| %s | `%s` | `%s` | %s | %s |" % (
                name, g["path"], g["realpath"], md_escape(g.get("version", "—")),
                ", ".join("`%s`" % a for a in g["aliases"]) or ""))
    for key, label in (("_snaps", "snaps"), ("_dpkg", "apt packages")):
        if data["tools"].get(key):
            L.append("")
            L.append("**%s:** %s" % (label, "; ".join("`%s`" % s for s in data["tools"][key])))
    L.append("")

    em = data["emacs"]
    L.append("## Emacs")
    L.append("")
    L.append("- daemon running: **%s**" % em["daemon_running"])
    for p in data["processes"]["emacs_daemons"] + data["processes"]["emacs_other"]:
        L.append("  - pid %d: `%s`" % (p["pid"], p["args"]))
    L.append("- server sockets: %s" % (", ".join("`%s`" % s for s in em["server_sockets"]) or "none"))
    if em.get("query"):
        L.append("- queried via `%s`:" % em.get("client_used"))
        for k, v in em["query"].items():
            L.append("  - %s: `%s`" % (k, md_escape(v)[:300]))
    L.append("")

    tm = data["tmux"]
    L.append("## tmux")
    L.append("")
    if not tm["server_running"]:
        L.append("No tmux server running (config file is still captured below).")
    else:
        for k, v in tm.items():
            if k == "root_bindings":
                L.append("- prefix-free (root table) bindings, mouse excluded:")
                for b in v:
                    L.append("  - `%s`" % b)
            elif k != "server_running":
                L.append("- %s: `%s`" % (k, md_escape(v)))
    L.append("")

    ssh = data["ssh"]
    L.append("## SSH")
    L.append("")
    L.append("- ~/.ssh mode: `%s`" % ssh.get("dir_mode"))
    L.append("- SSH_AUTH_SOCK: `%s`" % ssh.get("SSH_AUTH_SOCK"))
    for k in ssh.get("agent_keys", []):
        L.append("  - agent: `%s`" % k)
    if ssh.get("includes"):
        L.append("- Include: %s" % ", ".join("`%s`" % i for i in ssh["includes"]))
    for h in ssh.get("hosts", []):
        extra = "; ".join("%s=%s" % (k, ",".join(v)) for k, v in h.items() if k != "block")
        L.append("- `%s` — %s" % (h["block"], md_escape(extra)))
    if ssh.get("listing"):
        L.append("- ~/.ssh contents (names and modes only):")
        for e in ssh["listing"]:
            L.append("  - `%s`" % e)
    L.append("")

    L.append("## git (global config)")
    L.append("")
    for l in data["git"] or ["(none)"]:
        L.append("- `%s`" % md_escape(l))
    L.append("")

    sv = data["services"]
    L.append("## Services and scheduled jobs")
    L.append("")
    L.append("- enabled user units: %s" % (", ".join("`%s`" % u for u in sv.get("enabled_user_units") or [])
                                         or "none / systemd --user unavailable"))
    if sv.get("emacs_service"):
        L.append("- emacs.service: `%s`" % md_escape(json.dumps(sv["emacs_service"])))
    L.append("- linger: `%s`" % sv.get("linger"))
    L.append("- crontab:")
    for l in sv.get("crontab", []):
        L.append("  - `%s`" % md_escape(l))
    L.append("")

    if data["windows"]:
        w = data["windows"]
        L.append("## Windows side (WSL)")
        L.append("")
        L.append("- Windows Terminal unbound keys: %s"
                 % (", ".join("`%s`" % k for k in w.get("terminal_unbound_keys", [])) or "none found"))
        if "windows_ssh_agent_service" in w:
            L.append("- Windows OpenSSH agent service (should be Stopped/Disabled when Bitwarden "
                     "provides the agent): `%s`" % w["windows_ssh_agent_service"])
        L.append("")

    L.append("## Shell aliases and functions (static scan of startup files)")
    L.append("")
    for name, entries in sorted(data["shell_definitions"].items()):
        L.append("- `%s` — %s" % (name, "; ".join("%s at %s" % tuple(e[:2]) for e in entries)))
    L.append("")

    L.append("## Config files")
    L.append("")
    L.append("| file | status | sha256 | size | mode | symlink → | CRLF | redacted | identifiers |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for r in data["files"]:
        ids = ", ".join("%s×%d" % (k, len(v)) for k, v in sorted(r.get("identifiers", {}).items()))
        L.append("| `%s` | %s | `%s` | %s | %s | %s | %s | %s | %s |" % (
            r["path"], r["status"] + (" (%s)" % r["skipped"] if r.get("skipped") else ""),
            (r.get("sha256") or "")[:12], r.get("size", ""), r.get("mode", ""),
            ("`%s`" % r["resolves_to"]) if r.get("resolves_to") else "",
            r.get("crlf", "") or "", r.get("redactions", "") or "", md_escape(ids)))
    L.append("")
    if data.get("identifier_source"):
        L.append("Identifier words read from `%s`." % tilde(data["identifier_source"]))
        L.append("")
    L.append("**identifiers** = lines that name a private IP, tailnet, `.lan` host, email address, "
             "or a word from your denylist. Anything flagged here must move to the private overlay "
             "before that file goes into the public core repo. Line numbers are in report.json.")
    L.append("")
    with open(path, "w", encoding="utf-8", errors="replace") as fh:
        fh.write("\n".join(L))


# ---------------------------------------------------------------------------
# Main modes
# ---------------------------------------------------------------------------

def snapshot(args):
    os.umask(0o077)
    findings = Findings()
    identity = collect_identity()
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    if args.checks_only:
        import tempfile
        base = tempfile.mkdtemp(prefix="dot-inventory-")   # nothing kept; removed below
    else:
        base = os.path.expanduser(args.out)
    outdir = os.path.join(base, "%s-%s" % (identity["machine"], stamp))
    filesdir = os.path.join(outdir, "files")
    os.makedirs(filesdir, exist_ok=True)

    identifier_patterns, id_source = load_identifiers(args.identifiers)
    texts = {}
    raw_paths = []

    def copy_file(path, label):
        rec, text = file_record(path, label)
        if text is not None:
            texts[rec["path"]] = text
            red, n = redact(text)
            rec["redactions"] = n
            dest = os.path.join(filesdir, label)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8", errors="replace") as fh:
                fh.write(red)
            rec["copied_as"] = "files/" + label
            raw_paths.append(path)
        return rec

    files = []
    for path in expand_candidates():
        rel = os.path.relpath(path, HOME)
        if rel.startswith(("bin/", ".local/bin/")):
            # personal scripts: text files with a shebang only
            head = read_text(path) if os.path.isfile(path) else None
            if not head or not head.startswith("#!"):
                continue
        rec = copy_file(path, rel)
        if rec["status"] != "missing":
            files.append(rec)

    procs = collect_processes()
    data = {
        "tool": "dot-inventory", "version": VERSION,
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "identity": identity,
        "tools": collect_tools(findings),
        "processes": procs,
        "emacs": collect_emacs(procs, findings),
        "tmux": collect_tmux(findings),
        "ssh": collect_ssh(findings),
        "git": collect_git(),
        "services": collect_services(findings, identity, procs),
        "windows": collect_windows(identity, copy_file),
        "identifier_source": id_source,
    }
    if data["windows"].get("files"):
        files.extend(r for r in data["windows"]["files"] if r["status"] != "missing")

    # Identity-level checks
    home_emacs = [r for r in files if r["path"] in ("~/.emacs", "~/.emacs.el")]
    if home_emacs:
        findings.add("WARN", "emacs", "~/.emacs exists and is loaded INSTEAD of ~/.emacs.d/init.el",
                     ", ".join(r["path"] for r in home_emacs))
    if os.path.isdir(os.path.join(HOME, ".emacs.d")) and os.path.isdir(os.path.join(HOME, ".config/emacs")):
        findings.add("INFO", "emacs", "both ~/.emacs.d and ~/.config/emacs exist — Emacs uses ~/.emacs.d",
                     "")
    custom = [r for r in files if r["path"] == "~/.emacs.d/custom.el" and r.get("resolves_to")]
    if custom:
        findings.add("WARN", "emacs", "custom.el is a symlink into a repo — it is per-host state "
                     "and should not be shared", custom[0]["resolves_to"])
    svc = data["windows"].get("windows_ssh_agent_service", "")
    if svc and ("Running" in svc or "Disabled" not in svc):
        findings.add("WARN", "ssh", "Windows OpenSSH agent service is running or not Disabled — it "
                     "can grab the pipe Bitwarden's agent needs (Stop + set StartupType Disabled)", svc)

    data["shell_definitions"] = {k: v for k, v in
                                 static_checks(files, texts, findings, identifier_patterns).items()}
    data["files"] = files
    data["findings"] = findings.sorted()

    with open(os.path.join(outdir, "report.json"), "w", encoding="utf-8", errors="replace") as fh:
        json.dump(data, fh, indent=2, sort_keys=False, default=str)
    write_markdown(data, os.path.join(outdir, "report.md"))

    if args.checks_only:
        import shutil
        shutil.rmtree(base, ignore_errors=True)
        warns = [f for f in data["findings"] if f["level"] == "WARN"]
        for f in data["findings"]:
            print(ascii_safe("%-4s [%s] %s" % (f["level"], f["area"], f["message"])))
            if f["where"]:
                print(ascii_safe("       %s" % f["where"]))
        if not data["findings"]:
            print("OK   no problems found")
        return 1 if warns else 0

    tar_path = outdir + ".tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(outdir, arcname=os.path.basename(outdir))

    raw_path = None
    if args.raw_backup and raw_paths:
        raw_path = os.path.join(base, "RAW-BACKUP-DO-NOT-SHARE-%s-%s.tar.gz" % (identity["machine"], stamp))
        with tarfile.open(raw_path, "w:gz") as tar:
            for p in raw_paths:
                arc = os.path.relpath(p, HOME) if p.startswith(HOME + os.sep) \
                    else "_outside_home" + p
                tar.add(p, arcname=arc)

    warns = sum(1 for f in data["findings"] if f["level"] == "WARN")
    infos = sum(1 for f in data["findings"] if f["level"] == "INFO")
    total_red = sum(r.get("redactions") or 0 for r in files)
    print("dot-inventory %s - %s" % (VERSION, ascii_safe(identity["machine"])))
    print("  files captured : %d (%d values redacted)" % (len(files), total_red))
    print("  findings       : %d WARN, %d INFO" % (warns, infos))
    print("  report         : %s" % ascii_safe(tilde(os.path.join(outdir, "report.md"))))
    print("  share this     : %s" % ascii_safe(tilde(tar_path)))
    if raw_path:
        print("  RAW backup     : %s   <-- unredacted, keep local, never share" % ascii_safe(tilde(raw_path)))
    print("Read report.md before sharing; redaction is pattern-based, not a guarantee.")
    return 0


def compare(paths):
    reports = []
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            reports.append(json.load(fh))
    names = [r["identity"]["machine"] for r in reports]
    rows = {}
    for i, r in enumerate(reports):
        for f in r["files"]:
            rows.setdefault(f["path"], [None] * len(reports))[i] = (f.get("sha256") or f["status"])[:8]
    print("| file | " + " | ".join(names) + " | |")
    print("|---|" + "---|" * len(names) + "---|")
    for path in sorted(rows):
        vals = rows[path]
        present = [v for v in vals if v]
        mark = "same" if len(present) > 1 and len(set(present)) == 1 else \
            "DIFFERS" if len(set(present)) > 1 else ""
        print("| `%s` | %s | %s |" % (path, " | ".join(v or "-" for v in vals), mark))
    print()
    print("| tool | " + " | ".join(names) + " |")
    print("|---|" + "---|" * len(names))
    tools = sorted({t for r in reports for t in r["tools"] if not t.startswith("_")})
    for t in tools:
        cells = []
        for r in reports:
            groups = r["tools"].get(t) or []
            cells.append("<br>".join(md_escape(g.get("version") or g["path"])[:40] for g in groups) or "—")
        print("| %s | %s |" % (t, " | ".join(cells)))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Read-only snapshot of shell/editor/terminal config.")
    ap.add_argument("--out", default="~/dot-inventory", help="output directory (default ~/dot-inventory)")
    ap.add_argument("--identifiers", default="",
                    help="comma-separated extra words to flag as homelab/personal")
    ap.add_argument("--checks-only", action="store_true",
                    help="print findings only; write nothing (exit 1 if any WARN) - used by `dots doctor`")
    ap.add_argument("--raw-backup", action="store_true",
                    help="also write an UNREDACTED tarball of the config files (local only)")
    ap.add_argument("--compare", nargs="+", metavar="REPORT_JSON",
                    help="compare report.json files from several hosts and exit")
    ap.add_argument("--version", action="version", version=VERSION)
    args = ap.parse_args()
    if args.compare:
        import signal
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)   # quiet exit when piped into head/less
        return compare(args.compare)
    return snapshot(args)


if __name__ == "__main__":
    sys.exit(main())
