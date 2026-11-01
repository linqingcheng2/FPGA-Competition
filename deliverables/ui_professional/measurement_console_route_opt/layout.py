"""Native Tk instrument layout; transport commands are supplied by the console."""
import tkinter as tk
import tkinter.font as tf
from tkinter import ttk
import json
from theme import *
from theme import configure


class MenuCommand:
    """Adapter for the inherited busy-state updater's configure(state=...)."""
    def __init__(self, menu, index): self.menu, self.index = menu, index
    def configure(self, **options): self.menu.entryconfigure(self.index, **options)
    def __getitem__(self, name): return self.menu.entrycget(self.index, name)


class LaboratoryLayout:
    def setup_styles(self): configure(ttk.Style(self), self.ui_font)

    def build(self):
        self.title('数字基带测量仪 · 500 MSPS 预综合候选版')
        self.configure(background=BG)
        self.geometry('1520x940'); self.minsize(1240,800)
        families = set(tf.families(self))
        self.serif = 'Microsoft YaHei UI' if 'Microsoft YaHei UI' in families else '微软雅黑'
        self.latin = 'Consolas'
        self.ui_font, self.caption_font, self.chart_font = (self.serif,10), (self.serif,9), (self.latin,9)
        for name in ('TkDefaultFont','TkTextFont','TkMenuFont','TkHeadingFont'):
            tf.nametofont(name).configure(family=self.serif,size=9,slant='roman')
        self.option_add('*TCombobox*Listbox.font',self.ui_font)
        self.option_add('*TCombobox*Listbox.background',SURFACE)
        self.option_add('*TCombobox*Listbox.foreground',INK)
        self.setup_styles()
        self.imported_iq = self.imported_metadata = self.measurement_signature = None
        self.data_origin = '尚无测量'
        self.import_note = tk.StringVar(value='CSV / MEM · 12-bit I/Q')
        # A JTAG serial number belongs to the donor computer; blank means
        # discover the connected cable on this computer.
        self.cable_filter = tk.StringVar(value='')
        self.origin = tk.StringVar(value=self.data_origin)
        self.input_hint = tk.StringVar()
        self.source_choice = tk.StringVar(value='generated')
        self.dynamic_noise = tk.BooleanVar(value=False)
        self.wave_label = tk.StringVar(value=self.waves[self.kind.get()])
        self.connection_label = tk.StringVar(value='未连接')
        self.progress_note = tk.StringVar(value='就绪')
        self.frame_meta = tk.StringVar(value='尚无帧数据')
        self.frame_quality = tk.StringVar(value='核验：N/A')
        self.file_state = tk.StringVar(value='记录：N/A')
        self.footer_meta = tk.StringVar(value='采样率：N/A  |  FFT：N/A  |  窗：N/A  |  数据：Waiting')
        self.result_caption = tk.StringVar(value='测量结果  ·  Waiting')
        self.window_label = tk.StringVar(value='矩形')
        self.action_buttons, self.replay_fields, self.config_widgets, self.preset_buttons = {}, [], [], []
        self.latest_progress = {}
        self.phase_started = self.phase_name = self.job_started = None; self.phase_done = 0
        self.show_peak = tk.BooleanVar(value=True); self.show_obw = tk.BooleanVar(value=False); self.show_bw3 = tk.BooleanVar(value=False)
        self.init_comparison()
        self.build_menu()
        header = ttk.Frame(self,padding=(12,7)); header.pack(fill='x')
        title = ttk.Frame(header); title.pack(side='left')
        ttk.Label(title,text='数字基带测量仪',font=(self.serif,14,'bold')).pack(anchor='w')
        ttk.Label(title,text='I/Q 基带分析 · FPGA / PC',style='Muted.TLabel',font=self.caption_font).pack(anchor='w')
        info = ttk.Frame(header); info.pack(side='right')
        self.contest_label = ttk.Label(info,text='2026 安徽省集成电路精英赛 · 赛道二',font=(self.serif,9))
        self.contest_label.pack(anchor='e')
        self.entrants_label = ttk.Label(info,text='500 MSPS 数字基带测量仪',style='Muted.TLabel',font=self.caption_font)
        self.entrants_label.pack(anchor='e',pady=(2,0))
        from version_switch import install_version_selector
        self.version_header = header
        ttk.Separator(self).pack(fill='x')
        footer = ttk.Frame(self,padding=(12,4)); footer.pack(side='bottom',fill='x')
        ttk.Label(footer,textvariable=self.connection_label,style='Muted.TLabel').pack(side='left')
        ttk.Separator(footer,orient='vertical').pack(side='left',fill='y',padx=9)
        self.footer_label = ttk.Label(footer,textvariable=self.footer_meta,style='Muted.TLabel',font=self.caption_font)
        self.footer_label.pack(side='left')
        ttk.Label(footer,textvariable=self.frame_quality,style='Muted.TLabel',font=self.caption_font).pack(side='right')
        self.body = ttk.Frame(self,padding=(10,8)); self.body.pack(fill='both',expand=True)
        self.side_holder = tk.Frame(self.body,background=SIDE,width=292,highlightbackground=BORDER,highlightthickness=1)
        self.side_holder.pack(side='left',fill='y',padx=(0,10)); self.side_holder.pack_propagate(False)
        self.build_sidebar(self.side_holder)
        install_version_selector(self,self.version_header,500)
        self.main = ttk.Frame(self.body); self.main.pack(side='left',fill='both',expand=True)
        self.build_metrics(self.main)
        self.notebook = ttk.Notebook(self.main); self.notebook.pack(fill='both',expand=True,pady=(7,0))
        self.tabs = {}
        for key,label in [('完整频谱','频谱分析'),('时域快照','时域 I/Q'),('频谱历史','频谱历史'),
                          ('比赛验证','验证证据'),('诊断与上板','硬件与诊断'),('参考对比','参考对比')]:
            tab = ttk.Frame(self.notebook,style='Surface.TFrame',padding=9); self.tabs[key] = tab; self.notebook.add(tab,text=label)
        self.build_charts(); self.build_diagnostics(); self.build_tests(); self.build_comparison()
        self.use_replay.trace_add('write',lambda *_: self.sync_input())
        self.kind.trace_add('write',lambda *_: self.sync_wave())
        self.hann.trace_add('write',lambda *_: self.window_label.set('周期 Hann' if self.hann.get() else '矩形'))
        self.burst.trace_add('write',lambda *_: self.sync_input())
        self.origin.trace_add('write',lambda *_: self.update_frame_labels())
        for variable in (self.n,self.kind,self.f1,self.f2,self.amplitude,self.noise,self.burst_length,self.hann,self.burst,self.use_replay,self.hi,self.lo):
            variable.trace_add('write',lambda *_: self.mark_pending())
        self.sync_input(); self.after(250,self.refresh_presentation)

    def build_menu(self):
        menu = tk.Menu(self,tearoff=False,font=self.ui_font); self.configure(menu=menu)
        self.file_menu = tk.Menu(menu,tearoff=False,font=self.ui_font); menu.add_cascade(label='文件',menu=self.file_menu)
        for key,label,action in [('import_iq','选择外部 I/Q…',self.import_iq_file),('import','打开板卡实测记录…',self.open_hardware),
                                 ('simulation','载入 RTL 仿真…',self.open_simulation),('export','导出测量与证据…',self.export),
                                 ('export_comparison','导出参考对比…',self.save_comparison)]:
            self.file_menu.add_command(label=label,command=action)
            self.action_buttons[key] = MenuCommand(self.file_menu,self.file_menu.index('end'))
        self.file_menu.add_separator(); self.file_menu.add_command(label='关闭',command=self.close_console)
        view = tk.Menu(menu,tearoff=False,font=self.ui_font); menu.add_cascade(label='视图',menu=view)
        view.add_checkbutton(label='启用参考对比',variable=self.comparison_enabled,command=self.toggle_comparison)
        view.add_command(label='恢复全频段',command=self.reset_view)
        view.add_command(label='清空频谱历史 / 峰值保持',command=self.clear_history)

    def build_metrics(self,parent):
        strip = tk.Frame(parent,bg=SURFACE,highlightbackground=BORDER,highlightthickness=1); strip.pack(fill='x')
        heading=tk.Frame(strip,bg=SURFACE);heading.pack(fill='x')
        tk.Label(heading,textvariable=self.result_caption,bg=SURFACE,fg=MUTED,font=self.caption_font).pack(side='left',padx=10,pady=(5,3))
        self.build_compliance_header(heading)
        row = tk.Frame(strip,bg=SURFACE); row.pack(fill='x',padx=4,pady=(0,7))
        self.cards, self.card_value_labels, self.display_cards, self.card_caption_labels = {}, {}, {}, {}
        for i,(name,unit) in enumerate([('谱峰频点','MHz'),('99%占用带宽','MHz'),('−3dB主峰带宽','kHz'),('复数RMS','码值'),('帧长度','样本'),('硬件处理时间','μs'),('环形99%带宽','MHz')]):
            row.columnconfigure(2*i,weight=1,uniform='result')
            cell = tk.Frame(row,bg=SURFACE); cell.grid(row=0,column=2*i,sticky='nsew',padx=9)
            caption = name.replace('−3dB','−3 dB').replace('复数RMS','复数 RMS')
            if name=='99%占用带宽':caption='线性 99% 带宽 · PC'
            if name=='环形99%带宽':caption='环形 99% 带宽 · FPGA'
            caption_label=tk.Label(cell,text=caption+' / '+unit,bg=SURFACE,fg=MUTED,font=self.caption_font,wraplength=118,justify='left')
            caption_label.pack(anchor='w');self.card_caption_labels[name]=caption_label
            self.cards[name] = tk.StringVar(value='—'); self.display_cards[name] = tk.StringVar(value='N/A')
            label = tk.Label(cell,textvariable=self.display_cards[name],bg=SURFACE,fg=INK,font=(self.latin,13))
            label.pack(anchor='w',pady=(3,0)); self.card_value_labels[name] = label
            if i < 6: ttk.Separator(row,orient='vertical').grid(row=0,column=2*i+1,sticky='ns',pady=3)

    def group(self,parent,title):
        group = ttk.LabelFrame(parent,text=title,padding=(8,5)); group.pack(fill='x',pady=(0,7)); return group

    def build_sidebar(self,parent):
        controls = ttk.LabelFrame(parent,text='采集控制',padding=(8,6)); controls.pack(side='bottom',fill='x',padx=8,pady=(0,8))
        self.button(controls,'connect','连接开发板',self.connect_board,fill='x',pady=(0,5))
        row = ttk.Frame(controls,style='Side.TFrame'); row.pack(fill='x')
        self.button(row,'capture','单次采集',self.capture_board,primary=True,side='left',fill='x',expand=True,padx=(0,5))
        self.button(row,'live','连续采集',self.start_live,side='left',fill='x',expand=True)
        self.button(controls,'stop','停止 / 取消',self.stop_live,fill='x',pady=5).configure(style='Stop.TButton')
        self.progress = ttk.Progressbar(controls,mode='determinate'); self.progress.pack(fill='x',pady=(1,4))
        ttk.Label(controls,textvariable=self.progress_note,style='SideMuted.TLabel',font=self.caption_font,wraplength=250).pack(fill='x')
        holder = ttk.Frame(parent,style='Side.TFrame'); holder.pack(fill='both',expand=True,padx=7,pady=(7,0))
        self.side_canvas = tk.Canvas(holder,bg=SIDE,highlightthickness=0); self.side_canvas.pack(side='left',fill='both',expand=True)
        scrollbar = ttk.Scrollbar(holder,orient='vertical',command=self.side_canvas.yview); scrollbar.pack(side='right',fill='y')
        self.side_canvas.configure(yscrollcommand=scrollbar.set)
        side = ttk.Frame(self.side_canvas,style='Side.TFrame'); self.side_window = self.side_canvas.create_window(0,0,window=side,anchor='nw')
        side.bind('<Configure>',lambda _: self.side_canvas.configure(scrollregion=self.side_canvas.bbox('all')))
        self.side_canvas.bind('<Configure>',lambda e: self.side_canvas.itemconfigure(self.side_window,width=e.width))
        def wheel(event):
            if self.side_holder.winfo_rootx() <= event.x_root < self.side_holder.winfo_rootx()+self.side_holder.winfo_width():
                self.side_canvas.yview_scroll(-int(event.delta/120),'units')
        self.bind('<MouseWheel>',wheel,add='+')
        source = self.group(side,'输入源')
        for value,label in [('generated','合成 I/Q 回放'),('file','外部 I/Q 文件回放')]:
            w = ttk.Radiobutton(source,text=label,variable=self.source_choice,value=value,command=self.select_source); w.pack(anchor='w'); self.config_widgets.append(w)
        ttk.Label(source,textvariable=self.input_hint,style='SideMuted.TLabel',font=self.caption_font,wraplength=232).pack(fill='x',pady=(4,1))
        self.file_panel = ttk.Frame(side,style='Side.TFrame'); self.file_panel.pack(fill='x')
        row = ttk.Frame(self.file_panel,style='Side.TFrame'); row.pack(fill='x',pady=(0,4))
        self.button(row,'import_iq','选择 I/Q 文件…',self.import_iq_file,side='left',fill='x',expand=True)
        self.button(row,'clear_iq','清除',self.clear_import,side='right',padx=(5,0))
        self.import_label = ttk.Label(self.file_panel,textvariable=self.import_note,style='SideMuted.TLabel',font=self.caption_font,wraplength=240); self.import_label.pack(fill='x',pady=(0,6))
        self.generator_panel = ttk.Frame(side,style='Side.TFrame'); self.generator_panel.pack(fill='x')
        generator = self.group(self.generator_panel,'激励参数')
        self.wave_combo = ttk.Combobox(generator,textvariable=self.wave_label,values=list(self.waves.values()),state='readonly'); self.wave_combo.pack(fill='x',pady=(0,4)); self.replay_fields.append(self.wave_combo)
        self.wave_combo.bind('<<ComboboxSelected>>',lambda _: self.kind.set(next(k for k,v in self.waves.items() if v == self.wave_label.get())))
        self.frequency_labels, self.frequency_entries = [], []
        for label,var in [('频率 / MHz',self.f1),('频率 2 / MHz',self.f2),('幅度 / 码值',self.amplitude),('噪声 σ / 码值',self.noise)]:
            row = ttk.Frame(generator,style='Side.TFrame'); row.pack(fill='x',pady=2)
            text = ttk.Label(row,text=label,style='Side.TLabel',width=15); text.pack(side='left')
            entry = ttk.Entry(row,textvariable=var,width=11,font=(self.latin,9)); entry.pack(side='right',fill='x',expand=True); self.replay_fields.append(entry)
            if var in (self.f1,self.f2): self.frequency_labels.append(text); self.frequency_entries.append(entry)
        self.dynamic_noise_check = ttk.Checkbutton(generator,text='动态演示 · 每帧新噪声',variable=self.dynamic_noise,command=self.toggle_dynamic_noise)
        self.dynamic_noise_check.pack(anchor='w',pady=(4,0)); self.config_widgets.append(self.dynamic_noise_check)
        ttk.Label(generator,text='电脑合成噪声；实测与参考使用同一帧',style='SideMuted.TLabel',font=self.caption_font,wraplength=230).pack(anchor='w')
        self.analysis_panel = ttk.Frame(side,style='Side.TFrame'); self.analysis_panel.pack(fill='x')
        settings = self.group(self.analysis_panel,'分析设置')
        for label,var,choices in [('FFT 点数',self.n,['8192','16384']),('窗函数',self.window_label,['矩形','周期 Hann'])]:
            row = ttk.Frame(settings,style='Side.TFrame'); row.pack(fill='x',pady=(1,4))
            ttk.Label(row,text=label,style='Side.TLabel',width=12).pack(side='left')
            w = ttk.Combobox(row,textvariable=var,values=choices,state='readonly',width=12); w.pack(side='right',fill='x',expand=True); self.config_widgets.append(w)
            if var is self.window_label: w.bind('<<ComboboxSelected>>',lambda _: self.hann.set(self.window_label.get() == '周期 Hann'))
        for label,var in [('突发检测',self.burst),('读取板上前 1024 对 I/Q',self.scope_enabled)]:
            w = ttk.Checkbutton(settings,text=label,variable=var); w.pack(anchor='w',pady=1); self.config_widgets.append(w)
        self.burst_settings = ttk.Frame(settings,style='Side.TFrame'); self.burst_settings.pack(fill='x')
        ttk.Label(self.burst_settings,text='激励样本数',style='Side.TLabel',width=12).pack(side='left')
        self.burst_entry = ttk.Entry(self.burst_settings,textvariable=self.burst_length,width=12); self.burst_entry.pack(side='right',fill='x',expand=True); self.replay_fields.append(self.burst_entry)
        ttk.Label(settings,text='数字回放 500 MSPS；频谱采用批量读回',style='SideMuted.TLabel',font=self.caption_font,wraplength=230).pack(anchor='w',pady=(4,4))
        self.button(settings,'preview','软件参考预览',self.preview,fill='x')

    def build_charts(self):
        self.show_linear_obw=tk.BooleanVar(value=False)
        tab = self.tabs['完整频谱']; toolbar = ttk.Frame(tab,style='Surface.TFrame'); toolbar.pack(fill='x',pady=(0,5))
        ttk.Label(toolbar,text='相对本帧峰值功率 / dBc',style='SurfaceMuted.TLabel',font=self.caption_font).pack(side='left')
        for text,var in [('谱峰',self.show_peak),('环形99% 边界',self.show_obw),('线性99% 边界',self.show_linear_obw),('−3 dB 边界',self.show_bw3),('峰值保持',self.max_hold)]:
            ttk.Checkbutton(toolbar,text=text,variable=var,style='Chart.TCheckbutton',command=self.plot_spectrum).pack(side='left',padx=(8,0))
        ttk.Button(toolbar,text='全频段',command=self.reset_view).pack(side='right')
        self.spectrum_canvas = tk.Canvas(tab,bg=PLOT,highlightthickness=0,width=400,height=150); self.spectrum_canvas.pack(fill='both',expand=True)
        self.spectrum_canvas.bind('<Configure>',lambda _: self.schedule_plot('plot_spectrum')); self.spectrum_canvas.bind('<Motion>',self.cursor_move)
        self.spectrum_canvas.bind('<MouseWheel>',self.zoom_spectrum); self.spectrum_canvas.bind('<Double-Button-1>',self.reset_view)
        self.band_note = tk.StringVar(value='尚无频谱')
        ttk.Label(tab,textvariable=self.cursor,style='SurfaceMuted.TLabel',font=self.caption_font).pack(anchor='w',pady=(5,0))
        self.band_label = ttk.Label(tab,textvariable=self.band_note,style='SurfaceMuted.TLabel',font=self.caption_font,wraplength=1160); self.band_label.pack(anchor='w',pady=(2,0))
        tab.bind('<Configure>',lambda event:self.resize_caption(event,self.band_label),add='+')
        self.scope_note = tk.StringVar(value='尚无输入快照')
        ttk.Label(self.tabs['时域快照'],textvariable=self.scope_note,style='SurfaceMuted.TLabel',font=self.caption_font).pack(anchor='w',pady=(0,5))
        self.time_canvas = tk.Canvas(self.tabs['时域快照'],bg=PLOT,highlightthickness=0); self.time_canvas.pack(fill='both',expand=True); self.time_canvas.bind('<Configure>',lambda _: self.schedule_plot('plot_time'))
        tab = self.tabs['频谱历史']; row = ttk.Frame(tab,style='Surface.TFrame'); row.pack(fill='x',pady=(0,5))
        ttk.Label(row,text='最近 100 帧 · 逐帧归一化 −80…0 dB · 上旧下新',style='SurfaceMuted.TLabel',font=self.caption_font).pack(side='left')
        ttk.Button(row,text='清空历史 / 峰值保持',command=self.clear_history).pack(side='right')
        self.waterfall = tk.Canvas(tab,bg=PLOT,highlightthickness=0); self.waterfall.pack(fill='both',expand=True); self.waterfall.bind('<Configure>',lambda _: self.schedule_plot('plot_waterfall'))

    def build_diagnostics(self):
        tab = self.tabs['诊断与上板']
        for label,var in [('Vivado 可执行文件（填写 vivado.bat）',self.vivado),
                          ('JTAG 目标（留空自动发现）',self.target),
                          ('USB 线缆编号（留空自动发现）',self.cable_filter)]:
            row = ttk.Frame(tab,style='Surface.TFrame'); row.pack(fill='x',pady=(0,5))
            ttk.Label(row,text=label,style='SurfaceMuted.TLabel',width=18).pack(side='left')
            entry = ttk.Entry(row,textvariable=var); entry.pack(side='left',fill='x',expand=True); self.config_widgets.append(entry)
        # Never carry a target path from the donor computer.  The bridge will
        # select the only visible target, or list all targets if there are many.
        self.target.set('')
        row = ttk.Frame(tab,style='Surface.TFrame'); row.pack(fill='x',pady=5)
        for label,var in [('高能量门限',self.hi),('低能量门限',self.lo),('连续采集间隔 / s',self.interval)]:
            f = ttk.Frame(row,style='Surface.TFrame'); f.pack(side='left',fill='x',expand=True,padx=(0,9))
            ttk.Label(f,text=label,style='SurfaceMuted.TLabel',font=self.caption_font).pack(anchor='w')
            entry = ttk.Entry(f,textvariable=var,width=12); entry.pack(fill='x',pady=3); self.config_widgets.append(entry)
        ttk.Label(tab,text='突发：连续 4 点越高门限启动，连续 4 点低于低门限结束；间隔在上一帧传输后计时。',style='SurfaceMuted.TLabel',font=self.caption_font).pack(anchor='w',pady=(0,7))
        row = ttk.Frame(tab,style='Surface.TFrame'); row.pack(fill='x',pady=(0,7))
        self.button(row,'program','编程已验证固件',self.program,side='left',padx=(0,7)); self.button(row,'monitor','检查连续处理计数',self.monitor,side='left')
        logs = ttk.Frame(tab,style='Surface.TFrame'); logs.pack(fill='both',expand=True)
        self.diagnostic = tk.Text(logs,bg='#F9FAFB',fg=INK,insertbackground=BLUE,font=(self.latin,9),wrap='word',height=8,relief='flat',highlightbackground=BORDER,highlightthickness=1)
        self.diagnostic.pack(side='left',fill='both',expand=True)
        scrollbar = ttk.Scrollbar(logs,command=self.diagnostic.yview); scrollbar.pack(side='right',fill='y'); self.diagnostic.configure(yscrollcommand=scrollbar.set)
        self.diagnostic.insert('end','连接、固件和测量状态以操作返回为准。启动不会自动连接或编程。\n')
        self.transfer_label=ttk.Label(tab,textvariable=self.transfer,style='SurfaceMuted.TLabel',font=self.caption_font,wraplength=1160)
        self.transfer_label.pack(anchor='w',pady=(6,0))
        tab.bind('<Configure>',lambda event:self.resize_caption(event,self.transfer_label),add='+')

    def resize_caption(self,event,label):
        if event.widget is not label.master:return
        width=max(event.width-24,300)
        if int(label.cget('wraplength'))!=width:label.configure(wraplength=width)

    def build_tests(self):
        tab = self.tabs['比赛验证']
        ttk.Label(tab,text='比赛要求与验证记录',style='Surface.TLabel').pack(anchor='w')
        ttk.Label(tab,text='单帧实测不等于完整验收；未完成项目保留待验证状态。',style='SurfaceMuted.TLabel',font=self.caption_font).pack(anchor='w',pady=(3,7))
        demo=ttk.Frame(tab,style='Surface.TFrame');demo.pack(fill='x',pady=(0,7))
        ttk.Label(demo,text='比赛实测示例',style='SurfaceMuted.TLabel').pack(side='left',padx=(0,8))
        self.demo_choice=tk.StringVar()
        self.demo_combo=ttk.Combobox(demo,textvariable=self.demo_choice,state='readonly',width=36);self.demo_combo.pack(side='left',fill='x',expand=True)
        ttk.Button(demo,text='载入并对比',command=self.load_demo).pack(side='left',padx=(8,0))
        frame = ttk.Frame(tab,style='Surface.TFrame'); frame.pack(fill='both',expand=True)
        self.test_table = ttk.Treeview(frame,columns=('requirement','target','evidence'),show='headings')
        for key,label,width in [('requirement','要求 / 验证项',155),('target','工程指标',210),('evidence','证据与状态',530)]:
            self.test_table.heading(key,text=label); self.test_table.column(key,width=width,minwidth=110,anchor='w')
        self.test_table.pack(side='left',fill='both',expand=True)
        scrollbar = ttk.Scrollbar(frame,command=self.test_table.yview); scrollbar.pack(side='right',fill='y'); self.test_table.configure(yscrollcommand=scrollbar.set)
        scroll = ttk.Scrollbar(tab,orient='horizontal',command=self.test_table.xview); scroll.pack(fill='x'); self.test_table.configure(xscrollcommand=scroll.set)
        ttk.Button(tab,text='刷新验证记录',command=self.refresh_tests).pack(anchor='e',pady=(7,0)); self.refresh_tests()


