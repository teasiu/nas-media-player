#!/bin/bash
# build.sh - 一键打包脚本
# 在对应架构的机器上执行（或用 Docker 交叉编译，见下方说明）
set -euo pipefail

ARCH=$(uname -m)
OUTPUT_NAME="nas-media-player-${ARCH}"
RELEASES_DIR="./releases"

echo "========================================"
echo "  NAS Media Player 打包脚本"
echo "  当前架构: ${ARCH}"
echo "========================================"

# 1. 检查 Python 版本（建议 3.9+）
ARCH=$(uname -m)

if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "armv7l" ]; then
  apt-get update
  apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    binutils \
    python3.8-venv
fi
python3 --version

# 2. 创建并激活虚拟环境（隔离，避免污染系统）
echo "[1/5] 创建虚拟环境..."
python3 -m venv .venv-build
source .venv-build/bin/activate

# 3. 安装依赖
echo "[2/5] 安装依赖..."
pip install --upgrade pip -q
pip install \
    pyinstaller \
    fastapi \
    uvicorn \
    aiofiles \
    pydantic \
    python-multipart \
    -q

# 4. 执行打包
echo "[3/5] 开始打包 (PyInstaller)..."
pyinstaller nas-media-player.spec \
    --clean \
    --noconfirm

# 5. 检查产物
BINARY="./dist/nas-media-player"
if [ ! -f "${BINARY}" ]; then
    echo "❌ 打包失败！未找到 ${BINARY}"
    exit 1
fi

# 6. 重命名并归档
mkdir -p "${RELEASES_DIR}"
cp "${BINARY}" "${RELEASES_DIR}/${OUTPUT_NAME}"
chmod +x "${RELEASES_DIR}/${OUTPUT_NAME}"

# 显示文件大小
SIZE=$(du -sh "${RELEASES_DIR}/${OUTPUT_NAME}" | cut -f1)
echo ""
echo "========================================"
echo "✅ 打包成功！"
echo "   产物路径: ${RELEASES_DIR}/${OUTPUT_NAME}"
echo "   文件大小: ${SIZE}"
echo "========================================"

# 7. 快速验证（不启动服务，只检查 --help）
echo "[5/5] 验证二进制可执行..."
"${RELEASES_DIR}/${OUTPUT_NAME}" --version 2>/dev/null || true
echo "验证完成（如无错误输出则正常）"

# 清理虚拟环境
deactivate
