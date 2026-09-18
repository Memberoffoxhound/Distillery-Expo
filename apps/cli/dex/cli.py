"""dex CLI — demo, stages, routes, ingest."""

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
    print(
        f"Confirm flash: curl -X POST {base}/jobs/{data['id']}/flash/confirm "
        "-H 'Content-Type: application/json' -d '{\"confirm\":true}'"
    )
    return 0


def cmd_routes(args: argparse.Namespace) -> int:
    """List routes via API (preferred) or local ingest package."""
    base = args.api.rstrip("/")
    if not args.local:
        try:
            with httpx.Client(timeout=15.0) as client:
                r = client.get(f"{base}/routes", params={"source": args.source, "limit": args.limit})
                r.raise_for_status()
                data = r.json()
            print(json.dumps(data, indent=2))
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"warn: API unreachable ({exc}); using local ingest package", file=sys.stderr)

    from distillery_ingest import load_ingest_config
    from distillery_ingest.resolve import list_routes

    cfg = load_ingest_config()
    src, routes = list_routes(cfg, prefer=args.source, limit=args.limit)
    print(
        json.dumps(
            {
                "dongle_id": cfg.dongle_id,
                "source": src.name,
                "routes": [r.summary_dict() for r in routes],
            },
            indent=2,
        )
    )
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """Start ingest job via API, or run pipeline locally and print events."""
    base = args.api.rstrip("/")
    if not args.local:
        body: dict = {"source": args.source}
        if args.route:
            body["route_id"] = args.route
        try:
            with httpx.Client(timeout=15.0) as client:
                r = client.post(f"{base}/jobs/ingest", json=body)
                r.raise_for_status()
                data = r.json()
            print(json.dumps(data, indent=2))
            host = base.replace("http://", "").replace("https://", "")
            print(f"\nWebSocket: ws://{host}/ws/jobs/{data['id']}")
            print(f"Events:    {base}/jobs/{data['id']}/events")
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"warn: API unreachable ({exc}); running local ingest", file=sys.stderr)

    import asyncio

    from distillery_ingest import load_ingest_config, run_ingest_pipeline

    events: list[dict] = []

    async def emit(ev: dict) -> None:
        events.append(ev)
        kind = ev.get("kind")
        payload = ev.get("payload") or {}
        if kind == "sample":
            print(f"  sample cam={payload.get('cam')} label={payload.get('label')}")
        elif kind == "stage":
            print(f"  stage {payload.get('name')} → {payload.get('status')}")
        elif kind == "progress":
            print(f"  progress {payload.get('fraction'):.0%} {payload.get('detail') or ''}")
        elif kind == "log":
            print(f"  [{payload.get('level')}] {payload.get('message')}")

    cfg = load_ingest_config()

    async def _run() -> None:
        await run_ingest_pipeline(
            "local-cli",
            emit,
            route_id=args.route,
            prefer=args.source,
            cfg=cfg,
            tick=0.05,
        )

    asyncio.run(_run())
    print(f"\n{len(events)} events emitted (local)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dex", description="Distillery Expo engine CLI")
    parser.add_argument("--api", default=DEFAULT_API, help="API base URL")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_demo = sub.add_parser("demo", help="Start a demo pipeline job")
    p_demo.set_defaults(func=cmd_demo)

    p_stages = sub.add_parser("stages", help="List pipeline stages")
    p_stages.set_defaults(func=cmd_stages)

    p_routes = sub.add_parser("routes", help="List mici routes (Connect/SSH/fixture)")
    p_routes.add_argument(
        "--source",
        choices=["auto", "connect", "ssh", "fixture"],
        default="auto",
        help="Route source preference",
    )
    p_routes.add_argument("--limit", type=int, default=20)
    p_routes.add_argument(
        "--local",
        action="store_true",
        help="Skip API; use ingest package directly",
    )
    p_routes.set_defaults(func=cmd_routes)

    p_ingest = sub.add_parser("ingest", help="Start ingest job (or local run)")
    p_ingest.add_argument("--route", default=None, help="Route id (dongle|date--time)")
    p_ingest.add_argument(
        "--source",
        choices=["auto", "connect", "ssh", "fixture"],
        default="auto",
    )
    p_ingest.add_argument(
        "--local",
        action="store_true",
        help="Skip API; emit events to stdout",
    )
    p_ingest.set_defaults(func=cmd_ingest)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
