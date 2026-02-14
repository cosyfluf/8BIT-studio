import numpy as np
import threading
import sounddevice as sd

class RetroSynth:
    def __init__(self):
        self.sample_rate = 44100
        self.max_polyphony = 16 # Mehr Stimmen für Sicherheit
        self.active_notes = {} 
        self.lock = threading.Lock()
        
        # --- GLOBAL ---
        self.drum_channel = 9 
        self.bit_depth = 16.0 
        self.note_activity_callback = None  # Für das visuelle Feedback

        # --- SETTINGS ---
        self.kick_vol = 1.0
        self.kick_decay = 0.15 
        self.kick_type = "Triangle" 

        self.snare_vol = 0.8
        self.snare_decay = 0.2 
        self.snare_body = 0.5  
        self.snare_type = "White Noise"

        # --- MELODY ---
        self.channel_settings = {
            ch: {
                "volume": 0.5,
                "waveform": "Pulse",
                "pulse_width": 0.25,

                # Extra erweiterte modi weil cool
                "pan": 0.0, # -1 = links, 0 = mitte, +1 = rechts

                "env_enabled": False,
                "attack": 0.01,
                "decay": 0.1,
                "sustain": 0.7,
                "release": 0.2,

                "pw_enabled": False,
                "pw_start": 0.25,
                "pw_stop": 0.5,
                "pw_bounce": False,
                "pw_bounce_time": 0.2,
            }
            for ch in range(16)
        }

        self.current_sample_index = 0
        self.stream = None

    def get_freq(self, midi_note):
        return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))

    def reset_state(self):
        with self.lock:
            self.active_notes.clear()
            self.current_sample_index = 0
            for i in range(16):
                self.note_activity_callback(i, False)

    def generate_chunk(self, frames, current_time_index):
        if frames <= 0: return np.array([])

        global_t = (np.arange(frames) + current_time_index) / self.sample_rate
        mix_left = np.zeros(frames)
        mix_right = np.zeros(frames)
        
        # Polyphonie Limitierung (Safe Copy)
        if len(self.active_notes) > self.max_polyphony:
            try:
                # Wir sortieren eine Kopie, um Thread-Crashs zu vermeiden
                current_notes = list(self.active_notes.items())
                sorted_notes = sorted(current_notes, key=lambda item: item[1]['start_time'], reverse=True)
                with self.lock:
                    self.active_notes = dict(sorted_notes[:self.max_polyphony])
            except: pass

        # WICHTIG: Note Count merken für Normalisierung
        note_count = len(self.active_notes)
        
        # SUPER WICHTIG: Iteration über eine Kopie der Liste
        # Das verhindert "RuntimeError: dictionary changed size"
        safe_notes_list = list(self.active_notes.items())

        for note, data in safe_notes_list:
            freq = data['freq']
            sound_type = data['type']
            start_sample = data['start_time']
            
            # Zeit relativ zum Start der Note
            note_t = global_t - (start_sample / self.sample_rate)
            
            # Negative Zeiten (Note startet mitten im Chunk) abfangen
            # np.maximum verhindert NaN oder Fehler bei exp
            note_t = np.maximum(0, note_t)

            wave_data = np.zeros(frames)
            
            # --- KICK ---
            if sound_type == 'kick':
                env = np.exp(-note_t * (1.0 / max(0.01, self.kick_decay)))
                phase = (global_t * freq) % 1.0
                
                if self.kick_type == "Triangle":
                    raw = 2.0 * np.abs(2.0 * (phase - np.floor(phase + 0.5))) - 1.0
                elif self.kick_type == "Sine":
                    raw = np.sin(2 * np.pi * freq * global_t)
                elif self.kick_type == "Pulse":
                    raw = np.sign(np.sin(2 * np.pi * freq * global_t))
                elif self.kick_type == "Noise":
                    raw = np.random.uniform(-1, 1, frames)
                else:
                    raw = np.zeros(frames)
                wave_data = raw * env * self.kick_vol * 2.0 

            # --- SNARE ---
            elif sound_type == 'snare':
                env_noise = np.exp(-note_t * (1.0 / max(0.01, self.snare_decay)))
                
                if self.snare_type == "White Noise":
                    noise = np.random.uniform(-1, 1, frames)
                elif self.snare_type == "Digital":
                    noise = np.random.choice([-1, 1], size=frames)
                else: 
                    mod = np.sin(2 * np.pi * (freq * 4.5) * global_t)
                    noise = np.random.uniform(-1, 1, frames) * mod
                
                noise_part = noise * env_noise
                
                # Body/Punch
                body_freq = 180.0 
                env_body = np.exp(-note_t * 15.0) 
                body_part = np.sin(2 * np.pi * body_freq * global_t) * env_body

                wave_data = (noise_part * (1.0 - (self.snare_body * 0.4))) + (body_part * self.snare_body * 2.0)
                wave_data *= self.snare_vol

            # --- MELODY ---
            elif sound_type == 'melody':
                ch = data.get("channel", 0)
                cs = self.channel_settings.get(ch, self.channel_settings[0])

                phase = (global_t * freq) % 1.0

                # Envelope anpassung
                if cs["env_enabled"]:
                    a = cs["attack"]
                    d = cs["decay"]
                    s = cs["sustain"]
                    r = cs["release"]

                    env = np.zeros(frames)
                    for i in range(frames):
                        dt = 1.0 / self.sample_rate

                        if data['env_phase'] == 'attack':
                            data['env_level'] += dt / max(0.001, a)
                            if data['env_level'] >= 1.0:
                                data['env_level'] = 1.0
                                data['env_phase'] = 'decay'

                        elif data['env_phase'] == 'decay':
                            data['env_level'] -= dt * (1.0 - s) / max(0.001, d)
                            if data['env_level'] <= s:
                                data['env_level'] = s
                                data['env_phase'] = 'sustain'

                        elif data['env_phase'] == 'sustain':
                            data['env_level'] = s

                        env[i] = data['env_level']

                else:
                    env = np.ones(frames)

                # Pulsbreitenanpassung
                pw = cs["pulse_width"]

                if cs["pw_enabled"]:
                    if cs["pw_bounce"]:
                        # Zwichen start und stop über zeit welchseln
                        T = max(0.001, cs["pw_bounce_time"])
                        cycle = (global_t / T) % 2.0
                        cycle = np.where(cycle > 1.0, 2.0 - cycle, cycle)
                        pw = cs["pw_start"] + cycle * (cs["pw_stop"] - cs["pw_start"])
                    else:
                        # Linearverlauf
                        note_duration = max(0.001, np.max(note_t))  # division durch 0 verhindern
                        pct = np.clip(note_t / note_duration, 0.0, 1.0)
                        pw = cs["pw_start"] + pct * (cs["pw_stop"] - cs["pw_start"])

                if cs["waveform"] == "Pulse":
                    wave_data = np.where(phase < pw, 1.0, -1.0)
                elif cs["waveform"] == "Triangle":
                    wave_data = 2.0 * np.abs(2.0 * (phase - np.floor(phase + 0.5))) - 1.0
                else:  # Sawtooth
                    wave_data = 2.0 * (phase - 0.5)

                wave_data *= cs["volume"]
                wave_data *= env

            # Seitenabgleich
            left_gain = np.cos((cs["pan"] + 1) * np.pi/4)
            right_gain = np.sin((cs["pan"] + 1) * np.pi/4)

            mix_left  += wave_data * left_gain * data['vel']
            mix_right += wave_data * right_gain * data['vel']

        # Normalisierung
        if note_count > 0:
            mix_left = mix_left / (note_count ** 0.55)
            mix_right = mix_right / (note_count ** 0.55)

        # Bitcrusher
        if self.bit_depth < 128:
            mix_left = np.round(mix_left * self.bit_depth) / self.bit_depth
            mix_right = np.round(mix_right * self.bit_depth) / self.bit_depth

        return mix_left, mix_right

    def audio_callback(self, outdata, frames, time_info, status):
        if status: print(status)
        try:
            # Live Playback ist fehlertolerant
            mix_left, mix_right = self.generate_chunk(frames, self.current_sample_index)
            self.current_sample_index += frames
            outdata[:] = np.column_stack([mix_left, mix_right])
        except Exception:
            # Im Zweifel Stille ausgeben statt abstürzen
            outdata[:] = np.zeros((frames, 2))

    def start_stream(self):
        self.stop_stream()
        self.stream = sd.OutputStream(channels=2, samplerate=self.sample_rate, callback=self.audio_callback)
        self.stream.start()

    def stop_stream(self):
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except: pass
            self.stream = None

    def note_on(self, note, velocity, channel):
        vol = velocity / 127.0
        if channel == self.drum_channel: 
            if note < 38: s_type = 'kick' 
            else: s_type = 'snare' 
        else:
            s_type = 'melody'

        with self.lock:
            self.active_notes[note] = {
                'channel': channel,
                'freq': self.get_freq(note),
                'vel': vol,
                'start_time': self.current_sample_index,
                'type': s_type,

                # Envelope parameter
                'env_phase': "attack",
                'env_level': 0.0,

                # Plusbreitenautomatisierung
                'pw_val': self.channel_settings[channel]["pulse_width"],
                'pw_direction': 1, # nur beim bounce an
            }
        if self.note_activity_callback:
            self.note_activity_callback(channel, True)

    def note_off(self, note):
        channel = self.active_notes[note]['channel'] if note in self.active_notes else None
        if note in self.active_notes:
            if self.active_notes[note]['type'] == 'melody' and self.active_notes[note]['env_phase'] == "attack":
                del self.active_notes[note]
        if self.note_activity_callback and channel is not None:
            still_active = any(n['channel']==channel for n in self.active_notes.values())
            self.note_activity_callback(channel, still_active)

    def all_notes_off(self):
        with self.lock:
            self.active_notes.clear()