from DrissionPage import Chromium, ChromiumPage
import time
import random
import os
import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout, QHBoxLayout, 
                            QWidget, QLabel, QLineEdit, QTextEdit, QFileDialog, QComboBox, 
                            QProgressBar, QMessageBox, QGroupBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon


# ============================================================================
# 「继续阅读」展开 + 配额/注册弹窗检测（启发式 + 自诊断日志）
# 本函数在 auto_browser.py 与三个独立 GUI 里各有一份字节一致的拷贝
# （三个 GUI 用 PyInstaller --onefile 打包，不便共享 import，故复制；改一处要四处同步）。
# 标 CONFIRM-DOM 的选择器是启发式猜测，命中后会 log 出真实值，便于回填收紧。
# ============================================================================
_JUNK_MARKERS = ('剩余', '未阅读', '继续阅读')          # CONFIRM-DOM：以真实残留串为准
_CONTENT_SELS = ('.content', '.fulltext')              # CONFIRM-DOM：不同版本正文容器
_DIALOG_SELS = ['.el-dialog', '.el-dialog__wrapper', '[role=dialog]',
                '.el-message-box', '.dialog', '.modal', '.popup',
                '.layui-layer', '.van-dialog', '.ant-modal']   # CONFIRM-DOM
_POPUP_KW = ('完善', '注册', '手机', '行业', '验证码', '登录')  # 配额弹窗 vs 普通对话框


def _content_text(page):
    """读正文容器文本（DOM 级）。.content 不在则退回 .fulltext（法典老版）。"""
    try:
        js = ("var ss=" + repr(list(_CONTENT_SELS)).replace("'", '"') + ";"
              "for(var i=0;i<ss.length;i++){var c=document.querySelector(ss[i]);"
              "if(c)return c.innerText;}return '';")
        return page.run_js(js) or ''
    except Exception:
        return ''


def _popup_present(page):
    """页面上是否有可见且含配额关键词的对话框。返回 (bool, 说明串)。"""
    try:
        js = (
            "function vis(el){if(!el)return false;var s=getComputedStyle(el);"
            "if(s.display==='none'||s.visibility==='hidden'||parseFloat(s.opacity)===0)return false;"
            "var r=el.getBoundingClientRect();return r.width>0&&r.height>0;}"
            "var sels=" + repr(_DIALOG_SELS).replace("'", '"') + ";"
            "var kw=" + repr(list(_POPUP_KW)).replace("'", '"') + ";"
            "for(var i=0;i<sels.length;i++){var ns=document.querySelectorAll(sels[i]);"
            "for(var j=0;j<ns.length;j++){if(vis(ns[j])){var t=(ns[j].innerText||'');"
            "for(var k=0;k<kw.length;k++){if(t.indexOf(kw[k])>-1)"
            "return sels[i]+'|||'+t.slice(0,80);}}}}return '';"
        )
        hit = page.run_js(js)
    except Exception:
        return False, ''
    if hit:
        sel, _, txt = hit.partition('|||')
        return True, '%s 文本「%s」' % (sel, txt)
    return False, ''


def content_is_clean(text):
    """保存前对已取出字符串做最终校验。True=干净可写。"""
    return bool(text and text.strip()) and not any(m in text for m in _JUNK_MARKERS)


