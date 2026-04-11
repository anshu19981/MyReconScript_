# 🔥 Ghost Protocol v9.1 — DeepRecon

**Advanced Automated Reconnaissance Engine for Bug Bounty Hunters & Penetration Testers**

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Version](https://img.shields.io/badge/Version-8.1-red)

A powerful, fast, and feature-rich reconnaissance tool that performs deep passive + active recon on multiple targets with smart filtering, vulnerability hunting, and automated reporting.

### Why DeepRecon?
- DNS wildcard & dead subdomain filtering (dnsx)
- Non-standard port scanning (naabu)
- Historical endpoints discovery (gau + waybackurls)
- JS secret hunting + subdomain takeover checks
- 403 bypass attempts
- Advanced GF pattern matching (8 patterns)
- Nuclei + Katana crawling (depth 3)
- Discord webhook notifications for critical findings
- Resume capability (crash hone par bhi continue)
- Clean structured output with summary report

---

## ✨ Features

- **Multi-target support** with parallel scanning (safe for 16GB RAM)
- **Smart Subdomain Enumeration** (crt.sh + subfinder + assetfinder + amass)
- **DNS Resolution** with wildcard filtering using dnsx
- **Port Scanning** on 16+ common non-standard ports using naabu
- **Live Probing** with httpx (status, title, web server, CDN detection)
- **Historical URL Mining** using gau & waybackurls
- **Deep Crawling** with katana (depth = 3)
- **Vulnerability Scanning** with nuclei (critical + high severity)
- **JS Secret Extraction** using subjs
- **Subdomain Takeover** detection with subzy
- **CORS Misconfiguration** & **403 Bypass** module
- **GF Pattern Matching** (XSS, SSRF, SQLi, Open Redirect, LFI, RCE, IDOR, Debug Logic)
- **Screenshot Capture** using gowitness
- **Discord Alerts** for critical vulns & takeovers
- **Resume Support** + Detailed logging

---

## 🛠 Installation

```bash
git clone https://github.com/yourusername/DeepRecon.git
cd DeepRecon
pip install -r requirements.txt



Note: Script mostly uses external Go tools (subfinder, httpx, nuclei, etc.). Make sure they are installed and available in your $PATH.

Required Tools:

subfinder, assetfinder, amass, httpx, nuclei, katana, gowitness, gf, dnsx, naabu, gau

Optional Tools:

waybackurls, subjs, corsy, subzy
