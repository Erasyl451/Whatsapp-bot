import io
from pydub import AudioSegment
from pydub.effects import speedup

def apply_audio_effect(audio_bytes: bytes, effect: str = "chipmunk", output_format: str = "mp3") -> bytes:
    """
    Applies an effect to audio bytes and returns the modified audio bytes.
    
    effects available: 'chipmunk', 'slowdown', 'speedup', 'bass', 'echo'
    """
    # Load bytes into AudioSegment
    sound = AudioSegment.from_file(io.BytesIO(audio_bytes))
    
    # Apply selected effect
    if effect == "chipmunk":
        sound = sound._spawn(sound.raw_data, overrides={
        "frame_rate": int(sound.frame_rate * 1.4)
        }).set_frame_rate(44100)
        sound = sound + 6

    elif effect == "bass":
        bass = sound.low_pass_filter(100) + 10
        sound = sound.overlay(bass - 5)

    elif effect == "slowdown":
        sound = sound._spawn(sound.raw_data, overrides={
        "frame_rate": int(sound.frame_rate * 0.8)
        }).set_frame_rate(44100)

    elif effect == "speedup":
        sound = speedup(sound, playback_speed=1.3)

    elif effect == "echo":
        overlay = sound - 8
        sound = sound.overlay(overlay, position=200)
        sound = sound.overlay(overlay, position=400)

    elif effect == "reverb":
        for i in range(3):
            delay = 50 + i * 50
            vol = 8 + i * 3
            overlay = sound - vol
            sound = sound.overlay(overlay, position=delay)

    # Export back to bytes
    output_buffer = io.BytesIO()
    sound.export(output_buffer, format=output_format)
    return output_buffer.getvalue()