def expand_full_text(page, log=print, timeout=12):
    """点开「继续阅读」展开正文后半段，并判定是否触发配额/注册弹窗。

    返回:
      'ok'      正文已完整（无残留标记、无弹窗）
      'popup'   出现配额/注册弹窗 -> 调用方应停止整批并告警
      'partial' 没展开干净 -> 调用方应跳过该篇、不写文件
    """
    import time  # 局部 import，保证独立 GUI 直接粘贴可用

    # 0. 开页即弹的配额弹窗（少数情况）
    present, why = _popup_present(page)
    if present:
        log('⚠ 开页即检测到配额/注册弹窗（%s）→ 账号疑似已达上限' % why)
        return 'popup'

    # 1. 找「继续阅读」展开控件（启发式：按可见文本扫可点元素）
    find_js = (
        "var ms=" + repr(list(_JUNK_MARKERS)).replace("'", '"') + ";"
        "var cs=document.querySelectorAll('a,button,span,div,p');"
        "for(var i=0;i<cs.length;i++){var e=cs[i];var t=(e.innerText||'').trim();"
        "if(t.length<40){for(var k=0;k<ms.length;k++){if(t.indexOf(ms[k])>-1){"
        "var r=e.getBoundingClientRect();if(r.width>0&&r.height>0)"
        "return e.tagName+'|||'+(e.className||'')+'|||'+t;}}}}return '';"
    )
    try:
        info = page.run_js(find_js)
    except Exception:
        info = ''
    if not info:
        # 没找到展开控件：可能本就是短文书（已完整）；用残留标记区分，避免误判
        if any(m in _content_text(page) for m in _JUNK_MARKERS):
            log('⚠ 未找到「继续阅读」控件但正文仍含残留标记 → partial（请把本行上下文日志发我校正选择器）')
            return 'partial'
        return 'ok'
    log('命中展开控件：' + info.replace('|||', ' / '))   # 自诊断：回填精确选择器用

    # 2. 点击展开（text 定位 + by_js 兜底）
    expander = None
    for finder in (lambda: page.ele('text:继续阅读', timeout=1),
                   lambda: page.ele('text:未阅读', timeout=1),
                   lambda: page.ele('xpath://*[contains(text(),"继续阅读")]', timeout=1)):
        try:
            e = finder()
            if e:
                expander = e
                break
        except Exception:
            continue
    if expander:
        try:
            try:
                expander.scroll.to_see()
            except Exception:
                pass
            try:
                expander.click()
            except Exception:
                expander.click(by_js=True)
        except Exception as ex:
            log('点击「继续阅读」失败：%s' % ex)
            present, why = _popup_present(page)
            return 'popup' if present else 'partial'

    # 3. 等待：正文补全（残留消失 + 长度稳定）或弹窗出现
    last_len, stable = -1, 0
    end = time.time() + timeout
    while time.time() < end:
        time.sleep(0.5)
        present, why = _popup_present(page)
        if present:
            log('⚠ 点击后出现配额/注册弹窗（%s）→ 账号已达上限，停止整批' % why)
            return 'popup'
        txt = _content_text(page)
        has_junk = any(m in txt for m in _JUNK_MARKERS)
        cur = len(txt)
        stable = stable + 1 if (cur == last_len and cur > 0) else 0
        last_len = cur
        if (not has_junk) and stable >= 2:
            log('正文已展开完整（%d字）' % cur)
            return 'ok'

    # 4. 超时兜底
    if any(m in _content_text(page) for m in _JUNK_MARKERS):
        log('展开等待超时，正文仍含残留标记 → partial')
        return 'partial'
    log('展开等待超时，未见残留标记，按 ok 处理')
    return 'ok'


class CrawlerThread(QThread):
    """爬虫线程，避免界面卡死"""
    update_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)
    
    def __init__(self, crawler, mode):
        super().__init__()
        self.crawler = crawler
        self.mode = mode
        
    def run(self):
        try:
            # 重置爬虫状态
            self.crawler.state = 1
            self.crawler.stopped_by_popup = False

            if self.mode == 'collect':
                self.crawler.collect_urls(self)
                remaining = len(self.crawler.read_urls_from_file())
                self.finished_signal.emit(True, f"本页URL收集完成，当前共有{remaining}个URL待下载")
            elif self.mode == 'download':
                self.crawler.download_content(self)
                if getattr(self.crawler, 'stopped_by_popup', False):
                    self.finished_signal.emit(False, "账号已达下载上限（出现注册/配额弹窗），已停止。请更换账号或稍后再试。")
                    return
                remaining = len(self.crawler.read_urls_from_file())
                if remaining > 0:
                    self.finished_signal.emit(True, f"本批次下载完成，还有{remaining}个URL待下载")
                else:
                    self.finished_signal.emit(True, "所有URL已下载完成")
                
        except Exception as e:
            self.update_signal.emit(f"发生错误: {str(e)}")
            self.finished_signal.emit(False, f"爬虫任务失败: {str(e)}")


