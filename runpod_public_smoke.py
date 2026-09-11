#!/usr/bin/env python3
import json
import os
import sys

import requests

ENDPOINT = "https://api.runpod.ai/v2/infinitetalk/runsync?wait=300000"
IMAGE_URL = "https://raw.githubusercontent.com/newghost-ai/Infinitetalk/main/test_assets/elle%26lui%20cuisine_first_frame.png"
AUDIO_URL = "https://raw.githubusercontent.com/newghost-ai/Infinitetalk/main/test_assets/lead_voice_4s.wav"
PROMPT = (
    "Two people in a static kitchen. Only the man sings naturally with accurate lip sync, "
    "subtle head movement and very small hand gestures. The woman remains silent and natural, "
    "mouth closed, with only subtle blinking and tiny posture reactions. Camera fixed. "
    "Background and objects remain completely static."
)


def main() -> None:
    api_key = os.environ.get("RUNPOD_API_KEY")
    if not api_key:
        raise SystemExit("Missing RUNPOD_API_KEY environment variable")

    payload = {
        "input": {
            "prompt": PROMPT,
            "image": IMAGE_URL,
            "audio": AUDIO_URL,
            "size": "480p",
            "enable_safety_checker": True,
        }
    }

    print("Submitting RunPod public InfiniteTalk test...", flush=True)
    response = requests.post(
        ENDPOINT,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=(20, 330),
    )

    if not response.ok:
        print(response.text)
        response.raise_for_status()

    result = response.json()
    print(json.dumps(result, indent=2))

    if result.get("status") != "COMPLETED":
        raise SystemExit(1)

    output = result.get("output") or {}
    print("\nvideo_url:", output.get("video_url"))
    print("cost_usd:", output.get("cost"))


if __name__ == "__main__":
    main()
