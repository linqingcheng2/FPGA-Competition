"""Competition measurement console. Every view explicitly labels its data source."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
import json,datetime,threading,queue,hashlib,math,time,uuid
import numpy as np
from analysis import FS,make_iq,save_mem,reference_fft,measures,time_reference,bin_hz,WINDOW_ROUNDING
from capture import load_hardware,load_simulation,export_evidence
from live_transport import LiveSession,verify_firmware,classify_error,HardwareTransportError,AcquisitionCancelled
ROOT=Path(__file__).resolve().parents[1]
BG='#101923'; PANEL='#172432'; TEXT='#dce8f3'; MUTED='#8fa3b6'; BLUE='#55b8ff'; GREEN='#6be0b4'

class Console(tk.Tk):
    def __init__(self):
        super().__init__(); self.title('数字基带测量仪 · 安徽省集成电路精英赛 / 赛道二')
        self.geometry('1360x890'); self.minsize(1100,720); self.configure(bg=BG)
        self.metric=None; self.power=None; self.scope=None; self.context={}; self.history=[]; self.jobs=queue.Queue(); self.busy=False
        self.session=None;self.connected=False;self.attached=False;self.live_running=False;self.live_job=None;self.capture_count=0
        self.link=tk.StringVar(value='未连接开发板');self.transfer=tk.StringVar(value='传输：尚无数据');self.interval=tk.StringVar(value='1.0')
        self.target=tk.StringVar(value='');self.max_hold=tk.BooleanVar(value=False);self.hold_db=None
        self.view_low=-FS/2e6;self.view_high=FS/2e6;self.cursor=tk.StringVar(value='鼠标查看频点，滚轮缩放；双击恢复全频段')
        self.protocol('WM_DELETE_WINDOW',self.close_console)
        self.n=tk.StringVar(value='8192'); self.kind=tk.StringVar(value='tone'); self.f1=tk.StringVar(value='10'); self.f2=tk.StringVar(value='20')
        self.amplitude=tk.StringVar(value='1500'); self.burst_length=tk.StringVar(value='2048'); self.noise=tk.StringVar(value='0')
        self.hann=tk.BooleanVar(value=False); self.burst=tk.BooleanVar(value=False); self.scope_enabled=tk.BooleanVar(value=False)
        self.hi=tk.StringVar(value='300000'); self.lo=tk.StringVar(value='100000'); self.vivado=tk.StringVar(value='')
        self.use_replay=tk.BooleanVar(value=True); self.status=tk.StringVar(value='未加载数据 · 板级验证待完成')
        style=ttk.Style(self); style.theme_use('clam')
        style.configure('.',font=('Microsoft YaHei UI',10),background=PANEL,foreground=TEXT)
        style.configure('TFrame',background=BG); style.configure('Card.TFrame',background=PANEL)
        style.configure('TLabel',background=BG,foreground=TEXT); style.configure('Muted.TLabel',foreground=MUTED)
        style.configure('TButton',padding=(14,8),background='#284358'); style.map('TButton',background=[('active','#365c77')])
        style.configure('TEntry',fieldbackground='#223548',foreground=TEXT); style.configure('TCombobox',fieldbackground='#223548',foreground=TEXT)
        style.configure('TCheckbutton',background=BG,foreground=TEXT); style.map('TCheckbutton',background=[('active',BG)])
        style.configure('TNotebook',background=BG,borderwidth=0); style.configure('TNotebook.Tab',padding=(22,10),background=PANEL)
        style.map('TNotebook.Tab',background=[('selected','#28465e')],foreground=[('selected',BLUE)])
        style.configure('Treeview',background=PANEL,fieldbackground=PANEL,foreground=TEXT,rowheight=30)
        style.configure('Treeview.Heading',background='#294054',foreground=TEXT)
        self.build(); self.after(100,self.poll)

    def build(self):
        header=ttk.Frame(self,padding=(22,16)); header.pack(fill='x')
        ttk.Label(header,text='数字基带测量仪',font=('Microsoft YaHei UI',23,'bold')).pack(side='left')
        ttk.Label(header,text=f'12-bit I/Q   /   {FS/1e6:g} MSPS   /   8192 & 16384 FFT',foreground=BLUE).pack(side='right',padx=12)
        ttk.Label(self,textvariable=self.status,style='Muted.TLabel',padding=(24,0,24,10)).pack(fill='x')
        cards=ttk.Frame(self,padding=(18,0)); cards.pack(fill='x'); self.cards={}
        for title in ['谱峰频点','99%占用带宽','−3dB主峰带宽','复数RMS','帧长度','硬件处理时间']:
            frame=ttk.Frame(cards,style='Card.TFrame',padding=(15,12)); frame.pack(side='left',expand=True,fill='x',padx=5)
            tk.Label(frame,text=title,bg=PANEL,fg=MUTED,font=('Microsoft YaHei UI',10)).pack(anchor='w')
            value=tk.StringVar(value='—'); self.cards[title]=value
            tk.Label(frame,textvariable=value,bg=PANEL,fg=TEXT,font=('Microsoft YaHei UI',17,'bold')).pack(anchor='w',pady=(7,0))
        body=ttk.Frame(self,padding=18); body.pack(fill='both',expand=True)
        side_holder=ttk.Frame(body,width=290);side_holder.pack(side='left',fill='y',padx=(0,18));side_holder.pack_propagate(False)
        scroller=tk.Canvas(side_holder,bg=BG,highlightthickness=0);scroller.pack(side='left',fill='both',expand=True)
        scrollbar=ttk.Scrollbar(side_holder,orient='vertical',command=scroller.yview);scrollbar.pack(side='right',fill='y');scroller.configure(yscrollcommand=scrollbar.set)
        side=ttk.Frame(scroller);side_window=scroller.create_window(0,0,window=side,anchor='nw')
        side.bind('<Configure>',lambda e:scroller.configure(scrollregion=scroller.bbox('all')))
        scroller.bind('<Configure>',lambda e:scroller.itemconfigure(side_window,width=e.width))
        def sidebar_wheel(event):
            if side_holder.winfo_rootx()<=event.x_root<side_holder.winfo_rootx()+side_holder.winfo_width():scroller.yview_scroll(-int(event.delta/120),'units')
        self.bind('<MouseWheel>',sidebar_wheel,add='+')
        ttk.Label(side,text='激励与测量配置',font=('Microsoft YaHei UI',13,'bold')).pack(anchor='w',pady=(0,12))
        def field(label,var,choices=None):
            ttk.Label(side,text=label,style='Muted.TLabel').pack(anchor='w',pady=(5,3))
            widget=ttk.Combobox(side,textvariable=var,values=choices,state='readonly') if choices else ttk.Entry(side,textvariable=var)
            widget.pack(fill='x'); return widget
        field('FFT点数',self.n,['8192','16384']); field('激励类型',self.kind,['tone','chirp','wrap_chirp','qpsk','two_tone','burst','wide','zero'])
        pair=ttk.Frame(side); pair.pack(fill='x',pady=8)
        for label,var in [('频率1 / MHz',self.f1),('频率2 / MHz',self.f2)]:
            f=ttk.Frame(pair); f.pack(side='left',expand=True,fill='x',padx=(0,8)); ttk.Label(f,text=label,style='Muted.TLabel').pack(anchor='w'); ttk.Entry(f,textvariable=var,width=10).pack(fill='x')
        pair=ttk.Frame(side); pair.pack(fill='x')
        for label,var in [('幅度 / 码值',self.amplitude),('噪声σ / 码值',self.noise)]:
            f=ttk.Frame(pair); f.pack(side='left',expand=True,fill='x',padx=(0,8)); ttk.Label(f,text=label,style='Muted.TLabel').pack(anchor='w'); ttk.Entry(f,textvariable=var,width=10).pack(fill='x')
        field('突发有效样本数',self.burst_length)
        for text,var in [('周期Hann窗',self.hann),('突发检测模式',self.burst),('使用任意I/Q回放',self.use_replay),('读取板上前1024样本（JTAG较慢）',self.scope_enabled)]:
            ttk.Checkbutton(side,text=text,variable=var).pack(anchor='w',pady=3)
        buttons=[('生成参考模型预览',self.preview),('载入RTL仿真结果',self.open_simulation),('导入板卡采集目录',self.open_hardware),('导出测量与证据',self.export)]
        for text,command in buttons: ttk.Button(side,text=text,command=command).pack(fill='x',pady=4)
        ttk.Separator(side).pack(fill='x',pady=9)
        ttk.Label(side,textvariable=self.link,foreground=GREEN,wraplength=255).pack(fill='x')
        for text,command in [('连接 / 重新连接',self.connect_board),('编程完善版',self.program),('单次采集',self.capture_board),('开始连续采集',self.start_live),('停止 / 取消',self.stop_live)]:ttk.Button(side,text=text,command=command).pack(fill='x',pady=3)
        field('连续采集间隔 / 秒',self.interval)
        ttk.Label(side,text='参考模型 / RTL仿真 / 板卡数据\n始终分别标注，避免混淆。',style='Muted.TLabel',wraplength=245).pack(anchor='w',pady=10)
        book=ttk.Notebook(body); book.pack(side='left',fill='both',expand=True)
        self.tabs={name:ttk.Frame(book,padding=12) for name in ['完整频谱','时域快照','频谱历史','诊断与上板','比赛验证']}
        for name,frame in self.tabs.items(): book.add(frame,text=name)
        ttk.Label(self.tabs['完整频谱'],text='完整复数功率谱 · 横轴MHz，纵轴相对本帧峰值dB',style='Muted.TLabel').pack(anchor='w')
        self.spectrum_canvas=tk.Canvas(self.tabs['完整频谱'],bg=PANEL,highlightthickness=0); self.spectrum_canvas.pack(fill='both',expand=True,pady=10)
        self.spectrum_canvas.bind('<Configure>',lambda e:self.plot_spectrum())
        self.spectrum_canvas.bind('<Motion>',self.cursor_move);self.spectrum_canvas.bind('<MouseWheel>',self.zoom_spectrum);self.spectrum_canvas.bind('<Double-Button-1>',self.reset_view)
        toolbar=ttk.Frame(self.tabs['完整频谱']);toolbar.pack(fill='x')
        ttk.Checkbutton(toolbar,text='归一化峰值保持',variable=self.max_hold,command=self.plot_spectrum).pack(side='left')
        ttk.Button(toolbar,text='清空历史 / 峰值保持',command=self.clear_history).pack(side='right')
        ttk.Label(self.tabs['完整频谱'],textvariable=self.cursor,style='Muted.TLabel').pack(anchor='w')
        self.band_note=tk.StringVar(value='尚无频谱'); ttk.Label(self.tabs['完整频谱'],textvariable=self.band_note,style='Muted.TLabel').pack(anchor='w')
        self.scope_note=tk.StringVar(value='快照来源会在加载后显示'); ttk.Label(self.tabs['时域快照'],textvariable=self.scope_note,style='Muted.TLabel').pack(anchor='w')
        self.time_canvas=tk.Canvas(self.tabs['时域快照'],bg=PANEL,highlightthickness=0); self.time_canvas.pack(fill='both',expand=True,pady=10); self.time_canvas.bind('<Configure>',lambda e:self.plot_time())
        ttk.Label(self.tabs['频谱历史'],text='仅累积已加载的帧；切换点数或数据来源时清空。颜色为各帧归一化dB。',style='Muted.TLabel').pack(anchor='w')
        self.waterfall=tk.Canvas(self.tabs['频谱历史'],bg=PANEL,highlightthickness=0); self.waterfall.pack(fill='both',expand=True,pady=10); self.waterfall.bind('<Configure>',lambda e:self.plot_waterfall())
        self.build_diagnostics(); self.build_tests()
        footer=ttk.Frame(self,padding=(24,5,24,14)); footer.pack(fill='x')
        ttk.Label(footer,text='赛道二：幅度 · 帧长度 · 频点 · 带宽',style='Muted.TLabel').pack(side='left')
        ttk.Label(footer,text='硬件延迟与JTAG上传耗时分别记录',style='Muted.TLabel').pack(side='right')
        ttk.Label(self,textvariable=self.transfer,style='Muted.TLabel',padding=(24,0,24,10)).pack(fill='x')

    def build_diagnostics(self):
        tab=self.tabs['诊断与上板']
        ttk.Label(tab,text='启动时不自动连接或编程；连接、编程与采集分别操作。',style='Muted.TLabel').pack(anchor='w',pady=(0,10))
        ttk.Label(tab,text='Vivado路径').pack(anchor='w'); ttk.Entry(tab,textvariable=self.vivado).pack(fill='x',pady=5)
        ttk.Label(tab,text='JTAG目标（通常留空，仅发现一个目标时自动选择）').pack(anchor='w');ttk.Entry(tab,textvariable=self.target).pack(fill='x',pady=5)
        fields=ttk.Frame(tab); fields.pack(fill='x')
        for label,var in [('高能量门限',self.hi),('低能量门限',self.lo)]:
            f=ttk.Frame(fields); f.pack(side='left',fill='x',expand=True,padx=(0,12)); ttk.Label(f,text=label).pack(anchor='w'); ttk.Entry(f,textvariable=var).pack(fill='x',pady=5)
        row=ttk.Frame(tab); row.pack(fill='x',pady=10)
        for text,command in [('编程增强版',self.program),('装载并单次采集',self.capture_board),('检查连续处理计数',self.monitor)]: ttk.Button(row,text=text,command=command).pack(side='left',padx=(0,10))
        self.progress=ttk.Progressbar(tab,mode='indeterminate'); self.progress.pack(fill='x',pady=(0,8))
        self.diagnostic=tk.Text(tab,bg=PANEL,fg=TEXT,font=('Consolas',10),relief='flat',wrap='word',height=18); self.diagnostic.pack(fill='both',expand=True)
        self.diagnostic.insert('end','板级状态：待用户验证\n加载数据后显示输入丢失、协议错误、频谱跳帧和时域任务丢失。\n')

    def build_tests(self):
        tab=self.tabs['比赛验证']; self.test_table=ttk.Treeview(tab,columns=('requirement','target','evidence'),show='headings')
        for c,title,width in [('requirement','比赛要求',230),('target','工程目标',180),('evidence','验证证据 / 状态',450)]: self.test_table.heading(c,text=title); self.test_table.column(c,width=width,anchor='w')
        self.test_table.pack(fill='both',expand=True); ttk.Button(tab,text='刷新验证结果',command=self.refresh_tests).pack(anchor='e',pady=10); self.refresh_tests()

    def refresh_tests(self):
        self.test_table.delete(*self.test_table.get_children())
        verification={}; timing={}
        if (ROOT/'results/simulation_verification.json').exists(): verification=json.loads((ROOT/'results/simulation_verification.json').read_text())
        if (ROOT/'results/timing_status.json').exists(): timing=json.loads((ROOT/'results/timing_status.json').read_text())
        passed=len(verification.get('passed',[])); failed=len(verification.get('failed',[]))
        board={}
        if (ROOT/'results/board_summary.json').exists():board=json.loads((ROOT/'results/board_summary.json').read_text(encoding='utf-8'))
        board_note=f'实际板卡通过{board.get("passed_frames",0)}帧，覆盖{len(board.get("passed_cases",[]))}组场景；完整状态见板测报告' if board else '待实际板卡验证；导入单帧不代表全部指标通过'
        rows=[('I/Q ≥12 bit','12位有符号I/Q','RTL位宽与满幅边界仿真'),('速率 ≥100 MSPS',f'{FS/1e6:g} MSPS 实验配置',f'125 MHz × 4路时序：WNS {timing.get("wns_ns", 0):+.3f} ns / WHS {timing.get("whs_ns", 0):+.3f} ns；连续板测见板测报告' if timing else '时序未完成；连续板测见板测报告'),('FFT ≥8192点','8192 / 16384',f'完整FFT仿真通过{passed}项，失败/缺失{failed}项'),('分析延迟 ≤2 ms','以硬件周期计数','独立记录硬件延迟与JTAG耗时，参见results目录'),('幅度、帧长、频点、带宽','RMS / 突发与观察窗 / 完整复数频谱','测量定义、独立数值参考及边界回归'),('整体RTL与前仿真','保存可复现向量与日志','单元回归和完整原生FFT仿真'),('板级测试','实际采集与独立参考',board_note),('创新优化10分','双缓冲双点扫描、环形OBW、速率/分辨率取舍','以正确性、连续无丢帧和资源/时序报告支撑')]
        for row in rows:self.test_table.insert('', 'end',values=row)

    def parameters(self):
        n=int(self.n.get()); amp=int(self.amplitude.get()); noise=float(self.noise.get())
        length=int(self.burst_length.get()) if self.burst.get() else None
        return dict(kind=self.kind.get(),n=n,amplitude=amp,frequency=float(self.f1.get())*1e6,frequency2=float(self.f2.get())*1e6,burst_length=length,noise=noise)

    def iq(self): return make_iq(**self.parameters())

    def preview(self):
        if self.busy:return
        try:
            iq=self.iq(); power=reference_fft(iq,self.hann.get()); integer=np.rint(power/max(float(power.max()),1)*2**30).astype(np.uint64)
            m=measures(integer); n=len(iq); tr=time_reference(iq[:int(self.burst_length.get())] if self.burst.get() else iq)
            center=(m['lo']+(m['obw']-1)/2)%n if m['obw'] else 0
            m.update(source='golden_model',n=n,fs=FS,block_exponent=0,peak_hz=bin_hz(m['peak'],n),bw3_hz=m['bw3']*FS/n,obw_hz=m['obw']*FS/n,
                     lower_hz=bin_hz(m['lo'],n),upper_hz=bin_hz(m['hi'],n),center_hz=(center if center<n/2 else center-n)*FS/n,wraps=bin_hz(m['lo'],n)>bin_hz(m['hi'],n),latency_us=None,length_kind='配置的突发长度' if self.burst.get() else '参考观察窗',**tr)
            self.context=dict(self.parameters(),hann=self.hann.get(),scope_source='generated_stimulus')
            self.load(m,integer,iq[:1024])
        except Exception as e: messagebox.showerror('配置错误',str(e))

    def load(self,metric,power,scope=None):
        rate_changed=self.metric is None or self.metric['fs']!=metric['fs']
        if self.power is not None and (len(self.power)!=len(power) or self.metric['source']!=metric['source'] or rate_changed): self.history=[];self.hold_db=None
        if rate_changed:self.view_low=-metric['fs']/2e6;self.view_high=metric['fs']/2e6
        self.metric,self.power,self.scope=metric,power,scope
        source={'hardware':'板卡采集','simulation':'原生FFT RTL仿真','golden_model':'NumPy参考模型预览'}[metric['source']]
        self.status.set(f'{source} · N={metric["n"]} · 幅度单位为数字码值 · '+('无信号' if metric['no_signal'] else '已加载数据'))
        values={'谱峰频点':'无信号' if metric['no_signal'] else f'{metric["peak_hz"]/1e6:.5f} MHz','99%占用带宽':f'{metric["obw_hz"]/1e6:.4f} MHz','−3dB主峰带宽':f'{metric["bw3_hz"]/1e3:.2f} kHz','复数RMS':str(metric['rms']),'帧长度':f'{metric["length"]} 样本','硬件处理时间':'未测量' if metric.get('latency_us') is None else f'{metric["latency_us"]:.3f} μs'}
        for title,value in values.items(): self.cards[title].set(value)
        self.band_note.set(f'99%边界：{metric["lower_hz"]/1e6:.5f} → {metric["upper_hz"]/1e6:.5f} MHz'+('（跨正负频率边界）' if metric['wraps'] else '')+f'  |  区间中心 {metric["center_hz"]/1e6:.5f} MHz  |  '+metric['length_kind'])
        self.scope_note.set('实际板上输入前1024样本' if metric['source']=='hardware' and scope is not None else ('未读取板上I/Q快照' if metric['source']=='hardware' else '生成的激励前1024样本；不冒充板上测量'))
        self.history.append(self.db(power)); self.history=self.history[-100:]
        db=self.db(power);self.hold_db=db.copy() if self.hold_db is None else np.maximum(self.hold_db,db)
        self.plot_spectrum();self.plot_time();self.plot_waterfall()
        self.diagnostic.delete('1.0','end'); self.diagnostic.insert('end',json.dumps(metric,ensure_ascii=False,indent=2))

    @staticmethod
    def db(power):
        p=np.fft.fftshift(np.asarray(power,dtype=float)); return 10*np.log10(np.maximum(p/max(float(p.max()),1),1e-10))

    def axes(self,canvas,ymin,ymax,xmin,xmax,xlabel):
        canvas.delete('all'); w=max(canvas.winfo_width(),200);h=max(canvas.winfo_height(),200); l,r,t,b=64,w-24,24,h-46
        for j in range(6):
            y=t+(b-t)*j/5; canvas.create_line(l,y,r,y,fill='#2a3c4d');canvas.create_text(l-10,y,text=f'{ymax-(ymax-ymin)*j/5:g}',fill=MUTED,anchor='e')
        for j in range(6):
            x=l+(r-l)*j/5;canvas.create_line(x,t,x,b,fill='#213547');canvas.create_text(x,b+18,text=f'{xmin+(xmax-xmin)*j/5:.2f}',fill=MUTED)
        canvas.create_text((l+r)/2,h-8,text=xlabel,fill=MUTED); return l,r,t,b

    def plot_spectrum(self):
        l,r,t,b=self.axes(self.spectrum_canvas,-100,0,self.view_low,self.view_high,'频率 / MHz')
        if self.power is None:return
        full=self.db(self.power);n=len(full);fs=self.metric["fs"]/1e6;left=max(0,int((self.view_low+fs/2)*n/fs));right=min(n,int(math.ceil((self.view_high+fs/2)*n/fs)))
        for values,color in [(full,BLUE)]+([(self.hold_db,'#ffc76a')] if self.max_hold.get() and self.hold_db is not None else []):
            db=values[left:right];segments=min(len(db),max(int(r-l),100))
            if segments<2:continue
            points=[]
            for j,group in enumerate(np.array_split(db,segments)):points.extend([l+(r-l)*j/(segments-1),b-(b-t)*(max(float(group.max()),-100)+100)/100])
            self.spectrum_canvas.create_line(points,fill=color,width=1.4)
        if not self.metric['no_signal']:
            f=self.metric['peak_hz']/1e6
            if self.view_low<=f<=self.view_high:
                x=l+(f-self.view_low)/(self.view_high-self.view_low)*(r-l);self.spectrum_canvas.create_line(x,t,x,b,fill=GREEN,dash=(4,4))
                self.spectrum_canvas.create_text(min(max(x,l+70),r-70),t+15,text=f'主峰 {f:.5f} MHz',fill=GREEN)

    def cursor_move(self,event):
        if self.power is None:return
        width=max(self.spectrum_canvas.winfo_width(),200);fraction=np.clip((event.x-64)/max(width-88,1),0,1)
        f=self.view_low+float(fraction)*(self.view_high-self.view_low);n=len(self.power);fs=self.metric["fs"]/1e6;position=min(n-1,max(0,int((f+fs/2)*n/fs)))
        self.cursor.set(f'{f:.5f} MHz  |  bin {(position+n//2)%n}  |  {self.db(self.power)[position]:.2f} dB（本帧相对值）')
        self.spectrum_canvas.delete('cursor');self.spectrum_canvas.create_line(event.x,24,event.x,max(self.spectrum_canvas.winfo_height()-46,154),fill=MUTED,dash=(2,4),tags='cursor')

    def zoom_spectrum(self,event):
        fs=(self.metric['fs'] if self.metric else FS)/1e6
        span=self.view_high-self.view_low;new_span=np.clip(span/(1.5 if event.delta>0 else 1/1.5),fs/(self.metric['n'] if self.metric else 8192)*16,fs)
        width=max(self.spectrum_canvas.winfo_width(),200);fraction=float(np.clip((event.x-64)/max(width-88,1),0,1));center=self.view_low+span*fraction
        low=max(-fs/2,min(fs/2-new_span,center-new_span*fraction));self.view_low=float(low);self.view_high=float(low+new_span);self.plot_spectrum();return 'break'

    def reset_view(self,event=None):
        fs=(self.metric["fs"] if self.metric else FS)/1e6
        self.view_low=-fs/2;self.view_high=fs/2;self.plot_spectrum()
    def clear_history(self):self.history=[];self.hold_db=None;self.plot_waterfall();self.plot_spectrum()

    def plot_time(self):
        fs=(self.metric["fs"] if self.metric else FS)/1e6
        xmax=(len(self.scope)-1)/fs if self.scope is not None else 1023/fs
        l,r,t,b=self.axes(self.time_canvas,-2048,2048,0,xmax,'时间 / μs（输入快照）')
        if self.scope is None:return
        for column,color in [(0,BLUE),(1,GREEN)]:
            x=l+(r-l)*np.arange(len(self.scope))/max(len(self.scope)-1,1)
            y=t+(2048-self.scope[:,column].astype(float))/4096*(b-t)
            self.time_canvas.create_line(np.column_stack((x,y)).ravel().tolist(),fill=color,width=1.2)
        self.time_canvas.create_text(l+15,t+15,text='I',fill=BLUE); self.time_canvas.create_text(l+45,t+15,text='Q',fill=GREEN)

    def plot_waterfall(self):
        c=self.waterfall;c.delete('all');w=max(c.winfo_width(),200);h=max(c.winfo_height(),200)
        if not self.history:return
        width=min(360,w-60); rows=len(self.history); image=tk.PhotoImage(width=width,height=rows)
        lines=[]
        for values in self.history:
            groups=np.array_split(values,width); colors=[]
            for group in groups:
                a=np.clip((float(group.max())+80)/80,0,1);colors.append(f'#{int(16+40*a):02x}{int(28+170*a):02x}{int(55+195*a):02x}')
            lines.append('{'+ ' '.join(colors)+'}')
        image.put(' '.join(lines)); self.water_image=image.zoom(max(1,(w-60)//width),max(1,min(8,(h-50)//rows)))
        c.create_image(30,15,image=self.water_image,anchor='nw'); c.create_text(30,h-15,text=f'{-((self.metric["fs"] if self.metric else FS)/2e6):g} MHz',fill=MUTED,anchor='w'); c.create_text(w-30,h-15,text=f'+{((self.metric["fs"] if self.metric else FS)/2e6):g} MHz',fill=MUTED,anchor='e')

    def open_simulation(self):
        if self.busy:return
        path=filedialog.askopenfilename(initialdir=ROOT/'results/simulation',filetypes=[('仿真指标','metrics.csv'),('CSV','*.csv')])
        if not path:return
        try:
            path=Path(path);name=path.parent.name if path.name=='metrics.csv' else path.name.removesuffix('_metrics.csv');self.context=dict(case=name,scope_source='generated_stimulus');self.load(*load_simulation(ROOT,name))
        except Exception as e:messagebox.showerror('仿真导入失败',str(e))

    def open_hardware(self):
        if self.busy:return
        path=filedialog.askdirectory(initialdir=ROOT/'results/board')
        if not path:return
        try:
            folder=Path(path);context={}
            if (folder/'configuration.json').exists():context=json.loads((folder/'configuration.json').read_text(encoding='utf-8'))
            elif (folder/'measurement.json').exists():context=json.loads((folder/'measurement.json').read_text(encoding='utf-8')).get('context',{})
            self.context=dict(context,capture_folder=path,scope_source='hardware');self.load(*load_hardware(path))
        except Exception as e:messagebox.showerror('板卡数据导入失败',str(e))

    def export(self):
        if self.metric is None:return
        path=filedialog.askdirectory(initialdir=ROOT/'results')
        if path:
            folder=Path(path)/('measurement_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'));export_evidence(folder,self.metric,self.power,self.scope,self.context);messagebox.showinfo('已导出',str(folder))

    def worker(self,description,function):
        if self.busy:return
        self.busy=True;self.progress.configure(mode='indeterminate');self.progress.start(15);self.status.set(description)
        def run():
            try:self.jobs.put(('success',function()))
            except Exception as e:
                classified=classify_error(e)
                self.jobs.put(('error',dict(message=str(e),connection_lost=isinstance(classified,HardwareTransportError),cancelled=isinstance(classified,AcquisitionCancelled))))
        threading.Thread(target=run,daemon=True).start()

    def poll(self):
        for _ in range(100):
            try:kind,result=self.jobs.get_nowait()
            except queue.Empty:break
            if kind=='progress':
                self.status.set(result['message']);total=int(result.get('total',0));done=int(result.get('done',0))
                if total:self.progress.stop();self.progress.configure(mode='determinate',maximum=total,value=done)
                else:self.progress.configure(mode='indeterminate');self.progress.start(15)
                continue
            if kind=='success' and isinstance(result,tuple) and getattr(self,'_capture_cancel_event',None) is not None and self._capture_cancel_event.is_set():
                kind='error';result=dict(message='采集已取消；保留上次有效帧',connection_lost=False,cancelled=True)
            self.busy=False;self.progress.stop()
            self.progress.configure(mode='determinate',maximum=100,value=0 if kind=='error' else 100)
            if kind=='error':
                self.stop_live(cancel=False)
                details=result if isinstance(result,dict) else dict(message=str(result),connection_lost=False,cancelled=False)
                self.last_operation_error=details
                if details['connection_lost']:
                    self.connected=False;self.attached=False;self.link.set('调试连接中断，请重新连接')
                message='采集已取消；保留上次有效帧' if details['cancelled'] else '操作失败；已停止自动采集，详见诊断'
                self.status.set(message)
                self.diagnostic.insert('end','\n'+details['message']);self.diagnostic.see('end')
            elif isinstance(result,tuple):
                self.last_operation_error=None
                self.context=result[3];self.load(*result[:3]);self.capture_count+=1
                transport=self.context.get('transport',{})
                elapsed=float(transport.get('total_elapsed_ms',transport.get('elapsed_ms',0)))/1000
                recovery_count=int(transport.get('transport_recovery_count',0))
                self.transfer.set(f'有效采集 #{self.capture_count} · {self.context.get("captured_at", "")} · JTAG采集 {elapsed:.2f} s · 恢复重试 {recovery_count} 次 · 激励复用 {bool(int(transport.get("reused_vector",0)))} · 上传 {float(transport.get("load_ms",0))/1000:.2f} s · 频谱 {float(transport.get("spectrum_transfer_ms",0))/1000:.2f} s · 快照 {float(transport.get("scope_transfer_ms",0))/1000:.2f} s · 数据已自动归档')
                if self.live_running:self.live_job=self.after(int(self.live_interval*1000),self.capture_board)
            elif isinstance(result,dict):
                operation=result.pop('_operation','')
                if operation=='connect':
                    self.connected=True;self.attached=False;self.link.set('已连接 '+result.get('part','')+' · 尚未确认固件')
                elif operation=='program':self.attached=True;self.link.set('已连接 · 完善版固件已编程')
                self.status.set({'connect':'连接成功，可编程或采集','program':'编程成功，板级指标仍需实际测量'}.get(operation,'操作完成'))
                self.diagnostic.insert('end','\n'+json.dumps(result,ensure_ascii=False,indent=2))
            else:self.status.set(str(result));self.diagnostic.insert('end','\n'+str(result))
        self.after(100,self.poll)

    def get_session(self):
        if self.session is None:self.session=LiveSession(self.vivado.get())
        elif str(self.session.vivado)!=self.vivado.get():raise ValueError('修改Vivado路径后请关闭并重新打开界面')
        return self.session

    def report_progress(self,data):self.jobs.put(('progress',data))

    def connect_board(self):
        if self.busy:return
        # A copied project must not reuse the donor PC's cable serial/target.
        # An empty target asks hw_server/Vivado to discover the single board.
        self.stop_live(cancel=False);session=self.get_session();target=self.target.get().strip()
        def work():return dict(session.call('connect',target,progress=self.report_progress),_operation='connect')
        self.worker('连接USB/JTAG开发板…',work)

    def program(self):
        if self.busy:return
        if not self.connected:self.status.set('请先连接开发板');return
        self.stop_live(cancel=False);session=self.get_session()
        self.worker('编程已验证的完善版固件…',lambda:dict(session.call('program',progress=self.report_progress),_operation='program'))

    def start_live(self):
        if self.busy or self.live_running:return
        if not self.connected:self.status.set('请先连接开发板');return
        try:
            interval=float(self.interval.get())
            if not math.isfinite(interval) or not .2<=interval<=60:raise ValueError('间隔需为0.2到60秒')
        except ValueError as e:messagebox.showerror('配置错误',str(e));return
        self.live_interval=interval;self.live_running=True;self.capture_board()

    def stop_live(self,cancel=True):
        self.live_running=False
        if cancel and self.busy and getattr(self,'_capture_cancel_event',None) is not None:self._capture_cancel_event.set()
        if self.live_job is not None:self.after_cancel(self.live_job);self.live_job=None
        if cancel and self.busy and self.session:
            self.status.set('正在取消；等待当前JTAG事务结束')
            def cancel_work():
                try:self.session.cancel()
                except Exception as e:self.jobs.put(('progress',dict(message='取消请求失败：'+str(e))))
            threading.Thread(target=cancel_work,daemon=True).start()

    def prepare_acquisition(self):
        return self.parameters(),self.iq() if self.use_replay.get() else None,{}

    def capture_board(self):
        self.live_job=None
        if self.busy:return
        if not self.connected:self.stop_live(cancel=False);self.status.set('请先连接开发板');return
        try:
            parameters,iq,input_metadata=self.prepare_acquisition();hi=int(self.hi.get());lo=int(self.lo.get())
            if not 0<lo<hi<=8388608:raise ValueError('能量门限必须满足0<低<高≤8388608')
            session=self.get_session();verify_firmware()
        except Exception as e:self.stop_live(cancel=False);messagebox.showerror('配置错误',str(e));return
        out=ROOT/'results/board'/(datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]);out.mkdir(parents=True,exist_ok=True)
        vector=out/'stimulus.mem'
        if iq is not None:save_mem(vector,iq)
        args=[out,parameters['n'],int(self.hann.get()),int(self.burst.get()),vector if iq is not None else '-',hi,lo,int(self.scope_enabled.get())]
        context=dict(n=parameters['n'],hann=self.hann.get(),burst=self.burst.get(),window_rounding=WINDOW_ROUNDING,
            source_mode='iq_replay' if iq is not None else 'legacy_switch_source',stimulus_parameters=parameters if iq is not None else None,
            threshold_hi=hi,threshold_lo=lo,scope_source='hardware' if self.scope_enabled.get() else 'not_captured',capture_folder=str(out))
        context.update(input_metadata)
        if iq is not None:context['stimulus_sha256']=hashlib.sha256(vector.read_bytes()).hexdigest()
        (out/'configuration.json').write_text(json.dumps(context,ensure_ascii=False,indent=2),encoding='utf-8')
        cancelled=threading.Event();self._capture_cancel_event=cancelled
        def require_active():
            if cancelled.is_set():raise AcquisitionCancelled('采集已取消；保留上次有效帧')
        def work():
            try:
                recovery_before=len(session.recoveries)
                session.call('attach',progress=self.report_progress)
                require_active()
                context['transport']=session.call('capture',*args,progress=self.report_progress)
                require_active()
                context['transport_recovery_events']=session.recoveries[recovery_before:]
                context['transport']['transport_recovery_count']=len(context['transport_recovery_events'])
                context['bit_sha256']=hashlib.sha256((ROOT/'results/competition.bit').read_bytes()).hexdigest()
                context['captured_at']=datetime.datetime.now().astimezone().isoformat(timespec='seconds')
                pc_start=time.perf_counter()
                metric,power,scope=load_hardware(out)
                decoded=time.perf_counter()
                if metric["fs"]!=FS:raise RuntimeError("Returned clock disagrees with this parallel experiment; raw capture retained")
                faults=sum(metric[k] for k in ('input_drops','protocol_errors','skipped_frames','time_dropped_jobs','command_error'))
                if faults:raise RuntimeError(f'硬件报告丢失或错误计数{faults}，原始文件保留，但不纳入有效历史')
                context['validation']=dict(complete_spectrum=True,zero_faults=True,board_matrix_completed=False)
                if iq is not None:
                    from capture_validation import validate_replay
                    context['validation']['independent_reference']=validate_replay(metric,power,scope,iq,bool(args[2]),bool(args[3]))
                context['host_timings']=dict(decode_ms=round((decoded-pc_start)*1000,3),validation_ms=round((time.perf_counter()-decoded)*1000,3))
                require_active()
                export_evidence(out,metric,power,scope,context)
                require_active()
                return metric,power,scope,context
            except Exception as error:
                details=dict(error=str(error),error_type=type(classify_error(error)).__name__,measurement_valid=False,
                    created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),context=context,
                    runtime_log=str(session.runtime/'bridge.log') if session.runtime else None)
                (out/'capture_error.json').write_text(json.dumps(details,ensure_ascii=False,indent=2),encoding='utf-8')
                raise
        self.worker('装载激励并采集真实板卡数据…（JTAG装载耗时不计入硬件延迟）',work)

    def monitor(self):
        if self.busy:return
        if not self.connected:self.status.set('请先连接开发板');return
        self.stop_live(cancel=False);session=self.get_session()
        out=ROOT/'results/board'/('monitor_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]);out.mkdir(parents=True,exist_ok=True)
        def work():
            session.call('attach');session.call('start_continuous');rows=[]
            try:
                for i in range(6):
                    rows.append(session.call('counters'));self.report_progress(dict(message='观察连续硬件处理计数',done=i+1,total=6))
                    if i<5:time.sleep(1)
            finally:session.call('stop')
            (out/'counters.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
            return f'连续处理原始计数已保存：{out}；完整验收仍需比赛验证矩阵'
        self.worker('正在检查连续测量计数…',work)

    def close_console(self):
        self.stop_live();session=self.session
        if session:threading.Thread(target=session.close,daemon=False).start()
        self.destroy()

if __name__=='__main__':Console().mainloop()


