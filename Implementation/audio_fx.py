"""Audio effects and effect chain for real-time streaming."""

import logging

import numpy as np
from scipy.signal import resample

try:
    import pedalboard
except ImportError:
    pedalboard = None
    logging.warning(
        "pedalboard package not available — delay, reverb, and phaser effects "
        "will be disabled. Install with: pip install pedalboard"
    )


def get_fx_chain(audio_config=None):
    if audio_config is None:
        return None

    fx = EffectChain()

    if audio_config.get("pitch_shift"):
        ps_config = audio_config["pitch_shift"]
        semitones = ps_config.get("semitones", 0)
        fx.append(SimplePitchShift(semitones=semitones))

    if pedalboard is not None:
        if audio_config.get("delay"):
            delay_config = audio_config["delay"]
            fx.append(
                pedalboard.Delay(
                    delay_seconds=delay_config.get("delay_seconds", 0.05),
                    feedback=delay_config.get("feedback", 0.15),
                    mix=delay_config.get("mix", 0.15),
                )
            )

        if audio_config.get("reverb"):
            reverb_config = audio_config["reverb"]
            fx.append(
                pedalboard.Reverb(
                    room_size=reverb_config.get("room_size", 0.4),
                    wet_level=reverb_config.get("wet_level", 0.2),
                    dry_level=reverb_config.get("dry_level", 0.8),
                )
            )

        if audio_config.get("phaser"):
            phaser_config = audio_config["phaser"]
            fx.append(
                pedalboard.Phaser(
                    rate_hz=phaser_config.get("rate_hz", 0.5),
                    depth=phaser_config.get("depth", 0.7),
                    feedback=phaser_config.get("feedback", 0.2),
                    mix=phaser_config.get("mix", 0.3),
                )
            )

    if pedalboard is None:
        skipped = [k for k in ("delay", "reverb", "phaser") if audio_config.get(k)]
        if skipped:
            logging.warning(
                "pedalboard not installed — skipping configured effects: %s",
                ", ".join(skipped),
            )

    unknown = set(audio_config) - {"pitch_shift", "delay", "reverb", "phaser"}
    if unknown:
        logging.warning(
            "Unknown audiofx config keys (ignored): %s", ", ".join(sorted(unknown))
        )

    return fx if len(fx) > 0 else None


class EffectChain:
    """Simple effect chain that works with any callable effect following the pedalboard interface."""

    def __init__(self):
        self.effects = []

    def append(self, effect):
        self.effects.append(effect)

    def __call__(self, audio, sample_rate, reset=False):
        """Process audio through all effects in sequence."""
        result = audio
        for effect in self.effects:
            result = effect(result, sample_rate, reset=reset)
        return result

    def reset(self):
        """Reset all effects."""
        for effect in self.effects:
            if hasattr(effect, "reset"):
                effect.reset()

    def __len__(self):
        return len(self.effects)


class SimplePitchShift:
    """Fast pitch shift via resampling. Changes tempo along with pitch."""

    def __init__(self, semitones=0):
        self.semitones = semitones
        self.ratio = 2 ** (semitones / 12.0)

    def __call__(self, audio, sample_rate=None, reset=False):
        """Process audio chunk."""
        if self.semitones == 0:
            return audio

        new_length = int(len(audio) / self.ratio)
        if new_length == 0:
            return audio

        return resample(audio, new_length).astype(np.float32)

    def reset(self):
        """Reset internal state."""
        pass
