"""SSH route source — list segments from mici realdata layout."""

from __future__ import annotations

import logging
import subprocess
from typing import Any

from distillery_ingest.config import IngestConfig
from distillery_ingest.models import RouteInfo, SegmentInfo
from distillery_ingest.sources.base import RouteSource

log = logging.getLogger(__name__)

REALDATA = "/data/media/0/realdata"
_CAM_FILES = {
    "fcamera.hevc": "road",
    "ecamera.hevc": "wide",
    "dcamera.hevc": "driver",
}


class SshRouteSource(RouteSource):
    name = "ssh"  # type: ignore[assignment]

    def __init__(self, cfg: IngestConfig) -> None:
        self.cfg = cfg

    def available(self) -> bool:
        return self.cfg.ssh_available

    def _ssh(self, remote_cmd: str, timeout: float = 20.0) -> str:
        host = self.cfg.ssh_host
        if not host:
            raise RuntimeError("MICI_SSH_HOST not set")
        target = f"{self.cfg.ssh_user}@{host}"
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]
        if self.cfg.ssh_key_path:
            cmd.extend(["-i", self.cfg.ssh_key_path])
        cmd.extend([target, remote_cmd])
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or f"ssh exit {proc.returncode}")
        return proc.stdout

    def list_routes(self, *, limit: int = 20) -> list[RouteInfo]:
        # Route dirs look like YYYY-MM-DD--HH-MM-SS--N or date folders
        out = self._ssh(f"ls -1 {REALDATA} 2>/dev/null | head -n {max(limit * 4, 40)}")
        names = [ln.strip() for ln in out.splitlines() if ln.strip()]
        routes: list[RouteInfo] = []
        seen: set[str] = set()
        for name in names:
            # Normalize to dongle|date--time stem
            stem = name.split("--")[0] + ("--" + name.split("--")[1] if "--" in name else "")
            # Prefer full folder name as route suffix
            suffix = name.rsplit("--", 1)[0] if name.count("--") >= 2 else name
            route_id = f"{self.cfg.dongle_id}|{suffix}"
            if route_id in seen:
                continue
            seen.add(route_id)
            routes.append(
                RouteInfo(
                    route_id=route_id,
                    dongle_id=self.cfg.dongle_id,
                    display_name=suffix,
                    source="ssh",
                    segment_count=0,
                    segments=[],
                    meta={"fixture": False, "label": "ssh", "ssh_path": f"{REALDATA}/{name}"},
                )
            )
            if len(routes) >= limit:
                break
        return routes

    def get_route(self, route_id: str) -> RouteInfo | None:
        suffix = route_id.split("|", 1)[-1]
        # List segment indices under matching dirs
        listing = self._ssh(
            f"ls -d {REALDATA}/{suffix}* 2>/dev/null | head -n 40"
        )
        paths = [ln.strip() for ln in listing.splitlines() if ln.strip()]
        if not paths:
            return None
        segments: list[SegmentInfo] = []
        for i, p in enumerate(paths):
            files_out = self._ssh(f"ls -1 {p} 2>/dev/null")
            files = {ln.strip() for ln in files_out.splitlines() if ln.strip()}
            cams: dict[str, dict[str, Any]] = {}
            for fname, cam in _CAM_FILES.items():
                if cam not in self.cfg.cams:
                    continue
                if fname in files:
                    cams[cam] = {
                        "filename": fname,
                        "path": f"{p}/{fname}",
                        "codec": "hevc",
                        "fps": 20,
                        "exists": True,
                    }
            segments.append(
                SegmentInfo(
                    segment_id=f"{route_id}/{i}",
                    index=i,
                    duration_s=60.0,
                    cams=cams,
                    meta={"ssh_path": p},
                )
            )
        return RouteInfo(
            route_id=route_id,
            dongle_id=self.cfg.dongle_id,
            display_name=suffix,
            source="ssh",
            length_s=float(len(segments) * 60),
            segment_count=len(segments),
            segments=segments,
            meta={"fixture": False, "label": "ssh"},
        )
