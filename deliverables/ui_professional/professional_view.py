"""Instrument UI additions; analyses are explicitly PC-side and frame-bound."""
from pathlib import Path
from datetime import datetime, timezone
import csv, json, time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
from measurement_tools import band_mask, tone_estimate, statistics
from recording_import import read_recording, convert_recording, save_converted


class ProfessionalView:
    def build(self):
        self.session_rows = []; self.session_ids = set(); self.session_config = None
        self.mask_report = None; self.mask_window = None; self.import_window = None
        self.mask_enabled = tk.BooleanVar(value=False)
        self.mask_low = tk.StringVar(value='-50'); self.mask_high = tk.StringVar(value='50')
        self.mask_limit = tk.StringVar(value='-40')
        self.mask_note = tk.StringVar(value='模板未启用')
        self.estimate_note = tk.StringVar(value='单音估计：尚无数据')
        self.session_note = tk.StringVar(value='本会话新采集帧 0 · 历史记录与软件预览不计入')
        self.transport_note = tk.StringVar(value='本次操作：未测量 · 上传/下载参考上限见验证记录')
        super().build()
        from version_switch import LABELS
        self.title('数字基带测量仪 · '+LABELS[int(self.project_clock_hz/1e6)]+' · 专业测量台')
        self.contest_label.configure(text='数字基带分析 · 测量与验证')
        self.entrants_label.configure(text='12-bit I/Q  /  FPGA + PC')
        self.compliance_button.configure(text='原赛题指标…')
        self._build_analysis_tab()
        self.file_menu.insert_command(0,label='转换外部录波…',command=self.open_recording_converter)
        self._install_detail_strip()
        for var in (self.mask_enabled,self.mask_low,self.mask_high,self.mask_limit):
            var.trace_add('write',lambda *_:self.schedule_plot('plot_spectrum'))

    def _install_detail_strip(self):
        bar = ttk.Frame(self.main, style='Surface.TFrame', padding=(10,5))
        bar.pack(fill='x', before=self.notebook, pady=(5,0))
        ttk.Label(bar,textvariable=self.estimate_note,style='SurfaceMuted.TLabel',font=self.caption_font).pack(side='left')
        ttk.Button(bar,text='模板 / 统计',command=lambda:self.notebook.select(self.tabs['测量工具'])).pack(side='right')
        ttk.Label(self.tabs['诊断与上板'],textvariable=self.transport_note,
                  style='SurfaceMuted.TLabel',wraplength=1000).pack(fill='x',pady=4)

    def _build_analysis_tab(self):
        tab = ttk.Frame(self.notebook,style='Surface.TFrame',padding=12)
        self.tabs['测量工具'] = tab; self.notebook.add(tab,text='模板与统计')
        settings = ttk.Frame(tab,style='Surface.TFrame'); settings.pack(fill='x')
        ttk.Checkbutton(settings,text='启用带外频谱模板',variable=self.mask_enabled,
                        style='Chart.TCheckbutton').pack(side='left',padx=(0,14))
        for text,var in [('允许频带下限 / MHz',self.mask_low),('上限 / MHz',self.mask_high),('带外上限 / dBc',self.mask_limit)]:
            f = ttk.Frame(settings,style='Surface.TFrame'); f.pack(side='left',padx=8)
            ttk.Label(f,text=text,style='SurfaceMuted.TLabel').pack(anchor='w')
            ttk.Entry(f,textvariable=var,width=12).pack(pady=4)
        ttk.Button(settings,text='查看频谱',command=lambda:self.notebook.select(self.tabs['完整频谱'])).pack(side='right')
        self.mask_status_label=ttk.Label(tab,textvariable=self.mask_note,style='Surface.TLabel',wraplength=1100)
        self.mask_status_label.pack(fill='x',pady=(12,4))
        ttk.Label(tab,text='模板参考本帧最大谱功率；边界按FFT栅格判断。低于量化能力的阈值仅作观察。判定不是绝对功率校准，也不是赛事总体验收。',
                  style='SurfaceMuted.TLabel',wraplength=1050).pack(anchor='w',pady=(0,12))
        row=ttk.Frame(tab,style='Surface.TFrame');row.pack(fill='x')
        ttk.Label(row,textvariable=self.session_note,style='Surface.TLabel').pack(side='left')
        ttk.Button(row,text='导出统计',command=self.export_session).pack(side='right')
        ttk.Button(row,text='清空统计',command=self.clear_session).pack(side='right',padx=6)
        self.stats_table=ttk.Treeview(tab,columns=('name','count','mean','std','min','max','unit'),show='headings',height=5)
        for key,label,width in [('name','指标',145),('count','帧数',60),('mean','均值',130),('std','样本标准差',130),('min','最小值',130),('max','最大值',130),('unit','单位',60)]:
            self.stats_table.heading(key,text=label);self.stats_table.column(key,width=width,anchor='w' if key=='name' else 'e',stretch=True)
        self.stats_table.pack(fill='x',pady=8)
        ttk.Label(tab,text='仅统计本会话新采集的唯一硬件记录；每次改变采样率、点数、窗口或输入配置时重新建立统计组。软件预览、历史重放及界面重绘不累计。最多保留最近10000帧。',
                  style='SurfaceMuted.TLabel',wraplength=1100).pack(anchor='w')
        self.trend_canvas=tk.Canvas(tab,bg='#15191E',highlightthickness=0,height=160)
        self.trend_canvas.pack(fill='both',expand=True,pady=(10,0))
        self.trend_canvas.bind('<Configure>',lambda _:self.schedule_plot('plot_trend'))
        self.refresh_statistics()

    def load(self,metric,power,scope=None):
        super().load(metric,power,scope)
        for key,text in [('谱峰频点','谱峰频率\nMHz'),('99%占用带宽','线性99%带宽 · PC\nMHz'),
                         ('−3dB主峰带宽','−3 dB主峰带宽\nkHz'),('复数RMS','复数RMS\n码值'),
                         ('帧长度','当前帧长度\n样本'),('硬件处理时间','硬件处理延迟\nµs'),
                         ('环形99%带宽','环形99%带宽 · '+('FPGA' if metric['source']=='hardware' else '参考')+'\nMHz')]:
            self.card_caption_labels[key].configure(text=text)
        estimate=tone_estimate(power,metric['fs'])
        self.estimate_note.set(f'单音精细估计 {estimate["frequency_hz"]/1e6:.6f} MHz · PC插值，非分辨率'
                              if estimate['valid'] else '单音估计：'+estimate['reason'])
        archive=getattr(self,'_professional_archive',False) or getattr(self,'_reading_archive',False)
        faults=sum(int(metric.get(k) or 0) for k in ('input_drops','protocol_errors','skipped_frames','time_dropped_jobs','command_error'))
        if metric['source']=='hardware' and not archive and not faults:
            key=self.context.get('capture_folder') or self.context.get('captured_at')
            stimulus=dict(self.context.get('stimulus_parameters') or {})
            # Per-frame demo noise is a repeated experiment, not a new settings
            # group. Keep its provenance in the record while accumulating stats.
            stimulus.pop('noise_seed',None)
            config=json.dumps([metric['fs'],metric['n'],self.measurement_window(),stimulus,self.context.get('source_mode'),self.context.get('imported_file'),self.context.get('threshold_hi'),self.context.get('threshold_lo'),self.context.get('burst'),self.context.get('dynamic_noise_demo',False)],sort_keys=True,default=str)
            if key and key not in self.session_ids:
                if self.session_config!=config:
                    self.session_rows=[];self.session_ids=set();self.session_config=config
                self.session_ids.add(key)
                self.session_rows.append(dict(record=key,observed_utc=datetime.now(timezone.utc).isoformat(),
                    peak_hz=metric['peak_hz'] if not metric['no_signal'] else None,
                    bandwidth_hz=self.linear_bandwidth['width_hz'] if self.linear_bandwidth['valid'] else None,
                    rms=metric['rms'],latency_us=metric.get('latency_us')))
                self.session_rows=self.session_rows[-10000:]
                self.refresh_statistics()
        self.schedule_plot('plot_spectrum')

    def import_iq_file(self,path=None):
        if self.busy or self.live_running:return
        if path is None:
            path=filedialog.askopenfilename(title='导入12-bit I/Q帧',filetypes=[('I/Q帧','*.csv *.mem')])
        if not path:return
        audit_path=Path(path).with_suffix('.conversion.json');audit=None
        if audit_path.exists():
            try:
                if audit_path.stat().st_size>2_000_000:raise ValueError('转换审计记录过大')
                audit=json.loads(audit_path.read_text(encoding='utf-8'))
                import hashlib
                if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=audit['converted_sha256']:
                    raise ValueError('I/Q文件与转换审计哈希不一致')
                if float(audit['target_fs_hz'])!=self.project_clock_hz:
                    raise ValueError('转换文件的回放采样率与当前版本不一致，请在当前版本重新转换')
                source_rate=float(audit['source_fs_hz'])
                if not np.isfinite(source_rate) or source_rate<=0 or int(audit['n']) not in (8192,16384):
                    raise ValueError('转换审计中的采样率或帧长无效')
            except (ValueError,OSError,KeyError,TypeError) as e:
                messagebox.showerror('转换记录校验失败',str(e));return
        super().import_iq_file(path)
        if self.imported_metadata and self.imported_metadata.get('path')==str(Path(path).resolve()):
            if audit:
                self.imported_metadata['conversion']=audit
                self.import_note.set(f'{Path(path).name}\n源 {audit["source_fs_hz"]/1e6:g} → 回放 {self.project_clock_hz/1e6:g} MSPS\n转换审计与文件哈希匹配')
            else:
                self.import_note.set(f'{Path(path).name}\n{len(self.imported_iq):,} 对 · 回放 {self.project_clock_hz/1e6:g} MSPS\n原录波采样率未注明，不自动重采样')

    def plot_spectrum(self):
        super().plot_spectrum()
        if not hasattr(self,'mask_status_label'):return
        if not self.mask_enabled.get():
            self.mask_report=None;self.mask_note.set('模板未启用');return
        if self.power is None:self.mask_note.set('模板等待频谱数据');return
        try:report=band_mask(self.power,self.metric['fs'],self.mask_low.get(),self.mask_high.get(),self.mask_limit.get())
        except ValueError as e:
            self.mask_report=dict(state='invalid',error=str(e));self.mask_note.set('模板配置无效：'+str(e));return
        self.mask_report=report
        prefix='历史帧' if '历史' in self.origin.get() or getattr(self,'_professional_archive',False) else '软件参考' if self.metric['source']!='hardware' else '返回帧'
        if self.status.get().startswith('操作失败'):prefix='采集失败后保留帧'
        if '参数待采集' in self.origin.get():prefix+='（参数待采集）'
        if report['state']=='no_signal':self.mask_note.set(prefix+' · 无信号，不能判定模板通过');return
        worst='无带外频点' if report['worst_dbc'] is None else f'{report["worst_dbc"]:.2f} dBc'
        quantum_step=10*np.log10(1/float(self.metric['peak_power'])) if self.metric.get('peak_power',0)>0 else None
        if self.metric['source']=='hardware' and quantum_step is not None and report['limit_dbc']<quantum_step:
            report['state']='limited';report['quantum_step_dbc']=float(quantum_step)
        label='阈值低于功率量化步长，不能判定通过' if report['state']=='limited' else '超限' if report['state']=='fail' else '未检出超限'
        self.mask_note.set(f'{prefix} · '+label+
                           f' · 越界 {report["bins"]} 点 · 带外积分功率 {report["outside_percent"]:.5f}% · 带外最大 {worst}')
        self.mask_status_label.configure(foreground='#A63732' if report['state']=='fail' else '#946100' if report['state']=='limited' else '#226B53')
        c=self.spectrum_canvas; w,h=max(c.winfo_width(),200),max(c.winfo_height(),150)
        left,right,top,bottom=64,w-24,32,h-46
        limit=report['limit_dbc']; y=top-limit/100*(bottom-top)
        for lo,hi in [(-self.metric['fs']/2e6,float(self.mask_low.get())),(float(self.mask_high.get()),self.metric['fs']/2e6)]:
            lo=max(lo,self.view_low);hi=min(hi,self.view_high)
            if hi>lo:
                x1=left+(lo-self.view_low)/(self.view_high-self.view_low)*(right-left)
                x2=left+(hi-self.view_low)/(self.view_high-self.view_low)*(right-left)
                c.create_line(x1,y,x2,y,fill='#D98966',dash=(5,3),width=1.5,tags='mask')
        c.create_text(right-6,top+12,text=f'带外模板 {limit:g} dBc',fill='#D98966',anchor='e',font=self.caption_font,tags='mask')
        # Limit rendered markers to the plot's pixel columns, preserving full-bin evaluation.
        f=np.fft.fftfreq(len(self.power),1/self.metric['fs'])/1e6
        columns=set()
        for k in report['indices']:
            if self.view_low<=f[k]<=self.view_high:
                column=round(left+(f[k]-self.view_low)/(self.view_high-self.view_low)*(right-left));columns.add(column)
        for x in columns:c.create_line(x,top+24,x,top+29,fill='#EF8B79',tags='mask_violation')

    def refresh_statistics(self):
        if not hasattr(self,'stats_table'):return
        self.stats_table.delete(*self.stats_table.get_children())
        summary=statistics(self.session_rows)
        for key,label,scale,unit in [('peak_hz','谱峰频率',1e6,'MHz'),('bandwidth_hz','线性99%带宽',1e6,'MHz'),('rms','复数RMS',1,'码值'),('latency_us','硬件处理延迟',1,'µs')]:
            r=summary[key]
            values=[r['count']]+['—' if r[k] is None else f'{r[k]/scale:.6f}' for k in ('mean','std','minimum','maximum')]
            self.stats_table.insert('', 'end',values=(label,*values,unit))
        self.session_note.set(f'本会话新采集帧 {len(self.session_rows)} · 历史记录与软件预览不计入')
        self.schedule_plot('plot_trend')

    def clear_session(self):
        self.session_rows=[];self.session_ids=set();self.session_config=None;self.refresh_statistics()

    def plot_trend(self):
        if not hasattr(self,'trend_canvas'):return
        c=self.trend_canvas;c.delete('all');w,h=max(c.winfo_width(),200),max(c.winfo_height(),120)
        points=[(i,r['bandwidth_hz']/1e6) for i,r in enumerate(self.session_rows) if r['bandwidth_hz'] is not None]
        if len(points)<2:
            c.create_text(w/2,h/2,text='新采集两帧后显示线性99%带宽趋势',fill='#B8BEC5',font=self.ui_font);return
        lo=min(v for _,v in points);hi=max(v for _,v in points);margin=max((hi-lo)*.15,.0001);lo-=margin;hi+=margin
        for j in range(4):
            y=25+(h-65)*j/3;c.create_line(65,y,w-20,y,fill='#30363D')
            c.create_text(58,y,text=f'{hi-(hi-lo)*j/3:.5f}',fill='#B8BEC5',anchor='e',font=self.caption_font)
        # Every bucket retains extrema; narrow excursions survive downsampling.
        buckets=max(1,w-90);width=max(1,len(self.session_rows)/buckets);segments={}
        for i,value in points:segments.setdefault(int(i/width),[]).append((i,value))
        reduced=[]
        for items in segments.values():reduced.extend(sorted(set((min(items,key=lambda p:p[1]),max(items,key=lambda p:p[1])))))
        coords=[]
        for i,value in reduced:coords.extend([65+i/max(1,len(self.session_rows)-1)*(w-85),25+(hi-value)/(hi-lo)*(h-65)])
        if len(coords)>=4:c.create_line(coords,fill='#8CC5AE',width=1.3)
        c.create_text(70,12,text='线性99%带宽 / MHz',fill='#B8BEC5',anchor='w',font=self.caption_font)
        c.create_text(w/2,h-12,text='新采集帧序号（非连续采样时间轴）',fill='#B8BEC5',font=self.caption_font)

    def export_session(self,path=None):
        if not self.session_rows:
            messagebox.showinfo('统计导出','尚无本会话新采集帧');return
        path=path or filedialog.asksaveasfilename(title='导出采集统计',defaultextension='.json',filetypes=[('JSON','*.json')])
        if not path:return
        Path(path).write_text(json.dumps(dict(created_utc=datetime.now(timezone.utc).isoformat(),source='unique_new_hardware_captures',config=self.session_config,summary=statistics(self.session_rows),rows=self.session_rows),ensure_ascii=False,indent=2),encoding='utf-8')
        self.progress_note.set('统计已导出：'+str(path))

    def worker(self,description,function):
        if self.busy:return super().worker(description,function)
        started=time.perf_counter()
        def measured():
            state='完成'
            try:return function()
            except Exception:
                state='失败 / 取消';raise
            finally:
                # Thread writes plain data only; Tk consumes on its main thread.
                self._professional_operation=(description,state,time.perf_counter()-started)
        return super().worker(description,measured)

    def refresh_presentation(self):
        super().refresh_presentation()
        operation=getattr(self,'_professional_operation',None)
        if operation and hasattr(self,'transport_note'):
            description,state,seconds=operation
            self.transport_note.set(f'最近操作：{description} · {state} · 工作线程耗时 {seconds:.3f} s（含通信与处理，不等于FPGA延迟）')

    def open_recording_converter(self):
        if self.busy or self.live_running:return
        if self.import_window and self.import_window.winfo_exists():self.import_window.lift();return
        window=tk.Toplevel(self);self.import_window=window;window.title('外部I/Q录波转换');window.geometry('760x530')
        frame=ttk.Frame(window,padding=16);frame.pack(fill='both',expand=True)
        path=tk.StringVar();fs=tk.StringVar(value=str(int(self.project_clock_hz)));encoding=tk.StringVar(value='cf32_le')
        count=tk.StringVar(value=self.n.get());start=tk.StringVar(value='0');amplitude=tk.StringVar(value='1500')
        mode=tk.StringVar(value='保留原频率：滤波重采样')
        labels=[('源文件',path),('原采样率 / Hz',fs),('目标帧长',count),('起始样本序号',start),('目标I/Q分量峰值 / 码值',amplitude)]
        for index,(label,var) in enumerate(labels):
            ttk.Label(frame,text=label).grid(row=index,column=0,sticky='w',pady=7)
            ttk.Entry(frame,textvariable=var,width=50).grid(row=index,column=1,sticky='ew',pady=7)
        def browse():
            selected=filedialog.askopenfilename(parent=window,title='选择I/Q录波',filetypes=[('I/Q录波','*.sigmf-meta *.npy *.csv *.bin *.iq *.sigmf-data'),('所有文件','*.*')])
            if selected:path.set(selected)
        ttk.Button(frame,text='选择…',command=browse).grid(row=0,column=2,padx=8)
        for row,label,var,choices in [(5,'二进制数据类型',encoding,['cf32_le','ci16_le','ci8','cu8']),
                                      (6,'采样率处理',mode,['保留原频率：滤波重采样','按回放速率解释：频率缩放'])]:
            ttk.Label(frame,text=label).grid(row=row,column=0,sticky='w',pady=7)
            ttk.Combobox(frame,textvariable=var,values=choices,state='readonly',width=43).grid(row=row,column=1,sticky='ew',pady=7)
        ttk.Label(frame,text=f'回放采样率固定为 {self.project_clock_hz/1e6:g} MSPS。SigMF以元数据采样率为准。转换保存新CSV和审计JSON，原文件保持原样；不会自动上传或编程。',wraplength=650).grid(row=7,column=0,columnspan=3,sticky='w',pady=14)
        result=tk.StringVar(value='等待选择源文件')
        ttk.Label(frame,textvariable=result,wraplength=650).grid(row=8,column=0,columnspan=3,sticky='w')
        def convert():
            try:
                x,meta=read_recording(path.get(),encoding.get(),float(fs.get()))
                method='resample' if mode.get().startswith('保留') else 'reinterpret'
                iq,audit=convert_recording(x,meta,self.project_clock_hz,int(count.get()),int(start.get()),method,int(amplitude.get()))
                destination=filedialog.asksaveasfilename(parent=window,title='保存转换后的新I/Q文件',defaultextension='.csv',filetypes=[('I/Q CSV','*.csv')])
                if not destination:return
                save_converted(destination,iq,audit)
                self.import_iq_file(destination)
                self.imported_metadata['conversion']=audit
                self.import_note.set(f'{Path(destination).name}\n源 {meta["source_fs_hz"]/1e6:g} → 回放 {self.project_clock_hz/1e6:g} MSPS\n'+('保留频率 · 重采样' if method=='resample' else f'频率缩放 ×{audit["frequency_scale"]:g}'))
                result.set(f'已转换 {len(iq)} 对I/Q，缩放系数 {audit["normalization_scale"]:.6g}；审计记录已保存。')
            except (ValueError,OSError,KeyError,ImportError,TypeError) as e:result.set('转换失败：'+str(e))
        ttk.Button(frame,text='转换、保存并载入',command=convert).grid(row=9,column=1,sticky='e',pady=16)
