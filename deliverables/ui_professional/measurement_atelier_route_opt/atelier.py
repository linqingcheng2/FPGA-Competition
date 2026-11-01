"""Paper-themed presentation layer for the verified measurement console.

All measurement, firmware checks and JTAG operations are inherited unchanged.
This module lives outside the released FPGA project so its evidence stays valid.
"""
from pathlib import Path
import sys
import json
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from project_locator import resolve_project
PROJECT = resolve_project(500)
sys.path.insert(0, str(PROJECT / 'host'))
import app as backend
from capture import load_hardware
from live_transport import LiveSession, verify_firmware
from tkinter import filedialog, messagebox
from iq_import import load_iq_file

PAPER = '#F4F0E6'
SURFACE = '#FCF9F2'
SIDEBAR = '#ECE5D8'
INK = '#352F29'
MUTED = '#766D60'
BORDER = '#D8CDBA'
GRID = '#E8DFD0'
TERRA = '#A4543D'
TERRA_LIGHT = '#EEDCD0'
SAGE = '#566D58'
GOLD = '#8B713C'

# The inherited chart methods use these tokens; only this process sees the theme.
backend.BG = PAPER
backend.PANEL = SURFACE
backend.TEXT = INK
backend.MUTED = MUTED
backend.BLUE = TERRA
backend.GREEN = SAGE

WAVES = {
    'tone': '单频正弦', 'two_tone': '双频信号', 'chirp': '线性扫频',
    'wrap_chirp': '跨边界扫频', 'qpsk': 'QPSK 调制', 'burst': '突发单频',
    'wide': '平坦宽带', 'zero': '零输入', 'pn_qpsk':'全带宽 PN-QPSK',
}


