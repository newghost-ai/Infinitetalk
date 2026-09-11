# Single-stage build: runtime with ComfyUI + custom nodes
# Models are downloaded at startup (not baked into the image) to keep image small
# Base includes: CUDA 12.8.1, cuDNN, Python 3.12, PyTorch 2.8.0, torchvision, torchaudio
FROM runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404

SHELL ["/bin/bash", "-c"]
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# System packages (ffmpeg for video, git-lfs for model downloads, libgl1 for OpenCV)
RUN apt-get update --yes && \
    apt-get install --yes --no-install-recommends ffmpeg git-lfs libgl1 && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Python dependencies
# Keep the base PyTorch/CUDA stack untouched. Attention backends can fall back to PyTorch SDPA.
# The base image ships cryptography from Debian without pip RECORD metadata, so replace it first
# without attempting to uninstall the Debian-managed copy.
RUN pip install --no-cache-dir --ignore-installed cryptography && \
    pip install --no-cache-dir \
        misaki[en] "huggingface_hub[hf_transfer]" \
        runpod websocket-client librosa

WORKDIR /

# ComfyUI core
# Keep the frontend/runtime packages installed: current ComfyUI expects them at startup even for headless use.
RUN git clone https://github.com/comfyanonymous/ComfyUI.git && \
    cd /ComfyUI && \
    pip install --no-cache-dir -r requirements.txt

# Custom nodes (clone all, then install requirements)
RUN cd /ComfyUI/custom_nodes && \
    git clone https://github.com/city96/ComfyUI-GGUF && \
    git clone https://github.com/kijai/ComfyUI-KJNodes && \
    git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite && \
    git clone https://github.com/orssorbit/ComfyUI-wanBlockswap && \
    git clone https://github.com/kijai/ComfyUI-MelBandRoFormer && \
    git clone https://github.com/kijai/ComfyUI-WanVideoWrapper && \
    cd ComfyUI-GGUF && pip install --no-cache-dir -r requirements.txt && \
    cd ../ComfyUI-KJNodes && pip install --no-cache-dir -r requirements.txt && \
    cd ../ComfyUI-VideoHelperSuite && pip install --no-cache-dir -r requirements.txt && \
    cd ../ComfyUI-MelBandRoFormer && pip install --no-cache-dir -r requirements.txt && \
    cd ../ComfyUI-WanVideoWrapper && pip install --no-cache-dir -r requirements.txt && \
    find /ComfyUI -name ".git" -type d -exec rm -rf {} + 2>/dev/null || true && \
    find /ComfyUI -name "*.pyc" -delete 2>/dev/null || true && \
    find /ComfyUI -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# Handler files
COPY . .
RUN chmod +x /entrypoint.sh

ENV RUNPOD_PING_INTERVAL=3000
ENV RUNPOD_INIT_TIMEOUT=600

CMD ["/entrypoint.sh"]
