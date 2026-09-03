import re
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont
from PySide6.QtCore import Qt

class PythonSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighting_rules = []

        # Keyword format
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#569cd6"))
        keyword_format.setFontWeight(QFont.Bold)
        keywords = [
            "and", "as", "assert", "break", "class", "continue", "def",
            "del", "elif", "else", "except", "False", "finally", "for",
            "from", "global", "if", "import", "in", "is", "lambda", "None",
            "nonlocal", "not", "or", "pass", "raise", "return", "True",
            "try", "while", "with", "yield"
        ]
        for word in keywords:
            pattern = re.compile(r"\b" + word + r"\b")
            self.highlighting_rules.append((pattern, keyword_format))

        # API Functions format
        api_format = QTextCharFormat()
        api_format.setForeground(QColor("#4ec9b0"))
        api_format.setFontWeight(QFont.Bold)
        api_funcs = [
            "capture_frame", "set_exposure", "set_exposure_ms", "set_exposure_ev",
            "send_to_screen", "set_servo_angle", "get_servo_angle", "set_detected_spot"
        ]
        for func in api_funcs:
            pattern = re.compile(r"\b" + func + r"\b")
            self.highlighting_rules.append((pattern, api_format))

        # String format
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#ce9178"))
        self.highlighting_rules.append((re.compile(r'"[^"\\]*(\\.[^"\\]*)*"'), string_format))
        self.highlighting_rules.append((re.compile(r"'[^'\\]*(\\.[^'\\]*)*'"), string_format))

        # Comment format
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#6a9955"))
        self.highlighting_rules.append((re.compile(r"#[^\n]*"), comment_format))

        # Number format
        number_format = QTextCharFormat()
        number_format.setForeground(QColor("#b5cea8"))
        self.highlighting_rules.append((re.compile(r"\b[0-9]+(\.[0-9]+)?\b"), number_format))

    def highlightBlock(self, text):
        for pattern, format in self.highlighting_rules:
            for match in pattern.finditer(text):
                start, end = match.span()
                self.setFormat(start, end - start, format)
