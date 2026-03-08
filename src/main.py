# src/main.py

import sys
import os

# 프로젝트의 src 폴더를 경로에 강제 추가 (모듈 인식 오류 원천 차단)
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from PySide6.QtWidgets import QApplication
from gui.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    
    # R&D 다크 테마 및 안정화된 분할선 스타일
    app.setStyleSheet("""
        QMainWindow { background-color: #1e1e1e; }
        QSplitter::handle { background-color: #333333; }
        QSplitter::handle:horizontal { width: 5px; }
        QSplitter::handle:vertical { height: 5px; }
        QSplitter::handle:hover { background-color: #4CAF50; }
        QTabBar::tab { padding: 8px 15px; font-weight: bold; background-color: #2b2b2b; color: #aaaaaa; }
        QTabBar::tab:selected { background-color: #4CAF50; color: white; }
        QTreeView { background-color: #ffffff; color: #333333; border: none; }
    """)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()