class PkulawCrawler:
    def __init__(self):
        # 文件路径设置
        # 使用相对路径，这样打包后也能正常工作
        base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        self.urls_file = os.path.join(base_dir, 'urls.txt')
        self.folder_path = os.path.join(base_dir, 'downloads')
        
        # 爬虫状态
        self.state = 1
        
        # 等待时间区间设置
        self.min_wait_time = 1
        self.max_wait_time = 10
        
        # 确保保存目录存在
        if not os.path.exists(self.folder_path):
            os.makedirs(self.folder_path)
            
        # 初始化时连接浏览器
        try:
            print("正在连接到Chrome浏览器...")
            page = Chromium('127.0.0.1:9333')
            self.page = page.latest_tab
            print(f"已连接到浏览器，当前页面标题: {self.page.title}")
        except Exception as e:
            print(f"连接浏览器时出错: {e}")
            self.page = None
    
    def set_folder_path(self, path):
        """设置保存文件夹路径"""
        self.folder_path = path
        if not os.path.exists(self.folder_path):
            os.makedirs(self.folder_path)
    
    def collect_urls(self, thread=None):
        """收集列表页面的URL"""
        if thread:
            thread.update_signal.emit("开始收集URL...")
        else:
            print("开始收集URL...")
        
        try:
            # 每次点击按钮时重新连接浏览器
            if thread:
                thread.update_signal.emit("正在连接到Chrome浏览器...")
            else:
                print("正在连接到Chrome浏览器...")
                
            page = Chromium('127.0.0.1:9333')
            page = page.latest_tab
            
            if thread:
                thread.update_signal.emit(f'当前页面标题: {page.title}')
            else:
                print(f'当前页面标题: {page.title}')
            
            # 获取已存储的URL集合
            existing_urls = self.read_urls_from_file()
            
            # 获取页面上的元素
            target = page.ele('tag:tbody')
            if not target:
                if thread:
                    thread.update_signal.emit("未找到tbody元素，请确认页面已正确加载")
                else:
                    print("未找到tbody元素，请确认页面已正确加载")
                return
                
            items = target.eles('tag:tr')
            
            # 计数器
            new_count = 0
            total_items = len(items)
            
            for i, item in enumerate(items):
                url = item.ele('tag:a').attr('href')
                if url not in existing_urls:
                    # 添加到集合并写入文件
                    existing_urls.add(url)
                    self.append_url_to_file(url)
                    if thread:
                        thread.update_signal.emit(f'添加成功: {url}')
                    else:
                        print(f'添加成功: {url}')
                    new_count += 1
                else:
                    if thread:
                        thread.update_signal.emit(f'已存在: {url}')
                    else:
                        print(f'已存在: {url}')
                
                # 更新进度
                if thread:
                    progress = int((i + 1) / total_items * 100)
                    thread.progress_signal.emit(progress)
            
            if thread:
                thread.update_signal.emit(f"URL收集完成，新增{new_count}个URL")
            else:
                print(f"URL收集完成，新增{new_count}个URL")
            
        except Exception as e:
            if thread:
                thread.update_signal.emit(f"收集URL时出错: {e}")
            else:
                print(f"收集URL时出错: {e}")
    
    def download_content(self, thread=None):
        """下载URL对应的详细内容"""
        # 重置爬虫状态，确保每次下载都是从正常状态开始
        self.state = 1
        
        if thread:
            thread.update_signal.emit("开始下载内容...")
        else:
            print("开始下载内容...")
        
        # 创建新的浏览器实例用于下载
        page = ChromiumPage()
        
        # 读取所有URL
        urls = self.read_urls_from_file()
        
        if not urls:
            if thread:
                thread.update_signal.emit("没有URL需要下载")
            else:
                print("没有URL需要下载")
            return
        
        total_urls = len(urls)
        if thread:
            thread.update_signal.emit(f"共有{total_urls}个URL等待下载")
        else:
            print(f"共有{total_urls}个URL等待下载")
        
        # 下载计数
        success_count = 0
        
        # 设置每次下载的URL数量限制，可以根据需要调整
        batch_size = 10000
        urls_list = list(urls)[:batch_size]
        
        for i, url in enumerate(urls_list):  # 每次只处理一部分URL
            try:
                # 保护机制，使用用户设置的等待时间区间
                wait_time = random.randint(self.min_wait_time, self.max_wait_time)
                if thread:
                    thread.update_signal.emit(f"等待{wait_time}秒...")
                else:
                    print(f"等待{wait_time}秒...")
                time.sleep(wait_time)
                
                if self.state == 0:
                    if thread:
                        thread.update_signal.emit("程序被中断")
                    else:
                        print("程序被中断")
                    break
                
                # 下载内容
                page.get(url)
                time.sleep(2)
                
                # 展开「继续阅读」+ 判配额弹窗（修复：原来只取到前 50% 正文 + 残留垃圾串）
                status = expand_full_text(page, log=(thread.update_signal.emit if thread else print))
                if status == 'popup':
                    msg = '⚠ 账号已达下载上限（出现“完善信息”注册/配额弹窗），已停止下载。请更换账号或稍后再试。'
                    if thread:
                        thread.update_signal.emit(msg)
                    else:
                        print(msg)
                    self.stopped_by_popup = True
                    self.state = 0          # 复用既有“致命错误停止”机制
                    break
                if status == 'partial':
                    if thread:
                        thread.update_signal.emit(f'正文展开不完整，跳过(保留URL重试): {url}')
                    else:
                        print(f'正文展开不完整，跳过(保留URL重试): {url}')
                    continue                # 不删 URL、不写文件，下次可重试

                # 获取文本内容
                wenben = page.ele('.fulltext').text
                title = wenben.split()[0]
                if thread:
                    thread.update_signal.emit(f"正在下载: {title}")
                else:
                    print(f"正在下载: {title}")
                
                # 处理文件名中的非法字符
                for c in "*?:<>|/\\":
                    if c in title:
                        title = title.replace(c, '某')
                
                # 保存前校验：正文若仍含残留标记则跳过不写（避免存半截垃圾文件）
                if not content_is_clean(wenben):
                    if thread:
                        thread.update_signal.emit(f'正文仍含残留标记，跳过不保存: {url}')
                    else:
                        print(f'正文仍含残留标记，跳过不保存: {url}')
                    continue

                # 保存到文件
                file_path = os.path.join(self.folder_path, f'{title}.txt')
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(wenben)
                
                # 下载成功后从文件中删除该URL
                self.remove_url_from_file(url)
                success_count += 1
                if thread:
                    thread.update_signal.emit(f"下载成功: {title}")
                    # 更新进度
                    progress = int((i + 1) / len(urls_list) * 100)
                    thread.progress_signal.emit(progress)
                else:
                    print(f"下载成功: {title}")
                
            except Exception as e:
                if thread:
                    thread.update_signal.emit(f'下载失败 {url}: {e}')
                else:
                    print(f'下载失败 {url}: {e}')
                # 如果是致命错误，设置状态为0中断程序
                if "无法连接" in str(e) or "timeout" in str(e).lower():
                    self.state = 0
                    if thread:
                        thread.update_signal.emit("检测到网络问题，程序中断")
                    else:
                        print("检测到网络问题，程序中断")
                    break
        
        remaining = len(self.read_urls_from_file())
        if thread:
            thread.update_signal.emit(f"本次下载完成，成功下载{success_count}个文件，还剩{remaining}个URL待下载")
        else:
            print(f"本次下载完成，成功下载{success_count}个文件，还剩{remaining}个URL待下载")
        page.quit()
    
    def read_urls_from_file(self):
        """从文件读取URL集合"""
        urls = set()
        if os.path.exists(self.urls_file):
            with open(self.urls_file, 'r', encoding='utf-8') as f:
                for line in f:
                    url = line.strip()
                    if url:
                        urls.add(url)
        return urls
    
    def append_url_to_file(self, url):
        """将URL追加到文件"""
        with open(self.urls_file, 'a', encoding='utf-8') as f:
            f.write(url + '\n')
    
    def remove_url_from_file(self, url_to_remove):
        """从文件中删除指定URL"""
        urls = self.read_urls_from_file()
        urls.discard(url_to_remove)
        
        with open(self.urls_file, 'w', encoding='utf-8') as f:
            for url in urls:
                f.write(url + '\n')


class PkulawCrawlerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.crawler = PkulawCrawler()
        self.init_ui()
        
    def init_ui(self):
        """初始化UI界面"""
        self.setWindowTitle('北大法宝爬虫 - by hjhhoni')
        self.setGeometry(300, 300, 800, 600)
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QGroupBox {
                border: 1px solid #cccccc;
                border-radius: 5px;
                margin-top: 10px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QPushButton {
                background-color: #4a86e8;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #3a76d8;
            }
            QPushButton:pressed {
                background-color: #2a66c8;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
            QLineEdit, QComboBox {
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 6px;
                background-color: white;
            }
            QTextEdit {
                border: 1px solid #cccccc;
                border-radius: 4px;
                background-color: white;
                font-family: Consolas, Monaco, monospace;
            }
            QProgressBar {
                border: 1px solid #cccccc;
                border-radius: 4px;
                text-align: center;
                background-color: #f0f0f0;
            }
            QProgressBar::chunk {
                background-color: #4a86e8;
                width: 10px;
                margin: 0.5px;
            }
        """)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # 设置组
        settings_group = QGroupBox("设置")
        settings_layout = QVBoxLayout(settings_group)
        
        # 文件夹选择
        folder_layout = QHBoxLayout()
        folder_label = QLabel("保存文件夹:")
        self.folder_edit = QLineEdit(self.crawler.folder_path)
        self.folder_edit.setReadOnly(True)
        browse_button = QPushButton("浏览...")
        browse_button.setFixedWidth(100)
        browse_button.clicked.connect(self.browse_folder)
        
        folder_layout.addWidget(folder_label)
        folder_layout.addWidget(self.folder_edit)
        folder_layout.addWidget(browse_button)
        settings_layout.addLayout(folder_layout)
        
        # URL文件路径
        url_layout = QHBoxLayout()
        url_label = QLabel("URL文件:")
        self.url_edit = QLineEdit(self.crawler.urls_file)
        self.url_edit.setReadOnly(True)
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_edit)
        settings_layout.addLayout(url_layout)
        
        # 等待时间设置
        wait_time_layout = QHBoxLayout()
        wait_time_label = QLabel("等待时间区间(秒):")
        self.min_wait_edit = QLineEdit(str(self.crawler.min_wait_time))
        self.min_wait_edit.setFixedWidth(50)
        wait_time_to_label = QLabel("到")
        self.max_wait_edit = QLineEdit(str(self.crawler.max_wait_time))
        self.max_wait_edit.setFixedWidth(50)
        wait_time_layout.addWidget(wait_time_label)
        wait_time_layout.addWidget(self.min_wait_edit)
        wait_time_layout.addWidget(wait_time_to_label)
        wait_time_layout.addWidget(self.max_wait_edit)
        wait_time_layout.addStretch()
        settings_layout.addLayout(wait_time_layout)
        
        main_layout.addWidget(settings_group)
        
        # 操作按钮组
        action_group = QGroupBox("操作")
        action_layout = QHBoxLayout(action_group)
        
        self.collect_button = QPushButton("收集URL")
        self.collect_button.clicked.connect(lambda: self.start_crawler('collect'))
        
        self.download_button = QPushButton("下载内容")
        self.download_button.clicked.connect(lambda: self.start_crawler('download'))
        
        self.stop_button = QPushButton("停止爬虫")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_crawler)
        
        action_layout.addWidget(self.collect_button)
        action_layout.addWidget(self.download_button)
        action_layout.addWidget(self.stop_button)
        
        main_layout.addWidget(action_group)
        
        # 进度条
        progress_group = QGroupBox("进度")
        progress_layout = QVBoxLayout(progress_group)
        self.progress_bar = QProgressBar()
        progress_layout.addWidget(self.progress_bar)
        
        main_layout.addWidget(progress_group)
        
        # 日志输出
        log_group = QGroupBox("日志")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        
        main_layout.addWidget(log_group)
        
        # 添加版权信息
        copyright_label = QLabel("©2025 hjhhoni. All Rights Reserved.")
        copyright_label.setAlignment(Qt.AlignCenter)
        copyright_label.setStyleSheet("color: #888888; font-size: 17px; font-weight: bold;")
        main_layout.addWidget(copyright_label)
        
        # 状态栏
        self.statusBar().showMessage('就绪')
        
        # 显示窗口
        self.show()
        
        # 初始日志
        if self.crawler.page:
            self.log(f"已连接到浏览器，当前页面标题: {self.crawler.page.title}")
            self.log("请导航到目标页面，然后点击'收集URL'按钮")
        else:
            self.log("连接浏览器失败，请确保Chrome浏览器已打开并在端口9333上运行")
    
    def browse_folder(self):
        """浏览并选择保存文件夹"""
        folder = QFileDialog.getExistingDirectory(self, "选择保存文件夹", self.crawler.folder_path)
        if folder:
            self.folder_edit.setText(folder)
            self.crawler.set_folder_path(folder)
            self.log("已设置保存文件夹: " + folder)
    
    def log(self, message):
        """添加日志消息"""
        self.log_text.append(message)
        # 滚动到底部
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
    
    def start_crawler(self, mode):
        """启动爬虫"""
        # 更新等待时间设置
        try:
            min_wait = int(self.min_wait_edit.text())
            max_wait = int(self.max_wait_edit.text())
            if min_wait > 0 and max_wait >= min_wait:
                self.crawler.min_wait_time = min_wait
                self.crawler.max_wait_time = max_wait
            else:
                self.log("等待时间设置无效，使用默认值")
                self.min_wait_edit.setText(str(1))
                self.max_wait_edit.setText(str(10))
                self.crawler.min_wait_time = 1
                self.crawler.max_wait_time = 10
        except ValueError:
            self.log("等待时间必须是整数，使用默认值")
            self.min_wait_edit.setText(str(1))
            self.max_wait_edit.setText(str(10))
            self.crawler.min_wait_time = 1
            self.crawler.max_wait_time = 10
        
        # 重置爬虫状态
        self.crawler.state = 1
        
        self.collect_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress_bar.setValue(0)
        
        # 创建线程并连接信号
        self.crawler_thread = CrawlerThread(self.crawler, mode)
        self.crawler_thread.update_signal.connect(self.log)
        self.crawler_thread.progress_signal.connect(self.update_progress)
        self.crawler_thread.finished_signal.connect(self.crawler_finished)
        self.crawler_thread.start()
    
    def stop_crawler(self):
        """停止爬虫"""
        self.crawler.state = 0
        self.log("正在停止爬虫...")
        self.stop_button.setEnabled(False)
    
    def update_progress(self, value):
        """更新进度条"""
        self.progress_bar.setValue(value)
    
    def crawler_finished(self, success, message):
        """爬虫完成回调"""
        self.log(message)
        self.collect_button.setEnabled(True)
        self.download_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.statusBar().showMessage('就绪')
        
        if success:
            QMessageBox.information(self, "完成", message)
        else:
            QMessageBox.warning(self, "错误", message)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    gui = PkulawCrawlerGUI()
    sys.exit(app.exec_())