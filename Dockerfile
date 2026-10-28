# CISA — imagen para Jetson con JetPack 7.2 (L4T R39.2, CUDA 13.2, Ubuntu 24.04)
# Mismas versiones que funcionan en venv_nx. El driver de la GPU y los plugins de
# video de NVIDIA (nvv4l2decoder) los monta Docker desde la Jetson (CDI).
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

ARG TRT=10.16.2.10-1+cuda13.2

# 1) Sistema: Python 3.12, OpenCV de Ubuntu (trae GStreamer; el de pip no),
#    GStreamer y TensorRT de JetPack 7.2, del mismo repositorio que usa la Jetson.
#    Va primero porque es lo que más probablemente falle, y así falla rápido.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSL https://repo.download.nvidia.com/jetson/jetson-ota-public.asc \
         -o /etc/apt/trusted.gpg.d/jetson-ota-public.asc \
    && echo "deb https://repo.download.nvidia.com/jetson/common r39.2 main" \
         > /etc/apt/sources.list.d/nvidia-l4t-apt-source.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-dev build-essential \
        python3-opencv \
        gstreamer1.0-tools gstreamer1.0-plugins-base \
        gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
        libgl1 libglib2.0-0 \
        python3-libnvinfer=${TRT} libnvinfer10=${TRT} \
        libnvinfer-plugin10=${TRT} libnvonnxparsers10=${TRT} \
    && rm -rf /var/lib/apt/lists/*

# 2) PyTorch para CUDA 13.2, del repositorio oficial (igual que en venv_nx)
RUN pip install --index-url https://download.pytorch.org/whl/cu132 \
        torch==2.14.1 torchvision==0.29.1

# 3) Resto de dependencias. Se quita el opencv-python que trae ultralytics
#    para que se use el de Ubuntu, que sí tiene GStreamer.
RUN pip install ultralytics==8.4.171 lap==0.5.13 flask==3.1.3 \
        python-dotenv==1.2.4 requests "numpy<2" \
    && (pip uninstall -y opencv-python opencv-python-headless || true)

# 4) Revisión: si OpenCV no trae GStreamer o TensorRT no es la versión esperada, se detiene
RUN python3 -c "import cv2, torch; \
ok = any('GStreamer' in l and 'YES' in l for l in cv2.getBuildInformation().splitlines()); \
print('OpenCV', cv2.__version__, '| GStreamer', ok, '| torch', torch.__version__); \
assert ok, 'OpenCV sin GStreamer'" \
    && dpkg -s python3-libnvinfer | grep -q "Version: ${TRT}" && echo "TensorRT ${TRT} OK"

# 5) FFmpeg para la grabación cada hora (servicio cisa-grabacion)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
CMD ["python3", "pipe_stream_v2.py"]
