FROM nvidia/cuda:12.8.1-devel-ubuntu24.04@sha256:520292dbb4f755fd360766059e62956e9379485d9e073bbd2f6e3c20c270ed66 AS build

ARG CUDA_ARCH
ARG LLAMA_CPP_COMMIT=c5a5535e6ebc2e74ab0e3f1b249d7d989aba26a2

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake libssl-dev patch \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
ADD --checksum=sha256:879362552ee71d8e5415f47644412458218b5246ffbe6ce91e01464b4c72e9a8 \
    https://github.com/ggml-org/llama.cpp/archive/${LLAMA_CPP_COMMIT}.tar.gz \
    /tmp/llama-cpp.tar.gz
RUN tar -xzf /tmp/llama-cpp.tar.gz --strip-components=1

COPY qwen-video-format.patch /tmp/qwen-video-format.patch
RUN patch -p1 < /tmp/qwen-video-format.patch \
    && cmake -S . -B build \
        -DCMAKE_BUILD_TYPE=Release \
        ${CUDA_ARCH:+-DCMAKE_CUDA_ARCHITECTURES="$CUDA_ARCH"} \
        -DGGML_CUDA=ON \
        -DGGML_NATIVE=OFF \
        -DCMAKE_EXE_LINKER_FLAGS=-Wl,--allow-shlib-undefined \
        -DLLAMA_BUILD_EXAMPLES=OFF \
        -DLLAMA_BUILD_SERVER=ON \
        -DLLAMA_BUILD_TESTS=OFF \
        -DLLAMA_BUILD_UI=OFF \
        -DLLAMA_USE_PREBUILT_UI=OFF \
    && cmake --build build --parallel --target llama-server

FROM ghcr.io/ggml-org/llama.cpp@sha256:8557e3d273aa6010d46f355e826348b691ba3ddffccae8eaf0150596bbc3ec42
COPY --from=build /src/build/bin/ /app/
ENV LLAMA_QWEN_VIDEO_FORMAT=1
