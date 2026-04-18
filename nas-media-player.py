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
import unicodedata
import socket

VIDEO_DIR = os.getenv("NAS_MEDIA_VIDEO_DIR", "/mnt")
PORT = int(os.getenv("NAS_MEDIA_PORT", 8800))
APP_DIR = os.getenv("NAS_MEDIA_APP_DIR", "/opt/nas-media-player")
LOG_FILE = os.getenv("NAS_MEDIA_LOG_FILE", os.path.join(APP_DIR, "nas-media-player.log"))


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

# 挂载静态文件
app.mount("/static", StaticFiles(directory=Path(APP_DIR) / "static"), name="static")

def get_safe_cookie_key(dir_path: str) -> str:
    """将目录路径转换为MD5哈希值，避免Cookie键名包含非法字符"""
    encoded_path = dir_path.encode('utf-8')
    md5_hash = hashlib.md5(encoded_path).hexdigest()
    return f"auth_{md5_hash}"

# 密码管理功能
def init_password_file():
    """初始化密码文件（修复目录创建+合法JSON写入）"""
    app_dir = Path(APP_DIR)
    app_dir.mkdir(parents=True, exist_ok=True)

    if not PASSWORD_FILE.exists():
        with open(PASSWORD_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)
    else:
        try:
            with open(PASSWORD_FILE, 'r', encoding='utf-8') as f:
                json.load(f)
        except json.JSONDecodeError:
            with open(PASSWORD_FILE, 'w', encoding='utf-8') as f:
                json.dump({}, f)

def hash_password(password: str) -> str:
    """密码哈希"""
    return hashlib.sha256(password.encode()).hexdigest()

def save_directory_password(dir_path: str, password: str):
    """保存目录密码"""
    init_password_file()
    with open(PASSWORD_FILE, 'r+') as f:
        data = json.load(f)
        data[dir_path] = {
            "password_hash": hash_password(password),
            "created_at": datetime.now().isoformat()
        }
        f.seek(0)
        json.dump(data, f, indent=2)
        f.truncate()

def get_directory_password(dir_path: str) -> Optional[str]:
    """获取目录密码哈希"""
    init_password_file()
    if not PASSWORD_FILE.exists():
        return None
    with open(PASSWORD_FILE, 'r') as f:
        data = json.load(f)
        return data.get(dir_path, {}).get("password_hash")

def check_directory_password(dir_path: str, password: str) -> bool:
    """验证目录密码"""
    stored_hash = get_directory_password(dir_path)
    if not stored_hash:
        return True
    return stored_hash == hash_password(password)

def get_protected_directories() -> List[str]:
    """获取所有受保护的目录"""
    init_password_file()
    with open(PASSWORD_FILE, 'r') as f:
        data = json.load(f)
        return list(data.keys())

def is_protected_directory(dir_path: str) -> bool:
    """检查目录是否受保护（修复路径匹配逻辑）"""
    if not dir_path:
        return False
    protected_dirs = get_protected_directories()
    dir_path_normalized = dir_path.replace(os.sep, '/').rstrip('/')
    protected_dirs_normalized = [pdir.replace(os.sep, '/').rstrip('/') for pdir in protected_dirs]
    
    for pdir in protected_dirs_normalized:
        if dir_path_normalized == pdir or dir_path_normalized.startswith(f"{pdir}/"):
            return True
    return False

def get_top_protected_directory(dir_path: str) -> Optional[str]:
    """获取目录所属的顶级受保护目录（兼容Python 3.8-）"""
    if not dir_path or not is_protected_directory(dir_path):
        return None
    
    # 统一路径分隔符为/，便于匹配
    dir_path_normalized = dir_path.replace(os.sep, '/').rstrip('/')
    protected_dirs = get_protected_directories()
    protected_dirs_normalized = [pdir.replace(os.sep, '/').rstrip('/') for pdir in protected_dirs]
    
    top_dir = None
    max_depth = -1
    
    for pdir, pdir_original in zip(protected_dirs_normalized, protected_dirs):
        if dir_path_normalized == pdir or dir_path_normalized.startswith(f"{pdir}/"):
            depth = pdir.count('/')
            if top_dir is None or depth < max_depth:
                max_depth = depth
                top_dir = pdir_original
    
    return top_dir

async def verify_dir_access(request: Request, dir_path: str) -> bool:
    """验证目录访问权限（简化逻辑，避免误拦截）"""
    if not dir_path or not is_protected_directory(dir_path):
        return True
    
    top_protected_dir = get_top_protected_directory(dir_path)
    if not top_protected_dir:
        return True
    
    # 使用安全的Cookie键名
    cookie_key = get_safe_cookie_key(top_protected_dir)
    cookie_value = request.cookies.get(cookie_key)
    stored_hash = get_directory_password(top_protected_dir)
    
    # 兼容Cookie不存在的情况
    if cookie_value and stored_hash and cookie_value == stored_hash:
        logger.info(f"目录访问验证通过: {dir_path} (Cookie认证)")
        return True
    
    logger.warning(f"目录访问验证失败: {dir_path} (缺少有效Cookie)")
    return False

