#!/usr/bin/env python3
"""Per-tracker seeding limits for qBittorrent."""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse

import qbittorrentapi
import yaml


@dataclass
class Policy:
    """Policy thresholds and actions."""

    ratio: float
    seeding_minutes: int
    idle_minutes: int
    action: str = "pause"
    include_tags: List[str] = field(default_factory=list)
    exclude_tags: List[str] = field(default_factory=list)


@dataclass
class Config:
    qbittorrent: Dict[str, object]
    default_policy: Policy
    tracker_policies: Dict[str, Policy]
    interval_seconds: int
    dry_run: bool
    log_level: str = "INFO"

    @staticmethod
    def from_dict(data: Dict[str, object]) -> "Config":
        qbt = data.get("qbittorrent", {})
        policy = data.get("policy", {})
        default_policy = Policy(**policy.get("default", {}))
        trackers: Dict[str, Policy] = {
            host: Policy(**{**policy.get("default", {}), **cfg})
            for host, cfg in policy.get("trackers", {}).items()
        }
        runtime = data.get("runtime", {})
        return Config(
            qbittorrent=qbt,
            default_policy=default_policy,
            tracker_policies=trackers,
            interval_seconds=int(runtime.get("interval_seconds", 60)),
            dry_run=bool(runtime.get("dry_run", True)),
            log_level=str(runtime.get("log_level", "INFO")),
        )


def load_config(path: str) -> Config:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Config.from_dict(raw)


def normalize_tracker(url: str) -> Optional[str]:
    if not url:
        return None
    parsed = urlparse(url)
    return parsed.hostname


def match_tags(torrent_tags: Iterable[str], policy: Policy) -> bool:
    torrent_tags = set(tag.strip() for tag in torrent_tags if tag)
    if policy.include_tags and not torrent_tags.intersection(policy.include_tags):
        return False
    if policy.exclude_tags and torrent_tags.intersection(policy.exclude_tags):
        return False
    return True


def get_tracker_host(client: qbittorrentapi.Client, torrent_hash: str) -> Optional[str]:
    try:
        trackers = client.torrents_trackers(torrent_hash)
    except qbittorrentapi.APIError:
        return None
    for tr in trackers:
        host = normalize_tracker(tr.get("url"))
        if host:
            return host
    return None


class Sentinel:
    def __init__(self, cfg: Config, once: bool = False, dry_run_override: bool = False) -> None:
        self.cfg = cfg
        self.once = once
        self.dry_run = dry_run_override or cfg.dry_run
        self.state: Dict[str, Dict[str, float]] = {}
        client_params = dict(cfg.qbittorrent)
        if "verify_ssl" in client_params:
            client_params["VERIFY_WEBUI_CERTIFICATE"] = client_params.pop("verify_ssl")
        if "timeout" in client_params:
            client_params["REQUESTS_ARGS"] = {"timeout": client_params.pop("timeout")}
        self.client = qbittorrentapi.Client(**client_params)

    def run(self) -> None:
        while True:
            try:
                self._cycle()
            except qbittorrentapi.LoginFailed as exc:
                logging.error("Login failed: %s", exc)
                return
            except qbittorrentapi.APIConnectionError as exc:
                logging.error("Connection error: %s", exc)
                return
            if self.once:
                break
            time.sleep(self.cfg.interval_seconds)

    def _cycle(self) -> None:
        torrents = self.client.torrents_info(filter="seeding")
        now = time.time()
        for t in torrents:
            tracker_host = get_tracker_host(self.client, t.hash)
            policy = self.cfg.tracker_policies.get(tracker_host, self.cfg.default_policy)
            if not match_tags(t.tags.split(",") if t.tags else [], policy):
                continue

            reasons: List[str] = []
            if policy.ratio and t.ratio >= policy.ratio:
                reasons.append("ratio")
            if policy.seeding_minutes and t.seeding_time // 60 >= policy.seeding_minutes:
                reasons.append("seeding_time")

            st = self.state.setdefault(t.hash, {"uploaded": t.uploaded, "last_up": now})
            if t.uploaded > st["uploaded"]:
                st["uploaded"] = t.uploaded
                st["last_up"] = now
            elif policy.idle_minutes and t.upspeed == 0 and (now - st["last_up"]) / 60 >= policy.idle_minutes:
                reasons.append("idle")

            if reasons:
                self._apply_action(t, tracker_host, policy.action, reasons)

    def _apply_action(self, torrent, tracker_host: Optional[str], action: str, reasons: List[str]) -> None:
        action = action.lower()
        msg = f"{action.upper()} | {torrent.hash} | {torrent.name} | {tracker_host or '-'} | {','.join(reasons)}"
        if self.dry_run:
            logging.info("DRY-RUN: %s", msg)
            return
        if action == "pause":
            self.client.torrents_pause(torrent_hashes=torrent.hash)
        elif action == "remove":
            self.client.torrents_delete(torrent_hashes=torrent.hash)
        elif action == "remove_data":
            self.client.torrents_delete(delete_files=True, torrent_hashes=torrent.hash)
        logging.info(msg)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="qb-tracker-sentinel")
    parser.add_argument("--config", required=True, help="Path to config.yaml")
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="Force dry run")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    logging.basicConfig(level=getattr(logging, cfg.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s: %(message)s")
    sentinel = Sentinel(cfg, once=args.once, dry_run_override=args.dry_run)
    sentinel.run()


if __name__ == "__main__":
    main()
