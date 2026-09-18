"""dex CLI — demo + stages."""

from __future__ import annotations

import argparse
import json
import sys

import httpx

DEFAULT_API = "http://127.0.0.1:8000"


def cmd_stages(_: argparse.Namespace) -> int:
    stages = ["ingest", "shard", "teach", "train", "export", "eval", "flash"]
    print("Distillery Expo pipeline stages:")
    for i, s in enumerate(stages, 1):
        gate = " (gated)" if s == "flash" else ""
        print(f"  {i}. {s}{gate}")
    print("\nDesign locks: no Chestnut · stock-modelV2 I/O student · flash always gated")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    base = args.api.rstrip("/")
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.post(f"{base}/jobs/demo")
            r.raise_for_status()
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        print(f"error: could not reach API at {base}: {exc}", file=sys.stderr)
        print("hint: uvicorn apps.api.main:app --reload --port 8000", file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2))
    print(f"\nWebSocket: ws://{base.replace('http://','').replace('https://','')}/ws/jobs/{data['id']}")
    print(f"Confirm flash: curl -X POST {base}/jobs/{data['id']}/flash/confirm -H 'Content-Type: application/json' -d '{{\"confirm\":true}}'")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dex", description="Distillery Expo engine CLI")
    parser.add_argument("--api", default=DEFAULT_API, help="API base URL")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_demo = sub.add_parser("demo", help="Start a demo pipeline job")
    p_demo.set_defaults(func=cmd_demo)

    p_stages = sub.add_parser("stages", help="List pipeline stages")
    p_stages.set_defaults(func=cmd_stages)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