class Atelier(backend.Console):
    def build(self):
        self.imported_iq = None
        self.imported_metadata = None
        self.import_note = tk.StringVar(value='可导入自己的 12-bit I/Q 数据')
        # A copied project must discover the cable on the current PC.
        self.cable_filter = tk.StringVar(value='')
        self.measurement_signature = None
        self.data_origin = '尚未载入测量数据'
        self.title('Signal Atelier · 数字基带测量仪')
        icon = HERE/'assets/atelier.png'
        if icon.exists():
            self._icon_image = tk.PhotoImage(file=str(icon))
            self.iconphoto(True, self._icon_image)
        self.geometry('1420x920')
        self.minsize(1120, 760)
        families = set(tkfont.families(self))
        self.serif = 'Noto Serif SC' if 'Noto Serif SC' in families else '宋体'
        self.latin = 'Georgia' if 'Georgia' in families else 'Times New Roman'
        self.ui_font = (self.serif, 10)
        self.caption_font = (self.serif, 9)
        self.italic_font = (self.latin, 11, 'italic')
        self.chart_font = (self.latin, 10, 'italic')
        for named in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont'):
            tkfont.nametofont(named).configure(family=self.serif, size=10)
        self.option_add('*TCombobox*Listbox.font', self.ui_font)
        self.option_add('*TCombobox*Listbox.background', SURFACE)
        self.option_add('*TCombobox*Listbox.foreground', INK)
        self.setup_styles()
        self.action_buttons = {}
        self.replay_fields = []
        self.latest_progress = {}
        self.phase_started = None
        self.phase_name = None
        self.phase_done = 0
        self.job_started = None
        self.origin = tk.StringVar(value='尚未载入测量数据')
        self.input_hint = tk.StringVar()
        self.progress_note = tk.StringVar(value='准备就绪 · 选择输入，连接后采集')
        self.connection_label = tk.StringVar(value='未连接')
        self.wave_label = tk.StringVar(value=WAVES[self.kind.get()])

        header = ttk.Frame(self, padding=(28, 12, 28, 6))
        header.pack(fill='x')
        masthead = ttk.Frame(header)
        masthead.pack(side='left')
        ttk.Label(masthead, text='Signal Atelier', font=(self.latin, 27, 'italic'),
                  foreground=INK).pack(anchor='w')
        ttk.Label(masthead, text='数字基带测量仪  /  让每一段信号，都有清晰的刻度',
                  font=(self.serif, 10), foreground=MUTED).pack(anchor='w', pady=(2, 0))
        edition = ttk.Frame(header)
        edition.pack(side='right', anchor='n', pady=7)
        ttk.Label(edition, text='Anhui · Integrated Circuit Competition',
                  font=self.italic_font, foreground=TERRA).pack(anchor='e')
        ttk.Label(edition, text='12-bit I/Q   ·   500 MSPS   ·   8192 / 16384 FFT',
                  font=(self.latin, 10, 'italic'), foreground=MUTED).pack(anchor='e', pady=(8, 0))
        ttk.Separator(self).pack(fill='x', padx=28, pady=(5, 10))

        status = ttk.Frame(self, padding=(28, 0, 28, 5))
        status.pack(fill='x')
        ttk.Label(status, textvariable=self.origin, style='Badge.TLabel').pack(side='left')
        ttk.Label(status, textvariable=self.status, style='Muted.TLabel',
                  wraplength=900).pack(side='left', padx=14)

        cards = ttk.Frame(self, padding=(22, 0, 22, 12))
        cards.pack(fill='x')
        self.cards = {}
        self.card_value_labels = {}
        titles = [
            ('谱峰频点', 'Frequency'), ('99%占用带宽', 'Occupied bandwidth'),
            ('−3dB主峰带宽', 'Mainlobe'), ('复数RMS', 'Magnitude'),
            ('帧长度', 'Frame length'), ('硬件处理时间', 'Hardware latency'),
        ]
        for column, (title, english) in enumerate(titles):
            cards.columnconfigure(column, weight=1, uniform='metrics')
            card = tk.Frame(cards, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
            card.grid(row=0, column=column, sticky='nsew', padx=5)
            tk.Label(card, text=english, bg=SURFACE, fg=MUTED,
                     font=(self.latin, 8, 'italic')).pack(anchor='w', padx=13, pady=(6, 1))
            value = tk.StringVar(value='—')
            self.cards[title] = value
            value_label = tk.Label(card, textvariable=value, bg=SURFACE, fg=INK,
                     font=(self.serif, 14) if title == '帧长度' else (self.latin, 17, 'italic'))
            value_label.pack(anchor='w', padx=13, pady=(0, 2))
            self.card_value_labels[title] = value_label
            tk.Label(card, text=title, bg=SURFACE, fg=MUTED,
                     font=(self.serif, 8)).pack(anchor='w', padx=13, pady=(0, 7))

        # Footer is reserved before the expanding body so it remains visible.
        footer = ttk.Frame(self, padding=(28, 8, 28, 12))
        footer.pack(side='bottom', fill='x')
        ttk.Label(footer, text='Measured with care.', font=self.italic_font,
                  foreground=TERRA).pack(side='left')
        ttk.Label(footer, textvariable=self.transfer, style='Muted.TLabel',
                  wraplength=980).pack(side='right')

        body = ttk.Frame(self, padding=(28, 0, 28, 0))
        body.pack(fill='both', expand=True)
        self.side_holder = tk.Frame(body, bg=SIDEBAR, highlightbackground=BORDER,
                                    highlightthickness=1, width=286)
        self.side_holder.pack(side='left', fill='y', padx=(0, 22))
        self.side_holder.pack_propagate(False)
        self.build_sidebar(self.side_holder)
        main = ttk.Frame(body)
        main.pack(side='left', fill='both', expand=True)
        self.build_actions(main)

        self.notebook = ttk.Notebook(main, style='Atelier.TNotebook')
        self.notebook.pack(fill='both', expand=True, pady=(14, 0))
        self.tabs = {name: ttk.Frame(self.notebook, style='Surface.TFrame', padding=16)
                     for name in ['完整频谱', '时域快照', '频谱历史', '诊断与上板', '比赛验证']}
        for name, tab in self.tabs.items():
            self.notebook.add(tab, text=name)
        self.build_charts()
        self.build_diagnostics()
        self.build_tests()
        self.use_replay.trace_add('write', lambda *_: self.sync_input())
        self.kind.trace_add('write', lambda *_: self.sync_wave())
        for variable in (self.n, self.kind, self.f1, self.f2, self.amplitude, self.noise,
                         self.burst_length, self.hann, self.burst, self.use_replay, self.hi, self.lo):
            variable.trace_add('write', lambda *_: self.mark_pending())
        self.sync_input()
        self.after(250, self.refresh_presentation)

    def setup_styles(self):
        style = ttk.Style(self)
        style.configure('.', font=self.ui_font, background=PAPER, foreground=INK)
        style.configure('TFrame', background=PAPER)
        style.configure('Surface.TFrame', background=SURFACE)
        style.configure('Side.TFrame', background=SIDEBAR)
        style.configure('TLabel', background=PAPER, foreground=INK)
        style.configure('Muted.TLabel', background=PAPER, foreground=MUTED)
        style.configure('Side.TLabel', background=SIDEBAR, foreground=INK)
        style.configure('SideMuted.TLabel', background=SIDEBAR, foreground=MUTED, font=self.caption_font)
        style.configure('Surface.TLabel', background=SURFACE, foreground=INK)
        style.configure('SurfaceMuted.TLabel', background=SURFACE, foreground=MUTED)
        style.configure('Badge.TLabel', background=TERRA_LIGHT, foreground=TERRA, padding=(10, 2), font=self.caption_font)
        style.configure('TSeparator', background=BORDER)
        style.configure('TButton', font=self.ui_font, background=SURFACE, foreground=INK,
                        bordercolor=BORDER, lightcolor=SURFACE, darkcolor=BORDER,
                        borderwidth=1, relief='flat', padding=(12, 7), focuscolor=BORDER)
        style.map('TButton', background=[('active', '#E9E0D1'), ('pressed', '#DFD1BE')],
                  foreground=[('disabled', '#9B9285')], bordercolor=[('active', '#BCA991')])
        style.configure('Primary.TButton', background=TERRA, foreground=SURFACE,
                        lightcolor=TERRA, darkcolor=TERRA, bordercolor=TERRA)
        style.map('Primary.TButton', background=[('active', '#8F4532'), ('pressed', '#7D3D2D'), ('disabled', '#D1B8A7')],
                  foreground=[('disabled', SURFACE)])
        style.configure('TEntry', fieldbackground=SURFACE, foreground=INK,
                        bordercolor=BORDER, lightcolor=SURFACE, darkcolor=BORDER, padding=5)
        style.map('TEntry', fieldbackground=[('disabled', '#E5DED1')], foreground=[('disabled', '#9B9285')])
        style.configure('TCombobox', fieldbackground=SURFACE, foreground=INK, background=SIDEBAR,
                        arrowcolor=MUTED, bordercolor=BORDER, lightcolor=SURFACE, darkcolor=BORDER, padding=5)
        style.map('TCombobox', fieldbackground=[('disabled', '#E5DED1'), ('readonly', SURFACE)],
                  foreground=[('disabled', '#9B9285'), ('readonly', INK)], selectbackground=[('readonly', SURFACE)],
                  selectforeground=[('readonly', INK)])
        for kind in ('TCheckbutton', 'TRadiobutton'):
            style.configure(kind, background=SIDEBAR, foreground=INK, indicatorbackground=SURFACE,
                            indicatorforeground=TERRA, focuscolor=SIDEBAR, padding=(0, 3))
            style.map(kind, background=[('active', SIDEBAR)], foreground=[('disabled', '#9B9285')])
        style.configure('Chart.TCheckbutton', background=SURFACE)
        style.map('Chart.TCheckbutton', background=[('active', SURFACE)])
        style.configure('Atelier.TNotebook', background=PAPER, borderwidth=0, bordercolor=BORDER)
        style.configure('Atelier.TNotebook.Tab', font=self.ui_font, padding=(17, 7),
                        background=PAPER, foreground=MUTED, bordercolor=BORDER,
                        lightcolor=PAPER, darkcolor=BORDER)
        style.map('Atelier.TNotebook.Tab', background=[('selected', SURFACE), ('active', '#EDE4D6')],
                  foreground=[('selected', TERRA)])
        style.configure('Horizontal.TProgressbar', background=TERRA, troughcolor='#E7DECF',
                        bordercolor=PAPER, lightcolor=TERRA, darkcolor=TERRA, thickness=4)
        style.configure('Vertical.TScrollbar', background='#CFC1AE', troughcolor=SIDEBAR,
                        bordercolor=SIDEBAR, arrowcolor=MUTED, arrowsize=10)
        style.configure('Treeview', background=SURFACE, fieldbackground=SURFACE, foreground=INK,
                        rowheight=38, bordercolor=BORDER)
        style.map('Treeview', background=[('selected', TERRA_LIGHT)], foreground=[('selected', INK)])
        style.configure('Treeview.Heading', background=SIDEBAR, foreground=INK,
                        font=(self.serif, 10), relief='flat', bordercolor=BORDER)

    def button(self, parent, key, text, command, primary=False, **pack):
        widget = ttk.Button(parent, text=text, command=command,
                            style='Primary.TButton' if primary else 'TButton')
        widget.pack(**pack)
        self.action_buttons[key] = widget
        return widget

    def build_sidebar(self, parent):
        top = tk.Frame(parent, bg=SIDEBAR)
        top.pack(fill='x', padx=17, pady=(14, 10))
        tk.Label(top, text='The signal desk', bg=SIDEBAR, fg=TERRA,
                 font=(self.latin, 17, 'italic')).pack(anchor='w')
        tk.Label(top, text='输入与测量配置', bg=SIDEBAR, fg=INK,
                 font=(self.serif, 12)).pack(anchor='w', pady=(4, 0))
        bottom = ttk.Frame(parent, style='Side.TFrame', padding=(16, 10))
        bottom.pack(side='bottom', fill='x')
        self.button(bottom, 'preview', '参考模型预览', self.preview, fill='x', pady=3)
        row = ttk.Frame(bottom, style='Side.TFrame')
        row.pack(fill='x', pady=3)
        self.button(row, 'import', '导入实测', self.open_hardware, side='left', fill='x', expand=True, padx=(0, 5))
        self.button(row, 'export', '导出结果', self.export, side='left', fill='x', expand=True)
        ttk.Label(bottom, text='预览 / 仿真 / 实测分别标注', style='SideMuted.TLabel').pack(anchor='w', pady=(7, 0))
        holder = ttk.Frame(parent, style='Side.TFrame')
        holder.pack(fill='both', expand=True, padx=9)
        self.side_canvas = tk.Canvas(holder, background=SIDEBAR, highlightthickness=0)
        self.side_canvas.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(holder, orient='vertical', command=self.side_canvas.yview)
        scroll.pack(side='right', fill='y')
        self.side_canvas.configure(yscrollcommand=scroll.set)
        side = ttk.Frame(self.side_canvas, style='Side.TFrame', padding=(8, 0))
        self.side_window = self.side_canvas.create_window(0, 0, window=side, anchor='nw')
        side.bind('<Configure>', lambda _: self.side_canvas.configure(scrollregion=self.side_canvas.bbox('all')))
        self.side_canvas.bind('<Configure>', lambda e: self.side_canvas.itemconfigure(self.side_window, width=e.width))
        def wheel(event):
            if self.side_holder.winfo_rootx() <= event.x_root < self.side_holder.winfo_rootx()+self.side_holder.winfo_width():
                self.side_canvas.yview_scroll(-int(event.delta/120), 'units')
        self.bind('<MouseWheel>', wheel, add='+')
        ttk.Label(side, text='输入来源', style='SideMuted.TLabel').pack(anchor='w', pady=(0, 5))
        ttk.Label(side, text='电脑 I/Q 回放或外部 I/Q 文件', style='SideMuted.TLabel').pack(anchor='w')
        ttk.Label(side, textvariable=self.input_hint, style='SideMuted.TLabel',
                  wraplength=232, justify='left').pack(fill='x', pady=(6, 10))
        row = ttk.Frame(side, style='Side.TFrame')
        row.pack(fill='x', pady=(0, 5))
        self.button(row, 'import_iq', '导入 I/Q', self.import_iq_file, side='left', fill='x', expand=True, padx=(0, 4))
        self.button(row, 'clear_iq', '使用内置激励', self.clear_import, side='left', fill='x', expand=True)
        ttk.Label(side, textvariable=self.import_note, style='SideMuted.TLabel',
                  wraplength=232, justify='left').pack(fill='x', pady=(2, 5))
        ttk.Separator(side).pack(fill='x', pady=(0, 9))
        def field(label, variable, choices=None, replay=False):
            ttk.Label(side, text=label, style='SideMuted.TLabel').pack(anchor='w', pady=(5, 4))
            widget = ttk.Combobox(side, textvariable=variable, values=choices, state='readonly') if choices else ttk.Entry(side, textvariable=variable)
            widget.pack(fill='x')
            if replay:
                self.replay_fields.append(widget)
            return widget
        field('FFT 点数', self.n, ['8192', '16384'])
        self.wave_combo = field('激励类型', self.wave_label, list(WAVES.values()), replay=True)
        self.wave_combo.bind('<<ComboboxSelected>>', lambda _: self.kind.set(next(k for k,v in WAVES.items() if v == self.wave_label.get())))
        presets = ttk.Frame(side, style='Side.TFrame')
        presets.pack(fill='x', pady=(9, 4))
        self.preset_buttons = []
        for label, name in [('单频', 'tone'), ('双频', 'two_tone'), ('扫频', 'chirp')]:
            button = ttk.Button(presets, text=label, width=5, command=lambda k=name: self.preset(k))
            button.pack(side='left', expand=True, fill='x', padx=(0, 4))
            self.preset_buttons.append(button)
        for fields in [[('频率 1 / MHz', self.f1), ('频率 2 / MHz', self.f2)],
                       [('幅度 / 码值', self.amplitude), ('噪声 σ / 码值', self.noise)]]:
            pair = ttk.Frame(side, style='Side.TFrame')
            pair.pack(fill='x', pady=(5, 0))
            for index, (label, var) in enumerate(fields):
                frame = ttk.Frame(pair, style='Side.TFrame')
                frame.pack(side='left', expand=True, fill='x', padx=(0, 7 if index == 0 else 0))
                ttk.Label(frame, text=label, style='SideMuted.TLabel').pack(anchor='w', pady=(0, 4))
                entry = ttk.Entry(frame, textvariable=var, width=10, font=(self.latin, 11, 'italic'))
                entry.pack(fill='x')
                self.replay_fields.append(entry)
        field('突发有效样本数', self.burst_length, replay=True)
        ttk.Checkbutton(side, text='周期 Hann 窗', variable=self.hann).pack(anchor='w', pady=(10, 0))
        ttk.Checkbutton(side, text='突发检测模式', variable=self.burst).pack(anchor='w')
        ttk.Checkbutton(side, text='读取真实 I/Q 快照', variable=self.scope_enabled).pack(anchor='w')
        ttk.Label(side, text='快照读取前 1024 点，JTAG 耗时增加', style='SideMuted.TLabel', wraplength=232).pack(anchor='w', pady=(2, 6))
        field('连续采集间隔 / 秒', self.interval)
        ttk.Label(side, text='上一帧传输完成后开始计时', style='SideMuted.TLabel').pack(anchor='w', pady=(4, 10))

    def build_actions(self, parent):
        actions = ttk.Frame(parent)
        actions.pack(fill='x')
        self.button(actions, 'connect', '连接开发板', self.connect_board, side='left', padx=(0, 7))
        self.button(actions, 'capture', '单次采集', self.capture_board, primary=True, side='left', padx=(0, 7))
        self.button(actions, 'live', '连续采集', self.start_live, side='left', padx=(0, 7))
        self.button(actions, 'stop', '停止 / 取消', self.stop_live, side='left')
        ttk.Label(actions, textvariable=self.connection_label, foreground=SAGE,
                  font=self.caption_font).pack(side='right', padx=5)
        self.progress = ttk.Progressbar(parent, mode='indeterminate')
        self.progress.pack(fill='x', pady=(2, 5))
        ttk.Label(parent, textvariable=self.progress_note, style='Muted.TLabel',
                  wraplength=940).pack(anchor='w')

    def build_charts(self):
        tab = self.tabs['完整频谱']
        heading = ttk.Frame(tab, style='Surface.TFrame')
        heading.pack(fill='x')
        ttk.Label(heading, text='A spectrum, in full.', style='Surface.TLabel',
                  font=(self.latin, 17, 'italic')).pack(side='left')
        ttk.Label(heading, text='完整复数功率谱 · MHz / 相对 dB',
                  style='SurfaceMuted.TLabel', font=(self.serif, 8)).pack(side='right')
        self.spectrum_canvas = tk.Canvas(tab, bg=SURFACE, highlightthickness=0, width=400, height=120)
        self.spectrum_canvas.bind('<Configure>', lambda _: self.schedule_plot('plot_spectrum'))
        self.spectrum_canvas.bind('<Motion>', self.cursor_move)
        self.spectrum_canvas.bind('<MouseWheel>', self.zoom_spectrum)
        self.spectrum_canvas.bind('<Double-Button-1>', self.reset_view)
        chart_footer = ttk.Frame(tab, style='Surface.TFrame')
        chart_footer.pack(side='bottom', fill='x')
        row = ttk.Frame(chart_footer, style='Surface.TFrame')
        row.pack(fill='x')
        ttk.Checkbutton(row, text='归一化峰值保持', variable=self.max_hold,
                        command=self.plot_spectrum, style='Chart.TCheckbutton').pack(side='left')
        ttk.Button(row, text='恢复全频段', command=self.reset_view).pack(side='right', padx=(7, 0))
        ttk.Button(row, text='清空历史', command=self.clear_history).pack(side='right')
        ttk.Label(chart_footer, textvariable=self.cursor, style='SurfaceMuted.TLabel',
                  font=self.caption_font).pack(anchor='w', pady=(6, 0))
        self.band_note = tk.StringVar(value='尚无频谱')
        ttk.Label(chart_footer, textvariable=self.band_note, style='SurfaceMuted.TLabel',
                  font=self.caption_font, wraplength=1000).pack(anchor='w', pady=(3, 0))
        self.spectrum_canvas.pack(fill='both', expand=True, pady=(10, 6))
        tab = self.tabs['时域快照']
        ttk.Label(tab, text='The rhythm of I & Q.', style='Surface.TLabel',
                  font=(self.latin, 18, 'italic')).pack(anchor='w')
        self.scope_note = tk.StringVar(value='勾选“读取真实 I/Q 快照”，再采集以显示板上波形')
        ttk.Label(tab, textvariable=self.scope_note, style='SurfaceMuted.TLabel').pack(anchor='w', pady=(5, 0))
        self.time_canvas = tk.Canvas(tab, bg=SURFACE, highlightthickness=0, width=400, height=120)
        self.time_canvas.pack(fill='both', expand=True, pady=10)
        self.time_canvas.bind('<Configure>', lambda _: self.schedule_plot('plot_time'))
        tab = self.tabs['频谱历史']
        ttk.Label(tab, text='A little history of the signal.', style='Surface.TLabel',
                  font=(self.latin, 18, 'italic')).pack(anchor='w')
        ttk.Label(tab, text='按采集顺序排列，最多 100 帧；颜色为各帧归一化功率。',
                  style='SurfaceMuted.TLabel').pack(anchor='w', pady=(5, 0))
        self.waterfall = tk.Canvas(tab, bg=SURFACE, highlightthickness=0, width=400, height=120)
        self.waterfall.pack(fill='both', expand=True, pady=10)
        self.waterfall.bind('<Configure>', lambda _: self.schedule_plot('plot_waterfall'))

    def build_diagnostics(self):
        tab = self.tabs['诊断与上板']
        ttk.Label(tab, text='Behind the measurement.', style='Surface.TLabel',
                  font=(self.latin, 18, 'italic')).pack(anchor='w')
        ttk.Label(tab, text='连接、编程与采集分别操作；每次采集保留数据与配置。',
                  style='SurfaceMuted.TLabel').pack(anchor='w', pady=(5, 12))
        for label, var in [('Vivado 路径（填写 vivado.bat）', self.vivado), ('JTAG 目标（留空自动发现）', self.target),
                           ('USB 线缆编号（留空自动发现）', self.cable_filter)]:
            ttk.Label(tab, text=label, style='SurfaceMuted.TLabel').pack(anchor='w')
            ttk.Entry(tab, textvariable=var).pack(fill='x', pady=(4, 9))
        fields = ttk.Frame(tab, style='Surface.TFrame')
        fields.pack(fill='x')
        for label, var in [('高能量门限', self.hi), ('低能量门限', self.lo)]:
            frame = ttk.Frame(fields, style='Surface.TFrame')
            frame.pack(side='left', fill='x', expand=True, padx=(0, 12))
            ttk.Label(frame, text=label, style='SurfaceMuted.TLabel').pack(anchor='w')
            ttk.Entry(frame, textvariable=var).pack(fill='x', pady=5)
        row = ttk.Frame(tab, style='Surface.TFrame')
        row.pack(fill='x', pady=9)
        self.button(row, 'program', '编程完善版', self.program, side='left', padx=(0, 7))
        self.button(row, 'simulation', '载入 RTL 仿真', self.open_simulation, side='left', padx=(0, 7))
        self.button(row, 'monitor', '检查连续处理计数', self.monitor, side='left')
        self.diagnostic = tk.Text(tab, bg=SURFACE, fg=INK, insertbackground=TERRA,
                                  font=(self.latin, 10), relief='flat', wrap='word', height=10,
                                  highlightbackground=BORDER, highlightthickness=1)
        self.diagnostic.pack(fill='both', expand=True, pady=(4, 0))
        self.diagnostic.insert('end', '测量日志与原始指标将在这里显示。\n板级验证记录见“比赛验证”。\n')

    def build_tests(self):
        tab = self.tabs['比赛验证']
        ttk.Label(tab, text='Evidence, beautifully kept.', style='Surface.TLabel',
                  font=(self.latin, 18, 'italic')).pack(anchor='w')
        ttk.Label(tab, text='比赛指标与验证依据 · 实测数据和历史验收分别记录',
                  style='SurfaceMuted.TLabel').pack(anchor='w', pady=(5, 12))
        self.test_table = ttk.Treeview(tab, columns=('requirement', 'target', 'evidence'), show='headings')
        for key, title, width in [('requirement', '比赛要求', 190), ('target', '工程目标', 150), ('evidence', '验证证据 / 状态', 480)]:
            self.test_table.heading(key, text=title)
            self.test_table.column(key, width=width, minwidth=110, anchor='w')
        self.test_table.pack(fill='both', expand=True)
        scroll = ttk.Scrollbar(tab, orient='horizontal', command=self.test_table.xview)
        scroll.pack(fill='x')
        self.test_table.configure(xscrollcommand=scroll.set)
        ttk.Button(tab, text='刷新验证结果', command=self.refresh_tests).pack(anchor='e', pady=(10, 0))
        self.refresh_tests()

    def sync_wave(self):
        if self.kind.get() in WAVES:
            self.wave_label.set(WAVES[self.kind.get()])

    def refresh_tests(self):
        super().refresh_tests()
        self.test_table.insert('', 'end', values=('任意 I/Q 与可追溯性', 'CSV / MEM；无损 12-bit',
            '文件与固件 SHA；完整 FFT 对照；真实快照逐点核对，详见验证记录'))

    def sync_input(self):
        if self.use_replay.get():
            self.input_hint.set('导入 I/Q → FPGA 回放与测量\n回放速率固定 500 MSPS，不自动重采样。' if self.imported_iq is not None else '电脑生成 I/Q → FPGA 回放与测量\n新激励首次上传需等待；点击采集生效。')
        else:
            self.input_hint.set('请选择电脑生成 I/Q 或外部 I/Q 文件')
        for field in self.replay_fields:
            field.configure(state=('readonly' if isinstance(field, ttk.Combobox) else 'normal')
                            if self.use_replay.get() and not self.busy and self.imported_iq is None else 'disabled')
        for key in ('import_iq', 'clear_iq'):
            self.action_buttons[key].configure(state='disabled' if self.busy or self.live_running else 'normal')

    def import_iq_file(self, path=None):
        if self.busy or self.live_running:
            return
        if path is None:
            path = filedialog.askopenfilename(title='导入一帧 12-bit I/Q',
                filetypes=[('I/Q 数据', '*.csv *.mem'), ('CSV', '*.csv'), ('MEM', '*.mem')])
        if not path:
            return
        try:
            iq, metadata = load_iq_file(path)
        except (ValueError, OSError, UnicodeError) as e:
            messagebox.showerror('I/Q 导入失败', str(e))
            return
        self.imported_iq, self.imported_metadata = iq, metadata
        self.wave_label.set('外部 I/Q 文件')
        self.n.set(str(len(iq)))
        self.burst.set(False)
        self.use_replay.set(True)
        self.import_note.set(f'{Path(path).name}\n{len(iq):,} 对 · 12-bit · 文件 SHA 已记录')
        self.mark_pending()
        self.sync_input()
        self.progress_note.set('文件已载入 · 点击参考预览或单次采集；不会自动上传或编程。')

    def clear_import(self):
        if self.busy or self.live_running:
            return
        self.imported_iq = None
        self.imported_metadata = None
        self.import_note.set('可导入自己的 12-bit I/Q 数据')
        self.sync_wave()
        self.mark_pending()
        self.sync_input()

    def parameters(self):
        if self.imported_iq is None:
            return super().parameters()
        if int(self.n.get()) != len(self.imported_iq):
            raise ValueError('FFT 点数须与导入帧长度相同；请导入对应长度的文件或切回内置激励')
        return dict(kind='external_iq', n=len(self.imported_iq),
                    imported_file=self.imported_metadata)

    def iq(self):
        if self.imported_iq is None:
            return super().iq()
        self.parameters()
        return self.imported_iq.copy()

    def preview(self):
        super().preview()
        if self.imported_iq is not None and self.metric and self.metric['source'] == 'golden_model':
            self.scope_note.set('导入文件的前 1024 对 I/Q · 软件参考，未上板测量')

    def preset(self, name):
        if self.busy or self.live_running:
            self.progress_note.set('请先停止采集，再选择新的信号预设。')
            return
        self.use_replay.set(True)
        self.clear_import()
        self.n.set('8192')
        self.kind.set(name)
        self.amplitude.set('1500')
        self.noise.set('0')
        self.burst.set(False)
        frequencies = {'tone': ('10', '20'), 'two_tone': ('9.5', '10.5'), 'chirp': ('-40', '40')}
        first, second = frequencies[name]
        self.f1.set(first)
        self.f2.set(second)
        self.hann.set(name != 'tone')
        self.progress_note.set('预设已填写 · 点击“单次采集”测量，或“参考模型预览”查看软件结果。')

    def load(self, metric, power, scope=None):
        super().load(metric, power, scope)
        for title, label in self.card_value_labels.items():
            contains_chinese = any('\u4e00' <= char <= '\u9fff' for char in self.cards[title].get())
            label.configure(font=(self.serif, 14) if contains_chinese else (self.latin, 17, 'italic'))
        resolution = metric['fs']/metric['n']/1e3
        self.band_note.set(self.band_note.get()+f'  |  频率栅格 {resolution:.3f} kHz')
        proof = self.context.get('validation', {}).get('independent_reference')
        if metric['source'] == 'hardware' and proof:
            self.diagnostic.insert('end', '\n\n独立参考核验：\n'+json.dumps(proof, ensure_ascii=False, indent=2))
            self.band_note.set(self.band_note.get()+f'  |  FFT 对照误差 {100*proof["fft_relative_l1_error"]:.3f}%')
        labels = {'hardware': '板卡实测', 'simulation': 'RTL 仿真', 'golden_model': '软件参考预览'}
        self.data_origin = labels[metric['source']]
        self.measurement_signature = self.context.get('_ui_measurement_signature', self.input_signature()) if metric['source'] == 'hardware' else self.input_signature()
        self.mark_pending()
        if metric['source'] == 'hardware' and scope is None:
            self.scope_note.set('本帧未读取 I/Q 快照 · 勾选“读取真实 I/Q 快照”后再次采集')
        self.progress_note.set('本帧已加载 · 滚轮缩放频谱，双击恢复全频段。')

    def report_progress(self, data):
        # Called by the transport thread. Tk updates stay on its main thread.
        phase = data.get('message')
        done = int(data.get('done', 0))
        if phase != self.phase_name or done < self.phase_done:
            self.phase_started = time.monotonic()
            self.phase_name = phase
        self.phase_done = done
        self.latest_progress = dict(data)
        super().report_progress(data)

    def worker(self, description, function):
        if not self.busy:
            self.job_started = time.monotonic()
            self.latest_progress = {}
            self.phase_started = None
            self.phase_name = None
            self.phase_done = 0
        signature = self.input_signature()
        original = function
        def with_signature():
            result = original()
            if isinstance(result, tuple) and len(result) == 4:
                result[3]['_ui_measurement_signature'] = signature
            return result
        function = with_signature
        return super().worker(description, function)

    def input_signature(self):
        values = [v.get() for v in (self.n, self.kind, self.f1, self.f2, self.amplitude,
                  self.noise, self.burst_length, self.hann, self.burst, self.use_replay, self.hi, self.lo)]
        values.append(self.imported_metadata['sha256'] if self.imported_metadata else None)
        return values

    def get_session(self):
        selected = self.cable_filter.get().strip()
        if self.session is None:
            self.session = LiveSession(self.vivado.get(), cable_filter=selected)
        elif str(self.session.vivado) != self.vivado.get() or self.session.cable_filter != selected:
            raise ValueError('修改 Vivado 路径或 USB 线缆编号后，请关闭并重新打开界面')
        return self.session

    def mark_pending(self):
        if self.measurement_signature is None or self.metric is None:
            return
        changed = self.measurement_signature != self.input_signature()
        self.origin.set(self.data_origin + (' · 参数待采集' if changed else ''))

    def refresh_presentation(self):
        try:
            firmware_ready = json.loads((PROJECT/'results/firmware_manifest.json').read_text(encoding='utf-8')).get('eligible_for_board_validation') is True
        except (OSError, ValueError):
            firmware_ready = False
        available = self.connected and not self.busy and firmware_ready
        self.connection_label.set('已连接 / 固件就绪' if self.connected and self.attached else ('已连接' if self.connected else '未连接'))
        for key in ('capture', 'program', 'monitor'):
            self.action_buttons[key].configure(state='normal' if available else 'disabled')
        self.action_buttons['live'].configure(state='normal' if available and not self.live_running else 'disabled')
        for key in ('connect', 'preview', 'import', 'simulation'):
            self.action_buttons[key].configure(state='disabled' if self.busy or (key == 'connect' and not firmware_ready) else 'normal')
        self.action_buttons['stop'].configure(state='normal' if self.busy or self.live_running else 'disabled')
        for button in self.preset_buttons:
            button.configure(state='disabled' if self.busy or self.live_running else 'normal')
        signature = tuple(v.get() for v in (self.n,self.kind,self.f1,self.f2,self.amplitude,self.noise,self.burst_length,self.hann,self.burst,self.use_replay,self.hi,self.lo)) + (self.busy,self.live_running,)
        if signature != getattr(self,'_presentation_signature',None):
            self._presentation_signature = signature
            self.sync_input()
        if self.busy:
            data = self.latest_progress
            done, total = int(data.get('done', 0)), int(data.get('total', 0))
            elapsed = max(0, time.monotonic()-(self.job_started or time.monotonic()))
            note = str(data.get('message') or self.status.get())
            if total:
                note += f'  ·  {done:,} / {total:,}  ·  {100*done/max(total,1):.0f}%'
                if 0 < done < total and self.phase_started is not None:
                    phase_elapsed = max(0, time.monotonic()-self.phase_started)
                    if phase_elapsed > 1:
                        remaining = phase_elapsed*(total-done)/done
                        note += f'  ·  本阶段预计剩余 {remaining:.0f} 秒'
            self.progress_note.set(note + f'  ·  本次已用 {elapsed:.0f} 秒')
        self.after(250, self.refresh_presentation)

    def axes(self, canvas, ymin, ymax, xmin, xmax, xlabel):
        canvas.delete('all')
        w, h = max(canvas.winfo_width(), 200), max(canvas.winfo_height(), 120)
        left, right, top, bottom = 64, w-24, 24, h-46
        for j in range(6):
            y = top+(bottom-top)*j/5
            canvas.create_line(left, y, right, y, fill=GRID)
            canvas.create_text(left-10, y, text=f'{ymax-(ymax-ymin)*j/5:g}',
                               fill=MUTED, anchor='e', font=self.chart_font)
            x = left+(right-left)*j/5
            canvas.create_line(x, top, x, bottom, fill=GRID)
            canvas.create_text(x, bottom+18, text=f'{xmin+(xmax-xmin)*j/5:.2f}',
                               fill=MUTED, font=self.chart_font)
        canvas.create_line(left, top, left, bottom, right, bottom, fill=BORDER)
        canvas.create_text((left+right)/2, h-14, text=xlabel, fill=MUTED, font=(self.serif, 9))
        return left, right, top, bottom

    def plot_spectrum(self):
        if not hasattr(self, 'chart_font'):
            return
        super().plot_spectrum()
        for item in self.spectrum_canvas.find_all():
            if self.spectrum_canvas.type(item) == 'text':
                label = self.spectrum_canvas.itemcget(item, 'text')
                self.spectrum_canvas.itemconfigure(item, font=(self.serif, 9)
                    if any('\u3400' <= char <= '\u9fff' for char in label) else self.chart_font)
            elif self.spectrum_canvas.type(item) == 'line' and self.spectrum_canvas.itemcget(item, 'fill') == '#ffc76a':
                self.spectrum_canvas.itemconfigure(item, fill=GOLD)

    def plot_time(self):
        if not hasattr(self, 'chart_font'):
            return
        super().plot_time()
        for item in self.time_canvas.find_all():
            if self.time_canvas.type(item) == 'text':
                label = self.time_canvas.itemcget(item, 'text')
                self.time_canvas.itemconfigure(item, font=(self.serif, 9)
                    if any('\u3400' <= char <= '\u9fff' for char in label) else self.chart_font)

    def plot_waterfall(self):
        canvas = self.waterfall
        canvas.delete('all')
        w, h = max(canvas.winfo_width(), 200), max(canvas.winfo_height(), 200)
        if not self.history:
            canvas.create_text(w/2, h/2, text='等待采集，留下一段信号的历史。', fill=MUTED, font=(self.serif, 12))
            return
        width = min(360, w-60)
        rows = len(self.history)
        image = tk.PhotoImage(width=width, height=rows)
        lines = []
        pale = np.array([243, 235, 222])
        dark = np.array([158, 77, 53])
        for values in self.history:
            colors = []
            for group in np.array_split(values, width):
                level = np.clip((float(group.max())+80)/80, 0, 1)
                rgb = np.rint(pale*(1-level)+dark*level).astype(int)
                colors.append('#%02x%02x%02x' % tuple(rgb))
            lines.append('{'+ ' '.join(colors)+'}')
        image.put(' '.join(lines))
        self.water_image = image.zoom(max(1, (w-60)//width), max(1, min(8, (h-50)//rows)))
        canvas.create_image(30, 15, image=self.water_image, anchor='nw')
        canvas.create_text(30, h-15, text=f'{-((self.metric["fs"] if self.metric else backend.FS)/2e6):g} MHz', fill=MUTED, anchor='w', font=self.chart_font)
        canvas.create_text(w-30, h-15, text=f'+{((self.metric["fs"] if self.metric else backend.FS)/2e6):g} MHz', fill=MUTED, anchor='e', font=self.chart_font)


def load_record(console, folder):
    """Load an actual archived frame, always labelled as an archived record."""
    folder = Path(folder)
    record = json.loads((folder/'measurement.json').read_text(encoding='utf-8'))
    context = record.get('context', {})
    console.context = dict(context, capture_folder=str(folder), scope_source='hardware')
    case = context.get('stimulus_parameters') or context.get('case')
    if case:
        for variable, key in [(console.n, 'n'), (console.kind, 'kind'),
                              (console.amplitude, 'amplitude'), (console.noise, 'noise')]:
            if key in case and (key != 'kind' or case[key] in WAVES):
                variable.set(str(case[key]))
        if 'frequency' in case:
            console.f1.set(str(case['frequency']/1e6))
        if 'frequency2' in case:
            console.f2.set(str(case['frequency2']/1e6))
        console.hann.set(bool(context.get('hann', case.get('hann', False))))
        console.burst.set(bool(context.get('burst', case.get('burst', False))))
        if case.get('burst_length') is not None:console.burst_length.set(str(case['burst_length']))
    for variable,key in ((console.hi,'threshold_hi'),(console.lo,'threshold_lo')):
        if key in context:variable.set(str(context[key]))
    console.load(*load_hardware(folder))
    console.origin.set('历史板卡实测')
    console.data_origin = '历史板卡实测'
    stamp = context.get('captured_at') or record.get('created_utc') or '见记录文件'
    console.transfer.set(f'实测记录：{stamp} · 连接后可采集新帧')
    console.progress_note.set('已载入历史实测 · 启动未自动连接或编程开发板')