# 根路径返回前端页面
@app.get("/", response_class=HTMLResponse)
async def read_root():
    return FileResponse(str(Path(APP_DIR) / "static" / "index.html"))

# 安全检查路径（兼容Python 3.8及以下版本）
def safe_join(base: Path, *paths) -> Path:
    try:
        decoded_paths = [urllib.parse.unquote(path) for path in paths]
        joined_path = base.joinpath(*decoded_paths).resolve()
        joined_path.relative_to(base)
        return joined_path
    except ValueError:
        logger.error(f"路径越权：{joined_path} 不在 {base} 范围内")
        raise HTTPException(status_code=403, detail="无效路径（越权访问）")
    except Exception as e:
        logger.error(f"Path security check failed: {e}")
        raise HTTPException(status_code=403, detail="Invalid path")

# 获取目录结构
@app.get("/api/directories")
async def get_directories():
    dirs = []
    protected_dirs = get_protected_directories()
    
    def traverse_recursive_dirs(path: Path, rel_path: str = "") -> List[Dict]:
        items = []
        try:
            for dir in path.iterdir():
                if dir.is_dir() and not dir.name.startswith('.'):
                    sub_rel = f"{rel_path}/{dir.name}" if rel_path else dir.name
                    is_protected = is_protected_directory(sub_rel)
                    items.append({
                        "name": dir.name,
                        "path": sub_rel,
                        "type": "directory",
                        "protected": is_protected,
                        "children": traverse_recursive_dirs(dir, sub_rel)
                    })
        except Exception as e:
            logger.error(f"Directory traversal error: {e}")
        return items
    
    if VIDEO_ROOT.exists():
        dirs = traverse_recursive_dirs(VIDEO_ROOT)
    return {"directories": dirs}


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
                max_age=3600,
                httponly=True,
                secure=False,
                samesite="lax"
            )
            logger.info(f"目录密码验证成功: {top_protected_dir}")
            return response
        else:
            logger.warning(f"目录密码验证失败: {top_protected_dir}")
            return {"success": False, "message": "密码错误"}
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return {"success": False, "message": f"验证失败: {str(e)}"}

async def check_dir_access(dir_path: str, request: Request) -> bool:
    """检查目录访问权限"""
    if not dir_path:
        return True
    
    top_protected_dir = get_top_protected_directory(dir_path)
    if not top_protected_dir:
        return True
    
    cookie_key = get_safe_cookie_key(top_protected_dir)
    cookie_value = request.cookies.get(cookie_key)
    stored_hash = get_directory_password(top_protected_dir)
    
    if cookie_value and cookie_value == stored_hash:
        return True
    
    return False

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
        
        if subdir and subdir.strip():
            target_dir = safe_join(VIDEO_ROOT, subdir.strip())
        else:
            target_dir = VIDEO_ROOT
            
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
                    
                    media.append({
                        "name": file.name,
                        "type": file_type,
                        "extension": ext,
                        "size": file.stat().st_size,
                        "modified": file.stat().st_mtime,
                        "path": str(file)
                    })
        
        # 按文件名自然排序
        media.sort(key=lambda x: (len(x["name"]), x["name"]))
        logger.info(f"Found {len(media)} media files in {target_dir}")
        
        return {
            "media": media,
            "current_dir": subdir or "",
            "protected": is_protected_directory(subdir or ""),
            "top_protected_dir": get_top_protected_directory(subdir or "")
        }
    except Exception as e:
        logger.error(f"Error getting media list: {e}")
        return {"media": [], "current_dir": subdir or "", "error": str(e)}

