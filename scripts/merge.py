#!/usr/bin/env python3
"""Merge and curate public M3U playlists. No bandwidth testing is performed.

stdlib only; designed to run in a free GitHub Actions runner every six hours.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
SOURCES = ROOT / "sources.json"
USER_AGENT = "iptv-merge/1.0 (public M3U aggregator; github.com/Scluzlep/iptv-merge)"
ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
NAME_QUALITY_RE = re.compile(r'\s*[\[(（](?:\d{3,4}p|hd|sd|fhd|uhd|geo.blocked|\d+fps)[\])）]', re.I)
RESOLUTION_RE = re.compile(r'\s*(?:\d{3,4}p|[24]k|fhd|uhd|hd|sd|超清|高清|标清)\s*$', re.I)
MAX_ITEMS = 80000
MAX_BYTES = 35 * 1024 * 1024
# A backup cap avoids hundreds of endpoints for the same channel, but retains choice.
CAPS = {"china": 8, "global": 4, "loop": 6}
OUTPUTS = ("all", "china", "global", "loop", "ipv4", "ipv6")


@dataclass(frozen=True)
class Entry:
    name: str
    url: str
    meta: str
    source: str
    scope: str
    priority: int
    group: str
    ident: str


def fetch_source(source: dict) -> tuple[dict, str, str]:
    """Return source, content, error. Do not fetch streams."""
    try:
        req = Request(source["url"], headers={"User-Agent": USER_AGENT, "Accept": "text/plain,*/*"})
        with urlopen(req, timeout=23) as resp:
            data = resp.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("playlist exceeds source size limit")
        content = data.decode("utf-8-sig", errors="replace")
        if "#EXTINF:" not in content:
            raise ValueError("no #EXTINF channel records")
        return source, content, ""
    except (TimeoutError, HTTPError, URLError, OSError, ValueError) as exc:
        return source, "", f"{type(exc).__name__}: {exc}"


def classify_url(url: str) -> tuple[bool, str]:
    """Return (is_public_http_url, explicit_ip_family_or_domain)."""
    if not url or len(url) > 4096 or any(ord(ch) < 32 for ch in url):
        return False, ""
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in ("https", "http") or not parsed.hostname:
            return False, ""
        if parsed.username or parsed.password or (parsed.port is not None and parsed.port == 0):
            return False, ""
        hostname = parsed.hostname.lower().rstrip(".")
        if hostname == "localhost" or hostname.endswith((".local", ".localhost", ".internal")):
            return False, ""
        try:
            ip = ipaddress.ip_address(hostname)
            return (ip.is_global, "v6" if ip.version == 6 else "v4")
        except ValueError:
            if "." not in hostname or not re.fullmatch(r"[a-z0-9._-]+", hostname):
                return False, ""
            return True, "dns"
    except (ValueError, UnicodeError):
        return False, ""


def parse_m3u(content: str, source: dict) -> list[Entry]:
    entries: list[Entry] = []
    meta: str | None = None
    pending_opts: list[str] = []
    for raw in content.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if line.startswith("#EXTINF:"):
            meta = line
            pending_opts = []
        elif line.startswith(("#EXTVLCOPT:", "#KODIPROP:")) and meta:
            # Preserve common player request headers when present.
            if len(pending_opts) < 4:
                pending_opts.append(line)
        elif line and not line.startswith("#"):
            if meta:
                url = line.strip()
                valid, _ = classify_url(url)
                if valid:
                    prefix, sep, displayed = meta.partition(",")
                    attrs = dict(ATTR_RE.findall(prefix))
                    name = (displayed if sep else attrs.get("tvg-name", "")).strip()
                    if not name:
                        name = attrs.get("tvg-name", "").strip()
                    if name and len(name) <= 140:
                        name = NAME_QUALITY_RE.sub("", name).strip()
                        entries.append(Entry(name, url, meta + "\n" + "\n".join(pending_opts) if pending_opts else meta,
                                             source["name"], source["scope"], int(source.get("priority", 50)),
                                             attrs.get("group-title", "").strip(), attrs.get("tvg-id", "").strip()))
            meta = None
            pending_opts = []
            if len(entries) >= MAX_ITEMS:
                break
    return entries


def channel_key(entry: Entry) -> str:
    name = unicodedata.normalize("NFKC", entry.name).lower()
    name = NAME_QUALITY_RE.sub("", name).strip()
    name = RESOLUTION_RE.sub("", name).strip()
    name = re.sub(r"[\s·•_—–-]+", "", name)
    cctv = re.match(r"^cctv0?(\d{1,2})(\+)?", name)
    if cctv and not name.startswith(("cctv4k", "cctv8k")):
        return "cctv" + str(int(cctv.group(1))) + (cctv.group(2) or "")
    return re.sub(r"[^\w\u4e00-\u9fff+]", "", name) or entry.url


def region_scope(entry: Entry) -> str:
    if entry.scope != "global":
        return entry.scope
    country = entry.ident.lower().rsplit(".", 1)[-1].split("@", 1)[0]
    return "china" if country == "cn" else "global"


def group_for(entry: Entry, scope: str) -> str:
    if scope == "loop":
        return "轮播 / FAST · " + (entry.group or "影视动漫")
    if scope == "global":
        return "国际 · " + (entry.group or "电视")
    origin = entry.group or "国内其他"
    return "国内 · " + origin


def as_line(entry: Entry, scope: str) -> str:
    prefix, _, _ = entry.meta.partition(",")
    # Remove any source group; set consistent output classification.
    prefix = re.sub(r'\s*group-title="[^"]*"', "", prefix)
    group = group_for(entry, scope).replace('"', "'")
    title = entry.name.replace("\r", "").replace("\n", "").replace('"', "'")
    opts = entry.meta.split("\n")[1:]
    lines = [f'{prefix} group-title="{group}",{title}', *opts, entry.url]
    return "\n".join(lines) + "\n"


def family_for_hosts(hosts: set[str]) -> dict[str, set[str]]:
    """DNS record family lookup, not a playback/connectivity test.

    Unresolved domain streams remain in thematic playlists but are not labeled IPv4/6.
    """
    def resolve(host: str) -> tuple[str, set[str]]:
        try:
            info = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
            return host, {"v6" if row[0] == socket.AF_INET6 else "v4" for row in info
                          if row[0] in (socket.AF_INET, socket.AF_INET6)}
        except (socket.gaierror, OSError):
            return host, set()
    result = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
        for host, families in pool.map(resolve, sorted(hosts)):
            result[host] = families
    return result


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))
    for src in sources:
        if src["scope"] not in CAPS or not src["url"].startswith("https://"):
            raise ValueError(f"Invalid source: {src}")
    fetched = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for item in pool.map(fetch_source, sources):
            fetched.append(item)

    candidates: list[Entry] = []
    source_stats: list[dict] = []
    for source, content, err in fetched:
        records = parse_m3u(content, source) if content else []
        source_stats.append({"name": source["name"], "entries": len(records), "ok": bool(records), "error": err})
        print(f"{source['name']}: {len(records)} entries" + (f" ({err})" if err else ""), flush=True)
        candidates.extend(records)

    if len([s for s in source_stats if s["ok"]]) < 2 or len(candidates) < 200:
        raise RuntimeError("Not enough sources/entries; refusing to overwrite a previous release")

    # Rank source quality and down-rank URL credentials that often expire.
    def rank(entry: Entry) -> tuple[int, int, str]:
        penalized = bool(re.search(r"(?:[?&](?:authinfo|token|expires|sign|signature|key)=)", entry.url, re.I))
        return (entry.priority - (12 if penalized else 0), 1 if entry.url.startswith("https:") else 0, entry.url)

    # Deduplicate same stream across providers in a category, then cap backups by channel.
    # Global index contains some CN channels, and those are moved to china.
    ordered = sorted(candidates, key=lambda x: (-rank(x)[0], -rank(x)[1], rank(x)[2], x.source))
    buckets: dict[str, list[Entry]] = {k: [] for k in CAPS}
    counts: Counter[tuple[str, str]] = Counter()
    seen: set[tuple[str, str, str]] = set()
    discarded = Counter()
    for entry in ordered:
        scope = region_scope(entry)
        key = channel_key(entry)
        identity = (scope, key, entry.url)
        if identity in seen:
            discarded["duplicate"] += 1
            continue
        seen.add(identity)
        if counts[(scope, key)] >= CAPS[scope]:
            discarded["backup_cap"] += 1
            continue
        counts[(scope, key)] += 1
        buckets[scope].append(entry)

    # When two sources use the same live URL, avoid duplicate rows in all.m3u.
    all_entries: list[tuple[Entry, str]] = []
    all_seen: set[tuple[str, str]] = set()
    for scope in ("china", "loop", "global"):
        for entry in buckets[scope]:
            identity = (channel_key(entry), entry.url)
            if identity not in all_seen:
                all_entries.append((entry, scope))
                all_seen.add(identity)

    # The global playlist should also include FAST thematic channels.
    global_entries = list(buckets["global"]) + list(buckets["loop"])

    hostname_set: set[str] = set()
    for entry, _ in all_entries:
        valid, family = classify_url(entry.url)
        if valid and family == "dns":
            hostname_set.add(urlsplit(entry.url).hostname.lower().rstrip("."))
    dns_map = family_for_hosts(hostname_set)
    file_entries: dict[str, list[tuple[Entry, str]]] = {
        "all": all_entries,
        "china": [(x, "china") for x in buckets["china"]],
        "global": [(x, "global") for x in global_entries],
        "loop": [(x, "loop") for x in buckets["loop"]],
        "ipv4": [], "ipv6": [],
    }
    for entry, scope in all_entries:
        valid, fam = classify_url(entry.url)
        if not valid:
            continue
        families = ({fam} if fam != "dns" else dns_map.get(urlsplit(entry.url).hostname.lower().rstrip("."), set()))
        if "v4" in families:
            file_entries["ipv4"].append((entry, scope))
        if "v6" in families:
            file_entries["ipv6"].append((entry, scope))

    summary = {}
    for filename, items in file_entries.items():
        # Mix categories with stable ordering, keeping highest-ranked channels first.
        entries = sorted(items, key=lambda pair: ( {"china": 0, "loop": 1, "global": 2}[pair[1]],
                                                   channel_key(pair[0]), -pair[0].priority, pair[0].url))
        content = "#EXTM3U\n" + "".join(as_line(e, scope) for e, scope in entries)
        (OUTPUT / (filename + ".m3u")).write_text(content, encoding="utf-8")
        summary[filename] = len(entries)
        print(f"output/{filename}.m3u: {len(entries)}", flush=True)

    # Protect against catastrophic drop caused by temporary upstream outages.
    # GitHub Actions checks out previous output, but we already generated new files;
    # CI must avoid commits/releases if global data disappears (there are at least 2 sources).
    previous = ROOT / ".previous_count.json"
    if previous.exists():
        try:
            previous_all = int(json.loads(previous.read_text()).get("all", 0))
            if previous_all >= 200 and summary["all"] < previous_all * 0.45:
                raise RuntimeError(f"Channel count collapsed {previous_all} -> {summary['all']}; publication cancelled")
        except (ValueError, json.JSONDecodeError):
            pass

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    report = {
        "generated_at_utc": now,
        "validation": "URL format and public address checks; backup ranking; URL dedup; DNS-family lookup. No bandwidth/stream tests.",
        "count": summary,
        "candidates": len(candidates),
        "discarded": dict(discarded),
        "sources": source_stats,
    }
    (OUTPUT / "stats.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "release-notes.md").write_text(
        "## IPTV 聚合订阅（滚动更新）\n\n"
        f"更新时间（UTC）：`{now}`\n\n"
        + "\n".join(f"- **{key}.m3u**：{value:,} 条线路" for key, value in summary.items())
        + "\n\n> 仅执行格式、地址和 DNS 校验，**不代表线路已测速或可播放**。"
        "部分台源有地区、运营商、时效限制。\n",
        encoding="utf-8",
    )
    (ROOT / ".previous_count.json").write_text(json.dumps(summary), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
