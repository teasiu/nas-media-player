from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import aiofiles
import os
import logging
import json
import hashlib
import urllib.parse
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
import socket
import tempfile
import shutil

VIDEO_DIR = os.getenv("NAS_MEDIA_VIDEO_DIR", "/mnt")
PORT = int(os.getenv("NAS_MEDIA_PORT", 8800))
APP_DIR = os.getenv("NAS_MEDIA_APP_DIR", "/opt/nas-media-player")
LOG_FILE = os.getenv("NAS_MEDIA_LOG_FILE", os.path.join(APP_DIR, "nas-media-player.log"))

# 确保日志目录存在
log_dir = os.path.dirname(LOG_FILE)
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 配置路径
VIDEO_ROOT = Path(VIDEO_DIR).resolve()
PASSWORD_FILE = Path(APP_DIR) / "dir_passwords.json"

def path_is_relative_to(path: Path, base: Path) -> bool:
    """检查path是否是base的子路径（兼容Python 3.8-）"""
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False

def path_relative_to(path: Path, base: Path) -> str:
    """获取path相对于base的路径（兼容Python 3.8-）"""
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)

app = FastAPI(title="NAS 轻量媒体播放器")

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 支持的格式定义
SUPPORTED_VIDEO_FORMATS = {
    ".mp4": "video/mp4",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".flv": "video/x-flv",
    ".wmv": "video/x-ms-wmv",
    ".mpeg": "video/mpeg",
    ".mpg": "video/mpeg",
    ".m4v": "video/x-m4v"
}

SUPPORTED_IMAGE_FORMATS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff"
}

SUPPORTED_AUDIO_FORMATS = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".m4a": "audio/mp4",
    ".wma": "audio/x-ms-wma",
    ".ape": "audio/ape",
    ".alac": "audio/alac"
}

# 合并所有支持的格式
SUPPORTED_FORMATS = {**SUPPORTED_VIDEO_FORMATS, **SUPPORTED_IMAGE_FORMATS, **SUPPORTED_AUDIO_FORMATS}
SUPPORTED_EXTENSIONS = list(SUPPORTED_FORMATS.keys())

# 挂载静态文件（延迟到目录确实存在时）
static_dir = Path(APP_DIR) / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
else:
    logger.warning(f"静态文件目录不存在，跳过挂载: {static_dir}")


def get_safe_cookie_key(dir_path: str) -> str:
    """将目录路径转换为MD5哈希值，避免Cookie键名包含非法字符"""
    encoded_path = dir_path.encode('utf-8')
    md5_hash = hashlib.md5(encoded_path).hexdigest()
    return f"auth_{md5_hash}"


# ── 密码管理功能 ────────────────────────────────────────────────────────────────

