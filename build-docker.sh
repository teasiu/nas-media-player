#!/bin/bash
# build-docker.sh - 用 Docker 为三种架构分别打包
# 前提：本机安装了 Docker + QEMU（用于跨架构）
# 安装 QEMU：docker run --privileged --rm tonistiigi/binfmt --install all
set -euo pipefail

PLATFORMS=("linux/amd64" "linux/arm64" "linux/arm/v7")
ARCH_NAMES=("x86_64" "arm64" "armhf")

echo "开始多架构打包..."

for i in "${!PLATFORMS[@]}"; do
    PLATFORM="${PLATFORMS[$i]}"
    ARCH_NAME="${ARCH_NAMES[$i]}"
    OUTPUT="releases/nas-media-player-${ARCH_NAME}"

    echo ""
    echo "========================================="
    echo "  打包架构: ${PLATFORM} → ${ARCH_NAME}"
    echo "========================================="

    docker run --rm \
        --platform "${PLATFORM}" \
        -v "$(pwd):/workspace" \
        -w /workspace \
        python:3.11-slim \
        bash -c "
            set -e
            echo '--- 安装系统依赖 ---'
            apt-get update -qq && apt-get install -y -q binutils

            echo '--- 安装 Python 依赖 ---'
            pip install --upgrade pip -q
            pip install pyinstaller fastapi 'uvicorn[standard]' aiofiles \
                pydantic python-multipart httptools -q

            echo '--- 执行打包 ---'
            pyinstaller nas-media-player.spec --clean --noconfirm

            echo '--- 复制产物 ---'
            mkdir -p releases
            cp dist/nas-media-player releases/nas-media-player-${ARCH_NAME}
            chmod +x releases/nas-media-player-${ARCH_NAME}
            echo '产物大小:' \$(du -sh releases/nas-media-player-${ARCH_NAME})
        "

    echo "✅ ${ARCH_NAME} 打包完成 → ${OUTPUT}"
done

echo ""
echo "========================================="
echo "🎉 所有架构打包完成！"
ls -lh releases/
echo "========================================="
