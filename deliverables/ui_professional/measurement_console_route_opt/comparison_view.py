"""Opt-in reference view. PC and actual-board snapshots have separate lifetimes."""
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from pathlib import Path
import datetime
import json
import numpy as np
from theme import *
from comparison import Configuration, hardware_frame, reference_frame, bind_saved_input, pairing, export_comparison
from plotting import spectrum_points


class ComparisonView:
    def schedule_plot(self,name):
        pending=getattr(self,'_pending_plots',None)
        if pending is None:self._pending_plots=pending=set()
        if name in pending:return
        pending.add(name)
        def draw():
            pending.discard(name)
            getattr(self,name)()
        self.after_idle(draw)

    def init_comparison(self):
        self.comparison_enabled = tk.BooleanVar(value=False)
        self.show_reference = tk.BooleanVar(value=True)
        self.show_hardware = tk.BooleanVar(value=True)
        self.reference_snapshot = self.hardware_snapshot = None
        self.hardware_problem = ''
        self.comparison_status = tk.StringVar(value='对比关闭 · 普通测量模式')
        self.reference_info = tk.StringVar(value='Reference (PC)  ·  Waiting')
        self.hardware_info = tk.StringVar(value='FPGA (Hardware)  ·  Waiting')
        self.comparison_error = tk.StringVar(value='完整频谱误差：N/A')
        self.comparison_cursor = tk.StringVar(value='频谱采用同一 Reference 峰值归一化；功率不是 dBm。')
        self.comparison_report = dict(state='disabled',issues=[],rows=[],fft_error=None)

    def build_comparison(self):
        tab = self.tabs['参考对比']
        row = ttk.Frame(tab,style='Surface.TFrame'); row.pack(fill='x',pady=(0,5))
        ttk.Checkbutton(row,text='启用参考对比',variable=self.comparison_enabled,style='Chart.TCheckbutton',command=self.toggle_comparison).pack(side='left')
        self.reference_button = ttk.Button(row,text='当前输入生成参考',command=self.current_reference); self.reference_button.pack(side='left',padx=(10,5))
        self.rebuild_button = ttk.Button(row,text='从实测输入重建参考',command=self.record_reference); self.rebuild_button.pack(side='left')
        traces = ttk.Frame(tab,style='Surface.TFrame'); traces.pack(fill='x',pady=(0,5))
        ttk.Checkbutton(traces,text='橙色虚线 · PC 参考',variable=self.show_reference,style='Reference.TCheckbutton',command=self.plot_comparison).pack(side='left')
        ttk.Checkbutton(traces,text='青色实线 · FPGA 实测',variable=self.show_hardware,style='Hardware.TCheckbutton',command=self.plot_comparison).pack(side='left',padx=(14,0))
        self.comparison_status_label = ttk.Label(tab,textvariable=self.comparison_status,style='SurfaceMuted.TLabel',font=self.caption_font,wraplength=1150)
        self.comparison_status_label.pack(anchor='w',pady=(0,5))
        self.reference_label = ttk.Label(tab,textvariable=self.reference_info,style='Reference.TLabel',font=self.caption_font,wraplength=1150)
        self.reference_label.pack(anchor='w')
        self.hardware_label = ttk.Label(tab,textvariable=self.hardware_info,style='Hardware.TLabel',font=self.caption_font,wraplength=1150)
        self.hardware_label.pack(anchor='w',pady=(2,6))
        # A fixed-height table previously consumed nearly the whole page at
        # 125% display scaling. Share the remaining space through grid weights;
        # keep the spectrum readable and scroll the table's remaining rows.
        body = ttk.Frame(tab,style='Surface.TFrame'); body.pack(fill='both',expand=True)
        body.columnconfigure(0,weight=1)
        body.rowconfigure(0,weight=3,minsize=200)
        body.rowconfigure(1,weight=2,minsize=110)
        bottom = ttk.Frame(body,style='Surface.TFrame'); bottom.grid(row=1,column=0,sticky='nsew',pady=(6,0))
        bottom.columnconfigure(0,weight=1); bottom.rowconfigure(0,weight=1)
        table_row = ttk.Frame(bottom,style='Surface.TFrame');table_row.grid(row=0,column=0,sticky='nsew')
        table_row.columnconfigure(0,weight=1); table_row.rowconfigure(0,weight=1)
        self.comparison_table = ttk.Treeview(table_row,columns=('pc','hw','delta','unit','error'),show='tree headings',height=3,style='Compare.Treeview')
        for key,label,width in [('#0','测量项',155),('pc','Reference (PC)',130),('hw','FPGA (Hardware)',130),
                                ('delta','差值 HW − PC',130),('unit','单位',55),('error','误差说明',210)]:
            self.comparison_table.heading(key,text=label)
            self.comparison_table.column(key,width=width,minwidth=50,anchor='w' if key in ('#0','error') else 'e')
        vertical = ttk.Scrollbar(table_row,orient='vertical',command=self.comparison_table.yview);vertical.grid(row=0,column=1,sticky='ns')
        self.comparison_table.grid(row=0,column=0,sticky='nsew');self.comparison_table.configure(yscrollcommand=vertical.set)
        scroll = ttk.Scrollbar(bottom,orient='horizontal',command=self.comparison_table.xview); scroll.grid(row=1,column=0,sticky='ew'); self.comparison_table.configure(xscrollcommand=scroll.set)
        self.comparison_canvas = tk.Canvas(body,bg=PLOT,highlightthickness=0,width=400,height=200)
        self.comparison_canvas.grid(row=0,column=0,sticky='nsew')
        self.comparison_canvas.bind('<Configure>',lambda _: self.schedule_plot('plot_comparison'))
        self.comparison_canvas.bind('<MouseWheel>',self.zoom_comparison)
        self.comparison_canvas.bind('<Double-Button-1>',self.reset_comparison_view)
        self.comparison_canvas.bind('<Motion>',self.comparison_motion)
        self.comparison_canvas.bind('<Leave>',lambda _: self.comparison_canvas.delete('cursor'))
        tab.bind('<Configure>',self.resize_comparison,add='+')
        self.refresh_comparison()


    def resize_comparison(self,event):
        if event.widget is self.tabs['参考对比']:
            width = max(event.width-20,100)
            for label in (self.comparison_status_label,self.reference_label,self.hardware_label): label.configure(wraplength=width)

    def observe_frame(self,metric,power,scope):
        if metric['source'] == 'hardware':
            try:
                frame = hardware_frame(metric,power,scope,self.context)
                try: frame,_,_ = bind_saved_input(frame,self.project)
                except (ValueError,OSError,UnicodeError): pass
                self.hardware_snapshot = frame; self.hardware_problem = ''
            except (ValueError,OSError,KeyError,UnicodeError) as e:
                self.hardware_snapshot = None; self.hardware_problem = str(e)
        elif metric['source'] == 'golden_model':
            try: self.reference_snapshot = self.build_current_reference()
            except (ValueError,OSError) as e:
                self.reference_snapshot = None
                self.comparison_status.set('参考生成失败：'+str(e))
        if (metric['source']=='hardware' and self.context.get('dynamic_noise_demo')
            and self.comparison_enabled.get() and self.hardware_snapshot is not None):
            # Every demo frame has a different input: rebuild from its archived
            # full I/Q, never from a fresh random draw or the previous PC frame.
            self.record_reference(quiet=True)
        else:self.refresh_comparison()

    def build_current_reference(self):
        if not self.use_replay.get():
            raise ValueError('当前输入没有完整 I/Q；请先选择电脑生成 I/Q 或导入外部 I/Q 文件')
        iq = self.iq()
        config = Configuration(self.project_clock_hz,len(iq),bool(self.hann.get()),bool(self.burst.get()),int(self.hi.get()),int(self.lo.get()))
        metadata = dict(origin='当前电脑输入配置',stimulus_parameters=self.parameters())
        return reference_frame(iq,config,metadata)

    def current_reference(self):
        if not self.comparison_enabled.get() or self.busy: return
        try:
            self.reference_snapshot = self.build_current_reference()
            self.refresh_comparison()
        except (ValueError,OSError) as e:
            messagebox.showerror('参考生成失败',str(e))

    def record_reference(self,quiet=False):
        if not self.comparison_enabled.get() or self.busy: return
        if self.hardware_snapshot is None:
            if not quiet: messagebox.showinfo('等待真实板卡数据','FPGA (Hardware) 为 Waiting；请先采集或打开实测记录。')
            return
        try:
            frame,iq,provenance = bind_saved_input(self.hardware_snapshot,self.project)
            self.hardware_snapshot = frame
            self.reference_snapshot = reference_frame(iq,frame.config,dict(origin='实测关联输入',**provenance))
            self.refresh_comparison()
        except (ValueError,OSError,UnicodeError) as e:
            self.comparison_status.set('无法重建参考：'+str(e))
            if not quiet: messagebox.showerror('无法重建参考',str(e))

    def toggle_comparison(self):
        if self.comparison_enabled.get():
            self.notebook.select(self.tabs['参考对比'])
            self.refresh_comparison()
            if self.hardware_snapshot is not None and (self.reference_snapshot is None
                or self.hardware_snapshot.metadata['context'].get('dynamic_noise_demo')):
                self.record_reference(quiet=True)
        else:
            self.notebook.select(self.tabs['完整频谱']); self.refresh_comparison()

    def refresh_comparison(self):
        enabled = self.comparison_enabled.get()
        self.comparison_report = pairing(self.reference_snapshot,self.hardware_snapshot) if enabled else dict(state='disabled',issues=[],rows=[],fft_error=None)
        state = self.comparison_report['state']
        if state == 'disabled': self.comparison_status.set('对比关闭 · 普通测量模式')
        elif state == 'ready': self.comparison_status.set('配置与完整输入一致 · 差值 HW − PC · 完整频谱相对 L1：'+(f'{100*self.comparison_report["fft_error"]:.6f} %（BFP 已恢复）' if self.comparison_report['fft_error'] is not None else 'N/A'))
        else: self.comparison_status.set(('Waiting · ' if state == 'waiting' else '配置 / 输入不一致 · 禁止叠加与误差计算：')+'；'.join(self.comparison_report['issues'])+('；'+self.hardware_problem if self.hardware_problem else ''))
        if state=='ready':
            quality=self.comparison_report.get('spectral_quality',{})
            if quality:
                self.comparison_status.set(self.comparison_status.get()+f' · 带外新增功率 {100*quality["outside_excess_energy_ratio"]:.6f}%')
                if quality.get('weak_zero_fraction') is not None:
                    self.comparison_status.set(self.comparison_status.get()+f' · 弱谱零码 {100*quality["weak_zero_fraction"]:.1f}%（参考 −90 至 −40 dBc）')
            if quality.get('flat_top'):
                self.comparison_status.set(self.comparison_status.get()+' · 多个频点接近谱顶，峰位对量化敏感；请对比中心和边界')
                step=quality.get('power_quantization_step_dbc')
                if step is not None:self.comparison_status.set(self.comparison_status.get()+f' · 功率量化步长 {step:.1f} dBc；以下受量化限制')
        for frame,var,label in [(self.reference_snapshot,self.reference_info,'Reference (PC)'),(self.hardware_snapshot,self.hardware_info,'FPGA (Hardware)')]:
            if frame is None:
                var.set(label+'  ·  Waiting / N/A'); continue
            config = frame.config
            window = 'Hann' if config.hann is True else '矩形' if config.hann is False else '窗未记录'
            detail = frame.metadata.get('captured_at',frame.metadata.get('origin','PC 模型'))
            identity = frame.iq_sha256[:12] if frame.iq_sha256 else '未关联完整输入'
            var.set(f'{label}  ·  Fs {config.fs/1e6:g} MSPS / N {config.n} / {window}  ·  {detail}  ·  I/Q {identity}')
        self.comparison_error.set('完整频谱相对 L1 功率误差：'+(f'{100*self.comparison_report["fft_error"]:.6f} %（已恢复 BFP 尺度）' if state == 'ready' and self.comparison_report['fft_error'] is not None else 'N/A'))
        if hasattr(self,'comparison_table'):
            self.populate_comparison(); self.plot_comparison()
            available = enabled and not self.busy and not self.live_running
            self.reference_button.configure(state='normal' if available and self.use_replay.get() else 'disabled')
            self.rebuild_button.configure(state='normal' if available and self.hardware_snapshot is not None else 'disabled')
        if 'export_comparison' in self.action_buttons:
            self.action_buttons['export_comparison'].configure(state='normal' if enabled and state == 'ready' and not self.busy else 'disabled')

    @staticmethod
    def format_value(value,key):
        if value is None: return 'N/A'
        return f'{value:.0f}' if key in ('rms','length') else f'{value:.6f}'

    def populate_comparison(self):
        table = self.comparison_table; table.delete(*table.get_children())
        state = self.comparison_report['state']
        rows = {r['key']:r for r in self.comparison_report['rows']}
        for key,label,unit,scale in [('peak_hz','谱峰频点','MHz',1e6),('center_hz','环形99%区间中心','MHz',1e6),
                                   ('lower_hz','环形99%下边界','MHz',1e6),('upper_hz','环形99%上边界','MHz',1e6),
                                   ('obw_hz','环形99%带宽 · FPGA定义','MHz',1e6),('linear_obw_hz','线性99%带宽 · PC据全谱计算','MHz',1e6),('bw3_hz','−3 dB 主峰带宽','kHz',1e3),('rms','复数 RMS','码值',1),('length','帧长度','样本',1)]:
            row = rows.get(key)
            if row:
                values = (self.format_value(row['reference'],key),self.format_value(row['hardware'],key),
                          'N/A' if row['delta'] is None else f'{row["delta"]:+.6f}' if key.endswith('_hz') else f'{row["delta"]:+g}',unit,row['error'])
            else:
                values = []
                for frame in (self.reference_snapshot,self.hardware_snapshot):
                    value = frame.metric.get(key) if frame and state != 'disabled' else None
                    if key == 'peak_hz' and frame and frame.metric['no_signal']: value = None
                    values.append(self.format_value(None if value is None else value/scale,key))
                values += ['N/A',unit,'未比较']
            table.insert('','end',iid=key,text=label,values=values)
        hw_latency = self.hardware_snapshot.metric.get('latency_us') if self.hardware_snapshot and state != 'disabled' else None
        table.insert('','end',iid='latency',text='硬件处理时间',values=('N/A',self.format_value(hw_latency,'latency'),'N/A','μs','仅硬件周期计数'))

    def plot_comparison(self):
        if not hasattr(self,'comparison_canvas'): return
        c = self.comparison_canvas
        label = '频率 / MHz · 功率以 Reference 峰值归一化（非 dBm）' if self.reference_snapshot else '频率 / MHz · 功率以 FPGA 峰值归一化；Reference 为 Waiting'
        bounds = self.axes(c,-100,5,self.view_low,self.view_high,label)
        left,right,top,bottom = bounds
        state = self.comparison_report['state']
        if state in ('disabled','mismatch'):
            text = '对比关闭' if state == 'disabled' else '配置 / 输入不一致\n不绘制叠加频谱，不计算差值'
            c.create_text((left+right)/2,(top+bottom)/2,text=text,fill=TICK,font=self.ui_font); return
        reference,hardware = self.reference_snapshot,self.hardware_snapshot
        if reference is None and hardware is None:
            c.create_text((left+right)/2,(top+bottom)/2,text='Waiting / 尚无可显示的数据',fill=TICK,font=self.ui_font); return
        denominator = float(reference.power.max()) if reference else float(hardware.power.max())*2.**(2*hardware.metric['block_exponent'])
        if hardware and denominator>0:
            step=10*np.log10(2.**(2*hardware.metric['block_exponent'])/denominator)
            if -100<step<5:
                y=bottom-(step+100)/105*(bottom-top)
                c.create_line(left,y,right,y,fill=TICK,dash=(3,6),width=1,tags='quantization_step')
                c.create_text(right-4,y+5,text=f'功率量化步长 {step:.1f} dBc；零码落在显示底线',fill=TICK,anchor='ne',font=self.caption_font,tags='quantization_step')
        # Draw the wider solid hardware curve first. The thinner dashed PC
        # curve leaves cyan visible even when both spectra coincide exactly.
        for frame,color,tag,visible,width in [(hardware,HARDWARE_TRACE,'hardware',self.show_hardware.get(),3.0),(reference,REFERENCE_TRACE,'reference',self.show_reference.get(),1.8)]:
            if frame is None or not visible: continue
            p = frame.power.astype(float)*(2.**(2*frame.metric['block_exponent']) if frame.source == 'hardware' else 1.)
            points = spectrum_points(p,frame.config.fs,self.view_low,self.view_high,bounds,denominator,-100,5)
            if points: c.create_line(points,fill=color,width=width,dash=(8,5) if tag == 'reference' else (),tags=tag)
        for x,color,dash,text in [(left+7,REFERENCE_TRACE,(8,5),'Reference (PC)'),(left+207,HARDWARE_TRACE,(),'FPGA (Hardware)')]:
            c.create_line(x,top-15,x+32,top-15,fill=color,width=2.5,dash=dash,tags='legend')
            c.create_text(x+40,top-15,text=text,fill=color,anchor='w',font=self.chart_font,tags='legend')

    def zoom_comparison(self,event):
        if self.comparison_report['state'] == 'ready': self.zoom_spectrum(event); self.plot_comparison()
        return 'break'

    def reset_comparison_view(self,event=None):
        self.reset_view(); self.plot_comparison()

    def comparison_motion(self,event):
        if self.comparison_report['state'] != 'ready': return
        width = max(self.comparison_canvas.winfo_width()-88,1)
        frequency = self.view_low+float(np.clip((event.x-64)/width,0,1))*(self.view_high-self.view_low)
        frame = self.reference_snapshot; n,fs = frame.config.n,frame.config.fs
        index = int(round(frequency*1e6*n/fs))%n
        pc = float(frame.power[index]); hw = float(self.hardware_snapshot.power[index])*2.**(2*self.hardware_snapshot.metric['block_exponent'])
        signed = index if index < n//2 else index-n
        exact_frequency = signed*fs/n/1e6
        self.comparison_cursor.set(f'bin {index} / {exact_frequency:.5f} MHz\nP_PC {pc:.6g}  /  P_HW {hw:.6g}  /  ΔP {hw-pc:+.6g}')
        canvas = self.comparison_canvas; canvas.delete('cursor')
        canvas.create_text(canvas.winfo_width()-30,40,text=self.comparison_cursor.get(),
                           fill=TICK,anchor='ne',font=self.chart_font,tags='cursor')

    def save_comparison(self,path=None):
        if not self.comparison_enabled.get() or self.comparison_report['state'] != 'ready' or self.busy: return
        if path is None:
            selected = filedialog.askdirectory(title='导出参考对比证据')
            if not selected: return
            path = Path(selected)/('comparison_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        try:
            export_comparison(path,self.reference_snapshot,self.hardware_snapshot)
            self.progress_note.set('参考对比已导出：'+str(path))
        except (ValueError,OSError) as e:
            messagebox.showerror('对比导出失败',str(e))
