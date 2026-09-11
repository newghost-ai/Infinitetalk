#!/usr/bin/env python3
import argparse
import json
import mimetypes
import os
import tempfile
import time
import wave
from pathlib import Path
from urllib.parse import urlparse

import requests

API_BASE = "https://api.wavespeed.ai/api/v3"
MODEL_ID = "wavespeed-ai/infinitetalk-fast/multi"
DEFAULT_PROMPT = (
    "Two people in a static kitchen. Only the singing person performs naturally with accurate lip sync, "
    "subtle head movement and very small hand gestures. The other person remains silent and natural, "
    "mouth closed, with only subtle blinking and tiny posture reactions. "
    "The shot must remain completely fixed from the first frame to the last frame. Locked-off tripod camera. "
    "Keep exactly the same framing, composition, camera position, camera angle, focal length, perspective and crop for the entire video. "
    "Absolutely no camera movement or reframing: no pan, no tilt, no zoom, no push-in, no pull-out, no dolly, no orbit, no handheld motion, no shake and no crop change. "
    "The environment, furniture, table, lighting and all background objects remain completely static and unchanged. "
    "No objects appear, disappear, move, transform or pop into the scene. "
    "Nothing appears in either person's hands and no new props are introduced."
)


def auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        frame_rate = wav.getframerate()
        if frame_rate <= 0:
            raise ValueError(f"Invalid WAV sample rate: {frame_rate}")
        return wav.getnframes() / frame_rate


def create_silence_wav(path: Path, duration_s: float, sample_rate: int = 16000) -> None:
    frame_count = int(round(duration_s * sample_rate))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * frame_count)


def upload_file(api_key: str, path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)

    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    payload = {
        "filename": path.name,
        "size": path.stat().st_size,
        "content_type": content_type,
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


def resolve_input(api_key: str, value: str, label: str) -> str:
    if is_url(value):
        return value

    path = Path(value).expanduser()
    print(f"Uploading {label}: {path}", flush=True)
    return upload_file(api_key, path)


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
    parser = argparse.ArgumentParser(description="Elle&Lui WaveSpeed InfiniteTalk generation")
    parser.add_argument("--singer-side", choices=("left", "right"), required=True,
                        help="Side of the singing character as seen on screen")
    parser.add_argument("--image", required=True,
                        help="Local image path or public image URL")
    parser.add_argument("--audio", required=True,
                        help="Local WAV path or public audio URL")
    parser.add_argument("--duration", type=float,
                        help="Only needed when --audio is a URL and duration cannot be detected locally")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--seed", type=int, default=2)
    args = parser.parse_args()

    api_key = os.environ.get("WAVESPEED_API_KEY")
    if not api_key:
        raise SystemExit("Missing WAVESPEED_API_KEY environment variable")

    if is_url(args.audio):
        if args.duration is None:
            raise SystemExit("When --audio is a URL, also provide --duration in seconds")
        duration_s = args.duration
    else:
        audio_path = Path(args.audio).expanduser()
        if not audio_path.is_file():
            raise SystemExit(f"Audio file not found: {audio_path}")
        duration_s = wav_duration(audio_path)

    if not is_url(args.image) and not Path(args.image).expanduser().is_file():
        raise SystemExit(f"Image file not found: {Path(args.image).expanduser()}")

    print(f"Detected audio duration: {duration_s:.3f}s", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        silence_path = Path(tmp) / "silent_character.wav"
        create_silence_wav(silence_path, duration_s)

        image_url = resolve_input(api_key, args.image, "image")
        singer_audio_url = resolve_input(api_key, args.audio, "singer audio")
        print("Uploading silent track...", flush=True)
        silence_url = upload_file(api_key, silence_path)

        if args.singer_side == "left":
            left_audio, right_audio = singer_audio_url, silence_url
        else:
            left_audio, right_audio = silence_url, singer_audio_url

        payload = {
            "image": image_url,
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
