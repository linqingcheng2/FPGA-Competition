"""Select matched software and FPGA profiles in separate, clean processes."""
from pathlib import Path
import hashlib,json,subprocess,sys,threading
import tkinter as tk
from tkinter import ttk

LABELS={500:'500 MSPS 高参数版'}

def install_version_selector(app,header,version):
    app.version_id=version
    app.version_controller=VersionController(app,version)
    app.version_buttons={}
    panel=ttk.Frame(header);panel.pack(side='left',padx=28)
    row=ttk.Frame(panel);row.pack(anchor='w')
    for rate in (500,):
        button=tk.Button(row,text=LABELS[rate],font=(app.serif,9,'bold'),
            background=('#3F6B5B' if rate==150 else '#6F5844') if rate==version else '#E3E8ED',
            foreground='white' if rate==version else '#213547',relief='flat',borderwidth=1,padx=10,pady=2,
            command=lambda selected=rate:app.version_controller.switch(selected))
        button.pack(side='left',padx=(0,6));app.version_buttons[rate]=button
    app.version_note=tk.StringVar(value='连接时载入所选配套固件；切换会停止采集')
    ttk.Label(panel,textvariable=app.version_note,font=app.caption_font,style='Muted.TLabel').pack(anchor='w',pady=(3,0))
    app.action_buttons['connect'].configure(command=app.version_controller.activate)
    app.title('数字基带测量仪 · '+LABELS[version])

class VersionController:
    def __init__(self,app,version):
        self.app=app;self.version=version;self.switching=False;self.activating=False

    def activate(self):
        app=self.app
        if app.busy or self.activating or self.switching:return
        if self.version==500:
            try:
                from atelier import verify_firmware
                verify_firmware()
            except Exception as error:
                app.version_note.set('连接时载入所选配套固件；切换会停止采集')
                app.status.set('连接未启动：'+str(error))
                return
        app.stop_live(cancel=False)
        session=app.get_session();target=app.target.get().strip()
        self.activating=True;app.attached=False
        app.version_note.set('正在连接并载入 '+LABELS[self.version])
        def work():
            def connection_progress(event):
                if event.get('message')=='启动常驻Vivado会话':
                    event=dict(event,message='正在启动 Vivado 与 USB/JTAG 服务，首次连接通常需要 30–60 秒')
                app.report_progress(event)
            app.report_progress(dict(message='正在连接 USB/JTAG 开发板',done=0,total=0))
            connected=session.call('connect',target,progress=connection_progress)
            app.report_progress(dict(message='开发板已连接，正在载入 '+LABELS[self.version]+' 配套固件',done=0,total=0))
            programmed=session.call('program',progress=app.report_progress)
            app.report_progress(dict(message=LABELS[self.version]+' 固件已载入，正在更新界面状态',done=0,total=0))
            return dict(connected,programmed=programmed,_operation='connect')
        app.worker('载入 '+LABELS[self.version]+' 配套固件…',work)
        def finish():
            if app.busy:app.after(100,finish);return
            self.activating=False
            if app.connected:
                app.attached=True
                app.status.set(LABELS[self.version]+' 固件已就绪，可开始采集')
                app.version_note.set('当前 '+LABELS[self.version]+' · 固件已载入')
                project=Path(app.project)
                proof=dict(passed=True,version=self.version,fs_hz=self.version*1000000,
                    bit_sha256=hashlib.sha256((project/'results/competition.bit').read_bytes()).hexdigest(),
                    project=str(project),pid=__import__('os').getpid(),source='actual_connection_and_programming')
                runtime=Path(__file__).parent/'runtime';runtime.mkdir(exist_ok=True)
                (runtime/'version_activation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
            else:app.version_note.set('连接或编程失败，请查看硬件与诊断')
        app.after(100,finish)

    def switch(self,target):
        if target not in LABELS:raise ValueError('Unsupported FPGA version')
        if target==self.version or self.switching:return
        app=self.app;self.switching=True
        activate=app.connected or app.attached or self.activating
        cable=app.cable_filter.get();vivado=app.vivado.get()
        for button in app.version_buttons.values():button.configure(state='disabled')
        app.stop_live(cancel=True)
        app.version_note.set('正在停止采集并切换到 '+LABELS[target])
        def wait_idle():
            if app.busy:app.after(100,wait_idle);return
            app.busy=True
            complete=[]
            def close_session():
                try:
                    if app.session:app.session.close()
                    complete.append(None)
                except Exception as exc:complete.append(exc)
            threading.Thread(target=close_session,daemon=True).start()
            def launch():
                if not complete:app.after(100,launch);return
                if complete[0] is not None:
                    app.busy=False;self.switching=False;app.version_note.set('会话关闭失败：'+str(complete[0]))
                    for button in app.version_buttons.values():button.configure(state='normal')
                    return
                entry=Path(__file__).resolve().parents[1]/('measurement_console_route_opt' if target==500 else 'measurement_console_150_score')/'run_console.py'
                app.connected=False;app.attached=False;app.session=None
                args=[sys.executable,str(entry),'--version',str(target),'--cable',cable,'--vivado',vivado]
                if activate:args.append('--activate')
                if app.comparison_enabled.get():args.append('--comparison')
                try:subprocess.Popen(args,cwd=entry.parent,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                except Exception as exc:
                    app.busy=False;self.switching=False;app.version_note.set('打开目标版本失败：'+str(exc))
                    for button in app.version_buttons.values():button.configure(state='normal')
                    return
                for timer in app.tk.splitlist(app.tk.call('after','info')):app.after_cancel(timer)
                app.destroy()
            app.after(100,launch)
        app.after(100,wait_idle)
