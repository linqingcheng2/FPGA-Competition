"""Instrument presentation; acquisition and evidence operations remain inherited.

Uses the optimized project's verified transport, validation, and lossless importer.
Opening this view never connects, uploads, or programs hardware.
"""
from pathlib import Path
import sys
import json
import math
import secrets
import tkinter as tk
import tkinter.font as tf
from tkinter import ttk
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / 'vendor')]
from professional_view import ProfessionalView
sys.path.insert(0, str(HERE.parent / 'measurement_atelier_route_opt'))
from atelier import Atelier, PROJECT, WAVES, backend, load_record as original_load_record

from theme import *
from layout import LaboratoryLayout
from comparison_view import ComparisonView
from compliance_view import ComplianceView
from plotting import spectrum_points,waterfall_colors
from analysis import FS,linear_99_bandwidth

# Only this UI process gets the instrument palette.
backend.BG = BG
backend.PANEL = PLOT
backend.TEXT = INK
backend.MUTED = TICK
backend.BLUE = TRACE
backend.GREEN = GREEN


class OriginalConsole(ComplianceView, ComparisonView, LaboratoryLayout, Atelier):
    project = PROJECT
    project_clock_hz = FS
    def board_matrix_path(self):
        return PROJECT/'results/parallel_board_verification.json'
    waves = WAVES
    def toggle_dynamic_noise(self):
        if self.dynamic_noise.get():
            try:
                if float(self.noise.get()) == 0:self.noise.set('10')
            except ValueError:pass
            self.progress_note.set('动态演示开启 · 每帧重新上传电脑合成噪声；参考跟随实测输入')
        else:self.progress_note.set('固定种子实验 · 相同参数产生相同输入')
        self.sync_input()

    def prepare_acquisition(self):
        if not self.dynamic_noise.get() or not self.use_replay.get() or self.imported_iq is not None:
            return super().prepare_acquisition()
        parameters=self.parameters()
        if not 0<float(parameters['noise'])<=1024:
            raise ValueError('动态演示需设置噪声 σ > 0（建议 10）；关闭开关可进行无噪声固定回放')
        seed=secrets.randbits(64)
        parameters=dict(parameters,noise_seed=seed)
        iq=backend.make_iq(**parameters)
        return parameters,iq,dict(dynamic_noise_demo=True,noise_seed=seed,
            noise_origin='PC_synthesized_gaussian;not_analog_noise',waveform_seed=20261002)

    def build_current_reference(self):
        if self.dynamic_noise.get() and self.use_replay.get() and self.imported_iq is None:
            from comparison import bind_saved_input,reference_frame
            frame=self.hardware_snapshot
            context=frame.metadata['context'] if frame else {}
            recorded=dict(context.get('stimulus_parameters') or {}); recorded.pop('noise_seed',None)
            if (not context.get('dynamic_noise_demo') or recorded!=self.parameters()
                or frame.config.hann!=self.hann.get() or frame.config.burst!=self.burst.get()
                or frame.config.high!=int(self.hi.get()) or frame.config.low!=int(self.lo.get())):
                raise ValueError('动态参考使用本帧上传的完整 I/Q；请先按当前配置采集，再生成参考')
            _,iq,provenance=bind_saved_input(frame,self.project)
            return reference_frame(iq,frame.config,dict(origin='动态演示本帧完整输入',noise_seed=context['noise_seed'],**provenance))
        return super().build_current_reference()

    def select_source(self):
        choice = self.source_choice.get()
        if self.busy or self.live_running:
            self.sync_input(); return
        if choice == 'generated':
            self.clear_import(); self.use_replay.set(True)
        elif choice == 'file':
            if self.imported_iq is None:
                self.import_iq_file()
            else:
                self.use_replay.set(True)
        else:
            # The 500 MSPS UI intentionally exposes only PC-generated and
            # external-file I/Q sources; board-side switch generation remains
            # firmware-only and is not selectable from this console.
            self.source_choice.set('generated' if self.imported_iq is None else 'file')
            self.use_replay.set(True)
            self.sync_input()

    def import_iq_file(self, path=None):
        super().import_iq_file(path)
        self.sync_input()

    def clear_import(self):
        super().clear_import()
        self.sync_input()

    def sync_input(self):
        if not hasattr(self, 'source_choice'):
            return
        super().sync_input()
        if not self.use_replay.get():
            self.use_replay.set(True)
        self.source_choice.set('file' if self.imported_iq is not None else 'generated')
        self.import_label.configure(foreground=MUTED)
        if self.source_choice.get() == 'file':
            self.file_panel.pack(fill='x', before=self.analysis_panel)
        else:
            self.file_panel.pack_forget()
        if self.source_choice.get() == 'generated':
            self.generator_panel.pack(fill='x', before=self.analysis_panel)
        else:
            self.generator_panel.pack_forget()
        if self.burst.get() and self.source_choice.get() == 'generated':
            self.burst_settings.pack(fill='x',pady=3)
        else:
            self.burst_settings.pack_forget()
        self.input_hint.set('500 MSPS 动态噪声演示\n每帧新输入，参考跟随本帧。' if self.dynamic_noise.get() and self.imported_iq is None else '500 MSPS 实验回放；参数在下一次采集生效。')
        dual = self.kind.get() in ('two_tone','chirp','wrap_chirp','wide')
        self.frequency_labels[0].configure(text='起始频率 / MHz' if self.kind.get() in ('chirp','wrap_chirp') else '频带下限 / MHz' if self.kind.get() == 'wide' else '频率 / MHz')
        self.frequency_labels[1].configure(text='终止频率 / MHz' if self.kind.get() in ('chirp','wrap_chirp') else '频带上限 / MHz' if self.kind.get() == 'wide' else '频率 2 / MHz')
        if not dual: self.frequency_entries[1].configure(state='disabled')

    def sync_wave(self):
        super().sync_wave()
        self.sync_input()

    def open_hardware(self):
        self._reading_archive = True
        try: return super().open_hardware()
        finally: self._reading_archive = False




    def refresh_tests(self):
        super().refresh_tests()
        # Show partial matrix honestly even before a full release summary exists.
        p = self.board_matrix_path()
        if p.exists():
            matrix = json.loads(p.read_text(encoding='utf-8'))
            historical='125_release_results' in p.parts
            passed = sum(bool(t['passed']) for t in matrix.get('tests', []))
            state = '已完成' if matrix.get('complete',matrix.get('completed')) else '尚未完成'
            for row in self.test_table.get_children():
                values = self.test_table.item(row,'values')
                if values and values[0] == '板级测试' and not historical and not (PROJECT/'results/board_summary.json').exists():
                    proof_path=PROJECT/'results/parallel_board_verification.json'
                    proof=json.loads(proof_path.read_text(encoding='utf-8')) if proof_path.exists() else {}
                    detail=(f'{passed} 场景；连续无丢样长测 {proof.get("continuous_seconds",0):.1f} s'
                            if proof.get('passed') and proof.get('complete') else f'当前矩阵 {passed} 次通过，{state}；连续验收及完整汇总待完成')
                    self.test_table.item(row,values=('板级测试','实际采集与独立参考',detail))
            label='历史 125 MSPS 板测矩阵' if historical else '当前 500 MSPS 固件板测矩阵'
            self.test_table.insert('', 'end', values=(label, f'{len(matrix.get("requested_cases",matrix.get("tests",[])))} 场景', f'{passed} 次采集通过；矩阵{state}，以原始报告为准'))
        self.refresh_demos()
        speed_path=PROJECT/'results/windowed_warm_verification.json'
        if speed_path.exists():
            speed=json.loads(speed_path.read_text(encoding='utf-8'))
            if speed.get('passed') and speed.get('completed'):
                values='；'.join(f'{t["n"]} 点 {t["acked_load_ms"]/1000:.3f} → {t["windowed_load_ms"]/1000:.3f} s' for t in speed['tests'])
                self.test_table.insert('', 'end', values=('上轮 I/Q 提速（历史固件）','预热后交替板测；仅作为历史配对证据',values))
        for name,label,definition in [('dense_burst_verification','密集短突发 RTL','独立整数参考；顺序与字段一致'),('parallel_board_verification','500 板测与连续采样','配套新固件；原始状态与完整采集'),('parallel_precision_verification','500 精度扫描','频点 / 幅度 / 噪声 / 突发长度')]:
            path=PROJECT/f'results/{name}.json'
            if not path.exists():continue
            proof=json.loads(path.read_text(encoding='utf-8'))
            if name=='dense_burst_verification':detail=f'{proof["bursts"]} 个突发，新版丢失 {proof["new_dropped"]}，旧版丢失 {proof["baseline_dropped"]}'
            elif name=='parallel_board_verification':detail=f'{len(proof["tests"])} 场景；连续长测 {proof.get("continuous_seconds",0):.1f} s'
            else:detail=f'{len(proof["tests"])}/{proof["planned_cases"]} 组真实扫描'
            self.test_table.insert('', 'end', values=(label,definition,detail+('；通过' if proof.get('passed') else '；尚未完成')))
        for name,label in [('compliance_verification','指标边界与来源判定'),('compliance_ui_verification','指标窗口与界面集成')]:
            proof_path=HERE/f'runtime/{name}.json'
            if proof_path.exists():
                proof=json.loads(proof_path.read_text(encoding='utf-8'))
                self.test_table.insert('', 'end', values=(label,'本轮上位机检查',f'{proof["checks"]} 项通过' if proof.get('passed') else '尚未通过'))

    def refresh_demos(self):
        if not hasattr(self,'demo_combo'):return
        path=self.board_matrix_path()
        self.demo_records={}
        if path.exists():
            matrix=json.loads(path.read_text(encoding='utf-8'))
            names={'tone8k':'单频频点','negative8k':'负频点','zero8k':'无信号','hann8k':'Hann 窗','burst8k':'突发幅度与帧长','chirp8k':'扫频带宽','qpsk8k':'QPSK 调制','two_tone8k':'双频分辨','tone16k':'16384 点精细分辨','wrap16k':'跨频率边界','wide16k':'宽带分析','stream8k':'连续流','fullband8k':'全带宽 PN-QPSK','fullband16k':'接近全频带','edge16k':'接近奈奎斯特边界','hann16k':'16384 点 Hann 扫频'}
            for row in matrix.get('tests',[]):
                if not row.get('passed') or row.get('run',1)!=1:continue
                name=row['case'];folder=Path(row['transport']['folder'])
                prefix='历史 125 MSPS · ' if '125_release_results' in path.parts else '500 MSPS · '
                if (folder/'measurement.json').exists():self.demo_records[prefix+names.get(name,name)+' · '+name]=folder
        self.demo_combo.configure(values=list(self.demo_records))
        if self.demo_choice.get() not in self.demo_records:self.demo_choice.set(next(iter(self.demo_records),'暂无通过的板测示例'))

    def load_demo(self):
        if self.busy or self.live_running:return
        folder=self.demo_records.get(self.demo_choice.get())
        if folder is None:return
        self.reference_snapshot=None
        load_record(self,folder)
        self.comparison_enabled.set(True);self.toggle_comparison();self.record_reference(quiet=True)
        self.progress_note.set('已载入历史实测示例 · 对比参考由同一完整 I/Q 独立计算')

    def load(self, metric, power, scope=None):
        self.linear_bandwidth=linear_99_bandwidth(power,metric['fs'])
        super().load(metric, power, scope)
        linear=self.linear_bandwidth
        detail=(f'线性 99% 带宽 {linear["width_hz"]/1e6:.5f} MHz（PC 据完整谱计算；边界 {linear["lower_hz"]/1e6:.5f} → {linear["upper_hz"]/1e6:.5f} MHz）'
                if linear['valid'] else '线性 99% 带宽：无信号')
        circular_source={'hardware':'FPGA','simulation':'RTL 仿真','golden_model':'参考模型'}[metric['source']]
        self.band_note.set(detail+'\n'+self.band_note.get().replace('99%边界：',circular_source+' 环形 99% 边界：'))
        caption_source={'hardware':'FPGA','simulation':'RTL','golden_model':'模型'}[metric['source']]
        self.card_caption_labels['环形99%带宽'].configure(text='环形 99% 带宽 · '+caption_source+' / MHz')
        low_level=not metric['no_signal'] and 0<metric['rms']<=4
        if low_level:self.band_note.set(self.band_note.get()+'\n低幅度提示：输入接近量化步长，谱尾误差可显著影响 99% 带宽；建议提高输入幅度复测。')
        self.band_label.configure(foreground=AMBER if low_level else MUTED)
        if metric['source'] == 'hardware' and getattr(self,'_reading_archive',False):
            self.data_origin = '历史板卡实测'; self.origin.set(self.data_origin)
        for label in self.card_value_labels.values():
            label.configure(font=(self.serif, 12, 'bold'))
        hann = self.context.get('hann', self.context.get('case', {}).get('hann') if isinstance(self.context.get('case'), dict) else None)
        window = '周期 Hann' if hann is True else '矩形' if hann is False else '记录未注明'
        self.frame_meta.set(f'当前帧 · Fs {metric["fs"]/1e6:g} MSPS · FFT {metric["n"]} · Δf {metric["fs"]/metric["n"]/1e3:.3f} kHz · 窗 {window}')
        faults = sum((metric.get(k) or 0) for k in ('input_drops', 'protocol_errors', 'skipped_frames', 'time_dropped_jobs', 'command_error'))
        proof = self.context.get('validation', {}).get('independent_reference')
        self.frame_quality.set(('错误计数 '+str(faults) + (' · 独立对照通过' if proof and proof.get('passed') else ' · 核验见记录'))
                               if metric['source'] == 'hardware' else '软件数据 · 硬件延迟未测量')
        self.file_state.set('记录：'+Path(self.context['capture_folder']).name if self.context.get('capture_folder') else '记录：软件数据')
        display = ['无信号' if metric['no_signal'] else f'{metric["peak_hz"]/1e6:.5f}',
                   f'{metric["obw_hz"]/1e6:.4f}', f'{metric["bw3_hz"]/1e3:.2f}',
                   str(metric['rms']), str(metric['length']),
                   '未测量' if metric.get('latency_us') is None else f'{metric["latency_us"]:.3f}']
        for (name, var), text in zip(self.display_cards.items(), display):
            var.set(text)
            self.card_value_labels[name].configure(font=(self.serif, 10) if text in ('未测量', '无信号') else (self.latin, 13))
        self.display_cards['99%占用带宽'].set(f'{linear["width_hz"]/1e6:.4f}' if linear['valid'] else '无信号')
        self.display_cards['环形99%带宽'].set(f'{metric["obw_hz"]/1e6:.4f}')
        self.card_value_labels['环形99%带宽'].configure(font=(self.latin,13))
        if metric['source'] == 'simulation':
            self.display_cards['硬件处理时间'].set('N/A')
            self.frame_quality.set(f'RTL 仿真处理时间 {metric["latency_us"]:.3f} μs')
        self.update_frame_labels()
        self.observe_frame(metric,power,scope)
        self.refresh_compliance()

    def measurement_window(self):
        value = self.context.get('hann')
        case = self.context.get('case')
        if value is None and isinstance(case,dict): value = case.get('hann')
        if value is None and self.metric and self.metric['source'] == 'simulation':
            name = self.metric.get('case',case)
            cases = json.loads((PROJECT/'vectors/manifest.json').read_text(encoding='utf-8'))
            value = next((item['hann'] for item in cases if item['name'] == name),None)
        return 'Hann' if value is True else '矩形' if value is False else 'N/A'

    def update_frame_labels(self):
        if not hasattr(self,'footer_meta'): return
        self.result_caption.set('测量结果  ·  '+self.origin.get())
        if self.metric is not None:
            m = self.metric
            source = {'hardware':'Hardware','simulation':'RTL 仿真','golden_model':'Reference (PC)'}[m['source']]
            if self.origin.get().startswith('历史'): source = '历史 Hardware'
            self.footer_meta.set(f'Fs {m["fs"]/1e6:g} MSPS  |  FFT {m["n"]}  |  窗 {self.measurement_window()}  |  数据 {source}  |  Δf {m["fs"]/m["n"]/1e3:.3f} kHz')
            if self.context.get('dynamic_noise_demo'):
                self.result_caption.set(self.result_caption.get()+' · 动态噪声演示（电脑合成）')
                self.footer_meta.set(self.footer_meta.get()+' | 动态演示 · PC噪声')

    def refresh_presentation(self):
        super().refresh_presentation()
        disabled = self.busy or self.live_running
        for widget in self.config_widgets:
            widget.configure(state='disabled' if disabled else 'readonly' if isinstance(widget, ttk.Combobox) else 'normal')
        self.dynamic_noise_check.configure(state='normal' if not disabled and self.use_replay.get() and self.imported_iq is None else 'disabled')
        if self.imported_iq is not None and self.use_replay.get():
            for w in self.config_widgets:
                if isinstance(w, ttk.Combobox) and str(w.cget('textvariable')) == str(self.n):
                    w.configure(state='disabled')
        if disabled:
            for w in self.replay_fields:
                w.configure(state='disabled')
        self.action_buttons['preview'].configure(state='disabled' if disabled or not self.use_replay.get() else 'normal')
        if not self.busy and self.status.get().startswith('操作失败'):
            self.progress_note.set(self.status.get())
            self.connection_label.set('调试连接中断，详见诊断' if not self.connected else '已连接 · 本次采集失败，详见诊断')
        self.action_buttons['export'].configure(state='normal' if self.metric is not None and not self.busy else 'disabled')
        if hasattr(self,'comparison_table'):
            available = self.comparison_enabled.get() and not disabled
            self.reference_button.configure(state='normal' if available and self.use_replay.get() else 'disabled')
            self.rebuild_button.configure(state='normal' if available and self.hardware_snapshot is not None else 'disabled')
        self.update_frame_labels()
        self.refresh_compliance()

    def axes(self, canvas, ymin, ymax, xmin, xmax, xlabel):
        canvas.delete('all')
        w, h = max(canvas.winfo_width(), 200), max(canvas.winfo_height(), 150)
        l, r, t, b = 64, w-24, 32, h-46
        ticks = [0,-20,-40,-60,-80,-100] if ymin == -100 and ymax == 5 else [ymax-(ymax-ymin)*j/5 for j in range(6)]
        for value in ticks:
            y = t+(ymax-value)/(ymax-ymin)*(b-t)
            canvas.create_line(l, y, r, y, fill=GRID)
            canvas.create_text(l-10, y, text=f'{value:g}', fill=TICK, anchor='e', font=self.chart_font)
        for j in range(6):
            x = l+(r-l)*j/5
            canvas.create_line(x, t, x, b, fill=GRID)
            canvas.create_text(x, b+18, text=f'{xmin+(xmax-xmin)*j/5:.2f}', fill=TICK, font=self.chart_font)
        canvas.create_line(l, t, l, b, r, b, fill='#8191A3')
        canvas.create_text((l+r)/2, h-11, text=xlabel, fill=TICK, font=self.caption_font)
        return l, r, t, b

    def schedule_plot(self, name):
        pending = getattr(self, '_pending_plots', None)
        if pending is None: self._pending_plots = pending = set()
        if name in pending: return
        pending.add(name)
        def draw():
            pending.discard(name)
            getattr(self, name)()
        self.after_idle(draw)

    def plot_spectrum(self):
        if not hasattr(self, 'show_peak') or not hasattr(self, 'spectrum_canvas'):
            return
        c = self.spectrum_canvas
        l, r, t, b = self.axes(c, -100, 0, self.view_low, self.view_high, '频率 / MHz')
        if self.power is None:
            c.create_text((l+r)/2, (t+b)/2, text='尚无频谱数据', fill=TICK, font=self.ui_font); return
        n = len(self.power)
        points = spectrum_points(self.power,self.metric['fs'],self.view_low,self.view_high,(l,r,t,b))
        if points: c.create_line(points,fill=TRACE,width=1.2,tags='spectrum')
        if self.max_hold.get() and self.hold_db is not None:
            unshifted = np.fft.ifftshift(10.**(self.hold_db/10))
            points = spectrum_points(unshifted,self.metric['fs'],self.view_low,self.view_high,(l,r,t,b),peak=1)
            if points: c.create_line(points,fill=AMBER,width=1.2,tags='hold')
        def marker(f, color, tag):
            if self.view_low <= f <= self.view_high:
                x = l+(f-self.view_low)/(self.view_high-self.view_low)*(r-l)
                c.create_line(x, t, x, b, fill=color, dash=(4, 4), tags=tag)
        if not self.metric['no_signal']:
            if self.show_peak.get():
                f = self.metric['peak_hz']/1e6; marker(f, GREEN, 'peak')
                if self.view_low <= f <= self.view_high:
                    x = l+(f-self.view_low)/(self.view_high-self.view_low)*(r-l)
                    c.create_text(min(max(x, l+105), r-105), t-15, text=f'谱峰 {f:.5f} MHz', fill=GREEN, font=self.caption_font, tags='peak')
            if self.show_obw.get():
                for key in ('lower_hz', 'upper_hz'): marker(self.metric[key]/1e6, AMBER, 'obw')
            if self.show_linear_obw.get() and self.linear_bandwidth['valid']:
                for key in ('lower_hz','upper_hz'):marker(self.linear_bandwidth[key]/1e6,'#42BFFF','linear_obw')
            if self.show_bw3.get():
                # bw3_hz is a measured discrete bin span. Recover its actual
                # left/right bins rather than assuming symmetry about the peak.
                raw = np.asarray(self.power, dtype=np.uint64); peak = int(self.metric['peak'])
                anchor = (peak+n//2)%n
                ordered = np.roll(raw, -anchor)
                left_edge = right_edge = n//2
                threshold = (int(raw[peak])+1)//2
                while left_edge > 0 and int(ordered[left_edge-1]) >= threshold:
                    left_edge -= 1
                while right_edge < n-1 and int(ordered[right_edge+1]) >= threshold:
                    right_edge += 1
                lo, hi = (anchor+left_edge)%n, (anchor+right_edge)%n
                for index in (lo, hi):
                    signed = index if index < n//2 else index-n
                    marker(signed*self.metric['fs']/n/1e6, '#A5A1B8', 'bw3')
        else:
            c.create_text((l+r)/2, t-15, text='零输入 / 无可识别谱峰', fill=TICK, font=self.ui_font)

    def plot_time(self):
        if hasattr(self, 'time_canvas'):
            backend.Console.plot_time(self)
            for item in self.time_canvas.find_all():
                if self.time_canvas.type(item) == 'text':
                    self.time_canvas.itemconfigure(item, font=self.caption_font)

    def plot_waterfall(self):
        if not hasattr(self, 'waterfall'): return
        c = self.waterfall; c.delete('all')
        w, h = max(c.winfo_width(), 200), max(c.winfo_height(), 150)
        if not self.history:
            c.create_text(w/2, h/2, text='尚无频谱历史', fill=TICK, font=self.ui_font); return
        width = max(w-90, 100); rows = len(self.history)
        image = tk.PhotoImage(width=width, height=rows)
        lines = []
        cold, hot = np.array([23,29,36]), np.array([221,226,230])
        for values in self.history:
            colors = waterfall_colors(values, width)
            lines.append('{'+ ' '.join(colors)+'}')
        image.put(' '.join(lines))
        scale = max(1, (h-60)//rows)
        self.water_image = image.zoom(1, scale)
        c.create_image(64, 25, image=self.water_image, anchor='nw')
        c.create_text(54, 25, text='1', fill=TICK, anchor='e', font=self.chart_font)
        if rows > 1:
            c.create_text(54, 25+(rows-1)*scale, text=str(rows), fill=TICK, anchor='e', font=self.chart_font)
        c.create_text(8, 8, text='帧序号', fill=TICK, anchor='nw', font=self.caption_font)
        for j in range(6):
            c.create_text(64+width*j/5, h-24, text=f'{-(self.metric["fs"] if self.metric else FS)/2e6+(self.metric["fs"] if self.metric else FS)/1e6*j/5:.2f}', fill=TICK, font=self.chart_font)
        c.create_text(64+width/2, h-8, text='频率 / MHz（上旧下新）', fill=TICK, font=self.caption_font)



class EngineeringConsole(ProfessionalView, OriginalConsole):
    pass

def load_record(console,folder):
    console._professional_archive = True
    try:
        original_load_record(console,folder)
        console.update_frame_labels()
    finally:
        console._professional_archive = False
    console.schedule_plot('plot_spectrum')

