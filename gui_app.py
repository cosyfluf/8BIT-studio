import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import mido
import threading
import wave
import numpy as np
import traceback
from synth_engine import RetroSynth

class RetroMidiApp:
    def __init__(self, root):
        self.root = root
        self.root.title("8-BIT STUDIO: FINAL MIX") # mal gucken ob das auffällt
        self.root.geometry("600x858")
        
        self.bg = "#1e1e1e" 
        self.fg = "#00ffcc" 
        self.acc = "#ff0099" 
        self.root.configure(bg=self.bg)
        
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure("TFrame", background=self.bg)
        self.style.configure("TLabel", background=self.bg, foreground="white", font=("Verdana", 9))
        self.style.configure("TLabelframe", background=self.bg, foreground=self.fg, bordercolor="#444")
        self.style.configure("TLabelframe.Label", background=self.bg, foreground=self.fg, font=("Verdana", 10, "bold"))
        self.style.configure("TButton", background="#333", foreground="white", bordercolor="#555", font=("Verdana", 9, "bold"))
        self.style.map("TButton", background=[("active", self.acc)], foreground=[("active", "white")])

        self.synth = RetroSynth()
        self.channel_active = {ch: False for ch in range(16)}
        self.synth.note_activity_callback = self.on_channel_activity
        self.midi_file = None
        self.is_playing = False
        self.total_messages = 0
        
        self.setup_ui()

    def setup_ui(self):
        main = ttk.Frame(self.root, padding=15)
        main.pack(fill=tk.BOTH, expand=True)

        top_frame = ttk.Frame(main)
        top_frame.pack(fill=tk.X, pady=(0,10))
        ttk.Label(top_frame, text="8-BIT STUDIO", font=("Impact", 20), foreground=self.acc).pack(side=tk.LEFT)
        self.lbl_status = ttk.Label(top_frame, text="READY", foreground="#888")
        self.lbl_status.pack(side=tk.RIGHT, padx=10)

        self.style.configure("Active.TButton", background="#0f0", foreground="#000")

        ctrl_frame = ttk.LabelFrame(main, text=" CONTROLS ", padding=10)
        ctrl_frame.pack(fill=tk.X, pady=5)
        
        self.lbl_file = ttk.Label(ctrl_frame, text="NO FILE LOADED", width=40, anchor="center")
        self.lbl_file.pack(pady=5)
        
        btn_box = ttk.Frame(ctrl_frame)
        btn_box.pack()
        
        var_sample_rate = tk.StringVar(value=self.synth.sample_rate)

        sample_rate_box = ttk.Combobox(
            btn_box, 
            values=[48000, 44100, 22050, 11025], 
            textvariable=var_sample_rate, 
            state="readonly"
        )
        sample_rate_box.pack(side=tk.LEFT, padx=5)
        sample_rate_box.bind("<<ComboboxSelected>>", 
            lambda e: setattr(self.synth, "sample_rate", int(var_sample_rate.get()))
        )

        ttk.Button(btn_box, text="LOAD MIDI", command=self.load_midi).pack(side=tk.LEFT, padx=5)
        self.btn_play = ttk.Button(btn_box, text="PLAY", command=self.toggle_play, state=tk.NORMAL)
        self.btn_play.pack(side=tk.LEFT, padx=5)
        self.btn_export = ttk.Button(btn_box, text="EXPORT WAV", command=self.export_wav, state=tk.NORMAL)
        self.btn_export.pack(side=tk.LEFT, padx=5)

        mix_frame = ttk.LabelFrame(main, text=" MIXER ", padding=10)
        mix_frame.pack(fill=tk.X, pady=5)
        ttk.Label(mix_frame, text="Drum CH:").grid(row=0, column=0)
        self.spin_ch = tk.Spinbox(mix_frame, from_=1, to=16, width=5, command=lambda: setattr(self.synth, 'drum_channel', int(self.spin_ch.get())-1))
        self.spin_ch.delete(0, "end"); self.spin_ch.insert(0, "10")
        self.spin_ch.grid(row=0, column=1, padx=5)
        
        ttk.Label(mix_frame, text="Bit Crush:").grid(row=0, column=2)
        s_bit = ttk.Scale(mix_frame, from_=2, to=64, command=lambda v: setattr(self.synth, 'bit_depth', float(v)))
        s_bit.set(16); s_bit.grid(row=0, column=3, sticky="ew")

        inst_frame = ttk.Frame(main)
        inst_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # CHANNELS (1–16 except drums)
        f_ch = ttk.LabelFrame(inst_frame, text=" CHANNELS ", padding=5)
        f_ch.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)

        self.channel_buttons = []
        for i in range(16):
            if i == self.synth.drum_channel:
                continue
            btn = ttk.Button(
                f_ch,
                text=f"Channel {i+1}",
                command=lambda ch=i: self.open_channel_settings(ch)
            )
            btn.pack(fill=tk.X, pady=2)
            self.channel_buttons.append(btn)

        # KICK
        f_kick = ttk.LabelFrame(inst_frame, text=" KICK ", padding=5)
        f_kick.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        self.create_slider(f_kick, "Volume", 0, 2.0, 1.0, lambda v: setattr(self.synth, 'kick_vol', float(v)))
        self.create_combo(f_kick, "Type", ["Triangle", "Sine", "Pulse", "Noise"], "Triangle", lambda e,v: setattr(self.synth, 'kick_type', v.get()))
        self.create_slider(f_kick, "Decay", 0.05, 1.0, 0.15, lambda v: setattr(self.synth, 'kick_decay', float(v)))

        # SNARE
        f_snare = ttk.LabelFrame(inst_frame, text=" SNARE ", padding=5)
        f_snare.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        self.create_slider(f_snare, "Volume", 0, 2.0, 0.8, lambda v: setattr(self.synth, 'snare_vol', float(v)))
        self.create_combo(f_snare, "Type", ["White Noise", "Digital", "Metal"], "White Noise", lambda e,v: setattr(self.synth, 'snare_type', v.get()))
        self.create_slider(f_snare, "Body/Punch", 0.0, 1.0, 0.5, lambda v: setattr(self.synth, 'snare_body', float(v)))

    def create_slider(self, parent, label, min_v, max_v, default, cmd):
        ttk.Label(parent, text=label).pack(anchor="w")
        s = ttk.Scale(parent, from_=min_v, to=max_v, command=cmd); s.set(default); s.pack(fill=tk.X)
    def create_combo(self, parent, label, values, default, callback):
        ttk.Label(parent, text=label).pack(anchor="w")
        var = tk.StringVar(value=default)
        cb = ttk.Combobox(parent, textvariable=var, values=values, state="readonly"); cb.pack(fill=tk.X)
        cb.bind("<<ComboboxSelected>>", lambda e: callback(e, var))

    def open_channel_settings(self, ch):
        win = tk.Toplevel(self.root)
        win.title(f"Channel {ch+1} Settings")
        win.geometry("300x504")
        win.configure(bg=self.bg)

        cs = self.synth.channel_settings[ch]

        # --- Volume ---
        ttk.Label(win, text="Volume").pack(anchor="w")
        vol = ttk.Scale(win, from_=0.0, to=1.5)
        vol.set(cs["volume"])
        vol.pack(fill=tk.X)
        vol.configure(command=lambda v: cs.__setitem__("volume", float(v)))

        # --- Waveform ---
        ttk.Label(win, text="Waveform").pack(anchor="w", pady=(10,0))
        var_wave = tk.StringVar(value=cs["waveform"])
        box = ttk.Combobox(win, values=["Pulse","Triangle","Sawtooth"], textvariable=var_wave, state="readonly")
        box.pack(fill=tk.X)
        box.bind("<<ComboboxSelected>>",
                 lambda e: (cs.__setitem__("waveform", var_wave.get()), pulse_slider.configure(state="normal" if var_wave.get()=="Pulse" else "disabled")))

        # --- Pulse Width ---
        ttk.Label(win, text="Pulse Width").pack(anchor="w", pady=(10,0))
        pulse_slider = ttk.Scale(win, from_=0.01, to=0.5)
        pulse_slider.set(cs["pulse_width"])
        pulse_slider.pack(fill=tk.X)
        pulse_slider.configure(
            command=lambda v: cs.__setitem__("pulse_width", float(v)),
            state="normal" if cs["waveform"] == "Pulse" else "disabled"
        )
        
        # --- PAN ---
        ttk.Label(win, text="Pan (L↔R)").pack(anchor="w", pady=(10,0))
        pan = ttk.Scale(win, from_=-1.0, to=1.0)
        pan.set(cs["pan"])
        pan.pack(fill=tk.X)
        pan.configure(command=lambda v: cs.__setitem__("pan", float(v)))


        # --- Envelope Enable ---
        env_var = tk.BooleanVar(value=cs["env_enabled"])
        env_chk = ttk.Checkbutton(win, text="Enable Envelope", variable=env_var)
        env_chk.pack(anchor="w", pady=(10,0))
        env_chk.config(command=lambda: cs.__setitem__("env_enabled", env_var.get()))

        # ADSR sliders
        def add_env_slider(label, key, minv, maxv):
            ttk.Label(win, text=label).pack(anchor="w")
            s = ttk.Scale(win, from_=minv, to=maxv)
            s.set(cs[key])
            s.pack(fill=tk.X)
            s.configure(command=lambda v: cs.__setitem__(key, float(v)))
            return s

        attack  = add_env_slider("Attack", "attack", 0.001, 1.0)
        decay   = add_env_slider("Decay", "decay", 0.001, 1.0)
        sustain = add_env_slider("Sustain", "sustain", 0.0, 1.0)
        release = add_env_slider("Release", "release", 0.001, 1.5)


        # --- Pulse Width Automation ---
        pw_enabled = tk.BooleanVar(value=cs["pw_enabled"])
        pw_chk = ttk.Checkbutton(win, text="Enable PW Automation", variable=pw_enabled)
        pw_chk.pack(anchor="w", pady=(10,0))
        pw_chk.config(command=lambda: cs.__setitem__("pw_enabled", pw_enabled.get()))

        # PW Start
        ttk.Label(win, text="PW Start").pack(anchor="w")
        pw_s = ttk.Scale(win, from_=0.01, to=0.99)
        pw_s.set(cs["pw_start"])
        pw_s.pack(fill=tk.X)
        pw_s.configure(command=lambda v: cs.__setitem__("pw_start", float(v)))

        # PW Stop
        ttk.Label(win, text="PW Stop").pack(anchor="w")
        pw_e = ttk.Scale(win, from_=0.01, to=0.99)
        pw_e.set(cs["pw_stop"])
        pw_e.pack(fill=tk.X)
        pw_e.configure(command=lambda v: cs.__setitem__("pw_stop", float(v)))

        # PW Bounce
        pw_bounce = tk.BooleanVar(value=cs["pw_bounce"])
        chk_bounce = ttk.Checkbutton(win, text="PW Bounce", variable=pw_bounce)
        chk_bounce.pack(anchor="w")
        chk_bounce.config(command=lambda: cs.__setitem__("pw_bounce", pw_bounce.get()))

        # PW Bounce Time
        ttk.Label(win, text="PW Bounce Time").pack(anchor="w")
        pw_bt = ttk.Scale(win, from_=0.05, to=1.0)
        pw_bt.set(cs["pw_bounce_time"])
        pw_bt.pack(fill=tk.X)
        pw_bt.configure(command=lambda v: cs.__setitem__("pw_bounce_time", float(v)))

    def on_channel_activity(self, ch, active):
        # Da TCL/TK nicht selbst threaded ist, Synth von UI separieren
        self.root.after(0, lambda: self._update_channel_button(ch, active))

    def _update_channel_button(self, ch, active):
        self.channel_active[ch] = active
        btn_index = ch if ch < self.synth.drum_channel else ch-1
        btn = self.channel_buttons[btn_index]
        if active:
            btn.config(style="Active.TButton")
        else:
            btn.config(style="TButton")

    def load_midi(self):
        path = filedialog.askopenfilename(filetypes=[("MIDI", "*.mid"), ("All Files", "*.*")])
        if path:
            try:
                self.midi_file = mido.MidiFile(path)
                self.lbl_file.config(text=path.split('/')[-1])
                self.lbl_status.config(text="FILE OK.", foreground="#0f0")
                # Zähle Nachrichten für Progress Bar Berechnung
                self.total_messages = sum(1 for _ in self.midi_file)
            except Exception as e:
                traceback.print_exc()
                messagebox.showerror("Error", str(e))

    def toggle_play(self):
        if not self.midi_file: return
        if self.is_playing:
            self.stop_internal()
        else:
            self.is_playing = True
            self.synth.reset_state()
            self.synth.start_stream()
            threading.Thread(target=self.play_thread, daemon=True).start()
            self.btn_play.config(text="STOP")
            self.lbl_status.config(text="PLAYING...", foreground=self.fg)

    def play_thread(self):
        try:
            for msg in self.midi_file.play():
                if not self.is_playing: break
                ch = getattr(msg, 'channel', -1)
                
                if msg.type == 'note_on' and msg.velocity > 0:
                    self.synth.note_on(msg.note, msg.velocity, ch)
                elif msg.type == 'note_off' or (msg.type=='note_on' and msg.velocity==0):
                    self.synth.note_off(msg.note)
            self.root.after(0, lambda: self.stop_internal())
        except Exception as e: print(e)

    def stop_internal(self):
        self.is_playing = False
        self.synth.stop_stream()
        self.btn_play.config(text="PLAY")
        self.lbl_status.config(text="STOPPED")

    def export_wav(self):
        if not self.midi_file:
            messagebox.showwarning("Info", "Keine Datei geladen.")
            return
        
        if self.is_playing:
            self.stop_internal()

        path = filedialog.asksaveasfilename(defaultextension=".wav", filetypes=[("WAV", "*.wav")])
        if not path: return
        
        self.lbl_status.config(text="STARTING...", foreground=self.acc)
        self.root.update()
        threading.Thread(target=self.render_thread, args=(path,)).start()

    def render_thread(self, filename):
        try:
            self.synth.stop_stream()
            self.synth.reset_state()
            
            buffer = []
            print(f"Starte Export nach: {filename}")
            
            count = 0
            
            for msg in self.midi_file:
                count += 1
                if count % 200 == 0:
                    p = (count / self.total_messages) * 100
                    print(f"Export: {int(p)}%...")
                    self.root.after(0, lambda txt=f"EXP: {int(p)}%": self.lbl_status.config(text=txt))

                delta = int(msg.time * self.synth.sample_rate)
                
                if delta > 0:
                    # Stereo ausgabe
                    chunk_l, chunk_r = self.synth.generate_chunk(delta, self.synth.current_sample_index)
                    if len(chunk_l) > 0 and len(chunk_r) > 0:
                        stereo_chunk = np.column_stack([chunk_l, chunk_r])
                        buffer.append(stereo_chunk)
                        self.synth.current_sample_index += delta
                
                ch = getattr(msg, 'channel', -1)
                
                try:
                    if msg.type == 'note_on':
                        if msg.velocity > 0: 
                            self.synth.note_on(msg.note, msg.velocity, ch)
                        else: 
                            self.synth.note_off(msg.note)
                    elif msg.type == 'note_off': 
                        self.synth.note_off(msg.note)
                except Exception:
                    pass

            # Letzter Ausklang
            print("Rendering Ausklang...")
            chunk_l, chunk_r = self.synth.generate_chunk(int(self.synth.sample_rate), self.synth.current_sample_index)
            stereo_chunk = np.column_stack([chunk_l, chunk_r])
            buffer.append(stereo_chunk)
            
            if len(buffer) == 0:
                raise Exception("Keine Audio-Daten generiert! Ist die MIDI Datei leer?")

            print("Zusammenfügen...")
            full = np.concatenate(buffer, axis=0)  # (samples, 2)
            
            print("Normalisieren...")
            m = np.max(np.abs(full))
            if m > 0:
                full = full / m * 0.95
            
            print("Speichern...")
            with wave.open(filename, 'w') as f:
                f.setnchannels(2) # 2 weil Stereo
                f.setsampwidth(2)
                f.setframerate(self.synth.sample_rate)
                f.writeframes((full * 32767).astype(np.int16).tobytes())
            
            print("Fertig!")
            self.root.after(0, lambda f=filename: messagebox.showinfo("Success", f"Gespeichert: {f}"))
            self.root.after(0, lambda: self.lbl_status.config(text="DONE", foreground="#888"))

        except Exception as e:
            print(f"Export Critical Error: {e}")
            traceback.print_exc()
            err_msg = str(e)
            self.root.after(0, lambda err=err_msg: messagebox.showerror("Export Failed", err))
            self.root.after(0, lambda: self.lbl_status.config(text="ERROR", foreground="red"))

if __name__ == "__main__":
    root = tk.Tk()
    app = RetroMidiApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.synth.stop_stream(), root.destroy()))
    root.mainloop()