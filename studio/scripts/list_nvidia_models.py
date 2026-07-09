from __future__ import annotations

import json
import os
import urllib.request

key = os.environ.get("NVIDIA_API_KEY") or os.environ.get("NVAPI_KEY")
if not key:
    raise SystemExit("No NVIDIA API key in environment")

request = urllib.request.Request(
    "https://integrate.api.nvidia.com/v1/models",
    headers={"Authorization": f"Bearer {key}"},
)
with urllib.request.urlopen(request, timeout=30) as response:
    data = json.loads(response.read().decode())

ids = [entry["id"] for entry in data.get("data", [])]
needles = ["nemotron", "llama-3.3", "mistral", "qwen", "deepseek", "gemma", "dracarys"]
for needle in needles:
    print(f"== {needle}")
    for model_id in ids:
        if needle in model_id.lower():
            print(model_id)
