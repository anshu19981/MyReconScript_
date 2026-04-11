#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║        GHOST PROTOCOL v9.1 — DEEP RECON ENGINE               ║
║             Bug Bounty Hunter Edition                        ║
╚══════════════════════════════════════════════════════════════╝

WHAT'S NEW IN v9.1:
  ✔ Stealth Mode (-s/--stealth) to skip aggressive bruteforcing
    - Disables: DNS brute-force, permutation engine, VHost brute
    - Focuses on: Passive reconnaissance only
  ✔ Chaos Integration for passive subdomain enumeration
  ✔ Improved Resolvers fallback list (Cloudflare, Google, Quad9, OpenDNS)
  ✔ Nuclei severity expanded to critical,high,medium
  ✔ Enhanced 403 Bypass with more realistic headers (X-Real-IP, Client-IP)
  ✔ Better error handling for edge cases
  ✔ Improved FFuf JSON parsing for VHost detection

FIXED IN THIS VERSION:
  ✔ Critical: Fixed screenshot fallback logic (gowitness v2/v3)
  ✔ Critical: Fixed port sorting with numeric safety check
  ✔ Added proper error handling for file I/O operations
  ✔ Improved VHost stealth mode check before execution
  ✔ Better regex escaping for grep patterns
  ✔ Enhanced FFuf JSON error handling
