#!/bin/bash
set -euo pipefail

# ==============================================================================
# 配置中心
# ==============================================================================
readonly APP_DIR="/opt/nas-media-player"
readonly SERVICE_NAME="nas-media-player"
readonly WAIT_TIMEOUT=10
readonly SYSTEMD_SERVICE="/etc/systemd/system/${SERVICE_NAME}.service"
readonly PORT=8800                          # 服务监听端口
readonly VIDEO_DIR="/mnt"                   # 媒体文件根目录（和程序逻辑对齐）
readonly LOG_FILE="${APP_DIR}/${SERVICE_NAME}.log"  # 日志文件固定在运行目录
readonly PIP_MIRROR="https://mirrors.tencent.com/pypi/simple"  # 网络检查镜像
readonly BIN_NAME="${SERVICE_NAME}"         # 运行目录下的二进制文件名（统一命名）

# 必需文件列表（包含所有架构二进制，但部署时仅复制匹配的）
readonly REQUIRED_FILES=(
    "nas-media-player.py"
    "index.html"
    "zhinan.html"
    "releases/nas-media-player-armhf"
    "releases/nas-media-player-arm64"
    "releases/nas-media-player-x86_64"
)

# 架构映射表（uname -m → 二进制后缀）
declare -A ARCH_MAP=(
    ["armv7l"]="armhf"
    ["aarch64"]="arm64"
    ["x86_64"]="x86_64"
)

# ==============================================================================
# 颜色与样式定义（提升用户体验）
# ==============================================================================
readonly COLOR_RESET="\033[0m"
readonly COLOR_RED="\033[31m"
readonly COLOR_GREEN="\033[32m"
readonly COLOR_YELLOW="\033[33m"
readonly COLOR_BLUE="\033[34m"
readonly COLOR_BOLD="\033[1m"

# ==============================================================================
# 全局变量（检测后赋值）
# ==============================================================================
OS_NAME=""           # 系统发行版
DETECTED_ARCH=""     # 检测到的系统架构
SOURCE_BIN_FILE=""   # 源二进制文件（releases下的匹配文件）
TARGET_BIN_FILE=""   # 目标二进制文件（运行目录下）
HAS_SYSTEMD="false"  # 是否支持systemd

# ==============================================================================
# 日志与输出函数（统一输出格式）
# ==============================================================================
log_info() {
    echo -e "${COLOR_BLUE}[INFO]${COLOR_RESET} $*"
}

log_success() {
    echo -e "${COLOR_GREEN}[SUCCESS]${COLOR_RESET} $*"
}

log_warn() {
    echo -e "${COLOR_YELLOW}[WARN]${COLOR_RESET} $*"
}

log_error() {
    echo -e "${COLOR_RED}[ERROR]${COLOR_RESET} $*" >&2
}

log_step() {
    echo -e "\n${COLOR_BOLD}[$1/$2] $3${COLOR_RESET}"
}

# ==============================================================================
# 系统检测函数（核心：架构/发行版/systemd检测）
# ==============================================================================
detect_os_info() {
    log_step 1 7 "检测系统信息"
    
    # 1. 检测系统发行版
    if [ -f /etc/os-release ]; then
        source /etc/os-release
        OS_NAME="${NAME} ${VERSION_ID}"
    elif [ -f /etc/lsb-release ]; then
        source /etc/lsb-release
        OS_NAME="${DISTRIB_ID} ${DISTRIB_RELEASE}"
    else
        OS_NAME="Unknown Linux"
    fi
    log_info "系统发行版：${OS_NAME}"

    # 2. 检测系统架构并匹配二进制文件
    local raw_arch=$(uname -m)
    if [[ -v ARCH_MAP["${raw_arch}"] ]]; then
        DETECTED_ARCH="${ARCH_MAP["${raw_arch}"]}"
        SOURCE_BIN_FILE="releases/${SERVICE_NAME}-${DETECTED_ARCH}"  # 源文件（脚本同目录）
        TARGET_BIN_FILE="${APP_DIR}/${BIN_NAME}"                    # 目标文件（运行目录）
        log_info "检测到架构：${raw_arch} → 匹配二进制：${SOURCE_BIN_FILE} → 部署到：${TARGET_BIN_FILE}"
    else
        log_error "不支持的架构：${raw_arch}（仅支持armhf/arm64/x86_64）"
        exit 1
    fi

    # 3. 检测是否支持systemd
    if command -v systemctl >/dev/null 2>&1 && systemctl >/dev/null 2>&1; then
        HAS_SYSTEMD="true"
        log_info "系统支持systemd服务管理"
    else
        log_warn "系统不支持systemd，无法配置开机自启"
    fi
}

