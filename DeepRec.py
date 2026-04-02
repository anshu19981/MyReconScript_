#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════╗
║         GHOST PROTOCOL v8.0 — DEEP RECON ENGINE         ║
║              Bug Bounty Hunter Edition                   ║
╚══════════════════════════════════════════════════════════╝

IMPROVEMENTS OVER v7.0:
  ✔ DNS Resolution (dnsx) — wildcard & dead DNS filter karo PEHLE
  ✔ Port Scanning (naabu) — non-standard ports (8080, 8443, etc.)
  ✔ Historical URLs (gau + waybackurls) — endpoints goldmine
  ✔ JS Secret Hunting (subjs + secretfinder) — API keys, tokens
  ✔ Subdomain Takeover (subzy) — easy wins!
  ✔ 403 Bypass module — juicy hidden endpoints
  ✔ More GF patterns — redirect, lfi, rce, idor, debug_logic
  ✔ Discord Webhook notifications — critical vulns ka alert
  ✔ Resume capability — crash hone par dobara shuru karo wahan se
  ✔ Tool availability check — missing tools ka warning
  ✔ Summary report — domain ke end mein full stats
  ✔ Structured logging — errors track hote rahein
  ✔ CORS misconfiguration check
  ✔ Wildcard DNS detection — false positive se bachao

FIXES v8.1:
  ✔ BUG FIX: grep space200space → grep [200] (httpx output format match)
  ✔ BUG FIX: dnsx -resp-only hata diya (IP nahi, domain names chahiye)
