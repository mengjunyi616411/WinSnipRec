"""First-run guide.

The window doubles as the preview: it is a real FluentWindow, so picking a
style or a theme changes the very window the user is looking at. There are no
thumbnails to keep in sync and nothing can drift from the real appearance.

The light-strength step needs no preview widget either - the window already
carries the pointer light, so moving the mouse over it demonstrates the setting.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import icons
from ..i18n import t as _t
from ..settings import settings
from ..theme import apply_app_theme, rgba, theme
from .widgets import FluentButton, FluentWindow, Separator, TitleBar

RAIL_WIDTH = 176
CARD_WIDTH = 720
CARD_HEIGHT = 470

STYLE_CHOICES = [("win11", "Windows 11"), ("win10", "Windows 10")]
THEME_CHOICES = ["system", "light", "dark"]
BACKDROP_CHOICES = ["auto", "classic", "native"]
REVEAL_CHOICES = ["weak", "normal", "strong"]

#: The guide currently on screen, so the app only holds one and a language
#: change can replace it without the caller having to keep track.
_current: "OnboardingWindow | None" = None


def _language_options() -> list[tuple[str, str]]:
    from .. import i18n

    return i18n.available()


def _button(text: str, parent: QWidget, *, variant: str = "standard",
            on_click=None) -> FluentButton:
    """FluentButton has no `command` argument, so wire the click here.

    clicked() carries a `checked: bool`, and PySide hands it to any slot that
    accepts one argument. Connecting the callback directly meant every click
    arrived as False - i.e. index 0 - so the first option was always chosen.
    """
    button = FluentButton(text, parent, variant=variant)
    if on_click is not None:
        button.clicked.connect(lambda _checked=False: on_click())
    return button


def _theme_labels() -> list[str]:
    return [_t("跟随系统"), _t("浅色"), _t("深色")]


def _backdrop_labels() -> list[str]:
    return [_t("自动"), _t("经典（壁纸）"), _t("强制实时")]


def _reveal_labels() -> list[str]:
    return [_t("低"), _t("中"), _t("高")]


class _StepItem(QWidget):
    """One entry in the left rail: number badge plus title."""

    clicked = Signal(int)

    def __init__(self, index: int, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = index
        self.title = title
        self._active = False
        self.setFixedHeight(40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def set_active(self, active: bool) -> None:
        if self._active != active:
            self._active = active
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtGui import QFont, QPainter, QPainterPath

        palette = theme.palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        diameter = 22.0
        centre_y = self.height() / 2
        centre_x = 12 + diameter / 2
        circle = QPainterPath()
        circle.addEllipse(centre_x - diameter / 2, centre_y - diameter / 2,
                          diameter, diameter)
        if self._active:
            painter.fillPath(circle, QColor(palette.accent))
        elif self.underMouse():
            painter.fillPath(circle, rgba(palette.text_primary, 0.10))
        else:
            painter.fillPath(circle, rgba(palette.text_secondary, 0.16))

        font = QFont(self.font())
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF") if self._active else QColor(palette.text_secondary))
        painter.drawText(int(centre_x - diameter / 2), int(centre_y - diameter / 2),
                         int(diameter), int(diameter),
                         Qt.AlignmentFlag.AlignCenter, str(self.index + 1))

        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold if self._active else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(palette.text_primary if self._active
                              else palette.text_secondary))
        painter.drawText(int(centre_x + diameter / 2 + 12), 0,
                         int(self.width() - centre_x - diameter / 2 - 16), self.height(),
                         Qt.AlignmentFlag.AlignVCenter, self.title)
        painter.end()


class _ChoiceRow(QWidget):
    """A row of buttons where exactly one is selected."""

    changed = Signal(int)

    def __init__(self, labels: list[str], current: int,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._buttons: list[FluentButton] = []
        for index, label in enumerate(labels):
            button = _button(label, self, on_click=lambda i=index: self.select(i))
            button.setMinimumWidth(108)
            button.setMinimumHeight(36)
            self._buttons.append(button)
            layout.addWidget(button)
        layout.addStretch(1)
        self.select(current, emit=False)

    def select(self, index: int, *, emit: bool = True) -> None:
        for position, button in enumerate(self._buttons):
            new_variant = "accent" if position == index else "standard"
            if button.variant != new_variant:
                button.variant = new_variant
                # FluentButton draws everything in paintEvent; there is no
                # refresh() method, just repaint with the new variant.
                button.update()
        if emit:
            self.changed.emit(index)

    def current(self) -> int:
        for index, button in enumerate(self._buttons):
            if button.variant == "accent":
                return index
        return 0


class _StepPage(QWidget):
    """Title, description and one control."""

    def __init__(self, title: str, description: str, control: QWidget | None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setSpacing(10)

        self.heading = QLabel(title, self)
        self.heading.setObjectName("onboardingTitle")
        layout.addWidget(self.heading)

        self.body = QLabel(description, self)
        self.body.setObjectName("onboardingBody")
        self.body.setWordWrap(True)
        self.body.setMinimumHeight(62)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.body)

        self.control = control
        if control is not None:
            layout.addSpacing(4)
            layout.addWidget(control)
        layout.addStretch(1)


class OnboardingWindow(FluentWindow):
    """The guided first-run setup."""

    finished = Signal()

    def __init__(self) -> None:
        super().__init__(resizable=False, open_animation="slide")
        self.setWindowTitle(_t("首次使用引导"))
        self.set_card_size(CARD_WIDTH, CARD_HEIGHT)

        self._index = 0
        self._pages: list[_StepPage] = []
        self._items: list[_StepItem] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(self._margin, self._margin, self._margin, self._margin)
        root.setSpacing(0)

        self.title_bar = TitleBar(_t("首次使用引导"), self)
        self.title_bar.icon_label.setPixmap(icons.app_icon().pixmap(16, 16))
        self.title_bar.caption_buttons["min"].clicked.connect(self.minimize_animated)
        self.title_bar.caption_buttons["close"].clicked.connect(self._on_skip)
        root.addWidget(self.title_bar)

        body = QWidget(self)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(18, 10, 22, 6)
        body_layout.setSpacing(16)

        self.rail = QWidget(body)
        self.rail.setFixedWidth(RAIL_WIDTH)
        self.rail_layout = QVBoxLayout(self.rail)
        self.rail_layout.setContentsMargins(0, 4, 0, 0)
        self.rail_layout.setSpacing(2)

        self.stack = QStackedWidget(body)
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        body_layout.addWidget(self.rail)
        body_layout.addWidget(self.stack, 1)
        root.addWidget(body, 1)
        root.addWidget(Separator(self, vertical=False))

        footer = QWidget(self)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(22, 10, 22, 16)
        footer_layout.setSpacing(10)
        self.skip_button = _button(_t("跳过"), footer, variant="hyperlink",
                                   on_click=self._on_skip)
        self.step_label = QLabel("", footer)
        self.step_label.setObjectName("onboardingStep")
        self.back_button = _button(_t("上一步"), footer, on_click=self._on_back)
        self.next_button = _button(_t("下一步"), footer, variant="accent",
                                   on_click=self._on_next)
        footer_layout.addWidget(self.skip_button)
        footer_layout.addWidget(self.step_label)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self.back_button)
        footer_layout.addWidget(self.next_button)
        root.addWidget(footer)

        self._build_steps()
        self.refresh_theme()
        self._go_to(0)

    # ------------------------------------------------------------------ #
    # Building
    # ------------------------------------------------------------------ #
    def _add_step(self, rail_title: str, page: _StepPage) -> None:
        index = len(self._pages)
        item = _StepItem(index, rail_title, self.rail)
        item.clicked.connect(self._go_to)
        self.rail_layout.addWidget(item)
        self._items.append(item)
        self._pages.append(page)
        self.stack.addWidget(page)

    def _build_steps(self) -> None:
        # 1) 欢迎
        welcome = QWidget(self)
        welcome_layout = QVBoxLayout(welcome)
        welcome_layout.setContentsMargins(8, 22, 8, 8)
        welcome_layout.setSpacing(14)
        mark = QLabel(welcome)
        mark.setPixmap(icons.app_icon().pixmap(56, 56))
        welcome_layout.addWidget(mark)
        welcome_title = QLabel(_t("让截图工具变成你喜欢的样子"), welcome)
        welcome_title.setObjectName("onboardingTitle")
        welcome_layout.addWidget(welcome_title)
        welcome_body = QLabel(
            _t("接下来几个问题，帮你把外观调成自己喜欢的样子。"
               "每一步都会立刻作用在这个窗口上，你能直接看到效果。"), welcome)
        welcome_body.setObjectName("onboardingBody")
        welcome_body.setWordWrap(True)
        welcome_layout.addWidget(welcome_body)
        welcome_layout.addStretch(1)
        welcome_hint = QLabel(_t("这些选项随时可以在设置里修改"), welcome)
        welcome_hint.setObjectName("onboardingStep")
        welcome_layout.addWidget(welcome_hint)
        # Registered as a real step: adding it straight to the stack left it
        # unreachable, so the guide opened on the style page instead.
        self._add_step(_t("欢迎"), welcome)

        # 2) 界面风格
        self.style_choice = _ChoiceRow([label for _v, label in STYLE_CHOICES],
                                       self._style_index())
        self.style_choice.changed.connect(self._on_style)
        self._add_step(_t("界面风格"), _StepPage(
            _t("界面风格"),
            _t("选一个你更习惯的外观。选中的那一刻，这个窗口就会变成那个样子——"
               "圆角、材质和标题栏按钮都会跟着变。"),
            self.style_choice, self))

        # 3) 主题
        self.theme_choice = _ChoiceRow(_theme_labels(), self._theme_index())
        self.theme_choice.changed.connect(self._on_theme)
        self._add_step(_t("主题"), _StepPage(
            _t("主题"),
            _t("浅色或深色。选「跟随系统」就跟着 Windows 的设置走，"
               "系统切成深色时这个窗口也会变。"),
            self.theme_choice, self))

        # 4) 背景材质
        self.backdrop_choice = _ChoiceRow(_backdrop_labels(), self._backdrop_index())
        self.backdrop_choice.changed.connect(self._on_backdrop)
        self._add_step(_t("背景材质"), _StepPage(
            _t("背景材质"), self._backdrop_note(), self.backdrop_choice, self))

        # 5) 光效强度
        self.reveal_choice = _ChoiceRow(_reveal_labels(), self._reveal_index())
        self.reveal_choice.changed.connect(self._on_reveal)
        self._add_step(_t("光效强度"), _StepPage(
            _t("光效强度"),
            _t("Windows 10 风格下，鼠标移动会带起一束光。把鼠标移到这个窗口上划一划，"
               "就能感受到当前档位的强弱。"),
            self.reveal_choice, self))

        # 6) 界面语言
        self.language_choice = _ChoiceRow(
            [label for _code, label in _language_options()], self._language_index())
        self.language_choice.changed.connect(self._on_language)
        self._add_step(_t("界面语言"), _StepPage(
            _t("界面语言"),
            _t("界面文字的显示语言。选「跟随系统」就跟着 Windows 的显示语言走。"),
            self.language_choice, self))

        # 7) 完成
        done = QWidget(self)
        done_layout = QVBoxLayout(done)
        done_layout.setContentsMargins(8, 22, 8, 8)
        done_layout.setSpacing(12)
        done_title = QLabel(_t("都设置好了"), done)
        done_title.setObjectName("onboardingTitle")
        done_layout.addWidget(done_title)
        done_body = QLabel(_t("这些选项随时可以在设置里修改，也可以再运行一次这个引导。"),
                           done)
        done_body.setObjectName("onboardingBody")
        done_body.setWordWrap(True)
        done_layout.addWidget(done_body)
        self.summary = QLabel("", done)
        self.summary.setObjectName("onboardingSummary")
        self.summary.setWordWrap(True)
        done_layout.addWidget(self.summary)
        done_layout.addStretch(1)
        self.stack.addWidget(done)
        self._done_page = done

    # ------------------------------------------------------------------ #
    # Current values
    # ------------------------------------------------------------------ #
    @staticmethod
    def _style_index() -> int:
        value = getattr(settings, "style", "win11")
        for index, (code, _label) in enumerate(STYLE_CHOICES):
            if code == value:
                return index
        return 0

    @staticmethod
    def _theme_index() -> int:
        return {"system": 0, "light": 1, "dark": 2}.get(settings.theme, 0)

    @staticmethod
    def _backdrop_index() -> int:
        return {"auto": 0, "classic": 1, "native": 2}.get(
            getattr(settings, "backdrop", "auto"), 0)

    @staticmethod
    def _reveal_index() -> int:
        return {"weak": 0, "normal": 1, "strong": 2}.get(
            getattr(settings, "reveal_strength", "weak"), 0)

    @staticmethod
    def _language_index() -> int:
        current = getattr(settings, "language", "system")
        for index, (code, _label) in enumerate(_language_options()):
            if code == current:
                return index
        return 0

    def _backdrop_note(self) -> str:
        try:
            from .. import backdrop

            supported = backdrop.native_available()
        except Exception:
            supported = False
        if supported:
            return _t("本机支持实时模糊，用它更真实；不支持时会自动回退")
        return _t("本机实测不支持系统实时模糊（已自动回退到壁纸材质）")

    # ------------------------------------------------------------------ #
    # Applying a choice
    # ------------------------------------------------------------------ #
    def _persist(self, **values) -> None:
        for key, value in values.items():
            setattr(settings, key, value)
        try:
            settings.save()
        except Exception:
            pass

    def _on_style(self, index: int) -> None:
        style = STYLE_CHOICES[index][0]
        self._persist(style=style)
        theme.style = style
        theme.refresh()
        self._refresh_everything()

    def _on_theme(self, index: int) -> None:
        mode = THEME_CHOICES[index]
        self._persist(theme=mode)
        theme.mode = mode
        theme.refresh()
        self._refresh_everything()

    def _on_backdrop(self, index: int) -> None:
        self._persist(backdrop=BACKDROP_CHOICES[index])
        # A backdrop is chosen when a window is created, so it applies to windows
        # opened from now on - say that instead of implying it changed this one.
        self._pages[3].body.setText(
            self._backdrop_note() + "\n" + _t("切换背景材质后，新打开的窗口会使用它"))

    def _on_reveal(self, index: int) -> None:
        self._persist(reveal_strength=REVEAL_CHOICES[index])
        self._refresh_everything()

    def _on_language(self, index: int) -> None:
        code = _language_options()[index][0]
        self._persist(language=code)
        from .. import i18n
        from .widgets import retranslate_windows

        i18n.set_language(code)
        # The guide rebuilds itself below, but the main window stays open behind
        # it - without this it kept the old language, which looked exactly like
        # the setting had not worked at all.
        retranslate_windows()
        # Every label would have to be re-translated in place; rebuilding the
        # short-lived guide is simpler and cannot miss one.
        restart_onboarding(step=len(self._pages))

    # ------------------------------------------------------------------ #
    # Navigation
    # ------------------------------------------------------------------ #
    @property
    def total_steps(self) -> int:
        return len(self._pages) + 1          # content pages plus the summary

    def _go_to(self, index: int) -> None:
        index = max(0, min(self.total_steps - 1, index))
        self._index = index
        if index >= len(self._pages):
            self._update_summary()
            self.stack.setCurrentWidget(self._done_page)
        else:
            self.stack.setCurrentWidget(self._pages[index])
        for position, item in enumerate(self._items):
            item.set_active(position == index)
        last = index >= len(self._pages)
        self.back_button.setVisible(index > 0)
        self.next_button.setText(_t("完成") if last else _t("下一步"))
        self.step_label.setText(_t("第 {0} / {1} 步").format(index + 1, self.total_steps))
        self.skip_button.setVisible(not last)

    def _on_back(self) -> None:
        self._go_to(self._index - 1)

    def _on_next(self) -> None:
        if self._index >= len(self._pages):
            self._finish()
            return
        self._go_to(self._index + 1)

    def _on_skip(self) -> None:
        self._persist(onboarded=True)
        self.finished.emit()
        self.close()

    def _finish(self) -> None:
        self._persist(onboarded=True)
        self.finished.emit()
        self.close()

    def _update_summary(self) -> None:
        self.summary.setText("\n".join([
            _t("界面风格：{0}").format(STYLE_CHOICES[self.style_choice.current()][1]),
            _t("主题：{0}").format(_theme_labels()[self.theme_choice.current()]),
            _t("背景材质：{0}").format(_backdrop_labels()[self.backdrop_choice.current()]),
            _t("光效强度：{0}").format(_reveal_labels()[self.reveal_choice.current()]),
            _t("界面语言：{0}").format(
                [label for _c, label in _language_options()][self.language_choice.current()]),
        ]))

    # ------------------------------------------------------------------ #
    # Theme
    # ------------------------------------------------------------------ #
    def _refresh_everything(self) -> None:
        app = QApplication.instance()
        if app is not None:
            apply_app_theme(app)
        self.refresh_theme()
        # A style change moves the corner radius and the shadow margin, so the
        # card has to be re-rendered rather than merely repainted.
        self.invalidate_backdrop()
        self.update()

    def refresh_theme(self) -> None:
        palette = theme.palette
        self.setStyleSheet(f"""
            QLabel#onboardingTitle {{
                font-size: 20px; font-weight: 600; color: {palette.text_primary};
            }}
            QLabel#onboardingBody {{
                font-size: 13px; color: {palette.text_secondary};
            }}
            QLabel#onboardingStep {{
                font-size: 12px; color: {palette.text_secondary};
            }}
            QLabel#onboardingSummary {{
                font-size: 13px; color: {palette.text_primary};
                background: {rgba(palette.text_primary, 0.05).name(QColor.NameFormat.HexArgb)};
                border: 1px solid {palette.flyout_border};
                border-radius: 6px;
                padding: 12px 14px;
            }}
        """)
        for item in self._items:
            item.update()
        for page in self._pages:
            page.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._on_next()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._on_skip()
            return
        super().keyPressEvent(event)


def show_onboarding(*, step: int = 0) -> OnboardingWindow:
    """Create, centre and show the guide, replacing any previous one."""
    global _current
    previous = _current
    window = OnboardingWindow()
    _current = window
    screen = QApplication.primaryScreen()
    if screen is not None:
        area = screen.availableGeometry()
        window.move(area.center().x() - window.width() // 2,
                    area.center().y() - window.height() // 2)
    window.show()
    window.raise_()
    window.activateWindow()
    if step:
        window._go_to(step)
    if previous is not None:
        previous.close()
        previous.deleteLater()
    return window


def restart_onboarding(*, step: int = 0) -> OnboardingWindow:
    """Rebuild the guide in place (used after a language change)."""
    return show_onboarding(step=step)


def current_onboarding() -> "OnboardingWindow | None":
    return _current
