# NAS Media Player

轻量级NAS媒体播放器，专为多架构Linux系统设计（armhf/arm64/x86_64），完美兼容嵌入式设备（如hi3798mv100）和常规Ubuntu/Debian发行版，提供视频文件浏览、播放、上传、目录管理、私密目录保护等核心功能，开箱即用。

## 🌟 功能特性
- **多架构适配**：自动识别armv7l(armhf)、aarch64(arm64)、x86_64架构，无需手动选择二进制文件
- **核心功能**：视频文件浏览/播放、大文件上传、目录创建/删除、私密目录密码保护
- **轻量化部署**：单脚本一键安装，自动配置systemd服务（开机自启）
- **日志可视化**：运行日志固定存储在程序目录，便于问题排查
- **兼容性强**：适配嵌入式设备（如hi3798mv100）和普通Linux服务器

## 🚀 快速开始

### 1. 环境要求
- 系统：Linux（Ubuntu/Debian/嵌入式Linux，支持systemd最佳）
- 权限：需root权限（sudo）
- 网络：克隆仓库需网络连通（部署后无网络也可使用）
```tips
### 海纳思系统，直接如下安装即可

apt update

apt install nas-media-player

忽略下面一切

```
### 2. 克隆仓库
```bash
git clone https://github.com/teasiu/nas-media-player.git
cd nas-media-player
```

### 3. 一键安装 & 启动
安装脚本会自动完成「架构检测→文件部署→服务配置→启动运行」全流程：
```bash
sudo ./install.sh install
```

### 4. 访问服务
安装完成后，在浏览器中访问以下地址即可使用：
```plaintext
http://[你的设备IP]:8800
```
示例：`http://192.168.101.141:8800`

## ⚙️ 常用命令
| 功能         | 执行命令                                          | 说明                                    |
|--------------|---------------------------------------------------|-----------------------------------------|
| 启动服务     | `sudo ./install.sh start`                         | 启动NAS Media Player服务                |
| 停止服务     | `sudo ./install.sh stop`                          | 停止运行中的服务                        |
| 重启服务     | `sudo ./install.sh restart`                       | 重启服务（配置修改后生效）              |
| 查看状态     | `sudo ./install.sh status`                        | 查看服务运行状态、端口监听、目录状态    |
| 查看日志     | `tail -f /opt/nas-media-player/nas-media-player.log` | 实时查看运行日志                        |
| 卸载服务     | `sudo ./install.sh uninstall`                     | 卸载程序（保留/mnt媒体目录文件）        |
| 查看帮助     | `sudo ./install.sh help`                          | 查看所有可用命令                        |

## 🛠️ 配置说明
核心配置可在`install.sh`脚本头部修改，无需改动代码：
| 配置项       | 默认值                  | 说明                                  |
|--------------|-------------------------|---------------------------------------|
| `APP_DIR`    | `/opt/nas-media-player` | 程序安装目录                          |
| `PORT`       | `8800`                  | 服务监听端口                          |
| `VIDEO_DIR`  | `/mnt`                  | 媒体文件存储根目录                    |
| `LOG_FILE`   | `${APP_DIR}/nas-media-player.log` | 运行日志文件路径               |

## ❓ 常见问题
### Q1：安装后端口8800未监听？
- 嵌入式设备启动可能有延迟，等待1分钟后重试；
- 执行`sudo ./install.sh status`查看服务状态；
- 查看日志排查：`tail -f /opt/nas-media-player/nas-media-player.log`。

### Q2：上传文件失败/目录创建报错？
- 检查`/mnt`目录权限：`sudo chmod 777 /mnt`；
- 确认磁盘空间充足，大文件上传建议使用有线网络。

### Q3：不支持的架构报错？
- 仅支持armhf/arm64/x86_64架构，执行`uname -m`查看系统架构。

### Q4：卸载后重新安装失败？
- 先执行`sudo ./install.sh uninstall`清理残留，再重新安装。

## 📂 目录结构
```plaintext
nas-media-player/
├── install.sh          # 一键安装/管理脚本
├── nas-media-player.py # 主程序源码
├── index.html          # 前端页面
├── zhinan.html         # 帮助页面
├── releases/           # 多架构二进制文件目录
│   ├── nas-media-player-armhf
│   ├── nas-media-player-arm64
│   └── nas-media-player-x86_64
└── README.md           # 说明文档
```

## 📄 许可证
本项目采用 MIT 许可证 - 详见 `LICENSE` 文件。

## 🤝 贡献
欢迎提交Issue反馈问题，或PR优化功能，提交前请确保脚本在多架构环境下测试通过。
