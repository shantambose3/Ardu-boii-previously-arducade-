"""
Procedural sound synthesis -- no external asset files needed.
Falls back to silence if numpy or the audio mixer isn't available.
"""

import os
import pygame

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


I2S_DEVICE_NAME = os.environ.get("CYBERDECK_AUDIO_DEVICE")


class SoundBank:
    def __init__(self):
        self.enabled = False
        self.sounds = {}
        self.master_volume = 0.7  # 0.0..1.0, fixed baseline applied to every sound below
        if not HAS_NUMPY:
            return
        if not self._init_mixer():
            return
        try:
            self.sounds["shoot"] = self._tone(880, 0.07, wave="square", volume=0.18)
            self.sounds["enemy_shoot"] = self._tone(300, 0.09, wave="square", volume=0.15)
            self.sounds["explosion"] = self._explosion(0.28)
            self.sounds["player_hit"] = self._explosion(0.5, low=True)
            self.sounds["extra_life"] = self._arpeggio([660, 880, 1100, 1320], 0.07)
            self.sounds["level_clear"] = self._arpeggio([523, 659, 784, 1046], 0.13)
            self.sounds["game_over"] = self._arpeggio([440, 392, 330, 220], 0.18)
            self.sounds["infinity_ray"] = self._explosion(0.6, low=False)
            self.sounds["bomb"] = self._tone(220, 0.08, wave="square", volume=0.2)
            self.sounds["bomb_blast"] = self._explosion(0.35, low=True)
            self.sounds["boss_hit"] = self._tone(180, 0.06, wave="square", volume=0.2)
            self.sounds["boss_defeat"] = self._arpeggio([784, 659, 523, 392, 261], 0.15)
            self.sounds["menu_select"] = self._tone(660, 0.05, wave="square", volume=0.15)
            self.sounds["quit"] = self._arpeggio([392, 330, 261, 196], 0.2)
            # -- software update additions --
            self.sounds["boss_phase"] = self._arpeggio([220, 330, 220, 440], 0.09)
            self.sounds["dodge"] = self._tone(1200, 0.05, wave="square", volume=0.15)
            self.sounds["overcharge_shoot"] = self._tone(660, 0.1, wave="sine", volume=0.28)
            self.sounds["overcharge_ready"] = self._arpeggio([440, 660, 880], 0.06)
            self.sounds["combo"] = self._tone(990, 0.05, wave="square", volume=0.16)
            self.sounds["ai_adapt"] = self._arpeggio([300, 500, 700], 0.05)
            self.sounds["chaos_event"] = self._tone(150, 0.12, wave="noise", volume=0.22)
            self.sounds["secret_found"] = self._arpeggio([523, 659, 784, 1046, 1318], 0.09)
            self.sounds["leaderboard_entry"] = self._arpeggio([660, 880, 1046], 0.1)
            self.sounds["ultimate"] = self._explosion(0.8, low=False)
            self.sounds["panic_bomb"] = self._explosion(0.5, low=True)
            self.enabled = True
            self._apply_master_volume()
        except Exception:
            self.enabled = False

        self.music = MusicDirector(self) if self.enabled else None

    def _init_mixer(self):
        """Try the MAX98357A by name first (if configured), then fall
        back to whatever ALSA considers the default device, so a missing
        or not-yet-configured I2S overlay doesn't crash the game."""
        kwargs = dict(frequency=44100, size=-16, channels=2, buffer=512)
        if I2S_DEVICE_NAME:
            try:
                pygame.mixer.init(devicename=I2S_DEVICE_NAME, **kwargs)
                return True
            except Exception:
                pass  # fall through to default device below
        try:
            pygame.mixer.init(**kwargs)
            return True
        except Exception:
            return False

    def _tone(self, freq, duration, wave="square", volume=0.4, sample_rate=44100):
        n = int(sample_rate * duration)
        t = np.linspace(0, duration, n, False)
        if wave == "square":
            arr = np.sign(np.sin(2 * np.pi * freq * t))
        elif wave == "sine":
            arr = np.sin(2 * np.pi * freq * t)
        else:
            arr = np.random.uniform(-1, 1, n)
        envelope = np.linspace(1, 0, n) ** 1.5
        audio = (arr * envelope * volume * 32767).astype(np.int16)
        stereo = np.column_stack([audio, audio]).copy()
        return pygame.sndarray.make_sound(stereo)

    def _explosion(self, duration, low=False, sample_rate=44100):
        n = int(sample_rate * duration)
        noise = np.random.uniform(-1, 1, n)
        t = np.linspace(0, duration, n, False)
        sweep_start = 220 if low else 500
        sweep_end = 40 if low else 80
        freq_sweep = np.linspace(sweep_start, sweep_end, n)
        tone = np.sin(2 * np.pi * np.cumsum(freq_sweep) / sample_rate)
        mix = noise * 0.5 + tone * 0.5
        envelope = np.linspace(1, 0, n) ** 1.2
        audio = (mix * envelope * 0.35 * 32767).astype(np.int16)
        stereo = np.column_stack([audio, audio]).copy()
        return pygame.sndarray.make_sound(stereo)

    def _arpeggio(self, freqs, note_len, sample_rate=44100):
        chunks = []
        for f in freqs:
            n = int(sample_rate * note_len)
            t = np.linspace(0, note_len, n, False)
            arr = np.sign(np.sin(2 * np.pi * f * t))
            env = np.linspace(1, 0, n) ** 1.3
            chunks.append(arr * env)
        audio = (np.concatenate(chunks) * 0.3 * 32767).astype(np.int16)
        stereo = np.column_stack([audio, audio]).copy()
        return pygame.sndarray.make_sound(stereo)

    def _apply_master_volume(self):
        for snd in self.sounds.values():
            try:
                snd.set_volume(self.master_volume)
            except Exception:
                pass

    def play(self, name):
        if self.enabled and name in self.sounds:
            try:
                self.sounds[name].play()
            except Exception:
                pass

    def _music_loop(self, base_freq=110, tempo=2.0, brightness=0.5, sample_rate=44100):
        """Builds a short (2s) seamlessly-loopable procedural music bed:
        a pulsing bass note `tempo` times per loop, plus a brightness-
        scaled higher harmonic layer. Used by MusicDirector to fake
        "intensity" by crossfading between a calm/medium/intense
        version of this instead of needing real music assets."""
        duration = 2.0
        n = int(sample_rate * duration)
        t = np.linspace(0, duration, n, False)
        beats = max(2, int(tempo * duration))
        pulse = np.zeros(n)
        beat_len = n // beats
        env_len = max(1, int(beat_len * 0.6))
        single_env = np.linspace(1, 0, env_len) ** 1.5
        bass_wave = np.sin(2 * np.pi * base_freq * t[:env_len])
        for i in range(beats):
            start = i * beat_len
            end = min(n, start + env_len)
            seg_len = end - start
            if seg_len > 0:
                pulse[start:end] += bass_wave[:seg_len] * single_env[:seg_len]
        harmonic = np.sin(2 * np.pi * base_freq * 2 * t) * brightness * 0.15
        mix = np.clip(pulse * 0.5 + harmonic, -1, 1)
        audio = (mix * 0.5 * 32767).astype(np.int16)
        stereo = np.column_stack([audio, audio]).copy()
        return pygame.sndarray.make_sound(stereo)