"""

import subprocess
import os
import sys
import re
import datetime
import json
import logging
import shutil
import time
import tempfile
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    import requests
    from colorama import Fore, Style, init
    init(autoreset=True)
except ImportError as e:
    print(f"[!] Missing dependency: {e}")
    print("    pip install requests colorama")
    sys.exit(1)

# ─── CONFIGURATION ────────────────────────────────────────────────────────────
THREADS_HTTPX        = "100"
THREADS_GOWITNESS    = "5"
THREADS_NAABU        = "500"
THREADS_JS_FETCH     = 20          # Parallel JS file fetch threads
MAX_DOMAINS_PARALLEL = 2           # 16GB RAM ke liye safe
KATANA_DEPTH         = 3
NUCLEI_RATE_LIMIT    = "150"
AMASS_TIMEOUT        = 300         # Seconds — amass bahut slow hota hai
CMD_TIMEOUT          = 900         # Default command timeout

# ── Bruteforce Settings ───────────────────────────────────────────────────────
WORDLIST_CANDIDATES = [
    os.path.expanduser("~/wordlists/subdomains-top1million-110000.txt"),
    "/usr/share/seclists/Discovery/DNS/subdomains-top1million-110000.txt",
    "/usr/share/seclists/Discovery/DNS/subdomains-top1million-20000.txt",
    "/usr/share/wordlists/dnsmap.txt",
    os.path.expanduser("~/wordlists/dns_wordlist.txt"),
]
BRUTE_THREADS      = "100"
RESOLVERS_FILE     = os.path.expanduser("~/wordlists/resolvers.txt")
RESOLVERS_FALLBACK = [
    "1.1.1.1", "1.0.0.1", "8.8.8.8", 
    "8.8.4.4", "9.9.9.9", "149.112.112.112"
]
RECURSIVE_BRUTE    = True
RECURSIVE_TOP_N    = 10
VHOST_BRUTE        = True
VHOST_WORDLIST     = "/usr/share/seclists/Discovery/DNS/subdomains-top1million-5000.txt"
PERMUTATION_ENGINE = True

# Discord webhook (optional — khali chhoodo agar notifications nahi chahiye)
DISCORD_WEBHOOK_URL = ""

# Port list
NAABU_PORTS = "80,81,443,591,2082,2087,2095,8000,8008,8080,8443,8888,9000,9090,10000"

# Non-standard ports map (port → description)
INTERESTING_PORTS = {
    "81":    "Alt HTTP",
    "591":   "FileMaker Alt",
    "2082":  "cPanel HTTP",
    "2087":  "WHM/cPanel",
    "2095":  "cPanel Webmail",
    "8000":  "Django/Dev server",
    "8008":  "Alt HTTP",
    "8080":  "Alt HTTP/Dev proxy",
    "8443":  "Alt HTTPS",
    "8888":  "Jupyter/Dev panel",
    "9000":  "PHP-FPM/SonarQube",
    "9090":  "Prometheus/Grafana",
    "10000": "Webmin panel",
}
STANDARD_PORTS = {"80", "443"}

# GF patterns
GF_PATTERNS = {
    "xss":         "evidence/xss.txt",
    "ssrf":        "evidence/ssrf.txt",
    "sqli":        "evidence/sqli.txt",
    "redirect":    "evidence/open_redirect.txt",
    "lfi":         "evidence/lfi.txt",
    "rce":         "evidence/rce.txt",
    "idor":        "evidence/idor.txt",
    "debug_logic": "evidence/debug.txt",
}

# JS secret patterns (regex)
JS_SECRET_PATTERNS = [
    r'(?i)(api[_\-]?key|apikey)["\s]*[:=]["\s]*[A-Za-z0-9_\-]{16,}',
    r'(?i)(secret[_\-]?key|secret)["\s]*[:=]["\s]*[A-Za-z0-9_\-]{16,}',
    r'(?i)(access[_\-]?token|auth[_\-]?token)["\s]*[:=]["\s]*[A-Za-z0-9_\-]{16,}',
    r'(?i)(password|passwd|pwd)["\s]*[:=]["\s]*[A-Za-z0-9!@#$%^&*]{8,}',
    r'AKIA[0-9A-Z]{16}',                          # AWS Access Key
    r'(?i)aws[_\-]?secret["\s]*[:=]["\s]*[A-Za-z0-9/+]{40}',
    r'(?i)(github|gh)[_\-]?(token|pat)["\s]*[:=]["\s]*[A-Za-z0-9_]{36,}',
    r'(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}',
    r'(?i)private[_\-]?key["\s]*[:=]["\s]*-----BEGIN',
]

REQUIRED_TOOLS = [
    "subfinder", "assetfinder", "httpx", "nuclei",
    "katana", "gf", "dnsx", "naabu", "gau",
]
OPTIONAL_TOOLS = [
    "amass", "gowitness", "waybackurls", "subjs", "corsy",
    "subzy", "puredns", "shuffledns", "alterx", "ffuf",
    "massdns", "secretfinder", "chaos",
]


# ─── LOGGING (duplicate-handler safe) ────────────────────────────────────────
def setup_logger(log_file: str) -> logging.Logger:
    logger = logging.getLogger(f"DeepRecon_{os.getpid()}")
    if logger.handlers:                          # Already set up — don't add again
        return logger
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    return logger


# ─── DOMAIN VALIDATOR ─────────────────────────────────────────────────────────
_DOMAIN_RE = re.compile(
    r'^(?:[a-zA-Z0-9]'
    r'(?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)'
    r'+[a-zA-Z]{2,}$'
)

def is_valid_domain(d: str) -> bool:
    return bool(_DOMAIN_RE.match(d)) and len(d) <= 253


# ─── MAIN CLASS ───────────────────────────────────────────────────────────────
class DeepRecon:
    def __init__(self, target_file: str, stealth_mode: bool = False):
        self.stealth_mode = stealth_mode
        self.targets      = self.load_targets(target_file)
        self.session_id   = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        self.base_dir     = f"DEEP_RECON_{self.session_id}"
        os.makedirs(self.base_dir, exist_ok=True)
        self.logger       = setup_logger(f"{self.base_dir}/recon.log")
        self.wordlist     = self._detect_wordlist()
        self.resolvers    = self._detect_resolvers()
        self.check_tools()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def load_targets(self, file_path: str) -> list:
        if not os.path.exists(file_path):
            print(f"{Fore.RED}[!] Error: {file_path} nahi mila.")
            sys.exit(1)
        valid, invalid = [], []
        with open(file_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                d = line.strip().lower()
                if not d or d.startswith("#"):
                    continue
                if is_valid_domain(d):
                    valid.append(d)
                else:
                    invalid.append(d)
        if invalid:
            print(f"{Fore.YELLOW}[~] Invalid domains skip kiye: {', '.join(invalid)}")
        if not valid:
            print(f"{Fore.RED}[!] Koi valid domain nahi mila.")
            sys.exit(1)
        return valid

    def _detect_wordlist(self) -> str:
        for w in WORDLIST_CANDIDATES:
            if os.path.exists(w):
                if not self.stealth_mode:
                    print(f"{Fore.GREEN}[✔] Wordlist: {w}")
                return w
        if not self.stealth_mode:
            print(f"{Fore.YELLOW}[~] Wordlist nahi mili — bruteforce skip hoga.")
            print(f"    Fix: sudo apt install seclists")
        return ""

    def _detect_resolvers(self) -> str:
        """
        Try to find a valid resolvers file, with DNS connectivity check.
        Fallback to system DNS if needed.
        """
        if os.path.exists(RESOLVERS_FILE):
            # Verify the file has valid IPs
            try:
                with open(RESOLVERS_FILE, 'r') as f:
                    lines = [l.strip() for l in f if l.strip() and not l.startswith('#')]
                    if lines:
                        return RESOLVERS_FILE
            except:
                pass
        
        # Create fallback resolvers file with validation
        tmp = os.path.join(self.base_dir, "resolvers.txt")
        
        # Add some good public DNS servers
        fallback_list = [
            "1.1.1.1",      # Cloudflare Primary
            "1.0.0.1",      # Cloudflare Secondary
            "8.8.8.8",      # Google Primary
            "8.8.4.4",      # Google Secondary
            "9.9.9.9",      # Quad9
            "149.112.112.112",  # Quad9 Secondary
            "208.67.222.222",   # OpenDNS Primary
            "208.67.220.220",   # OpenDNS Secondary
        ]
        
        # Test which resolvers are reachable
        valid_resolvers = []
        for resolver in fallback_list:
            try:
                # Quick test to see if DNS server responds
                result = subprocess.run(
                    f"timeout 2 dig @{resolver} google.com +short 2>/dev/null | head -1",
                    shell=True, capture_output=True, text=True, timeout=3
                )
                if result.stdout.strip():  # Got a response
                    valid_resolvers.append(resolver)
                    if len(valid_resolvers) >= 6:  # We have enough
                        break
            except:
                pass
        
        # Fallback if none respond (use all)
        if not valid_resolvers:
            valid_resolvers = fallback_list
        
        Path(tmp).write_text("\n".join(valid_resolvers) + "\n")
        print(f"{Fore.CYAN}    Resolvers: {len(valid_resolvers)} IPs configured")
        return tmp

    def check_tools(self):
        print(f"{Fore.YELLOW}[~] Tool check...")
        missing  = [t for t in REQUIRED_TOOLS  if not shutil.which(t)]
        opt_miss = [t for t in OPTIONAL_TOOLS  if not shutil.which(t)]
        if missing:
            print(f"{Fore.RED}[!] REQUIRED tools missing: {', '.join(missing)}")
            print(f"{Fore.RED}    Install karke dobara chalao.")
            sys.exit(1)
        if opt_miss:
            print(f"{Fore.YELLOW}[~] Optional (skip hoga): {', '.join(opt_miss)}")
        if not shutil.which("puredns") and not shutil.which("shuffledns") and not self.stealth_mode:
            print(f"{Fore.YELLOW}[~] puredns/shuffledns missing — bruteforce disabled.")
        print(f"{Fore.GREEN}[✔] Required tools OK\n")

    def tmp(self, domain: str, name: str) -> str:
        """
        Domain-specific temp file path.
        Parallel domains ke beech /tmp clash nahi hoga.
        """
        safe = domain.replace(".", "_").replace("-", "_")
        d    = os.path.join(tempfile.gettempdir(), f"gp_{safe}")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, name)

    def run_cmd(self, cmd: str, msg: str = None,
                timeout: int = CMD_TIMEOUT) -> str:
        if msg:
            print(f"{Fore.CYAN}  [*] {msg}...")
        self.logger.debug(f"CMD: {cmd}")
        try:
            r = subprocess.run(
                cmd, shell=True, capture_output=True,
                text=True, timeout=timeout, errors="replace"
            )
            if r.returncode != 0 and r.stderr:
                self.logger.warning(f"exit={r.returncode}: {r.stderr[:200]}")
            return r.stdout.strip()
        except subprocess.TimeoutExpired:
            self.logger.error(f"TIMEOUT ({timeout}s): {cmd}")
            print(f"{Fore.YELLOW}      [!] Timeout — skipping: {msg or cmd[:60]}")
            return ""
        except Exception as e:
            self.logger.error(f"EXCEPTION [{cmd[:80]}]: {e}")
            return ""

    def file_has_content(self, path: str) -> bool:
        return os.path.isfile(path) and os.path.getsize(path) > 0

    def count_lines(self, path: str) -> int:
        if not self.file_has_content(path):
            return 0
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                return sum(1 for ln in f if ln.strip())
        except Exception:
            return 0

    def append_unique(self, src: str, dst: str):
        """src ke lines ko dst mein append karo, duplicates hata ke."""
        if not self.file_has_content(src):
            return
        self.run_cmd(f"cat {src} >> {dst} && sort -u {dst} -o {dst}")

    def notify_discord(self, message: str):
        if not DISCORD_WEBHOOK_URL:
            return
        try:
            requests.post(
                DISCORD_WEBHOOK_URL,
                json={"content": f"🚨 **GHOST PROTOCOL**\n```{message}```"},
                timeout=10
            )
        except Exception as e:
            self.logger.warning(f"Discord failed: {e}")

    def is_already_scanned(self, domain: str) -> bool:
        return os.path.exists(f"{self.base_dir}/{domain}/.scan_complete")

    def mark_scan_complete(self, domain: str, d_dir: str):
        Path(f"{d_dir}/.scan_complete").write_text(
            datetime.datetime.now().isoformat()
        )

    def phase_timer(self, name: str) -> float:
        print(f"\n{Fore.YELLOW}  ── {name} ──")
        return time.time()

    def phase_done(self, t0: float):
        print(f"{Fore.CYAN}      ⏱  {round(time.time()-t0, 1)}s")

    # ── DNS output parse ──────────────────────────────────────────────────────

    def extract_domains_from_dnsx(self, dnsx_out: str, clean_file: str):
        """
        dnsx output: 'domain.com [1.2.3.4]'  OR  'domain.com'
        Sirf domain names nikalo (no IP, no trailing dot).
        """
        if not self.file_has_content(dnsx_out):
            return
        domains = set()
        with open(dnsx_out, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                part = line.split()[0].rstrip(".")
                if part and is_valid_domain(part):
                    domains.add(part.lower())
        Path(clean_file).write_text("\n".join(sorted(domains)) + "\n")

    # ── Phase 1 ───────────────────────────────────────────────────────────────

    def phase1_subdomain_enum(self, domain: str, d_dir: str) -> str:
        t0           = self.phase_timer("PHASE 1: SUBDOMAIN ENUMERATION")
        raw          = f"{d_dir}/raw_subs.txt"
        resolved_raw = f"{d_dir}/resolved_dnsx.txt"
        resolved     = f"{d_dir}/resolved_subs.txt"

        # 1a. Passive ─────────────────────────────────────────────────────────
        print(f"{Fore.CYAN}  [*] 1a. Passive enum...")

        self._get_crt_sh(domain, raw)

        # subfinder: stdout directly → raw (no shared /tmp file)
        self.run_cmd(
            f"subfinder -d {domain} -silent -all 2>/dev/null >> {raw}"
        )
        self.run_cmd(
            f"assetfinder --subs-only -- {domain} 2>/dev/null >> {raw}"
        )
        if shutil.which("amass"):
            self.run_cmd(
                f"amass enum -passive -d {domain} -silent 2>/dev/null >> {raw}",
                "amass passive",
                timeout=AMASS_TIMEOUT
            )
        if shutil.which("chaos"):
            self.run_cmd(
                f"chaos -d {domain} -silent 2>/dev/null >> {raw}",
                "chaos passive"
            )
        self.run_cmd(f"sort -u {raw} -o {raw}")
        passive_count = self.count_lines(raw)
        print(f"      Passive: {Fore.GREEN}{passive_count}")

        # 1b. Bruteforce ──────────────────────────────────────────────────────
        brute_out = f"{d_dir}/brute_subs.txt"
        if self.stealth_mode:
            print(f"{Fore.YELLOW}  [~] 1b. Bruteforce skip (Stealth Mode Enabled)")
        elif self.wordlist:
            print(f"{Fore.CYAN}  [*] 1b. Subdomain bruteforcing...")
            self._run_brute(domain, brute_out)
            self.append_unique(brute_out, raw)
            print(f"      Brute: {Fore.GREEN}{self.count_lines(brute_out)}")
        else:
            print(f"{Fore.YELLOW}  [~] 1b. Bruteforce skip (wordlist nahi mili)")

        # 1c. Permutations (alterx) ───────────────────────────────────────────
        perm_out = f"{d_dir}/perm_subs.txt"
        if self.stealth_mode:
            print(f"{Fore.YELLOW}  [~] 1c. Permutations skip (Stealth Mode Enabled)")
        elif PERMUTATION_ENGINE and shutil.which("alterx"):
            print(f"{Fore.CYAN}  [*] 1c. Permutation engine (alterx)...")
            self._run_permutation(domain, raw, d_dir, perm_out)
            self.append_unique(perm_out, raw)
            print(f"      Permutations: {Fore.GREEN}{self.count_lines(perm_out)}")
        elif PERMUTATION_ENGINE:
            print(f"{Fore.YELLOW}  [~] 1c. alterx not found — skip")

        # 1d. DNS Resolution ──────────────────────────────────────────────────
        total_raw = self.count_lines(raw)
        print(f"{Fore.CYAN}  [*] 1d. DNS resolving ({total_raw} candidates)...")
        self.run_cmd(
            f"timeout 180 dnsx -l {raw} -silent -a -wd {domain} -t 150 -o {resolved_raw} 2>/dev/null",
            timeout=200
        )
        self.extract_domains_from_dnsx(resolved_raw, resolved)
        resolved_count = self.count_lines(resolved)
        dead = total_raw - resolved_count
        print(f"      Resolved: {Fore.GREEN}{resolved_count} "
              f"({Fore.RED}-{dead} dead/wildcard{Fore.WHITE})")
        self.phase_done(t0)
        return resolved

    def _get_crt_sh(self, domain: str, out_file: str):
        try:
            r = requests.get(
                f"https://crt.sh/?q=%25.{domain}&output=json",
                timeout=20, headers={"Accept": "application/json"}
            )
            if r.status_code != 200:
                return
            names = set()
            for entry in r.json():
                for name in entry.get("name_value", "").splitlines():
                    name = name.strip().lstrip("*.")
                    if name and is_valid_domain(name):
                        names.add(name.lower())
            if names:
                try:
                    with open(out_file, "a", encoding="utf-8") as f:
                        f.write("\n".join(names) + "\n")
                    self.logger.info(f"crt.sh: {len(names)} for {domain}")
                except IOError as e:
                    self.logger.error(f"Failed to write crt.sh results: {e}")
        except Exception as e:
            self.logger.warning(f"crt.sh error ({domain}): {e}")

    def _run_brute(self, domain: str, out_file: str):
        wl = self.wordlist
        if shutil.which("puredns"):
            cmd = (
                f"timeout 120 puredns bruteforce {wl} {domain} "
                f"-r {self.resolvers} --threads {BRUTE_THREADS} "
                f"--quiet -w {out_file} 2>/dev/null"
            )
            self.run_cmd(cmd, "puredns bruteforce", timeout=140)
            
        elif shutil.which("shuffledns"):
            cmd = (
                f"timeout 120 shuffledns -d {domain} -w {wl} "
                f"-r {self.resolvers} -t {BRUTE_THREADS} "
                f"-silent -o {out_file} 2>/dev/null"
            )
            self.run_cmd(cmd, "shuffledns bruteforce", timeout=140)
            
        elif shutil.which("massdns"):
            self._brute_via_massdns(domain, wl, out_file)
        else:
            print(f"{Fore.YELLOW}      [~] No brute tool found. Install puredns.")

    def _brute_via_massdns(self, domain: str, wordlist: str, out_file: str):
        # Domain-specific temp files (parallel-safe)
        tmp_fqdn = self.tmp(domain, "massdns_fqdn.txt")
        tmp_out  = self.tmp(domain, "massdns_out.txt")
        self.run_cmd(
            f"awk '{{print $1\".{domain}\"}}' {wordlist} > {tmp_fqdn}"
        )
        self.run_cmd(
            f"timeout 120 massdns -r {self.resolvers} -t A -o S "
            f"{tmp_fqdn} -w {tmp_out} --quiet 2>/dev/null",
            "massdns bruteforce",
            timeout=140
        )
        self.run_cmd(
            f"grep ' A ' {tmp_out} | awk '{{print $1}}' "
            f"| sed 's/\\.$//' | grep -iF '.{domain}' "
            f"| sort -u > {out_file}"
        )

    def _run_permutation(self, domain: str, known_subs: str,
                         d_dir: str, out_file: str):
        perm_raw = f"{d_dir}/perm_raw.txt"
        self.run_cmd(
            f"cat {known_subs} | alterx -silent 2>/dev/null > {perm_raw}",
            "alterx generating"
        )
        if not self.file_has_content(perm_raw):
            return
        print(f"      Generated: {Fore.GREEN}{self.count_lines(perm_raw)}")

        if shutil.which("puredns"):
            self.run_cmd(
                f"timeout 120 puredns resolve {perm_raw} -r {self.resolvers} "
                f"--quiet -w {out_file} 2>/dev/null",
                "Resolving permutations",
                timeout=140
            )
        elif shutil.which("shuffledns"):
            self.run_cmd(
                f"timeout 120 shuffledns -list {perm_raw} -r {self.resolvers} "
                f"-t {BRUTE_THREADS} -silent -o {out_file} 2>/dev/null",
                "Resolving permutations",
                timeout=140
            )
        else:
            tmp_r = self.tmp(domain, "perm_dnsx.txt")
            self.run_cmd(
                f"timeout 180 dnsx -l {perm_raw} -silent -a -t 100 "
                f"-o {tmp_r} 2>/dev/null",
                timeout=200
            )
            self.extract_domains_from_dnsx(tmp_r, out_file)

    def phase1b_recursive_brute(self, domain: str, d_dir: str, resolved: str) -> str:
        if self.stealth_mode:
            return resolved
        if not RECURSIVE_BRUTE or not self.wordlist:
            return resolved
        t0 = self.phase_timer("PHASE 1b: RECURSIVE BRUTEFORCING")
        print(f"      Top {RECURSIVE_TOP_N} subs ke andar bhi brute...")

        top_subs = []
        if self.file_has_content(resolved):
            with open(resolved, encoding="utf-8", errors="ignore") as f:
                top_subs = [l.strip() for l in f if l.strip()][:RECURSIVE_TOP_N]

        recursive_all = f"{d_dir}/recursive_subs.txt"
        for sub in top_subs:
            sub_out = self.tmp(domain, f"rec_{sub.replace('.','_')}.txt")
            self._run_brute(sub, sub_out)
            if self.file_has_content(sub_out):
                c = self.count_lines(sub_out)
                if c:
                    print(f"      {Fore.GREEN}+{c}{Fore.WHITE} ← {sub}")
                self.append_unique(sub_out, recursive_all)

        if self.file_has_content(recursive_all):
            merged = f"{d_dir}/resolved_subs_final.txt"
            self.run_cmd(
                f"cat {resolved} {recursive_all} | sort -u > {merged}"
            )
            print(f"      Recursive new: "
                  f"{Fore.GREEN}{self.count_lines(recursive_all)}")
            self.phase_done(t0)
            return merged

        self.phase_done(t0)
        return resolved

    # ── Phase 2 ───────────────────────────────────────────────────────────────

    def phase2_port_and_probe(self, domain: str, d_dir: str, resolved: str) -> tuple:
        t0        = self.phase_timer("PHASE 2: PORT SCAN + HTTP PROBING")
        port_file = f"{d_dir}/open_ports.txt"
        ports_dir = f"{d_dir}/ports"
        os.makedirs(ports_dir, exist_ok=True)

        # 2a. Port scan ───────────────────────────────────────────────────────
        self.run_cmd(
            f"timeout 300 naabu -l {resolved} -p {NAABU_PORTS} "
            f"-silent -t {THREADS_NAABU} -o {port_file} 2>/dev/null",
            "Port scanning (naabu)",
            timeout=320
        )
        print(f"      Open combinations: {Fore.GREEN}{self.count_lines(port_file)}")

        # 2b. Port-wise breakdown ─────────────────────────────────────────────
        port_map: dict = {}
        if self.file_has_content(port_file):
            with open(port_file, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    # naabu output: host:port
                    # IPv6 guard: rsplit on last colon
                    idx = line.rfind(":")
                    if idx == -1:
                        continue
                    host = line[:idx].strip()
                    port = line[idx+1:].strip()
                    if port.isdigit():
                        port_map.setdefault(port, []).append(host)

        port_summary_file = f"{d_dir}/port_summary.txt"
        print(f"\n{Fore.YELLOW}      ── Port Breakdown ──")
        with open(port_summary_file, "w", encoding="utf-8") as psf:
            psf.write(f"Port breakdown — {domain}\n{'='*50}\n\n")
            for port in sorted(port_map, key=lambda x: int(x) if x.isdigit() else 0):
                hosts = sorted(set(port_map[port]))
                per_port_file = f"{ports_dir}/hosts_{port}.txt"
                Path(per_port_file).write_text("\n".join(hosts) + "\n")

                label    = INTERESTING_PORTS.get(port, "")
                is_std   = port in STANDARD_PORTS
                color    = Fore.RED    if (not is_std and port in INTERESTING_PORTS) \
                      else Fore.YELLOW if not is_std \
                      else Fore.WHITE
                flag     = " ◄ INTERESTING" if not is_std and port in INTERESTING_PORTS else ""
                desc_str = f" ({label})" if label else ""

                print(f"      {color}:{port}{desc_str}{flag}{Fore.WHITE} "
                      f"— {len(hosts)} host(s)")
                for h in hosts[:5]:
                    print(f"          {Fore.CYAN}{h}")
                if len(hosts) > 5:
                    print(f"          {Fore.CYAN}... +{len(hosts)-5} more")

                psf.write(f":{port}{desc_str} — {len(hosts)} hosts{flag}\n")
                for h in hosts:
                    psf.write(f"  {h}\n")
                psf.write("\n")

        # 2c. HTTP probe ──────────────────────────────────────────────────────
        live_file = f"{d_dir}/live.txt"
        live_200  = f"{d_dir}/live_200.txt"
        input_src = port_file if self.file_has_content(port_file) else resolved

        # httpx host:port → tries http:// and https:// automatically
        self.run_cmd(
            f"cat {input_src} | timeout 300 httpx -silent -t {THREADS_HTTPX} "
            f"-sc -td -title -web-server -content-length -cdn "
            f"-follow-redirects -o {live_file} 2>/dev/null",
            "HTTP probing (all ports)",
            timeout=320
        )

        # [200] filter — httpx format: https://url [200] [title] ...
        self.run_cmd(
            f"grep '\\[200\\]' {live_file} "
            f"| awk '{{print $1}}' > {live_200} 2>/dev/null"
        )
        print(f"\n      Live:   {Fore.GREEN}{self.count_lines(live_file)}")
        print(f"      200 OK: {Fore.GREEN}{self.count_lines(live_200)}")

        # 2d. Per-port live files ─────────────────────────────────────────────
        print(f"\n{Fore.YELLOW}      ── Live by Port ──")
        port_live: dict = {}
        if self.file_has_content(live_file):
            with open(live_file, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    url  = line.split()[0]
                    port = self._port_from_url(url)
                    port_live.setdefault(port, []).append(line)

        for port, entries in sorted(
            port_live.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0
        ):
            live_p = f"{ports_dir}/live_{port}.txt"
            Path(live_p).write_text(
                "\n".join(e.split()[0] for e in entries) + "\n"
            )
            ok_c  = sum(1 for e in entries if "[200]" in e)
            label = INTERESTING_PORTS.get(port, "")
            desc  = f" ({label})" if label else ""
            flag  = f"{Fore.RED} ◄◄" if port in INTERESTING_PORTS \
                                      and port not in STANDARD_PORTS else ""
            print(f"      :{port}{desc}{flag}{Fore.WHITE} "
                  f"— {Fore.GREEN}{len(entries)}{Fore.WHITE} live, "
                  f"{Fore.GREEN}{ok_c}{Fore.WHITE} x 200 OK")

            if port not in STANDARD_PORTS:
                for e in entries[:3]:
                    parts = e.split()
                    url   = parts[0]
                    sc    = parts[1] if len(parts) > 1 else ""
                    title = " ".join(p for p in parts[2:]
                                     if not p.startswith("[")) if len(parts) > 2 else ""
                    c = Fore.GREEN if "[200]" in sc \
                   else Fore.YELLOW if sc.startswith("[3") \
                   else Fore.RED
                    print(f"          {Fore.CYAN}{url} {c}{sc} "
                          f"{Fore.WHITE}{title[:50]}")

        # 2e. Non-standard alert ──────────────────────────────────────────────
        nonstd = f"{d_dir}/nonstandard_live.txt"
        if self.file_has_content(live_file):
            self.run_cmd(
                f"grep '\\[200\\]' {live_file} | grep -vE ':(80|443)([^0-9]|$)' "
                f"> {nonstd} 2>/dev/null"
            )
            ns = self.count_lines(nonstd)
            if ns > 0:
                print(f"\n{Fore.RED}      🎯 NON-STANDARD PORT SERVICES: {ns}")
                self.notify_discord(
                    f"[{domain}] {ns} non-standard port services! → {nonstd}"
                )

        # 2f. VHost brute ─────────────────────────────────────────────────────
        if VHOST_BRUTE and not self.stealth_mode and self.file_has_content(live_200):
            self._run_vhost_brute(domain, d_dir, live_200)

        self.phase_done(t0)
        return live_file, live_200

    def _port_from_url(self, url: str) -> str:
        """URL → port string. IPv6-safe."""
        try:
            no_scheme = url.split("://", 1)[-1]
            host_part = no_scheme.split("/")[0]
            # IPv6: [::1]:8080
            if host_part.startswith("["):
                bracket_end = host_part.find("]")
                after = host_part[bracket_end+1:]
                if after.startswith(":") and after[1:].isdigit():
                    return after[1:]
            elif ":" in host_part:
                port = host_part.rsplit(":", 1)[-1]
                if port.isdigit():
                    return port
            return "443" if url.startswith("https") else "80"
        except Exception:
            return "80"

    def _run_vhost_brute(self, domain: str, d_dir: str, live_200: str):
        if not shutil.which("ffuf"):
            print(f"{Fore.YELLOW}      [~] ffuf not found — vhost skip")
            return
        wl = VHOST_WORDLIST if os.path.exists(VHOST_WORDLIST) else self.wordlist
        if not wl:
            return

        vhost_out = f"{d_dir}/evidence/vhosts.txt"
        print(f"{Fore.CYAN}  [*] VHost bruteforce (ffuf)...")

        targets = []
        with open(live_200, encoding="utf-8", errors="ignore") as f:
            targets = [l.strip() for l in f if l.strip()][:5]

        found = 0
        for target in targets:
            tmp_j = self.tmp(domain, "vhost_ffuf.json")
            self.run_cmd(
                f"ffuf -u {target} -H 'Host: FUZZ.{domain}' "
                f"-w {wl} -mc 200,301,302,403 "
                f"-t 50 -s -o {tmp_j} -of json 2>/dev/null"
            )
            if not self.file_has_content(tmp_j):
                continue
            try:
                data    = json.loads(Path(tmp_j).read_text(errors="ignore"))
                results = data.get("results", [])
                with open(vhost_out, "a", encoding="utf-8") as vf:
                    for r in results:
                        vh = r.get("input", {}).get("FUZZ", "")
                        if vh:
                            vf.write(f"{vh}.{domain}\n")
                found += len(results)
            except (json.JSONDecodeError, KeyError) as e:
                self.logger.warning(f"ffuf parse error ({target}): {e}")
            except IOError as e:
                self.logger.error(f"vhost write error: {e}")

        if found:
            print(f"{Fore.RED}      🏠 VHOSTS: {found}")
            self.notify_discord(f"[{domain}] {found} VHosts found!")
        else:
            print(f"      VHosts: none")

    # ── Phase 3 ───────────────────────────────────────────────────────────────

    def phase3_historical_urls(self, domain: str, d_dir: str) -> str:
        t0        = self.phase_timer("PHASE 3: HISTORICAL URLS")
        hist_file = f"{d_dir}/historical_urls.txt"

        # gau — newer versions: domain as positional arg at the end
        self.run_cmd(
            f"timeout 120 gau --mc 200,301,302 --threads 5 --subs {domain} "
            f">> {hist_file} 2>/dev/null",
            "GAU",
            timeout=140
        )
        if shutil.which("waybackurls"):
            self.run_cmd(
                f"echo {domain} | timeout 60 waybackurls >> {hist_file} 2>/dev/null",
                timeout=80
            )
        if self.file_has_content(hist_file):
            self.run_cmd(f"sort -u {hist_file} -o {hist_file}")

        print(f"      Historical URLs: {Fore.GREEN}{self.count_lines(hist_file)}")

        # Quick grep for interesting file types
        if self.file_has_content(hist_file):
            juicy_pattern = r'\.(env|bak|old|backup|config|sql|zip|tar\.gz|log|key|pem)'
            juicy = self.run_cmd(
                f"grep -iE '{juicy_pattern}' {hist_file} | wc -l"
            )
            if juicy and int(juicy) > 0:
                juicy_file = f"{d_dir}/evidence/juicy_urls.txt"
                self.run_cmd(
                    f"grep -iE '{juicy_pattern}' {hist_file} > {juicy_file} 2>/dev/null"
                )
                print(f"{Fore.RED}      🗂  Juicy file extensions: {juicy}")

        self.phase_done(t0)
        return hist_file

    # ── Phase 4 ───────────────────────────────────────────────────────────────

    def phase4_scan_crawl(self, domain: str, d_dir: str,
                          live_200: str, hist_file: str) -> str:
        t0       = self.phase_timer("PHASE 4: VULN SCAN + CRAWL")
        evidence = f"{d_dir}/evidence"

        # Nuclei — update templates silently first
        self.run_cmd("nuclei -update-templates -silent 2>/dev/null",
                     "Nuclei template update")
        self.run_cmd(
            f"timeout 600 nuclei -l {live_200} -severity critical,high,medium "
            f"-rl {NUCLEI_RATE_LIMIT} -silent "
            f"-o {evidence}/vulns.txt 2>/dev/null",
            "Nuclei (critical/high/medium)",
            timeout=620
        )
        vc = self.count_lines(f"{evidence}/vulns.txt")
        if vc:
            print(f"{Fore.RED}      🔥 VULNS: {vc}")
            self.notify_discord(f"[{domain}] {vc} critical/high/medium vulns!")

        # Katana crawl
        endpoints = f"{d_dir}/endpoints.txt"
        self.run_cmd(
            f"timeout 300 katana -list {live_200} -jc -d {KATANA_DEPTH} "
            f"-kf all -silent -o {endpoints} 2>/dev/null",
            f"Katana (depth={KATANA_DEPTH})",
            timeout=320
        )

        # Merge endpoints + history
        merged = f"{d_dir}/all_endpoints.txt"
        self.run_cmd(
            f"cat {endpoints} {hist_file} 2>/dev/null | sort -u > {merged}"
        )
        print(f"      Endpoints: {Fore.GREEN}{self.count_lines(merged)}")

        # Screenshots — support gowitness v2 and v3
        self._take_screenshots(d_dir, evidence, live_200)

        # Subdomain takeover
        if shutil.which("subzy"):
            # Use resolved_subs.txt — already clean domain list
            target_list = (f"{d_dir}/resolved_subs_final.txt"
                           if os.path.exists(f"{d_dir}/resolved_subs_final.txt")
                           else f"{d_dir}/resolved_subs.txt")
            self.run_cmd(
                f"subzy run --targets {target_list} "
                f"--hide-fails -o {evidence}/takeover.txt 2>/dev/null",
                "Subdomain takeover (subzy)"
            )
            tc = self.count_lines(f"{evidence}/takeover.txt")
            if tc:
                print(f"{Fore.RED}      💀 TAKEOVER: {tc}")
                self.notify_discord(f"[{domain}] {tc} takeover candidates!")
        else:
            print(f"{Fore.YELLOW}      [~] subzy not found — takeover skip")

        self.phase_done(t0)
        return merged

    def _take_screenshots(self, d_dir: str, evidence: str, live_200: str):
        """gowitness v2 aur v3 dono support karta hai."""
        ss_dir = f"{evidence}/screenshots"
        if not shutil.which("gowitness"):
            print(f"{Fore.YELLOW}      [~] gowitness not found — screenshots skip")
            return

        # Try v3 syntax first, fallback to v2
        ret = self.run_cmd(
            f"timeout 300 gowitness scan file -f {live_200} "
            f"--threads {THREADS_GOWITNESS} "
            f"--screenshot-path {ss_dir} 2>/dev/null",
            timeout=320
        )
        # Fallback to v2 if v3 failed or produced no screenshots
        if not ret or (os.path.exists(ss_dir) and not os.listdir(ss_dir)):
            # v2 syntax
            self.run_cmd(
                f"timeout 300 gowitness file -f {live_200} "
                f"--threads {THREADS_GOWITNESS} "
                f"--screenshot-path {ss_dir} --disable-db 2>/dev/null",
                "Screenshots (gowitness)",
                timeout=320
            )

    # ── Phase 5 ───────────────────────────────────────────────────────────────

    def phase5_js_secrets(self, domain: str, d_dir: str, live_200: str):
        t0       = self.phase_timer("PHASE 5: JS SECRET HUNTING")
        evidence = f"{d_dir}/evidence"
        js_urls  = f"{d_dir}/js_urls.txt"

        if not shutil.which("subjs"):
            print(f"{Fore.YELLOW}      [~] subjs not found — JS skip")
            self.phase_done(t0)
            return

        self.run_cmd(
            f"cat {live_200} | subjs -c 20 2>/dev/null | sort -u > {js_urls}"
        )
        js_count = self.count_lines(js_urls)
        print(f"      JS files: {Fore.GREEN}{js_count}")

        if not js_count:
            self.phase_done(t0)
            return

        secrets_file = f"{evidence}/js_secrets.txt"

        if shutil.which("secretfinder"):
            # secretfinder — better than raw grep
            self.run_cmd(
                f"cat {js_urls} | xargs -P 5 -I@ "
                f"python3 $(which secretfinder) -i @ -o cli 2>/dev/null "
                f">> {secrets_file}",
                "SecretFinder"
            )
        else:
            # Python-based JS fetch + regex (reliable, no xargs crash)
            self._fetch_js_secrets_python(js_urls, secrets_file)

        sc = self.count_lines(secrets_file)
        if sc:
            print(f"{Fore.RED}      🔑 SECRETS: {sc}")
            self.notify_discord(f"[{domain}] {sc} potential JS secrets!")
        self.phase_done(t0)

    def _fetch_js_secrets_python(self, js_urls_file: str, out_file: str):
        """
        Python requests se JS fetch karo (xargs+curl se zyada reliable).
        Thread pool use karo — har file parallel fetch hoga.
        """
        import concurrent.futures
        urls = []
        with open(js_urls_file, encoding="utf-8", errors="ignore") as f:
            urls = [l.strip() for l in f if l.strip()]

        compiled = [re.compile(p) for p in JS_SECRET_PATTERNS]

        def fetch_and_scan(url: str) -> list:
            try:
                r = requests.get(url, timeout=10, verify=False,
                                 headers={"User-Agent": "Mozilla/5.0"})
                found = []
                for pat in compiled:
                    for m in pat.findall(r.text):
                        found.append(f"{url} → {m[:120]}")
                return found
            except Exception:
                return []

        all_found = []
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=THREADS_JS_FETCH
        ) as ex:
            for result in ex.map(fetch_and_scan, urls):
                all_found.extend(result)

        if all_found:
            with open(out_file, "a", encoding="utf-8") as f:
                f.write("\n".join(all_found) + "\n")

    # ── Phase 6 ───────────────────────────────────────────────────────────────

    def phase6_data_mining(self, domain: str, d_dir: str, merged: str):
        t0       = self.phase_timer("PHASE 6: DATA MINING")
        evidence = f"{d_dir}/evidence"

        if not self.file_has_content(merged):
            print(f"{Fore.YELLOW}      [~] No endpoints — GF skip")
            self.phase_done(t0)
            return

        # GF patterns ─────────────────────────────────────────────────────────
        for pattern, out_rel in GF_PATTERNS.items():
            out_abs = f"{d_dir}/{out_rel}"
            self.run_cmd(
                f"cat {merged} | gf {pattern} > {out_abs} 2>/dev/null"
            )
            c = self.count_lines(out_abs)
            if c:
                print(f"      {pattern:15}: {Fore.GREEN}{c} params")

        # CORS ────────────────────────────────────────────────────────────────
        cors_out = f"{evidence}/cors.txt"
        if shutil.which("corsy"):
            self.run_cmd(
                f"timeout 120 corsy -i {d_dir}/live_200.txt -t 10 "
                f"--headers 'User-Agent: Mozilla' "
                f"-o {cors_out} 2>/dev/null",
                "CORS check (corsy)",
                timeout=140
            )
        else:
            # httpx -mr flag (correct name, not -match-regex)
            self.run_cmd(
                f"cat {d_dir}/live_200.txt | timeout 120 httpx -silent "
                f"-H 'Origin: https://evil.com' "
                f"-mr 'Access-Control-Allow-Origin: https://evil.com' "
                f"-o {cors_out} 2>/dev/null",
                "CORS check (httpx)",
                timeout=140
            )
        if self.count_lines(cors_out):
            print(f"{Fore.RED}      🌐 CORS: {self.count_lines(cors_out)}")

        # 403 Bypass ──────────────────────────────────────────────────────────
        # Domain-specific temp file (parallel-safe)
        targets_403 = self.tmp(domain, "403_targets.txt")
        self.run_cmd(
            f"grep '\\[403\\]' {d_dir}/live.txt "
            f"| awk '{{print $1}}' > {targets_403} 2>/dev/null"
        )
        if self.file_has_content(targets_403):
            bypass_out = f"{evidence}/403_bypass.txt"
            bypass_headers = [
                "X-Original-URL: /",
                "X-Forwarded-For: 127.0.0.1",
                "X-Custom-IP-Authorization: 127.0.0.1",
                "X-Rewrite-URL: /",
                "X-Host: 127.0.0.1",
                "X-Forwarded-Host: 127.0.0.1",
                "X-Real-IP: 127.0.0.1",
                "Client-IP: 127.0.0.1",
            ]
            hdr_str = " ".join(
                f'-H "{h}"' for h in bypass_headers
            )
            bypass_cmd = (
                f"while IFS= read -r url; do "
                f"  code=$(curl -sk -o /dev/null -w '%{{http_code}}' "
                f"  {hdr_str} \"$url\"); "
                f"  [ \"$code\" = '200' ] && "
                f"  echo \"BYPASS: $url\" >> {bypass_out}; "
                f"done < {targets_403}"
            )
            self.run_cmd(bypass_cmd, "403 Bypass")
            bc = self.count_lines(bypass_out)
            if bc:
                print(f"{Fore.RED}      🚪 403 BYPASSED: {bc}")
                self.notify_discord(f"[{domain}] {bc} 403 bypass!")

        self.phase_done(t0)

    # ── Summary ───────────────────────────────────────────────────────────────

    def generate_summary(self, domain: str, d_dir: str):
        ev = f"{d_dir}/evidence"

        stats = {
            # Subdomain stats
            "Subdomains raw":        self.count_lines(f"{d_dir}/raw_subs.txt"),
            "Subdomains brute":      self.count_lines(f"{d_dir}/brute_subs.txt"),
            "Subdomains permut.":    self.count_lines(f"{d_dir}/perm_subs.txt"),
            "Subdomains recursive":  self.count_lines(f"{d_dir}/recursive_subs.txt"),
            "Subdomains resolved":   self.count_lines(f"{d_dir}/resolved_subs.txt"),
            # Port stats
            "Open port:host pairs":  self.count_lines(f"{d_dir}/open_ports.txt"),
            "Non-std live services": self.count_lines(f"{d_dir}/nonstandard_live.txt"),
            "VHosts":                self.count_lines(f"{ev}/vhosts.txt"),
            # HTTP
            "Live hosts":            self.count_lines(f"{d_dir}/live.txt"),
            "200 OK":                self.count_lines(f"{d_dir}/live_200.txt"),
            "Endpoints":             self.count_lines(f"{d_dir}/all_endpoints.txt"),
            "Juicy ext URLs":        self.count_lines(f"{ev}/juicy_urls.txt"),
            # Vulns
            "Nuclei vulns":          self.count_lines(f"{ev}/vulns.txt"),
            "XSS params":            self.count_lines(f"{ev}/xss.txt"),
            "SQLi params":           self.count_lines(f"{ev}/sqli.txt"),
            "SSRF params":           self.count_lines(f"{ev}/ssrf.txt"),
            "Open redirect":         self.count_lines(f"{ev}/open_redirect.txt"),
            "LFI params":            self.count_lines(f"{ev}/lfi.txt"),
            "RCE params":            self.count_lines(f"{ev}/rce.txt"),
            "IDOR params":           self.count_lines(f"{ev}/idor.txt"),
            # High value
            "Takeover":              self.count_lines(f"{ev}/takeover.txt"),
            "JS secrets":            self.count_lines(f"{ev}/js_secrets.txt"),
            "403 bypassed":          self.count_lines(f"{ev}/403_bypass.txt"),
            "CORS issues":           self.count_lines(f"{ev}/cors.txt"),
        }

        # Save JSON
        with open(f"{d_dir}/summary.json", "w", encoding="utf-8") as f:
            json.dump({
                "domain":    domain,
                "timestamp": datetime.datetime.now().isoformat(),
                "stats":     stats,
            }, f, indent=2)

        # ── Print ──
        HIGH_VALUE = {
            "Nuclei vulns", "Takeover", "JS secrets",
            "403 bypassed", "Non-std live services",
            "VHosts", "CORS issues", "Juicy ext URLs",
        }
        W = 30
        print(f"\n{Fore.MAGENTA}{'═'*54}")
        print(f"{Fore.MAGENTA}  SUMMARY  →  {domain}")
        print(f"{'═'*54}{Style.RESET_ALL}")
        for k, v in stats.items():
            if k in HIGH_VALUE:
                color = Fore.RED    if v > 0 else Fore.WHITE
            else:
                color = Fore.GREEN  if v > 0 else Fore.WHITE
            print(f"  {k:<{W}} {color}{v}{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}{'═'*54}{Style.RESET_ALL}")

        # Discord final summary
        if DISCORD_WEBHOOK_URL:
            hv = {k: v for k, v in stats.items() if k in HIGH_VALUE and v > 0}
            if hv:
                msg = f"[{domain}] FINAL:\n" + "\n".join(
                    f"  {k}: {v}" for k, v in hv.items()
                )
                self.notify_discord(msg)

    # ── Master ────────────────────────────────────────────────────────────────

    def process_target(self, domain: str):
        d_dir = f"{self.base_dir}/{domain}"
        if self.is_already_scanned(domain):
            print(f"{Fore.YELLOW}[~] {domain} — already scanned (resume mode)")
            return

        print(f"\n{Fore.MAGENTA}{'='*55}")
        print(f"  [#] SCANNING: {domain}")
        print(f"{'='*55}{Style.RESET_ALL}")
        t_start = time.time()

        for sub in ["evidence/screenshots", "ports"]:
            os.makedirs(f"{d_dir}/{sub}", exist_ok=True)

        try:
            resolved            = self.phase1_subdomain_enum(domain, d_dir)
            resolved            = self.phase1b_recursive_brute(domain, d_dir, resolved)
            live_file, live_200 = self.phase2_port_and_probe(domain, d_dir, resolved)

            if not self.file_has_content(live_200):
                print(f"{Fore.RED}  [!] No 200 OK hosts — deep scan skip")
            else:
                hist   = self.phase3_historical_urls(domain, d_dir)
                merged = self.phase4_scan_crawl(domain, d_dir, live_200, hist)
                self.phase5_js_secrets(domain, d_dir, live_200)
                self.phase6_data_mining(domain, d_dir, merged)

        except Exception as e:
            self.logger.error(f"process_target crash ({domain}): {e}", exc_info=True)
            print(f"{Fore.RED}  [!] Unexpected error: {e}")

        self.generate_summary(domain, d_dir)
        self.mark_scan_complete(domain, d_dir)
        elapsed = round(time.time() - t_start, 1)
        print(f"\n{Fore.GREEN}  [✔] {domain} done in {elapsed}s → {d_dir}{Style.RESET_ALL}")

    def start(self):
        stealth_status = f"{Fore.GREEN}Enabled" if self.stealth_mode else f"{Fore.RED}Disabled"
        banner = f"""
{Fore.RED}  ██████╗ ██╗  ██╗ ██████╗ ███████╗████████╗
{Fore.RED}  ██╔════╝██║  ██║██╔═══██╗██╔════╝╚══██╔══╝
{Fore.YELLOW}  ██║  ███╗███████║██║   ██║███████╗   ██║
{Fore.YELLOW}  ██║   ██║██╔══██║██║   ██║╚════██║   ██║
{Fore.GREEN}  ╚██████╔╝██║  ██║╚██████╔╝███████║   ██║
{Fore.GREEN}   ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝   ╚═╝
{Fore.CYAN}       PROTOCOL v9.1 — Bug Bounty Edition
{Fore.WHITE}       Targets : {len(self.targets)}
{Fore.WHITE}       Session : {self.session_id}
{Fore.YELLOW}       Wordlist: {self.wordlist or "NOT FOUND"}
{Fore.CYAN}       Stealth : {stealth_status}
        """
        print(banner)
        with ThreadPoolExecutor(max_workers=MAX_DOMAINS_PARALLEL) as ex:
            ex.map(self.process_target, self.targets)
        print(f"\n{Fore.MAGENTA}[!!!] ALL DONE → {self.base_dir}/{Style.RESET_ALL}")


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GHOST PROTOCOL v9.1 — DEEP RECON ENGINE")
    parser.add_argument("targets", help="File containing list of domains (one per line)")
    parser.add_argument("-s", "--stealth", action="store_true", help="Enable Stealth Mode (skips active bruteforcing & permutations)")
    
    args = parser.parse_args()

    # urllib3 SSL warnings suppress karo (verify=False use hota hai JS fetch mein)
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    DeepRecon(args.targets, stealth_mode=args.stealth).start()