# 编码文件名用于HTTP头
def encode_filename_for_header(filename: str) -> str:
    """编码文件名以支持中文等特殊字符"""
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
        media_dir = path_relative_to(full_media_path.parent, VIDEO_ROOT) if path_is_relative_to(full_media_path.parent, VIDEO_ROOT) else str(full_media_path.parent)
        
        if is_protected_directory(media_dir) and not await verify_dir_access(request, media_dir):
            raise HTTPException(status_code=403, detail="需要密码访问")
        
        if not full_media_path.exists() or not full_media_path.is_file():
            logger.warning(f"Media file not found: {full_media_path}")
            return JSONResponse(
                status_code=404,
                content={"error": "Media file not found"}
            )
        
        ext = full_media_path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return JSONResponse(
                status_code=400,
                content={"error": f"Unsupported format: {ext}"}
            )
        
        mime_type = SUPPORTED_FORMATS.get(ext, "application/octet-stream")
        
        # 处理图片
        if ext in SUPPORTED_IMAGE_FORMATS:
            logger.info(f"Serving image: {full_media_path}")
            
            # 处理中文文件名的HTTP头
            filename = full_media_path.name
            encoded_filename = encode_filename_for_header(filename)
            
            headers = {
                "Cache-Control": "max-age=3600",
                "Content-Disposition": f"inline; filename=\"{encoded_filename}\"; filename*=UTF-8''{encoded_filename}"
            }
            
            return FileResponse(
                path=str(full_media_path),
                media_type=mime_type,
                filename=encoded_filename,
                headers=headers
            )
        
        # 处理音频
        elif ext in SUPPORTED_AUDIO_FORMATS:
            logger.info(f"Serving audio: {full_media_path}")
            
            # 处理中文文件名的HTTP头
            filename = full_media_path.name
            encoded_filename = encode_filename_for_header(filename)
            
            headers = {
                "Content-Disposition": f"inline; filename=\"{encoded_filename}\"; filename*=UTF-8''{encoded_filename}"
            }
            
            return FileResponse(
                path=str(full_media_path),
                media_type=mime_type,
                filename=encoded_filename,
                headers=headers
            )
        
        # 视频处理断点续传
        file_size = full_media_path.stat().st_size
        range_header = request.headers.get("Range")
        
        if range_header:
            try:
                range_str = range_header.split("=")[-1]
                start_str, end_str = range_str.split("-")
                start = int(start_str) if start_str else 0
                end = int(end_str) if end_str else file_size - 1
                end = min(end, file_size - 1)
                start = max(0, start)
            except:
                start = 0
                end = min(1024*1024*2, file_size - 1)
        else:
            start = 0
            end = min(1024*1024*2, file_size - 1)
        
        # 异步分块读取
        async def iterfile():
            async with aiofiles.open(str(full_media_path), 'rb') as f:
                await f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk_size = min(1024*1024, remaining)
                    chunk = await f.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
                    remaining -= chunk_size
        
        # 处理视频文件名
        filename = full_media_path.name
        encoded_filename = encode_filename_for_header(filename)
        
        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
            "Content-Type": mime_type,
            "Content-Disposition": f"inline; filename=\"{encoded_filename}\"; filename*=UTF-8''{encoded_filename}"
        }
        
        logger.info(f"Serving video: {full_media_path} (bytes {start}-{end}/{file_size})")
        return StreamingResponse(
            iterfile(),
            status_code=206,
            headers=headers,
            media_type=mime_type
        )
        
    except HTTPException as e:
        raise
    except Exception as e:
        logger.error(f"Error serving media: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Server error: {str(e)}"}
        )

# 获取所有目录路径
@app.get("/api/all-directories")
async def get_all_directories():
    all_dirs = []
    
    def traverse_all_dirs(path: Path, rel_path: str = ""):
        try:
            all_dirs.append({
                "name": rel_path if rel_path else "主目录",
                "path": rel_path,
                "protected": is_protected_directory(rel_path)
            })
            for dir in path.iterdir():
                if dir.is_dir() and not dir.name.startswith('.'):
                    sub_rel = f"{rel_path}/{dir.name}" if rel_path else dir.name
                    traverse_all_dirs(dir, sub_rel)
        except Exception as e:
            logger.error(f"Error traversing all directories: {e}")
    
    if VIDEO_ROOT.exists():
        traverse_all_dirs(VIDEO_ROOT)
    return {"directories": all_dirs}