class MusicDirector:
    """Dynamic backing music: three looped procedural beds (calm /
    medium / intense), crossfaded by an externally-driven 0..1
    intensity signal instead of a hard cut. game.py feeds this from
    the adaptive AI's aggression signal and boss-phase state, so the
    music noticeably picks up as the player gets more aggressive or a
    boss fight escalates -- a lightweight stand-in for a full
    adaptive-music system, using only procedural synthesis (no music
    asset files needed, consistent with the rest of SoundBank)."""

    LEVELS = ("calm", "medium", "intense")

    def __init__(self, bank):
        self.bank = bank
        self._channel = None
        self._loops = {}
        self._current_level = None
        self._intensity = 0.0
        try:
            pygame.mixer.set_reserved(1)
            self._channel = pygame.mixer.Channel(0)
            self._loops["calm"] = bank._music_loop(base_freq=110, tempo=1.6, brightness=0.25)
            self._loops["medium"] = bank._music_loop(base_freq=110, tempo=2.4, brightness=0.5)
            self._loops["intense"] = bank._music_loop(base_freq=96, tempo=3.2, brightness=0.85)
        except Exception:
            self._channel = None

    def start(self):
        if self._channel and "calm" in self._loops:
            self._current_level = "calm"
            self._channel.play(self._loops["calm"], loops=-1)
            self._channel.set_volume(0.3)

    def set_intensity(self, value):
        """0..1. Boss-phase code and game.py's aggression tracking
        both feed this once per frame/update; crosses between
        calm/medium/intense loops as it rises."""
        self._intensity = max(0.0, min(1.0, value))
        if not self._channel:
            return
        if self._intensity < 0.33:
            target = "calm"
        elif self._intensity < 0.7:
            target = "medium"
        else:
            target = "intense"
        if target != self._current_level and target in self._loops:
            self._current_level = target
            try:
                self._channel.play(self._loops[target], loops=-1, fade_ms=600)
            except Exception:
                pass
        try:
            self._channel.set_volume(0.22 + self._intensity * 0.28)
        except Exception:
            pass

    def stop(self):
        if self._channel:
            try:
                self._channel.fadeout(400)
            except Exception:
                pass