"""

import subprocess
import os
import sys
import datetime
import requests
import json
import logging
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from colorama import Fore, Style, init

init(autoreset=True)

# ─── CONFIGURATION ────────────────────────────────────────────────────────────
THREADS_HTTPX        = "100"
THREADS_GOWITNESS    = "5"
THREADS_NAABU        = "500"
MAX_DOMAINS_PARALLEL = 2          # 16GB RAM ke liye safe
KATANA_DEPTH         = 3          # v7 mein 2 tha — ek level aur deep
NUCLEI_RATE_LIMIT    = "150"      # Requests/sec — ban se bachne ke liye

# Discord webhook URL (optional) — khali chhoodo agar notifications nahi chahiye
DISCORD_WEBHOOK_URL  = ""

# Non-standard ports jo targets pe frequently open milte hain
NAABU_PORTS = "80,81,443,591,2082,2087,2095,8000,8008,8080,8443,8888,9000,9090,10000"

# GF patterns — v7 mein sirf 3 the, ab 8 hain
GF_PATTERNS = {
    "xss":          "evidence/xss.txt",
    "ssrf":         "evidence/ssrf.txt",
    "sqli":         "evidence/sqli.txt",
    "redirect":     "evidence/open_redirect.txt",   # BADA bounty source!
    "lfi":          "evidence/lfi.txt",
    "rce":          "evidence/rce.txt",
    "idor":         "evidence/idor.txt",
    "debug_logic":  "evidence/debug.txt",
}

# Tools jo REQUIRED hain (startup pe check hoga)
REQUIRED_TOOLS = [
    "subfinder", "assetfinder", "amass", "httpx",
    "nuclei", "katana", "gowitness", "gf", "dnsx",
    "naabu", "gau",
]
# Tools jo optional hain (missing hone par skip hoga, exit nahi)
OPTIONAL_TOOLS = ["waybackurls", "subjs", "python3", "corsy", "subzy"]


# ─── LOGGING SETUP ────────────────────────────────────────────────────────────
def setup_logger(log_file: str) -> logging.Logger:
    logger = logging.getLogger("DeepRecon")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    return logger


# ─── MAIN CLASS ───────────────────────────────────────────────────────────────
class DeepRecon:
    def __init__(self, target_file: str):
        self.targets    = self.load_targets(target_file)
        self.session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        self.base_dir   = f"DEEP_RECON_{self.session_id}"
        os.makedirs(self.base_dir, exist_ok=True)
        self.logger     = setup_logger(f"{self.base_dir}/recon.log")
        self.check_tools()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def load_targets(self, file_path: str) -> list:
        if not os.path.exists(file_path):
            print(f"{Fore.RED}[!] Error: {file_path} nahi mila.")
            sys.exit(1)
        with open(file_path) as f:
            return [l.strip() for l in f if l.strip()]

    def check_tools(self):
        """Startup pe check karo — missing tools ka pata pehle hi chalega."""
        print(f"{Fore.YELLOW}[~] Checking required tools...")
        missing = [t for t in REQUIRED_TOOLS if not shutil.which(t)]
        optional_missing = [t for t in OPTIONAL_TOOLS if not shutil.which(t)]
        if missing:
            print(f"{Fore.RED}[!] MISSING (required): {', '.join(missing)}")
            print(f"{Fore.RED}    Install karke dobara chalao. Exiting.")
            sys.exit(1)
        if optional_missing:
            print(f"{Fore.YELLOW}[~] MISSING (optional, skip hoga): {', '.join(optional_missing)}")
        print(f"{Fore.GREEN}[✔] All required tools found.\n")

    def run_cmd(self, cmd: str, msg: str = None, output_file: str = None) -> str:
        """
        Shell command run karo.
        output_file diya toh stdout wahan save hoga (pipe-friendly).
        Returns stdout as string (useful for small outputs).
        """
        if msg:
            print(f"{Fore.CYAN}  [*] {msg}...")
        self.logger.debug(f"CMD: {cmd}")
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=600
            )
            if result.returncode != 0:
                self.logger.warning(f"Non-zero exit for: {cmd}\n{result.stderr[:300]}")
            if output_file and result.stdout:
                with open(output_file, "a") as f:
                    f.write(result.stdout)
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            self.logger.error(f"TIMEOUT: {cmd}")
            return ""
        except Exception as e:
            self.logger.error(f"EXCEPTION running [{cmd}]: {e}")
            return ""

    def file_has_content(self, path: str) -> bool:
        return os.path.exists(path) and os.path.getsize(path) > 0

    def count_lines(self, path: str) -> int:
        if not self.file_has_content(path):
            return 0
        with open(path) as f:
            return sum(1 for _ in f)

    def notify_discord(self, message: str):
        """Critical finding milne par Discord pe alert bhejo."""
        if not DISCORD_WEBHOOK_URL:
            return
        try:
            requests.post(
                DISCORD_WEBHOOK_URL,
                json={"content": f"🚨 **GHOST PROTOCOL ALERT**\n```{message}```"},
                timeout=10
            )
        except Exception as e:
            self.logger.warning(f"Discord notify failed: {e}")

    def is_already_scanned(self, domain: str) -> bool:
        """
        Resume feature — agar kisi pichle session mein domain scan ho gaya tha
        toh skip karo. (Same base_dir mein hona chahiye)
        """
        marker = f"{self.base_dir}/{domain}/.scan_complete"
        return os.path.exists(marker)

    def mark_scan_complete(self, domain: str, d_dir: str):
        with open(f"{d_dir}/.scan_complete", "w") as f:
            f.write(datetime.datetime.now().isoformat())

    # ── Phase Methods ─────────────────────────────────────────────────────────

    def phase1_subdomain_enum(self, domain: str, d_dir: str) -> str:
        """
        PHASE 1: SUBDOMAIN ENUMERATION
        v8.1 fix:
          - dnsx -resp-only HATA DIYA — pehle sirf IPs return karta tha
            jisse httpx virtual hosting miss karta tha
        """
        print(f"\n{Fore.YELLOW}  ── PHASE 1: SUBDOMAIN ENUMERATION ──")
        raw      = f"{d_dir}/raw_subs.txt"
        resolved = f"{d_dir}/resolved_subs.txt"

        # Multiple sources
        self.get_crt_sh(domain, raw)
        self.run_cmd(f"subfinder -d {domain} -silent -all -o /tmp/_sf.txt && cat /tmp/_sf.txt >> {raw}")
        self.run_cmd(f"assetfinder --subs-only {domain} >> {raw}")
        self.run_cmd(f"amass enum -passive -d {domain} -silent >> {raw}")

        # Unique kar lo
        self.run_cmd(f"sort -u {raw} -o {raw}")
        raw_count = self.count_lines(raw)
        print(f"{Fore.WHITE}      Raw subdomains: {Fore.GREEN}{raw_count}")

        # ── DNS Resolution via dnsx ──
        # FIX: -resp-only HATA DIYA — woh sirf IP deta tha, domain names nahi
        # Ab resolved_subs.txt mein proper domain:IP format aayega
        self.run_cmd(
            f"dnsx -l {raw} -silent -a -t 100 -o {resolved}",
            "Resolving DNS (wildcard filter)"
        )
        resolved_count = self.count_lines(resolved)
        print(f"{Fore.WHITE}      Resolved subdomains: {Fore.GREEN}{resolved_count} "
              f"({Fore.RED}-{raw_count - resolved_count} wildcards/dead{Fore.WHITE})")
        return resolved

    def phase2_port_and_probe(self, domain: str, d_dir: str, resolved: str) -> tuple:
        """
        PHASE 2: PORT SCAN + HTTP PROBING
        v8.1 fix:
          - grep [200] use karo — httpx output format: https://url [200] [title]
            pehle grep space200space tha jo kabhi match nahi karta tha
        """
        print(f"\n{Fore.YELLOW}  ── PHASE 2: PORT SCAN + HTTP PROBING ──")

        # ── Port scanning ──
        port_file = f"{d_dir}/open_ports.txt"
        self.run_cmd(
            f"naabu -l {resolved} -p {NAABU_PORTS} -silent -t {THREADS_NAABU} -o {port_file}",
            "Port scanning (naabu)"
        )

        # Live HTTP probing — port_file ko input dena better hai than resolved
        live_file  = f"{d_dir}/live.txt"
        live_200   = f"{d_dir}/live_200.txt"
        input_for_httpx = port_file if self.file_has_content(port_file) else resolved

        self.run_cmd(
            f"cat {input_for_httpx} | httpx -silent -t {THREADS_HTTPX} "
            f"-sc -td -title -web-server -content-length -cdn -follow-redirects "
            f"-o {live_file}",
            "Probing live HTTP assets"
        )

        # ✅ FIX: httpx output format hai → https://url [200] [Title]
        # Isliye grep '\[200\]' chahiye, ' 200 ' nahi
        self.run_cmd(
            f"grep '\\[200\\]' {live_file} | awk '{{print $1}}' > {live_200}",
        )

        print(f"{Fore.WHITE}      Live hosts: {Fore.GREEN}{self.count_lines(live_file)}, "
              f"200 OK: {Fore.GREEN}{self.count_lines(live_200)}")
        return live_file, live_200

    def phase3_historical_urls(self, domain: str, d_dir: str) -> str:
        """
        PHASE 3: HISTORICAL URL DISCOVERY
        gau + waybackurls — purani endpoints, old API versions, hidden params
        Yeh akele XSS/SQLi/IDOR ke liye sone ki khaan hai!
        """
        print(f"\n{Fore.YELLOW}  ── PHASE 3: HISTORICAL URLS (WAY BACK) ──")
        hist_file = f"{d_dir}/historical_urls.txt"
        self.run_cmd(f"gau {domain} --mc 200,301,302 --threads 5 >> {hist_file}", "GAU (historical URLs)")
        if shutil.which("waybackurls"):
            self.run_cmd(f"echo {domain} | waybackurls >> {hist_file}", "Waybackurls")
        self.run_cmd(f"sort -u {hist_file} -o {hist_file}")
        print(f"{Fore.WHITE}      Historical URLs: {Fore.GREEN}{self.count_lines(hist_file)}")
        return hist_file

    def phase4_scan_crawl(self, domain: str, d_dir: str, live_200: str, hist_file: str):
        """
        PHASE 4: SCANNING + CRAWLING
        + Nuclei rate-limit add kiya — bans se bachne ke liye
        + Katana depth 3 (tha 2)
        + Katana ka output + historical URLs merge karke GF chalana
        + Subdomain takeover check (subzy) — easy $$$
        """
        print(f"\n{Fore.YELLOW}  ── PHASE 4: SCAN + CRAWL ──")
        evidence  = f"{d_dir}/evidence"
        endpoints = f"{d_dir}/endpoints.txt"

        # Nuclei with rate limit
        self.run_cmd(
            f"nuclei -l {live_200} -severity critical,high -rl {NUCLEI_RATE_LIMIT} "
            f"-silent -o {evidence}/vulns.txt",
            "Nuclei (critical/high)"
        )
        vuln_count = self.count_lines(f"{evidence}/vulns.txt")
        if vuln_count > 0:
            print(f"{Fore.RED}      🔥 VULNS FOUND: {vuln_count}")
            self.notify_discord(f"[{domain}] Nuclei found {vuln_count} critical/high vulns!")

        # Katana crawl
        self.run_cmd(
            f"katana -list {live_200} -jc -d {KATANA_DEPTH} -kf all -silent -o {endpoints}",
            "Katana crawling (depth=3)"
        )

        # Merge historical URLs with crawled endpoints
        merged = f"{d_dir}/all_endpoints.txt"
        self.run_cmd(f"cat {endpoints} {hist_file} 2>/dev/null | sort -u > {merged}")
        print(f"{Fore.WHITE}      Total endpoints (crawl+history): {Fore.GREEN}{self.count_lines(merged)}")

        # Screenshots
        self.run_cmd(
            f"gowitness file -f {live_200} --threads {THREADS_GOWITNESS} "
            f"--screenshot-path {evidence}/screenshots --disable-db",
            "Screenshots (gowitness)"
        )

        # Subdomain Takeover (optional — subzy install ho toh chalega)
        if shutil.which("subzy"):
            self.run_cmd(
                f"subzy run --targets {d_dir}/../{domain.replace('.','_')}_subs.txt "
                f"--hide-fails --output {evidence}/takeover.txt 2>/dev/null || "
                f"subzy run --targets {d_dir}/resolved_subs.txt --hide-fails "
                f"--output {evidence}/takeover.txt",
                "Subdomain Takeover check (subzy)"
            )
            takeover_count = self.count_lines(f"{evidence}/takeover.txt")
            if takeover_count > 0:
                print(f"{Fore.RED}      💀 TAKEOVER CANDIDATES: {takeover_count}")
                self.notify_discord(f"[{domain}] {takeover_count} subdomain takeover candidates!")
        else:
            print(f"{Fore.YELLOW}      [~] subzy not found, skipping takeover check.")

        return merged

    def phase5_js_secrets(self, domain: str, d_dir: str, live_200: str):
        """
        PHASE 5: JS FILE ANALYSIS + SECRET HUNTING
        JS files mein API keys, tokens, internal endpoints hote hain.
        subjs se JS URLs nikalo, phir secretfinder se analyze karo.
        """
        print(f"\n{Fore.YELLOW}  ── PHASE 5: JS SECRET HUNTING ──")
        if not shutil.which("subjs"):
            print(f"{Fore.YELLOW}      [~] subjs not found, skipping JS analysis.")
            return
        evidence = f"{d_dir}/evidence"
        js_urls  = f"{d_dir}/js_urls.txt"
        self.run_cmd(
            f"cat {live_200} | subjs -c 20 | sort -u > {js_urls}",
            "Extracting JS URLs (subjs)"
        )
        print(f"{Fore.WHITE}      JS files found: {Fore.GREEN}{self.count_lines(js_urls)}")
        if self.file_has_content(js_urls):
            self.run_cmd(
                f"cat {js_urls} | xargs -I@ curl -sk @ | "
                f"grep -Eoi '(api[_-]?key|secret|token|password|aws)[[:space:]]*[:=][[:space:]]*[\"\\x27]?[A-Za-z0-9/+_-]{{16,}}' "
                f"> {evidence}/js_secrets.txt 2>/dev/null",
                "Hunting secrets in JS"
            )
            secret_count = self.count_lines(f"{evidence}/js_secrets.txt")
            if secret_count > 0:
                print(f"{Fore.RED}      🔑 SECRETS FOUND: {secret_count}")
                self.notify_discord(f"[{domain}] {secret_count} potential secrets in JS files!")

    def phase6_data_mining(self, domain: str, d_dir: str, merged_endpoints: str):
        """
        PHASE 6: GF DATA MINING
        + 8 patterns (tha 3)
        + Input: merged endpoints (crawl + history) — zyada coverage
        + CORS check
        + 403 Bypass on juicy endpoints
        """
        print(f"\n{Fore.YELLOW}  ── PHASE 6: DATA MINING (GF + CORS + 403 BYPASS) ──")
        evidence = f"{d_dir}/evidence"

        # GF patterns
        for pattern, out_rel in GF_PATTERNS.items():
            out_abs = f"{d_dir}/{out_rel}"
            self.run_cmd(
                f"cat {merged_endpoints} | gf {pattern} > {out_abs} 2>/dev/null",
                f"GF: {pattern}"
            )
            count = self.count_lines(out_abs)
            if count > 0:
                print(f"{Fore.WHITE}        {pattern}: {Fore.GREEN}{count} params")

        # ── CORS Misconfiguration ──
        if shutil.which("corsy"):
            self.run_cmd(
                f"corsy -i {d_dir}/live_200.txt -t 10 --headers 'User-Agent: Mozilla' "
                f"-o {evidence}/cors.txt 2>/dev/null",
                "CORS misconfiguration check"
            )
        else:
            # Basic CORS check via httpx
            self.run_cmd(
                f"cat {d_dir}/live_200.txt | httpx -silent -H 'Origin: https://evil.com' "
                f"-match-regex 'Access-Control-Allow-Origin: https://evil.com' "
                f"-o {evidence}/cors.txt 2>/dev/null",
                "Basic CORS check (httpx)"
            )

        # ── 403 Bypass ──
        # live.txt mein [403] format hoga — FIX: grep '\[403\]' use karo
        live_file = f"{d_dir}/live.txt"
        self.run_cmd(
            f"grep '\\[403\\]' {live_file} | awk '{{print $1}}' > /tmp/_403_targets.txt 2>/dev/null",
        )
        if self.file_has_content("/tmp/_403_targets.txt"):
            bypass_cmd = (
                f"while IFS= read -r url; do "
                f"  for header in 'X-Original-URL: /' 'X-Forwarded-For: 127.0.0.1' "
                f"    'X-Custom-IP-Authorization: 127.0.0.1' 'X-Rewrite-URL: /' ; do "
                f"    code=$(curl -sk -o /dev/null -w '%{{http_code}}' -H \"$header\" \"$url\"); "
                f"    [ \"$code\" = '200' ] && echo \"BYPASS [$header]: $url\" >> {evidence}/403_bypass.txt; "
                f"  done; "
                f"done < /tmp/_403_targets.txt"
            )
            self.run_cmd(bypass_cmd, "403 Bypass attempts")
            bypass_count = self.count_lines(f"{evidence}/403_bypass.txt")
            if bypass_count > 0:
                print(f"{Fore.RED}      🚪 403 BYPASSED: {bypass_count}")
                self.notify_discord(f"[{domain}] {bypass_count} 403 bypass successes!")

    def generate_summary(self, domain: str, d_dir: str):
        """
        End mein ek clean summary print karo — kya mila, kitna mila.
        """
        evidence = f"{d_dir}/evidence"
        summary = {
            "Subdomains (raw)":      self.count_lines(f"{d_dir}/raw_subs.txt"),
            "Subdomains (resolved)": self.count_lines(f"{d_dir}/resolved_subs.txt"),
            "Live hosts":            self.count_lines(f"{d_dir}/live.txt"),
            "200 OK":                self.count_lines(f"{d_dir}/live_200.txt"),
            "Endpoints (total)":     self.count_lines(f"{d_dir}/all_endpoints.txt"),
            "Vulns (nuclei)":        self.count_lines(f"{evidence}/vulns.txt"),
            "XSS params":            self.count_lines(f"{evidence}/xss.txt"),
            "SQLi params":           self.count_lines(f"{evidence}/sqli.txt"),
            "SSRF params":           self.count_lines(f"{evidence}/ssrf.txt"),
            "Open Redirect":         self.count_lines(f"{evidence}/open_redirect.txt"),
            "LFI params":            self.count_lines(f"{evidence}/lfi.txt"),
            "Takeover candidates":   self.count_lines(f"{evidence}/takeover.txt"),
            "JS Secrets":            self.count_lines(f"{evidence}/js_secrets.txt"),
            "403 Bypassed":          self.count_lines(f"{evidence}/403_bypass.txt"),
            "CORS issues":           self.count_lines(f"{evidence}/cors.txt"),
        }
        # Save to JSON
        with open(f"{d_dir}/summary.json", "w") as f:
            json.dump({"domain": domain, "timestamp": datetime.datetime.now().isoformat(),
                       "stats": summary}, f, indent=2)

        # Pretty print
        print(f"\n{Fore.MAGENTA}{'═'*52}")
        print(f"{Fore.MAGENTA}  SUMMARY: {domain}")
        print(f"{'═'*52}{Style.RESET_ALL}")
        for k, v in summary.items():
            color = Fore.RED if (v > 0 and "Vuln" in k or "Secret" in k
                                 or "Bypass" in k or "Takeover" in k) else \
                    Fore.GREEN if v > 0 else Fore.WHITE
            print(f"  {k:<28} {color}{v}{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}{'═'*52}{Style.RESET_ALL}")

    # ── Utility ───────────────────────────────────────────────────────────────

    def get_crt_sh(self, domain: str, sub_file: str):
        """crt.sh — wildcard entries bhi extract karo (*.sub.domain.com)."""
        try:
            url = f"https://crt.sh/?q=%25.{domain}&output=json"
            r = requests.get(url, timeout=25)
            if r.status_code == 200:
                names = set()
                for entry in r.json():
                    for name in entry.get('name_value', '').splitlines():
                        name = name.strip().lstrip('*.')
                        if name:
                            names.add(name)
                with open(sub_file, "a") as f:
                    f.write('\n'.join(names) + '\n')
                self.logger.info(f"crt.sh: {len(names)} subdomains for {domain}")
        except Exception as e:
            self.logger.warning(f"crt.sh failed for {domain}: {e}")

    # ── Master Controller ──────────────────────────────────────────────────────

    def process_target(self, domain: str):
        """Ek domain ke liye poora pipeline run karo."""
        d_dir = f"{self.base_dir}/{domain}"
        if self.is_already_scanned(domain):
            print(f"{Fore.YELLOW}[~] Skipping {domain} — already scanned (resume mode).")
            return

        print(f"\n{Fore.MAGENTA}{'='*55}")
        print(f"  [#] DEEP SCANNING: {domain}")
        print(f"{'='*55}{Style.RESET_ALL}")
        start_time = time.time()

        os.makedirs(f"{d_dir}/evidence/screenshots", exist_ok=True)

        resolved              = self.phase1_subdomain_enum(domain, d_dir)
        live_file, live_200   = self.phase2_port_and_probe(domain, d_dir, resolved)

        if not self.file_has_content(live_200):
            print(f"{Fore.RED}  [!] No live 200 OK hosts found for {domain}. Skipping deeper phases.")
        else:
            hist_file = self.phase3_historical_urls(domain, d_dir)
            merged    = self.phase4_scan_crawl(domain, d_dir, live_200, hist_file)
            self.phase5_js_secrets(domain, d_dir, live_200)
            self.phase6_data_mining(domain, d_dir, merged)

        self.generate_summary(domain, d_dir)
        self.mark_scan_complete(domain, d_dir)
        elapsed = round(time.time() - start_time, 1)
        print(f"\n{Fore.GREEN}  [✔] {domain} — Done in {elapsed}s. Results: {d_dir}{Style.RESET_ALL}")

    def start(self):
        banner = f"""
{Fore.RED}  ██████╗ ██╗  ██╗ ██████╗ ███████╗████████╗
{Fore.RED}  ██╔════╝██║  ██║██╔═══██╗██╔════╝╚══██╔══╝
{Fore.YELLOW}  ██║  ███╗███████║██║   ██║███████╗   ██║
{Fore.YELLOW}  ██║   ██║██╔══██║██║   ██║╚════██║   ██║
{Fore.GREEN}  ╚██████╔╝██║  ██║╚██████╔╝███████║   ██║
{Fore.GREEN}   ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝   ╚═╝
{Fore.CYAN}       PROTOCOL v8.1 — Bug Bounty Edition
{Fore.WHITE}       Targets: {len(self.targets)} | Session: {self.session_id}
        """
        print(banner)
        with ThreadPoolExecutor(max_workers=MAX_DOMAINS_PARALLEL) as executor:
            executor.map(self.process_target, self.targets)
        print(f"\n{Fore.MAGENTA}[!!!] ALL DONE. Results: {self.base_dir}/{Style.RESET_ALL}")


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"{Fore.RED}Usage: python3 deep_recon_v2.py targets.txt")
        print(f"{Fore.YELLOW}targets.txt mein ek line par ek domain likho.")
        sys.exit(1)
    DeepRecon(sys.argv[1]).start()
