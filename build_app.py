"""macOS 打包脚本：产出原生 .app（与 Windows 版同款体验，双击运行）。

用法：
    .venv-mac/bin/python build_app.py
产物在 dist/ 下，例如 dist/北大法宝爬虫.app

切换版本：改下面的 TARGET 为对应的 GUI 源文件名即可。
依赖：PyQt5 DrissionPage pyinstaller Pillow（Pillow 用于把 .ico 自动转成 mac 的 .icns）
"""
import os
import PyInstaller.__main__

current_dir = os.path.dirname(os.path.abspath(__file__))

# 要打包的源文件（三选一）：
#   北大法典爬虫GUI.py            <- 上游 build_exe.py 的默认
#   北大法宝爬虫下载附件版GUI.py
#   北大法宝爬虫不下载附件版GUI.py
TARGET = '北大法典爬虫GUI.py'

# PyInstaller 在装了 Pillow 时会把 .ico 自动转成 macOS 需要的 .icns
icon_path = os.path.join(current_dir, 'icon.ico')

PyInstaller.__main__.run([
    os.path.join(current_dir, TARGET),
    '--name=北大法宝爬虫',
    '--onefile',
    '--windowed',          # macOS 下生成 .app 包
    f'--icon={icon_path}',
    '--clean',
    '--noconfirm',
])

print("打包完成！见 dist/北大法宝爬虫.app")