@app.post("/api/create-directory")
async def create_directory(
    target_path: str = Form(""), 
    new_dir: str = Form(...),
    dir_password: Optional[str] = Form(None)
):
    try:
        if not new_dir or new_dir.strip() == "":
            raise HTTPException(status_code=400, detail="目录名不能为空")
        
        # 安全路径拼接
        if target_path and target_path.strip():
            parent_dir = safe_join(VIDEO_ROOT, target_path.strip())
        else:
            parent_dir = VIDEO_ROOT
        
        # 新增：检查父目录是否存在且可写
        if not parent_dir.exists():
            raise HTTPException(status_code=404, detail=f"父目录不存在: {parent_dir}")
        if not os.access(parent_dir, os.W_OK):
            raise HTTPException(status_code=403, detail=f"父目录无写入权限: {parent_dir}")
        
        new_dir_path = parent_dir / new_dir.strip()
        new_dir_rel_path = path_relative_to(new_dir_path, VIDEO_ROOT) if path_is_relative_to(new_dir_path, VIDEO_ROOT) else str(new_dir_path)
        
        # 检查目录名合法性
        invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        if any(char in new_dir for char in invalid_chars):
            raise HTTPException(status_code=400, detail="目录名包含非法字符（/\:*?\"<>|）")
        
        # 新增：检查目录是否已存在
        if new_dir_path.exists():
            raise HTTPException(status_code=409, detail=f"目录已存在: {new_dir_path.name}")
        
        # 创建目录（增强异常捕获）
        try:
            new_dir_path.mkdir(parents=True, exist_ok=False)
        except PermissionError:
            raise HTTPException(status_code=403, detail=f"创建目录失败：权限不足（{new_dir_path}）")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"创建目录失败：{str(e)}")
        
        # 设置密码保护
        if dir_password and dir_password.strip():
            save_directory_password(new_dir_rel_path, dir_password.strip())
            logger.info(f"带密码保护的目录创建成功: {new_dir_path}")
        else:
            logger.info(f"目录创建成功: {new_dir_path}")
        
        return {
            "success": True, 
            "message": f"目录创建成功: {new_dir_path.name}" + ("（已设置密码保护）" if dir_password else ""),
            "path": new_dir_rel_path,
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
    try:
        logger.info(f"开始处理上传请求 - 目标目录: {target_dir}, 文件名: {file.filename}")
        
        if is_protected_directory(target_dir) and not await verify_dir_access(request, target_dir):
            logger.warning(f"加密目录上传权限拒绝: {target_dir}")
            return {"success": False, "message": "无权访问该目录，请先验证密码"}
        
        if not file or not file.filename:
            logger.warning("上传失败：未选择文件")
            return {"success": False, "message": "未选择文件"}
        
        filename = file.filename
        file_ext = Path(filename).suffix.lower()
        if file_ext not in SUPPORTED_EXTENSIONS:
            logger.warning(f"上传失败：不支持的文件格式 {file_ext}")
            return {
                "success": False, 
                "message": f"不支持的文件格式: {file_ext}，支持的格式: {', '.join(SUPPORTED_EXTENSIONS)}"
            }
        
        if target_dir.strip():
            upload_dir = safe_join(VIDEO_ROOT, target_dir.strip())
        else:
            upload_dir = VIDEO_ROOT
        
        os.makedirs(upload_dir, exist_ok=True)
        logger.info(f"上传目录已确认: {upload_dir}")
        
        file_path = upload_dir / filename
        counter = 1
        while file_path.exists():
            stem = Path(filename).stem
            new_filename = f"{stem}_{counter}{file_ext}"
            file_path = upload_dir / new_filename
            counter += 1
        
        try:
            async with aiofiles.open(str(file_path), 'wb') as f:
                content_length = 0
                while chunk := await file.read(1024 * 1024):
                    await f.write(chunk)
                    content_length += len(chunk)
            
            if not file_path.exists():
                raise Exception("文件保存失败：文件不存在")
            if file_path.stat().st_size != content_length:
                logger.warning(f"文件大小不一致 - 预期: {content_length}, 实际: {file_path.stat().st_size}")
            
            # 确定文件类型
            if file_ext in SUPPORTED_VIDEO_FORMATS:
                file_type = "视频"
            elif file_ext in SUPPORTED_AUDIO_FORMATS:
                file_type = "音频"
            else:
                file_type = "图片"
            
            logger.info(f"文件上传成功: {file_path} ({file_type}, {file_path.stat().st_size} bytes)")
            
            return {
                "success": True,
                "message": f"{file_type}文件 {file_path.name} 上传成功",
                "filename": file_path.name,
                "path": target_dir,
                "size": file_path.stat().st_size
            }
            
        except Exception as e:
            # 清理不完整文件
            if file_path.exists() and file_path.stat().st_size == 0:
                file_path.unlink()
                logger.warning(f"清理空文件: {file_path}")
            raise Exception(f"保存文件失败: {str(e)}")
            
    except Exception as e:
        logger.error(f"上传失败: {str(e)}")
        return {
            "success": False, 
            "message": f"上传失败: {str(e)}"
        }
    finally:
        # 确保文件句柄关闭
        try:
            await file.close()
        except Exception as e:
            logger.error(f"关闭文件句柄失败: {e}")

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
        logger.error(f"Clear auth error: {e}")
        return {"success": False, "message": f"清除失败: {str(e)}"}


@app.get("/api/protected-directories")
async def get_protected_dirs():
    return {"protected_dirs": get_protected_directories()}

def create_listen_sockets(port: int) -> list:
    sockets = []

    # ===== IPv4 =====
    sock4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock4.bind(("0.0.0.0", port))
    sock4.listen(2048)
    sockets.append(sock4)
    logger.info(f"IPv4 监听: 0.0.0.0:{port}")

    # ===== IPv6 =====
    try:
        sock6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sock6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        # 关键：必须是 1
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
    main()

