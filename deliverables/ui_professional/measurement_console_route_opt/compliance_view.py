"""Always-visible verdict and a live modeless detail window."""
import json,tkinter as tk
from tkinter import ttk
from compliance import profile,evaluate
from theme import SURFACE,INK,MUTED,BORDER
COLORS={'pass':('#147B4F','#E8F5ED'),'fail':('#B52E3A','#FCEBED'),'pending':('#946100','#FFF4D8'),'info':('#00758D','#E7F3F6')}
LABELS={'pass':'满足','fail':'未通过','pending':'待确认','info':'计分项'}

class ComplianceView:
    def build_compliance_header(self,parent):
        self.compliance_evidence=profile(self.project)
        self.compliance_report=None;self.compliance_window=None;self._compliance_signature=None
        self.compliance_text=tk.StringVar(value='等待返回数据')
        self.compliance_button=ttk.Button(parent,text='比赛指标…',command=self.open_compliance_window)
        self.compliance_button.pack(side='right',padx=(5,7),pady=2)
        self.compliance_badge=tk.Label(parent,textvariable=self.compliance_text,font=self.caption_font,fg=COLORS['pending'][0],bg=COLORS['pending'][1],padx=7,pady=2)
        self.compliance_badge.pack(side='right',padx=3,pady=2)

    def refresh_compliance(self):
        if not hasattr(self,'compliance_badge'):return
        metric=self.metric;context=self.context if isinstance(self.context,dict) else {}
        origin=self.origin.get();failed=self.status.get().startswith('操作失败')
        snapshot=getattr(self,'hardware_snapshot',None)
        raw=snapshot is not None and snapshot.metric==metric and snapshot.metadata.get('acquisition') in ('raw_ILA_VIO','raw_AXI') and snapshot.metadata.get('bit_sha256')==context.get('bit_sha256')
        if raw and not context.get('captured_at'):
            context=dict(context,captured_at=snapshot.metadata.get('captured_at'))
        cancelled=self.status.get().startswith(('采集已取消','正在取消'))
        report=evaluate(metric,context,origin,self.compliance_evidence,raw_verified=raw,operation_error=failed,operation_cancelled=cancelled)
        signature=json.dumps(report,ensure_ascii=False,sort_keys=True)
        if signature==self._compliance_signature:return
        self._compliance_signature=signature;self.compliance_report=report
        self.compliance_text.set(report['summary']);fg,bg=COLORS[report['state']]
        self.compliance_badge.configure(fg=fg,bg=bg)
        if self.compliance_window is not None and self.compliance_window.winfo_exists():self.render_compliance_window()

    def open_compliance_window(self):
        if self.compliance_window is not None and self.compliance_window.winfo_exists():self.compliance_window.lift();return
        self.refresh_compliance()
        window=tk.Toplevel(self);self.compliance_window=window
        window.title('原集成电路赛题指标 · 当前返回帧');window.configure(bg=SURFACE)
        window.geometry('980x550');window.minsize(820,500)
        body=tk.Frame(window,bg=SURFACE);body.pack(fill='both',expand=True,padx=14,pady=12)
        self.compliance_summary=tk.Label(body,anchor='w',font=(self.serif,12,'bold'),padx=9,pady=7);self.compliance_summary.pack(fill='x')
        self.compliance_origin=tk.Label(body,anchor='w',bg=SURFACE,fg=MUTED,font=self.caption_font);self.compliance_origin.pack(fill='x',pady=(7,9))
        self.compliance_grid=tk.Frame(body,bg=SURFACE);self.compliance_grid.pack(fill='x')
        for col,title in enumerate(('检查项','返回值 / 证据','赛题要求','判定')):
            self.compliance_grid.columnconfigure(col,weight=(2,2,3,1)[col])
            tk.Label(self.compliance_grid,text=title,anchor='w',bg='#ECEFF1',fg=INK,font=self.ui_font,padx=7,pady=7).grid(row=0,column=col,sticky='nsew')
        self.compliance_cells=[]
        for row in range(7):
            cells=[]
            for col in range(4):
                cell=tk.Label(self.compliance_grid,anchor='w',bg=SURFACE,fg=INK,font=self.ui_font,padx=7,pady=7)
                cell.grid(row=row+1,column=col,sticky='nsew');cells.append(cell)
            self.compliance_cells.append(cells)
        self.compliance_notes=tk.Label(body,anchor='nw',justify='left',wraplength=900,bg=SURFACE,fg=MUTED,font=self.caption_font)
        self.compliance_notes.pack(fill='both',expand=True,pady=(10,4))
        footer=ttk.Frame(body);footer.pack(fill='x')
        ttk.Button(footer,text='完整验证证据',command=lambda:self.notebook.select(self.tabs['比赛验证'])).pack(side='left')
        ttk.Button(footer,text='关闭',command=self.close_compliance_window).pack(side='right')
        window.protocol('WM_DELETE_WINDOW',self.close_compliance_window)
        window.bind('<Configure>',lambda event:self.compliance_notes.configure(wraplength=max(window.winfo_width()-35,300)) if event.widget is window else None)
        self.render_compliance_window()

    def render_compliance_window(self):
        report=self.compliance_report
        if not report:return
        fg,bg=COLORS[report['state']];self.compliance_summary.configure(text=report['summary'],fg=fg,bg=bg)
        identity=f'帧 {report["frame"] if report["frame"] is not None else "N/A"} · {report["origin"]} · {report["captured_at"] or "时间见实测记录"}'
        self.compliance_origin.configure(text=identity)
        notes=[]
        for row,cells in zip(report['rows'],self.compliance_cells):
            for cell,value in zip(cells,(row['title'],row['current'],row['rule'],LABELS[row['state']])):cell.configure(text=value)
            fg,bg=COLORS[row['state']];cells[-1].configure(fg=fg,bg=bg)
            if row['state'] in ('fail','pending'):notes.append(row['title']+'：'+row['note'])
        base='位宽依据匹配固件；速率依据采样配置与时序验证。分析延迟不含 JTAG 装载时间。\nFPGA 返回环形带宽；线性带宽由 PC 据完整实测谱计算。赛题未规定带宽数值门槛。'
        self.compliance_notes.configure(text=base+('\n'+'\n'.join(notes[:3]) if notes else ''))

    def close_compliance_window(self):
        if self.compliance_window is not None:self.compliance_window.destroy()
        self.compliance_window=None
