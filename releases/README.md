## 打包二进制制作方法

```
apt update && apt install -y python3 python3-pip python3-dev gcc g++ make libffi-dev libssl-dev patchelf
pip_select.sh
pip3 install fastapi uvicorn aiofiles python-multipart pyinstaller

```

```
pyinstaller --onefile --name=nas-media-player-armhf --distpath=dist --workpath=tmp --clean --exclude-module=tkinter --exclude-module=unittest --exclude-module=sqlite3 nas-media-player.py
pyinstaller --onefile --name=nas-media-player-arm64 --distpath=dist --workpath=tmp --clean --exclude-module=tkinter --exclude-module=unittest --exclude-module=sqlite3 nas-media-player.py
pyinstaller --onefile --name=nas-media-player-x86_64 --distpath=dist --workpath=tmp --clean --exclude-module=tkinter --exclude-module=unittest --exclude-module=sqlite3 nas-media-player.py

~/.local/bin/pyinstaller --onefile --name=nas-media-player-x86_64 --distpath=dist --workpath=tmp --clean --exclude-module=tkinter --exclude-module=unittest --exclude-module=sqlite3 nas-media-player.py

```    
    
```
chmod +x dist/nas-media-player-x86_64

./dist/nas-media-player-x86_64
```