def init_password_file():
    """初始化密码文件"""
    app_dir = Path(APP_DIR)
    app_dir.mkdir(parents=True, exist_ok=True)

    if not PASSWORD_FILE.exists():
        PASSWORD_FILE.write_text("{}", encoding="utf-8")
    else:
        try:
            json.loads(PASSWORD_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            PASSWORD_FILE.write_text("{}", encoding="utf-8")


def hash_password(password: str) -> str:
    """密码哈希"""
    return hashlib.sha256(password.encode()).hexdigest()


def _read_password_data() -> dict:
    """读取密码文件数据（内部辅助函数）"""
    init_password_file()
    try:
        return json.loads(PASSWORD_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_directory_password(dir_path: str, password: str):
    """保存目录密码（原子写入，防止并发破坏）"""
    data = _read_password_data()
    data[dir_path] = {
        "password_hash": hash_password(password),
        "created_at": datetime.now().isoformat()
    }
    # 原子写：先写临时文件再替换
    tmp_path = PASSWORD_FILE.with_suffix(".tmp")
    try:
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        shutil.move(str(tmp_path), str(PASSWORD_FILE))
    except Exception as e:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise e


def get_directory_password(dir_path: str) -> Optional[str]:
    """获取目录密码哈希"""
    return _read_password_data().get(dir_path, {}).get("password_hash")


def check_directory_password(dir_path: str, password: str) -> bool:
    """验证目录密码"""
    stored_hash = get_directory_password(dir_path)
    if not stored_hash:
        return True  # 未设置密码，视为通过
    return stored_hash == hash_password(password)


def get_protected_directories() -> List[str]:
    """获取所有受保护的目录"""
    return list(_read_password_data().keys())


def is_protected_directory(dir_path: str) -> bool:
    """检查目录（或其祖先）是否受保护"""
    if not dir_path:
        return False
    protected_dirs = get_protected_directories()
    norm = dir_path.replace(os.sep, '/').rstrip('/')
    for pdir in protected_dirs:
        pnorm = pdir.replace(os.sep, '/').rstrip('/')
        if norm == pnorm or norm.startswith(f"{pnorm}/"):
            return True
    return False


def get_top_protected_directory(dir_path: str) -> Optional[str]:
    """获取目录所属的顶级受保护祖先目录"""
    if not dir_path or not is_protected_directory(dir_path):
        return None

    norm = dir_path.replace(os.sep, '/').rstrip('/')
    protected_dirs = get_protected_directories()
    top_dir = None
    min_depth = float('inf')

    for pdir in protected_dirs:
        pnorm = pdir.replace(os.sep, '/').rstrip('/')
        if norm == pnorm or norm.startswith(f"{pnorm}/"):
            depth = pnorm.count('/')
            if depth < min_depth:
                min_depth = depth
                top_dir = pdir

    return top_dir


def _verify_cookie(request: Request, top_protected_dir: str) -> bool:
    """检查 Cookie 是否匹配受保护目录的密码哈希"""
    cookie_key = get_safe_cookie_key(top_protected_dir)
    cookie_value = request.cookies.get(cookie_key)
    stored_hash = get_directory_password(top_protected_dir)
    return bool(cookie_value and stored_hash and cookie_value == stored_hash)


async def check_dir_access(dir_path: str, request: Request) -> bool:
    """检查目录访问权限（统一入口）"""
    if not dir_path:
        return True
    top_protected_dir = get_top_protected_directory(dir_path)
    if not top_protected_dir:
        return True
    result = _verify_cookie(request, top_protected_dir)
    if result:
        logger.info(f"目录访问验证通过: {dir_path}")
    else:
        logger.warning(f"目录访问验证失败: {dir_path}")
    return result


# ── 路径安全辅助 ────────────────────────────────────────────────────────────────

def safe_join(base: Path, *paths) -> Path:
    """安全拼接路径，防止路径穿越攻击"""
    try:
        decoded_paths = [urllib.parse.unquote(p) for p in paths]
        joined = base.joinpath(*decoded_paths).resolve()
        joined.relative_to(base)  # 若越界则抛 ValueError
        return joined
    except ValueError:
        raise HTTPException(status_code=403, detail="无效路径（越权访问）")
    except Exception as e:
        logger.error(f"路径安全检查失败: {e}")
        raise HTTPException(status_code=403, detail="Invalid path")


# ── 自然排序辅助 ────────────────────────────────────────────────────────────────

import re

def _natural_sort_key(s: str):
    """将字符串拆分为文本/数字段，用于自然排序（1, 2, 10 而不是 1, 10, 2）"""
    parts = re.split(r'(\d+)', s.lower())
    return [int(p) if p.isdigit() else p for p in parts]


# ── API 路由 ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def read_root():
    index_path = Path(APP_DIR) / "static" / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="前端页面未找到")
    return FileResponse(str(index_path))


@app.get("/api/directories")
async def get_directories(max_depth: int = 3):
    def traverse(path: Path, rel_path: str = "", depth: int = 0) -> List[Dict]:
        items = []
        if depth >= max_depth:
            return items  # 超过深度限制，返回空列表
        try:
            for d in sorted(path.iterdir(), key=lambda x: _natural_sort_key(x.name)):
                if d.is_dir() and not d.name.startswith('.'):
                    sub_rel = f"{rel_path}/{d.name}" if rel_path else d.name
                    items.append({
                        "name": d.name,
                        "path": sub_rel,
                        "type": "directory",
                        "protected": is_protected_directory(sub_rel),
                        "children": traverse(d, sub_rel, depth + 1)
                    })
        except PermissionError:
            logger.warning(f"目录无读取权限: {path}")
        except Exception as e:
            logger.error(f"目录遍历错误: {e}")
        return items

    dirs = traverse(VIDEO_ROOT) if VIDEO_ROOT.exists() else []
    return {"directories": dirs}


@app.get("/api/all-directories")
async def get_all_directories(max_depth: int = 3):
    all_dirs = []

    def traverse(path: Path, rel_path: str = "", depth: int = 0):
        if depth >= max_depth:
            return  # 超过深度限制，停止遍历
        all_dirs.append({
            "name": rel_path if rel_path else "主目录",
            "path": rel_path,
            "protected": is_protected_directory(rel_path)
        })
        try:
            for d in sorted(path.iterdir(), key=lambda x: _natural_sort_key(x.name)):
                if d.is_dir() and not d.name.startswith('.'):
                    sub_rel = f"{rel_path}/{d.name}" if rel_path else d.name
                    traverse(d, sub_rel, depth + 1)
        except PermissionError:
            logger.warning(f"目录无读取权限: {path}")
        except Exception as e:
            logger.error(f"目录遍历错误: {e}")

    if VIDEO_ROOT.exists():
        traverse(VIDEO_ROOT)
    return {"directories": all_dirs}


@app.get("/api/protected-directories")
async def get_protected_dirs():
    return {"protected_dirs": get_protected_directories()}


@app.post("/api/verify-dir-password")
async def verify_dir_password(dir_path: str = Form(...), password: str = Form(...)):
    try:
        top_protected_dir = get_top_protected_directory(dir_path)
        if not top_protected_dir:
            return {"success": True, "message": "目录不受保护"}

        if check_directory_password(top_protected_dir, password):
            cookie_key = get_safe_cookie_key(top_protected_dir)
            response = JSONResponse({"success": True, "message": "密码正确"})
            response.set_cookie(
                key=cookie_key,
                value=hash_password(password),
                max_age=3600 * 8,   # 8小时（原来1小时，延长减少重复验证）
                httponly=True,
                secure=False,       # LAN 部署通常无 HTTPS
                samesite="lax"
            )
            logger.info(f"目录密码验证成功: {top_protected_dir}")
            return response
        else:
            logger.warning(f"目录密码验证失败: {top_protected_dir}")
            return {"success": False, "message": "密码错误"}
    except Exception as e:
        logger.error(f"密码验证异常: {e}")
        return {"success": False, "message": f"验证失败: {str(e)}"}


@app.post("/api/clear-dir-auth")
async def clear_dir_auth(dir_path: str = Form(...)):
    try:
        top_protected_dir = get_top_protected_directory(dir_path)
        if not top_protected_dir:
            return {"success": True, "message": "目录不受保护"}

        cookie_key = get_safe_cookie_key(top_protected_dir)
        response = JSONResponse({"success": True, "message": "已清除访问权限"})
        response.delete_cookie(cookie_key)
        return response
    except Exception as e:
        logger.error(f"清除认证失败: {e}")
        return {"success": False, "message": f"清除失败: {str(e)}"}


@app.get("/api/media")
async def get_media(subdir: Optional[str] = None, request: Request = None):
    try:
        if subdir and not await check_dir_access(subdir, request):
            return {
                "media": [],
                "current_dir": subdir or "",
                "protected": True,
                "top_protected_dir": get_top_protected_directory(subdir)
            }

        target_dir = safe_join(VIDEO_ROOT, subdir.strip()) if subdir and subdir.strip() else VIDEO_ROOT

        if not target_dir.exists() or not target_dir.is_dir():
            return {"media": [], "current_dir": subdir or ""}

        media = []
        for file in target_dir.iterdir():
            if file.is_file():
                ext = file.suffix.lower()
                if ext in SUPPORTED_EXTENSIONS:
                    if ext in SUPPORTED_VIDEO_FORMATS:
                        file_type = "video"
                    elif ext in SUPPORTED_AUDIO_FORMATS:
                        file_type = "audio"
                    else:
                        file_type = "image"
                    stat = file.stat()
                    media.append({
                        "name": file.name,
                        "type": file_type,
                        "extension": ext,
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                        "path": str(file)
                    })

        # 自然排序（1, 2, 10 顺序，而非 1, 10, 2）
        media.sort(key=lambda x: _natural_sort_key(x["name"]))
        logger.info(f"Found {len(media)} media files in {target_dir}")

        return {
            "media": media,
            "current_dir": subdir or "",
            "protected": is_protected_directory(subdir or ""),
            "top_protected_dir": get_top_protected_directory(subdir or "")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取媒体列表失败: {e}")
        return {"media": [], "current_dir": subdir or "", "error": str(e)}


def encode_filename_for_header(filename: str) -> str:
    """编码文件名以支持中文等非 ASCII 字符"""
    try:
        filename.encode('ascii')
        return filename
    except UnicodeEncodeError:
        return urllib.parse.quote(filename)


@app.get("/api/media/{path:path}")
async def serve_media(path: str, request: Request):
    try:
        decoded_path = urllib.parse.unquote(path)
        full_media_path = safe_join(VIDEO_ROOT, decoded_path)
        media_dir = (
            path_relative_to(full_media_path.parent, VIDEO_ROOT)
            if path_is_relative_to(full_media_path.parent, VIDEO_ROOT)
            else str(full_media_path.parent)
        )

        if is_protected_directory(media_dir) and not await check_dir_access(media_dir, request):
            raise HTTPException(status_code=403, detail="需要密码访问")

        if not full_media_path.exists() or not full_media_path.is_file():
            return JSONResponse(status_code=404, content={"error": "Media file not found"})

        ext = full_media_path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return JSONResponse(status_code=400, content={"error": f"Unsupported format: {ext}"})

        mime_type = SUPPORTED_FORMATS.get(ext, "application/octet-stream")
        filename = full_media_path.name
        encoded_filename = encode_filename_for_header(filename)
        content_disp = f'inline; filename="{encoded_filename}"; filename*=UTF-8\'\'{encoded_filename}'

        # 图片：直接返回
        if ext in SUPPORTED_IMAGE_FORMATS:
            logger.info(f"Serving image: {full_media_path}")
            return FileResponse(
                path=str(full_media_path),
                media_type=mime_type,
                headers={"Cache-Control": "max-age=3600", "Content-Disposition": content_disp}
            )

        # 音频：直接返回（浏览器原生断点续传）
        if ext in SUPPORTED_AUDIO_FORMATS:
            logger.info(f"Serving audio: {full_media_path}")
            return FileResponse(
                path=str(full_media_path),
                media_type=mime_type,
                headers={"Content-Disposition": content_disp, "Accept-Ranges": "bytes"}
            )

        # 视频：手动处理 Range 断点续传
        file_size = full_media_path.stat().st_size
        range_header = request.headers.get("Range")

        start, end = 0, min(1024 * 1024 * 2, file_size - 1)  # 默认前 2 MB
        if range_header:
            try:
                range_str = range_header.split("=")[-1]
                start_str, end_str = range_str.split("-")
                start = int(start_str) if start_str else 0
                end = int(end_str) if end_str else file_size - 1
                start = max(0, start)
                end = min(end, file_size - 1)
            except (ValueError, IndexError):
                start, end = 0, min(1024 * 1024 * 2, file_size - 1)

        async def iterfile():
            async with aiofiles.open(str(full_media_path), 'rb') as f:
                await f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = await f.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    yield chunk
                    remaining -= len(chunk)

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
            "Content-Type": mime_type,
            "Content-Disposition": content_disp,
        }
        logger.info(f"Serving video: {full_media_path} (bytes {start}-{end}/{file_size})")
        return StreamingResponse(iterfile(), status_code=206, headers=headers, media_type=mime_type)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"媒体文件服务失败: {e}")
        return JSONResponse(status_code=500, content={"error": f"Server error: {str(e)}"})