# ==============================================================================
# 前置检查函数
# ==============================================================================
check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        log_error "请使用 root 用户执行（sudo -i 后运行）"
        exit 1
    fi
}

check_network() {
    log_step 2 7 "检查网络连通性"
    if ! curl -s --connect-timeout 5 "${PIP_MIRROR}" >/dev/null; then
        log_warn "网络连接可能不稳定（不影响本地部署）"
    else
        log_success "网络连通性检查通过"
    fi
}

check_required_files() {
    log_step 3 7 "检查必需文件"
    local missing_files=()
    for file in "${REQUIRED_FILES[@]}"; do
        if [ ! -f "${file}" ]; then
            missing_files+=("${file}")
        fi
    done

    if [ ${#missing_files[@]} -gt 0 ]; then
        log_error "缺失必需文件：${missing_files[*]}"
        log_error "请确保所有必需文件与脚本同目录"
        exit 1
    fi
    log_success "所有必需文件检查通过"
}

check_system_deps() {
    log_step 4 7 "检查系统依赖"
    # 检查必要命令
    local required_cmds=("curl" "awk" "grep" "pkill" "pgrep")
    for cmd in "${required_cmds[@]}"; do
        if ! command -v "${cmd}" >/dev/null 2>&1; then
            log_error "缺失必需命令：${cmd}（请先安装）"
            exit 1
        fi
    done
    log_success "系统依赖检查通过"
}

# ==============================================================================
# 核心功能函数
# ==============================================================================
create_app_dirs() {
    log_step 5 7 "创建应用目录"
    # 仅创建必要目录
    mkdir -p "${APP_DIR}" \
             "${APP_DIR}/static" \
             "${VIDEO_DIR}"
    
    # 创建日志文件并设置权限（确保运行目录可写）
    touch "${LOG_FILE}"
    chmod 644 "${LOG_FILE}"
    chmod 755 "${APP_DIR}"  # 确保运行目录有执行权限
    log_success "应用目录创建完成：${APP_DIR}（日志文件：${LOG_FILE}）"
}

deploy_app_files() {
    log_step 6 7 "部署程序文件"
    
    # 复制主程序文件
    cp -f "nas-media-player.py" "${APP_DIR}/" || { log_error "复制主程序文件失败"; exit 1; }
    
    # 复制静态文件
    cp -f "index.html" "zhinan.html" "${APP_DIR}/static/" || { log_error "复制静态文件失败"; exit 1; }
    
    # 仅复制匹配架构的二进制文件到运行目录（核心改动）
    cp -f "${SOURCE_BIN_FILE}" "${TARGET_BIN_FILE}" || { log_error "复制二进制文件 ${SOURCE_BIN_FILE} 失败"; exit 1; }
    
    # 给二进制文件加可执行权限（关键）
    chmod +x "${TARGET_BIN_FILE}" || { log_error "设置二进制文件可执行权限失败"; exit 1; }
    
    # 验证部署
    if [ -f "${APP_DIR}/static/index.html" ] && [ -x "${TARGET_BIN_FILE}" ]; then
        log_success "程序文件部署完成："
        log_success "  - 主程序：${APP_DIR}/nas-media-player.py"
        log_success "  - 静态文件：${APP_DIR}/static/"
        log_success "  - 二进制文件：${TARGET_BIN_FILE}（${DETECTED_ARCH}架构）"
        log_success "  - 日志文件：${LOG_FILE}"
    else
        log_error "文件部署失败！请检查 ${APP_DIR} 目录权限"
        exit 1
    fi
}

create_systemd_service() {
    log_step 7 7 "配置系统服务（开机启动）"
    
    if [ "${HAS_SYSTEMD}" != "true" ]; then
        log_warn "跳过systemd服务配置（系统不支持）"
        return 0
    fi

    # 写入服务文件（日志固定输出到运行目录，二进制路径为运行目录）
    cat > "${SYSTEMD_SERVICE}" <<EOF
[Unit]
Description=Lightweight NAS Media Player Service
Documentation=https://github.com/teasiu/nas-media-player
After=network.target network-online.target local-fs.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=${APP_DIR}
ExecStart=${TARGET_BIN_FILE}
ExecReload=/bin/kill -HUP \$MAINPID
Restart=always
RestartSec=5
TimeoutStartSec=30
TimeoutStopSec=10
LimitNOFILE=65535
StandardOutput=append:${LOG_FILE}
StandardError=append:${LOG_FILE}

[Install]
WantedBy=multi-user.target
EOF

    # 验证并启用服务
    if [ -f "${SYSTEMD_SERVICE}" ]; then
        systemctl daemon-reload
        systemctl enable "${SERVICE_NAME}" >/dev/null 2>&1
        log_success "systemd服务配置完成（已启用开机启动）"
    else
        log_error "systemd服务文件创建失败"
        exit 1
    fi
}

# 检查端口监听状态
check_port_listen() {
    local port=$1
    if command -v ss >/dev/null 2>&1; then
        ss -tulpn 2>/dev/null | grep -q ":${port}.*${BIN_NAME}"
    elif command -v netstat >/dev/null 2>&1; then
        netstat -tulpn 2>/dev/null | grep -q ":${port}.*${BIN_NAME}"
    else
        return 1
    fi
}

# 启动服务
start_service() {
    log_info "\n========== 启动服务 =========="
    
    # 停止旧进程
    log_info "清理旧进程..."
    pkill -f "${TARGET_BIN_FILE}" >/dev/null 2>&1 || true
    sleep 2

    if [ "${HAS_SYSTEMD}" = "true" ]; then
        # systemd启动
        systemctl start "${SERVICE_NAME}"

        # 等待服务启动
        log_info "等待服务启动（最长 ${WAIT_TIMEOUT} 秒）..."
        local counter=0
        while [ ${counter} -lt ${WAIT_TIMEOUT} ]; do
            if systemctl is-active --quiet "${SERVICE_NAME}"; then
                if check_port_listen "${PORT}"; then
                    log_success "服务启动成功（端口${PORT}已监听）"
                    return 0
                else
                    log_warn "服务已启动，但端口${PORT}未监听（嵌入式设备可能延迟，建议等待1分钟后重试）"
                    return 0
                fi
            fi
            counter=$((counter + 1))
            sleep 1
        done

        # 启动失败处理
        log_error "服务启动失败！"
        log_info "错误日志（最后20行）："
        tail -n 20 "${LOG_FILE}" || log_warn "无法读取日志文件：${LOG_FILE}"
        log_info "请检查服务状态：systemctl status ${SERVICE_NAME}"
        exit 1
    else
        # 非systemd启动（前台运行）
        log_warn "非systemd系统，将以前台方式启动服务（关闭终端则停止）"
        nohup "${TARGET_BIN_FILE}" > "${LOG_FILE}" 2>&1 &
        sleep 3
        if check_port_listen "${PORT}"; then
            log_success "服务前台启动成功（端口${PORT}已监听）"
            log_info "日志文件：${LOG_FILE}"
        else
            log_error "服务启动失败！请查看日志：${LOG_FILE}"
            exit 1
        fi
    fi
}

stop_service() {
    log_info "\n========== 停止服务 =========="
    
    # systemd停止
    if [ "${HAS_SYSTEMD}" = "true" ] && systemctl is-active --quiet "${SERVICE_NAME}"; then
        systemctl stop "${SERVICE_NAME}"
        sleep 2
    fi

    # 强制清理残留进程
    pkill -9 -f "${TARGET_BIN_FILE}" >/dev/null 2>&1 || true
    sleep 1

    if ! pgrep -f "${TARGET_BIN_FILE}" >/dev/null; then
        log_success "服务已停止"
    else
        log_error "服务停止失败，请手动执行：pkill -9 -f '${TARGET_BIN_FILE}'"
        exit 1
    fi
}

# 获取本地IP（优先非回环IPv4）
get_local_ip() {
    local ip
    ip=$(hostname -I | awk '{print $1}' | grep -v '^127.' | grep -v '^::') || \
    ip=$(ip addr show | grep 'inet ' | grep -v '127.0.0.1' | grep -v '::1' | head -n1 | awk '{print $2}' | cut -d'/' -f1) || \
    ip="127.0.0.1"
    echo "${ip}"
}

# 安装完成总结
show_install_summary() {
    local ip=$(get_local_ip)
    echo -e "\n${COLOR_BOLD}========================================${COLOR_RESET}"
    echo -e "${COLOR_GREEN}🎉 ${SERVICE_NAME} 安装成功！${COLOR_RESET}"
    echo -e "${COLOR_BOLD}========================================${COLOR_RESET}"
    echo -e "📍 访问地址：${COLOR_BLUE}http://${ip}:${PORT}${COLOR_RESET}"
    echo -e "📁 运行目录：${APP_DIR}"
    echo -e "🎬 媒体目录：${VIDEO_DIR}"
    echo -e "📜 日志文件：${LOG_FILE}（固定在运行目录）"
    echo -e "⚙️  运行二进制：${TARGET_BIN_FILE}（${DETECTED_ARCH}架构）"
    echo -e "🔧 系统服务：${SERVICE_NAME}"
    echo -e "${COLOR_BOLD}========================================${COLOR_RESET}"
    echo -e "✨ 功能特性："
    echo -e "  ✅ 自动匹配系统架构部署二进制文件"
    echo -e "  ✅ 支持子目录浏览和播放"
    echo -e "  ✅ 支持视频文件上传（大小不限）"
    echo -e "  ✅ 支持创建新目录/私密目录"
    echo -e "  ✅ 丝滑的上传进度条显示"
    echo -e "  ✅ 支持MP4/AVI/MKV/WEBM等主流格式"
    echo -e "${COLOR_BOLD}========================================${COLOR_RESET}"
    echo -e "📋 常用命令："
    echo -e "  启动服务：${0} start 或 systemctl start ${SERVICE_NAME}"
    echo -e "  停止服务：${0} stop 或 systemctl stop ${SERVICE_NAME}"
    echo -e "  重启服务：${0} restart 或 systemctl restart ${SERVICE_NAME}"
    echo -e "  查看状态：${0} status 或 systemctl status ${SERVICE_NAME}"
    echo -e "  查看日志：tail -f ${LOG_FILE}（推荐）或 journalctl -u ${SERVICE_NAME} -f"
    echo -e "  卸载服务：${0} uninstall"
    echo -e "${COLOR_BOLD}========================================${COLOR_RESET}"
}

# 卸载服务
uninstall_service() {
    echo -e "${COLOR_BOLD}========================================${COLOR_RESET}"
    echo -e "${COLOR_YELLOW}开始卸载 ${SERVICE_NAME} 服务${COLOR_RESET}"
    echo -e "${COLOR_BOLD}========================================${COLOR_RESET}"

    # 停止并清理systemd服务
    if [ "${HAS_SYSTEMD}" = "true" ] && [ -f "${SYSTEMD_SERVICE}" ]; then
        systemctl stop "${SERVICE_NAME}" >/dev/null 2>&1 || true
        systemctl disable "${SERVICE_NAME}" >/dev/null 2>&1 || true
        rm -f "${SYSTEMD_SERVICE}"
        systemctl daemon-reload
        log_success "systemd服务已清理"
    fi

    # 停止残留进程
    stop_service >/dev/null 2>&1 || true

    # 删除程序目录（包含日志文件）
    log_info "删除运行目录（含日志文件）..."
    rm -rf "${APP_DIR}" && log_success "运行目录 ${APP_DIR} 已删除"

    # 保留媒体目录
    log_warn "媒体目录 ${VIDEO_DIR} 已保留（包含您的媒体文件）"

    echo -e "\n${COLOR_BOLD}========================================${COLOR_RESET}"
    echo -e "${COLOR_GREEN}✅ ${SERVICE_NAME} 服务卸载完成${COLOR_RESET}"
    echo -e "${COLOR_BOLD}========================================${COLOR_RESET}"
    exit 0
}

# 显示帮助信息
show_help() {
    echo -e "${COLOR_BOLD}========================================${COLOR_RESET}"
    echo -e "${COLOR_BLUE}${SERVICE_NAME} 安装管理脚本${COLOR_RESET}"
    echo -e "${COLOR_BOLD}========================================${COLOR_RESET}"
    echo -e "使用方法：${0} [命令]"
    echo -e "\n可用命令："
    echo -e "  install   - 安装并启动服务（核心命令）"
    echo -e "  start     - 启动服务"
    echo -e "  stop      - 停止服务"
    echo -e "  restart   - 重启服务"
    echo -e "  status    - 查看服务状态"
    echo -e "  uninstall - 卸载服务（保留媒体文件）"
    echo -e "  help      - 显示此帮助信息"
    echo -e "${COLOR_BOLD}========================================${COLOR_RESET}"
    exit 0
}

# 显示服务状态
show_status() {
    echo -e "${COLOR_BOLD}========================================${COLOR_RESET}"
    echo -e "${COLOR_BLUE}${SERVICE_NAME} 服务状态${COLOR_RESET}"
    echo -e "${COLOR_BOLD}========================================${COLOR_RESET}"
    echo -e "服务名称：${SERVICE_NAME}"
    echo -e "运行架构：${DETECTED_ARCH:-未检测}"
    echo -e "运行二进制：${TARGET_BIN_FILE:-未知}"
    if [ "${HAS_SYSTEMD}" = "true" ]; then
        echo -e "运行状态：$(systemctl is-active --quiet "${SERVICE_NAME}" && echo -e "${COLOR_GREEN}运行中${COLOR_RESET}" || echo -e "${COLOR_RED}已停止${COLOR_RESET}")"
    else
        echo -e "运行状态：$(pgrep -f "${TARGET_BIN_FILE}" >/dev/null && echo -e "${COLOR_GREEN}运行中${COLOR_RESET}" || echo -e "${COLOR_RED}已停止${COLOR_RESET}")"
    fi
    echo -e "监听端口：$(check_port_listen "${PORT}" && echo -e "${COLOR_GREEN}${PORT}（已监听）${COLOR_RESET}" || echo -e "${COLOR_RED}${PORT}（未监听）${COLOR_RESET}")"
    echo -e "运行目录：${APP_DIR} ($([ -d "${APP_DIR}" ] && echo -e "${COLOR_GREEN}存在${COLOR_RESET}" || echo -e "${COLOR_RED}不存在${COLOR_RESET}"))"
    echo -e "媒体目录：${VIDEO_DIR} ($([ -d "${VIDEO_DIR}" ] && echo -e "${COLOR_GREEN}存在${COLOR_RESET}" || echo -e "${COLOR_RED}不存在${COLOR_RESET}"))"
    echo -e "日志文件：${LOG_FILE} ($([ -f "${LOG_FILE}" ] && echo -e "${COLOR_GREEN}存在${COLOR_RESET}" || echo -e "${COLOR_RED}不存在${COLOR_RESET}"))"
    echo -e "系统发行版：${OS_NAME:-未知}"
    echo -e "${COLOR_BOLD}========================================${COLOR_RESET}"
}

# ==============================================================================
# 主函数（处理命令参数）
# ==============================================================================
main() {
    # 无参数时显示帮助
    if [ $# -eq 0 ]; then
        show_help
    fi

    local cmd="$1"
    case "${cmd}" in
        install)
            check_root
            detect_os_info
            check_network
            check_required_files
            check_system_deps
            create_app_dirs
            deploy_app_files
            if [ "${HAS_SYSTEMD}" = "true" ]; then
                create_systemd_service
            fi
            start_service
            show_install_summary
            ;;
        start)
            check_root
            detect_os_info
            start_service
            ;;
        stop)
            check_root
            detect_os_info
            stop_service
            ;;
        restart)
            check_root
            detect_os_info
            stop_service
            start_service
            ;;
        status)
            detect_os_info
            show_status
            ;;
        uninstall)
            check_root
            detect_os_info
            uninstall_service
            ;;
        help)
            show_help
            ;;
        *)
            log_error "无效命令：${cmd}（使用 ${0} help 查看帮助）"
            exit 1
            ;;
    esac
}

# ==============================================================================
# 执行入口
# ==============================================================================
main "$@"

