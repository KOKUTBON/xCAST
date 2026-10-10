"""Command-line interface (tic) for Thinking in Code (Podcastify)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from podcastify_contracts.podcast_job import ScriptReviewAction

from podcastify_client.client import ClientError, ThinkingInCodeClient


def _format_json(data: Any) -> str:
    return json.dumps(data, indent=2)


def cmd_submit(args: argparse.Namespace, client: ThinkingInCodeClient) -> int:
    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"Error: file not found: {pdf_path}", file=sys.stderr)
        return 1

    try:
        res = client.submit_job(
            pdf_path=pdf_path,
            language=args.language,
            style=args.style,
            target_minutes=args.minutes,
            pause_at_script=args.pause_at_script,
            job_id=args.job_id,
        )
    except ClientError as exc:
        print(f"Error submitting job: {exc}", file=sys.stderr)
        return 1

    job_id = res.get("job_id")
    status = res.get("status")
    print("Job submitted successfully!")
    print(f"  Job ID : {job_id}")
    print(f"  Status : {status}")

    if args.wait:
        print(f"Waiting for job {job_id} to finish...")
        try:
            for event in client.stream_progress(job_id):
                st = event.get("status")
                stage = event.get("stage")
                detail = event.get("detail", "")
                print(f"[{st.upper()}] stage: {stage or 'n/a'} {f'- {detail}' if detail else ''}")
                if st in {"succeeded", "failed", "awaiting_review"}:
                    break
        except KeyboardInterrupt:
            print("\nWatch interrupted by user.")
            return 130
        except Exception as exc:
            print(f"Progress stream ended: {exc}")

        if args.download:
            try:
                artifacts = client.list_artifacts(job_id)
                for art in artifacts:
                    name = art["name"]
                    if name.endswith(".mp3") or name == "podcast.mp3":
                        dest = client.download_artifact(job_id, name, args.download)
                        print(f"Downloaded audio artifact to: {dest}")
                        break
            except Exception as exc:
                print(f"Warning: could not download artifact: {exc}", file=sys.stderr)

    return 0


def cmd_status(args: argparse.Namespace, client: ThinkingInCodeClient) -> int:
    try:
        res = client.get_status(args.job_id)
    except ClientError as exc:
        print(f"Error fetching status: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(_format_json(res))
    else:
        print(f"Job ID: {res.get('job_id')}")
        print(f"Status: {res.get('status')}")
        print(f"Stage : {res.get('stage')}")
        if res.get("detail"):
            print(f"Detail: {res.get('detail')}")
        if res.get("updated_at"):
            print(f"Updated: {res.get('updated_at')}")
    return 0


def cmd_watch(args: argparse.Namespace, client: ThinkingInCodeClient) -> int:
    job_id = args.job_id
    print(f"Streaming progress events for job {job_id}...")
    try:
        for event in client.stream_progress(job_id):
            if args.json:
                print(json.dumps(event))
            else:
                st = event.get("status", "unknown")
                stage = event.get("stage", "n/a")
                detail = event.get("detail", "")
                print(f"[{st.upper()}] stage: {stage} {f'- {detail}' if detail else ''}")
                if st in {"succeeded", "failed", "awaiting_review"}:
                    print(f"Job reached terminal/pause state: {st}")
                    break
    except KeyboardInterrupt:
        print("\nStreaming interrupted by user.")
        return 130
    except ClientError as exc:
        print(f"Error during stream: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_script(args: argparse.Namespace, client: ThinkingInCodeClient) -> int:
    try:
        res = client.get_script(args.job_id)
    except ClientError as exc:
        print(f"Error fetching script: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(_format_json(res))
    elif args.raw:
        print(res.get("script_md", ""))
    else:
        print(f"=== Script for Job {args.job_id} (Status: {res.get('status')}) ===")
        segments = res.get("segments") or []
        for i, seg in enumerate(segments, 1):
            title = seg.get("title", "")
            spk = seg.get("speaker", "Speaker")
            text = seg.get("text", "")
            print(f"\n[{i}] {title} ({spk}):")
            print(f"    {text}")
    return 0


def cmd_review(args: argparse.Namespace, client: ThinkingInCodeClient) -> int:
    action = ScriptReviewAction(args.action.lower())
    segments = None
    if args.segments_file:
        file_path = Path(args.segments_file)
        if not file_path.exists():
            print(f"Error: segments file not found: {file_path}", file=sys.stderr)
            return 1
        try:
            segments = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"Error parsing segments JSON: {exc}", file=sys.stderr)
            return 1

    try:
        res = client.submit_review(
            job_id=args.job_id,
            action=action,
            segments=segments,
            notes=args.notes,
        )
    except ClientError as exc:
        print(f"Error submitting review: {exc}", file=sys.stderr)
        return 1

    print("Review submitted successfully:")
    print(f"  Job ID : {res.job_id}")
    print(f"  Status : {res.status.value}")
    print(f"  Message: {res.message}")
    return 0


def cmd_download(args: argparse.Namespace, client: ThinkingInCodeClient) -> int:
    try:
        out_path = client.download_artifact(
            job_id=args.job_id,
            artifact_name=args.artifact_name,
            output_path=args.output,
        )
        print(f"Artifact downloaded successfully to: {out_path}")
    except ClientError as exc:
        print(f"Error downloading artifact: {exc}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tic",
        description="Thinking in Code (Podcastify) CLI client.",
    )
    parser.add_argument("--url", default=None, help="Base URL of API (or TIC_API_URL env var)")
    parser.add_argument("--api-key", default=None, help="API key (or TIC_API_KEY env var)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # submit
    p_submit = subparsers.add_parser("submit", help="Submit a PDF to create a podcast episode")
    p_submit.add_argument("pdf_path", help="Path to local PDF file")
    p_submit.add_argument("--language", default="en", help="Language code (default: en)")
    p_submit.add_argument("--style", default="everyday", help="Tone/style (default: everyday)")
    p_submit.add_argument("--minutes", type=int, default=8, help="Target duration in minutes")
    p_submit.add_argument(
        "--pause-at-script",
        action="store_true",
        help="Pause job at script stage for human review",
    )
    p_submit.add_argument("--job-id", default=None, help="Custom job ID")
    p_submit.add_argument("--wait", action="store_true", help="Wait for job to finish")
    p_submit.add_argument(
        "--download",
        default=None,
        help="Download generated mp3 to specified directory when finished",
    )

    # status
    p_status = subparsers.add_parser("status", help="Get status of a job")
    p_status.add_argument("job_id", help="Job ID")
    p_status.add_argument("--json", action="store_true", help="Output raw JSON")

    # watch
    p_watch = subparsers.add_parser("watch", help="Watch progress events in real-time via SSE")
    p_watch.add_argument("job_id", help="Job ID")
    p_watch.add_argument("--json", action="store_true", help="Output raw JSON stream")

    # script
    p_script = subparsers.add_parser("script", help="Fetch generated script for a job")
    p_script.add_argument("job_id", help="Job ID")
    p_script.add_argument("--json", action="store_true", help="Output JSON segments")
    p_script.add_argument("--raw", action="store_true", help="Output raw markdown script")

    # review
    p_review = subparsers.add_parser("review", help="Approve or reject a script awaiting review")
    p_review.add_argument("job_id", help="Job ID")
    p_review.add_argument(
        "action", choices=["approve", "reject"], help="Review action (approve|reject)"
    )
    p_review.add_argument("--notes", default=None, help="Optional feedback or notes")
    p_review.add_argument(
        "--segments-file", default=None, help="Optional path to edited segments JSON file"
    )

    # download
    p_dl = subparsers.add_parser("download", help="Download an artifact from a completed job")
    p_dl.add_argument("job_id", help="Job ID")
    p_dl.add_argument("artifact_name", help="Name of the artifact (e.g. podcast.mp3, script.md)")
    p_dl.add_argument(
        "--output", "-o", default=".", help="Destination path or directory (default: current dir)"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    client = ThinkingInCodeClient(base_url=args.url, api_key=args.api_key)
    try:
        if args.command == "submit":
            return cmd_submit(args, client)
        if args.command == "status":
            return cmd_status(args, client)
        if args.command == "watch":
            return cmd_watch(args, client)
        if args.command == "script":
            return cmd_script(args, client)
        if args.command == "review":
            return cmd_review(args, client)
        if args.command == "download":
            return cmd_download(args, client)
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