@app.post("/api/create-directory")
async def create_directory(
    target_path: str = Form(""),
    new_dir: str = Form(...),
    dir_password: Optional[str] = Form(None)
):
    try:
        if not new_dir or not new_dir.strip():
            raise HTTPException(status_code=400, detail="目录名不能为空")

        new_dir = new_dir.strip()

        invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|', '\0']
        if any(c in new_dir for c in invalid_chars):
            raise HTTPException(status_code=400, detail="目录名包含非法字符（/\\:*?\"<>|）")

        parent_dir = safe_join(VIDEO_ROOT, target_path.strip()) if target_path and target_path.strip() else VIDEO_ROOT

        if not parent_dir.exists():
            raise HTTPException(status_code=404, detail=f"父目录不存在: {parent_dir}")
        if not os.access(parent_dir, os.W_OK):
            raise HTTPException(status_code=403, detail="父目录无写入权限")

        new_dir_path = parent_dir / new_dir
        if new_dir_path.exists():
            raise HTTPException(status_code=409, detail=f"目录已存在: {new_dir}")

        try:
            new_dir_path.mkdir(parents=False, exist_ok=False)
        except PermissionError:
            raise HTTPException(status_code=403, detail="创建目录失败：权限不足")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"创建目录失败：{str(e)}")

        new_dir_rel = (
            path_relative_to(new_dir_path, VIDEO_ROOT)
            if path_is_relative_to(new_dir_path, VIDEO_ROOT)
            else str(new_dir_path)
        )

        if dir_password and dir_password.strip():
            save_directory_password(new_dir_rel, dir_password.strip())
            logger.info(f"带密码保护的目录创建成功: {new_dir_path}")
        else:
            logger.info(f"目录创建成功: {new_dir_path}")

        return {
            "success": True,
            "message": f"目录创建成功: {new_dir}" + ("（已设置密码保护）" if dir_password else ""),
            "path": new_dir_rel,
            "protected": bool(dir_password)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建目录异常: {e}", exc_info=True)
        return {"success": False, "message": f"创建失败: {str(e)}"}


@app.post("/api/upload-media")
async def upload_media(
    request: Request,
    target_dir: str = Form(""),
    file: UploadFile = File(...)
):
    file_path = None
    try:
        logger.info(f"上传请求 - 目标目录: {target_dir}, 文件: {file.filename}")

        if is_protected_directory(target_dir) and not await check_dir_access(target_dir, request):
            return {"success": False, "message": "无权访问该目录，请先验证密码"}

        if not file or not file.filename:
            return {"success": False, "message": "未选择文件"}

        filename = file.filename
        file_ext = Path(filename).suffix.lower()
        if file_ext not in SUPPORTED_EXTENSIONS:
            return {
                "success": False,
                "message": f"不支持的文件格式: {file_ext}，支持的格式: {', '.join(SUPPORTED_EXTENSIONS)}"
            }

        upload_dir = safe_join(VIDEO_ROOT, target_dir.strip()) if target_dir.strip() else VIDEO_ROOT
        os.makedirs(upload_dir, exist_ok=True)

        # 文件名去重
        file_path = upload_dir / filename
        counter = 1
        while file_path.exists():
            stem = Path(filename).stem
            file_path = upload_dir / f"{stem}_{counter}{file_ext}"
            counter += 1

        # 写入文件（先写临时文件，成功后原子移动）
        tmp_fd, tmp_name = tempfile.mkstemp(dir=upload_dir)
        try:
            content_length = 0
            async with aiofiles.open(tmp_name, 'wb') as f:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    await f.write(chunk)
                    content_length += len(chunk)

            os.close(tmp_fd)
            shutil.move(tmp_name, str(file_path))
        except Exception as e:
            os.close(tmp_fd)
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise Exception(f"保存文件失败: {str(e)}")

        actual_size = file_path.stat().st_size
        if actual_size != content_length:
            logger.warning(f"文件大小不一致 - 写入: {content_length}, 磁盘: {actual_size}")

        file_type = "视频" if file_ext in SUPPORTED_VIDEO_FORMATS else ("音频" if file_ext in SUPPORTED_AUDIO_FORMATS else "图片")
        logger.info(f"上传成功: {file_path} ({file_type}, {actual_size} bytes)")

        return {
            "success": True,
            "message": f"{file_type}文件 {file_path.name} 上传成功",
            "filename": file_path.name,
            "path": target_dir,
            "size": actual_size
        }

    except HTTPException:
        raise
    except Exception as e:
        # 清理可能已创建的残留文件
        if file_path and isinstance(file_path, Path) and file_path.exists() and file_path.stat().st_size == 0:
            file_path.unlink(missing_ok=True)
        logger.error(f"上传失败: {e}")
        return {"success": False, "message": f"上传失败: {str(e)}"}
    finally:
        try:
            await file.close()
        except Exception:
            pass


@app.delete("/api/delete-file")
async def delete_file(request: Request, file_path: str):
    """删除媒体文件"""
    try:
        full_path = safe_join(VIDEO_ROOT, urllib.parse.unquote(file_path))
        media_dir = (
            path_relative_to(full_path.parent, VIDEO_ROOT)
            if path_is_relative_to(full_path.parent, VIDEO_ROOT)
            else str(full_path.parent)
        )

        if is_protected_directory(media_dir) and not await check_dir_access(media_dir, request):
            raise HTTPException(status_code=403, detail="需要密码访问")

        if not full_path.exists():
            raise HTTPException(status_code=404, detail="文件不存在")
        if not full_path.is_file():
            raise HTTPException(status_code=400, detail="路径不是文件")

        full_path.unlink()
        logger.info(f"文件删除成功: {full_path}")
        return {"success": True, "message": f"文件 {full_path.name} 删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除文件失败: {e}")
        return {"success": False, "message": f"删除失败: {str(e)}"}


@app.delete("/api/delete-directory")
async def delete_directory(request: Request, dir_path: str):
    """删除目录（仅允许删除空目录）"""
    try:
        full_path = safe_join(VIDEO_ROOT, urllib.parse.unquote(dir_path))
        rel_path = (
            path_relative_to(full_path, VIDEO_ROOT)
            if path_is_relative_to(full_path, VIDEO_ROOT)
            else str(full_path)
        )

        if not full_path.exists():
            raise HTTPException(status_code=404, detail="目录不存在")
        if not full_path.is_dir():
            raise HTTPException(status_code=400, detail="路径不是目录")
        if full_path == VIDEO_ROOT:
            raise HTTPException(status_code=403, detail="不允许删除根目录")

        # 检查目录是否为空
        if any(full_path.iterdir()):
            raise HTTPException(status_code=409, detail="目录不为空，请先删除其中的文件")

        full_path.rmdir()

        # 同步清理密码记录
        data = _read_password_data()
        if rel_path in data:
            del data[rel_path]
            PASSWORD_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        logger.info(f"目录删除成功: {full_path}")
        return {"success": True, "message": f"目录 {full_path.name} 删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除目录失败: {e}")
        return {"success": False, "message": f"删除失败: {str(e)}"}


# ── 启动入口 ────────────────────────────────────────────────────────────────────

def create_listen_sockets(port: int) -> list:
    sockets = []

    # IPv4
    sock4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except (AttributeError, OSError):
        pass  # SO_REUSEPORT 并非所有平台都支持
    sock4.bind(("0.0.0.0", port))
    sock4.listen(2048)
    sockets.append(sock4)
    logger.info(f"IPv4 监听: 0.0.0.0:{port}")

    # IPv6（可选）
    try:
        sock6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sock6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass
        sock6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        sock6.bind(("::", port))
        sock6.listen(2048)
        sockets.append(sock6)
        logger.info(f"IPv6 监听: [::]:{port}")
    except OSError as e:
        logger.warning(f"IPv6 不可用，仅启用 IPv4: {e}")

    return sockets


def main():
    init_password_file()
    import uvicorn
    sockets = create_listen_sockets(PORT)
    config = uvicorn.Config(
        app,
        log_level="warning",
        workers=1,
        access_log=False,
        timeout_keep_alive=30
    )
    server = uvicorn.Server(config)
    server.run(sockets=sockets)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--version", action="store_true")

    args = parser.parse_args()

    if args.version:
        print("nas-media-player v1.2")
        raise SystemExit(0)

    main()
