from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)


def show_unlock_dialog(parent):
    """
    显示高级用户功能解锁说明弹窗
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle("高级用户功能解锁说明")
    dialog.setModal(True)
    dialog.resize(700, 550)

    # 设置窗口标志，确保弹窗置顶
    dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)

    layout = QVBoxLayout(dialog)

    # 标题
    title_label = QLabel("🔓 高级用户功能解锁")
    title_font = QFont()
    title_font.setPixelSize(21)
    title_font.setBold(True)
    title_label.setFont(title_font)
    title_label.setAlignment(Qt.AlignCenter)
    layout.addWidget(title_label)

    # 分隔线
    line1 = QLabel("─" * 50)
    line1.setAlignment(Qt.AlignCenter)
    layout.addWidget(line1)

    # 说明内容文本框（带滚动条）
    text_browser = QTextBrowser()
    text_browser.setOpenExternalLinks(True)  # 允许点击链接

    unlock_content = r"""
# 如何解锁高级用户功能？

## 📌 解锁方式

为了获得高级用户功能的访问权限，您需要完成以下步骤：

### 方式一：GitHub 免费点亮 ⭐ Star 支持（推荐）

1. **访问本项目 GitHub 仓库**
   - 项目地址：[https://github.com/syfoud/Simulated_Scepter](https://github.com/syfoud/Simulated_Scepter)
   - 若因网络问题无法进入 或 访问缓慢，查看QQ群（见下文）内置顶群公告的“常见问题文档”以解决
   
2. **点击 Star 按钮**
   - 在页面右上角找到 ⭐ Star 按钮
   - 点击即可为项目点亮 ⭐ Star

3. **截图保存**
   - 保持在上一步刚点亮 ⭐ Star 的页面
   - 截取包含您的 GitHub 用户名（鼠标点击右上角头像即可显示）和 ⭐ Star 状态的完整页面
   - 确保截图中能清晰看到您已 ⭐ Star 该项目

### 方式二：赞助开发者

如果您希望进一步支持项目开发，可以选择赞助：

- **赞助方式**：请联系开发者获取赞助渠道（README.md中有）
- **赞助金额**：随意，一杯咖啡即可 ☕
- **赞助福利**：优先技术支持 + 高级功能解锁

---

## 📸 联系开发者或管理者

完成上述任一方式后，请按以下步骤操作：

### 步骤 1：准备截图
- 项目点 ⭐ Star 页面截图 **或** 赞助凭证截图
- 确保截图清晰可见

### 步骤 2：加入 QQ 群
-（两个群任选其一，无区别。若同时申请加俩群，则随机拉进群黑名单）
- **QQ 一群**：1072802257（上限500人）
- **QQ 二群**：870863632（上限2000人）
- 群问题仅用于证明你确实是一名崩铁玩家，且具备最基础的尝试自主解决问题的态度与能力，与剧情无关
- 因此，不正常回答群问题，答非所问的，疑似人机/广告的，视程度拒绝或拉进群黑名单

### 步骤 3：提交申请以获取密码
- 关于这一步，查看QQ群内的置顶群公告

### 步骤 4：使用密码
- 下载群文件内的加密压缩包（ *群文件/模拟权杖程序&密钥* 目录下的**cipher(进阶功能扩展包).7z**）
- 使用上一步获得的密码解压（请勿使用 WPS 解压，可能显示密码错误）
- 将解压出的 **kesln.onnx** 文件放置于 **程序主目录/user/** 目录下
- 关闭并重新启动本软件
---
"""

    text_browser.setMarkdown(unlock_content)
    layout.addWidget(text_browser)

    # 按钮区域
    button_layout = QHBoxLayout()

    github_btn = QPushButton("前往 GitHub")
    close_btn = QPushButton("关闭")

    # 设置按钮样式
    github_btn.setStyleSheet("""
        QPushButton {
            background-color: #24292e;
            color: white;
            padding: 10px 20px;
            border-radius: 5px;
            font-weight: bold;
            font-size: 12px;
        }
        QPushButton:hover {
            background-color: #1b1f23;
        }
    """)


    close_btn.setStyleSheet("""
        QPushButton {
            background-color: #6c757d;
            color: white;
            padding: 10px 20px;
            border-radius: 5px;
            font-size: 12px;
        }
        QPushButton:hover {
            background-color: #5a6268;
        }
    """)

    button_layout.addWidget(github_btn)
    button_layout.addWidget(close_btn)
    layout.addLayout(button_layout)

    # 按钮事件处理
    def open_github():
        import webbrowser
        webbrowser.open("https://github.com/syfoud/Simulated_Scepter")


    github_btn.clicked.connect(open_github)
    close_btn.clicked.connect(dialog.close)

    # 显示弹窗
    dialog.exec_()

