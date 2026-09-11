#!/usr/bin/env python3
import argparse
import json
import os
import tempfile
import time
import wave
from pathlib import Path

import requests

API_BASE = "https://api.wavespeed.ai/api/v3"
MODEL_ID = "wavespeed-ai/infinitetalk-fast/multi"
DEFAULT_IMAGE = "https://raw.githubusercontent.com/newghost-ai/Infinitetalk/main/test_assets/elle%26lui%20cuisine_first_frame.png"
DEFAULT_AUDIO = "https://raw.githubusercontent.com/newghost-ai/Infinitetalk/main/test_assets/lead_voice_4s.wav"
DEFAULT_PROMPT = (
    "Two people in a static kitchen. Only the singing person performs naturally with accurate lip sync, "
    "subtle head movement and very small hand gestures. The other person remains silent and natural, "
    "mouth closed, with only subtle blinking and tiny posture reactions. Camera fixed. "
    "Background and objects remain completely static."
)


def auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def create_silence_wav(path: Path, duration_s: float, sample_rate: int = 16000) -> None:
    frame_count = int(duration_s * sample_rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * frame_count)


def upload_file(api_key: str, path: Path) -> str:
    payload = {
        "filename": path.name,
        "size": path.stat().st_size,
        "content_type": "audio/wav",
    }
    ticket_response = requests.post(
        f"{API_BASE}/media/uploads",
        headers={**auth_headers(api_key), "Content-Type": "application/json"},
        json=payload,
        timeout=(10, 30),
    )
    ticket_response.raise_for_status()
    body = ticket_response.json()
    if body.get("code") != 200:
        raise RuntimeError(body.get("message", "WaveSpeed upload ticket failed"))

    ticket = body["data"]
    with path.open("rb") as file:
        upload_response = requests.put(
            ticket["upload"]["url"],
            headers=ticket["upload"]["headers"],
            data=file,
            timeout=(10, 300),
        )
    upload_response.raise_for_status()
    return ticket["download_url"]


def submit(api_key: str, payload: dict) -> dict:
    response = requests.post(
        f"{API_BASE}/{MODEL_ID}",
        headers={**auth_headers(api_key), "Content-Type": "application/json"},
        json=payload,
        timeout=(10, 60),
    )
    response.raise_for_status()
    body = response.json()
    if body.get("code") != 200:
        raise RuntimeError(body.get("message", "WaveSpeed submission failed"))
    return body["data"]


def poll(api_key: str, task: dict, timeout_s: int = 1800) -> dict:
    task_id = task["id"]
    result_url = task.get("urls", {}).get("get") or f"{API_BASE}/predictions/{task_id}/result"
    failure_statuses = {"failed", "cancelled", "timeout", "deleted"}
    deadline = time.monotonic() + timeout_s
    interval = 2.0

    while time.monotonic() < deadline:
        response = requests.get(
            result_url,
            headers=auth_headers(api_key),
            timeout=(10, 30),
        )
        response.raise_for_status()
        body = response.json()
        if body.get("code") != 200:
            raise RuntimeError(body.get("message", "WaveSpeed result query failed"))

        result = body["data"]
        status = result.get("status")
        print(f"status={status}", flush=True)
        if status == "completed":
            return result
        if status in failure_statuses:
            raise RuntimeError(result.get("error") or f"WaveSpeed task ended with {status}")

        time.sleep(interval)
        interval = min(10.0, interval + 1.0)

    raise TimeoutError(f"Timed out waiting for WaveSpeed task {task_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Elle&Lui WaveSpeed InfiniteTalk smoke test")
    parser.add_argument("--singer-side", choices=("left", "right"), required=True,
                        help="Side of LUI in the input image")
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--audio", default=DEFAULT_AUDIO)
    parser.add_argument("--duration", type=float, default=4.0,
                        help="Silence duration for the non-singing character")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--seed", type=int, default=2)
    args = parser.parse_args()

    api_key = os.environ.get("WAVESPEED_API_KEY")
    if not api_key:
        raise SystemExit("Missing WAVESPEED_API_KEY environment variable")

    with tempfile.TemporaryDirectory() as tmp:
        silence_path = Path(tmp) / "silent_character.wav"
        create_silence_wav(silence_path, args.duration)
        print("Uploading silent track...", flush=True)
        silence_url = upload_file(api_key, silence_path)

        if args.singer_side == "left":
            left_audio, right_audio = args.audio, silence_url
        else:
            left_audio, right_audio = silence_url, args.audio

        payload = {
            "image": args.image,
            "left_audio": left_audio,
            "right_audio": right_audio,
            "order": "meanwhile",
            "prompt": args.prompt,
            "seed": args.seed,
        }

        print("Submitting WaveSpeed InfiniteTalk Fast Multi...", flush=True)
        task = submit(api_key, payload)
        print(f"prediction_id={task['id']}", flush=True)
        result = poll(api_key, task)
        print(json.dumps({
            "id": result.get("id"),
            "status": result.get("status"),
            "outputs": result.get("outputs", []),
            "timings": result.get("timings", {}),
        }, indent=2))


if __name__ == "__main__":
    main()
