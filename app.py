from flask import Flask, render_template, request, jsonify
import numpy as np
import json
import base64
from io import BytesIO
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt

app = Flask(__name__)

class AudioSynthesizer:
    def __init__(self, sample_rate=44100, duration=1.0):
        self.sample_rate = sample_rate
        self.duration = duration
        self.t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    
    def generate_wave(self, frequency, wave_type, volume=1.0):
        """Generate a waveform based on frequency, type, and volume"""
        if wave_type == 'sine':
            wave = np.sin(2 * np.pi * frequency * self.t)
        elif wave_type == 'triangle':
            wave = 2 * np.arcsin(np.sin(2 * np.pi * frequency * self.t)) / np.pi
        elif wave_type == 'saw':
            wave = 2 * (frequency * self.t - np.floor(0.5 + frequency * self.t))
        elif wave_type == 'square':
            wave = np.sign(np.sin(2 * np.pi * frequency * self.t))
        else:
            wave = np.zeros_like(self.t)
        
        return wave * volume
    
    def mix_waves(self, oscillators):
        """Mix multiple oscillators together with ADSR envelopes"""
        mixed_wave = np.zeros_like(self.t)
        active_count = 0
        
        for i, osc in enumerate(oscillators):
            if osc['enabled']:
                active_count += 1
                # Generate base waveform
                wave = self.generate_wave(
                    osc['frequency'], 
                    osc['wave_type'], 
                    osc['volume']
                )
                
                # Apply ADSR envelope if provided
                if 'adsr' in osc:
                    adsr = osc['adsr']
                    envelope = self.generate_adsr_envelope(
                        adsr['attack'],
                        adsr['decay'], 
                        adsr['sustain'],
                        adsr['release']
                    )
                    # Ensure envelope and wave have same length
                    min_length = min(len(wave), len(envelope))
                    wave = wave[:min_length] * envelope[:min_length]
                
                mixed_wave[:len(wave)] += wave
        
        # Debug info removed for performance
        
        # Normalize to prevent clipping - use soft limiting for better accuracy
        max_amplitude = np.max(np.abs(mixed_wave))
        if max_amplitude > 0:
            if max_amplitude > 1.0:
                # Apply soft limiting to preserve waveform shape
                mixed_wave = mixed_wave / max_amplitude * 0.95  # Slight headroom
            else:
                # If already within bounds, keep original amplitudes for accuracy
                mixed_wave = mixed_wave
        
        return mixed_wave
    
    def generate_adsr_envelope(self, attack, decay, sustain, release):
        """Generate ADSR envelope for the given duration
        
        Args:
            attack: Attack time in seconds
            decay: Decay time in seconds  
            sustain: Sustain time in seconds (changed from amplitude level)
            release: Release time in seconds
        """
        total_duration = self.duration
        total_samples = int(total_duration * self.sample_rate)
        
        # Convert time values to samples
        attack_samples = int(max(0.01, attack) * self.sample_rate)  # Minimum 0.01s attack
        decay_samples = int(decay * self.sample_rate)
        sustain_samples = int(sustain * self.sample_rate)  # Now sustain is time-based
        release_samples = int(release * self.sample_rate)
        
        # For very short durations, ensure minimum viable envelope
        if total_samples < 100:  # Less than ~2ms at 44kHz
            # Use simplified envelope for very short durations
            envelope = np.ones(total_samples) * 0.7  # Fixed sustain level
            return envelope
        
        # Ensure ADSR phases don't exceed total duration
        adsr_total = attack_samples + decay_samples + sustain_samples + release_samples
        if adsr_total > total_samples:
            # Scale down proportionally if phases are too long
            scale_factor = total_samples / adsr_total
            attack_samples = max(1, int(attack_samples * scale_factor))
            decay_samples = max(1, int(decay_samples * scale_factor))
            sustain_samples = max(1, int(sustain_samples * scale_factor))
            release_samples = max(1, int(release_samples * scale_factor))
        
        # Fixed sustain amplitude level (instead of using sustain as amplitude)
        sustain_level = 0.7  # 70% amplitude for sustain phase
        
        envelope = np.zeros(total_samples)
        current_idx = 0
        
        # Attack phase: 0 to 1
        if attack_samples > 0 and current_idx < len(envelope):
            end_idx = min(current_idx + attack_samples, len(envelope))
            if end_idx > current_idx:
                num_samples = end_idx - current_idx
                if num_samples > 0:
                    envelope[current_idx:end_idx] = np.linspace(0, 1, num_samples)
            current_idx = end_idx
        else:
            # If no attack phase, start at full amplitude
            if current_idx < len(envelope):
                envelope[current_idx] = 1
        
        # Decay phase: 1 to sustain level
        if decay_samples > 0 and current_idx < len(envelope):
            end_idx = min(current_idx + decay_samples, len(envelope))
            if end_idx > current_idx:
                num_samples = end_idx - current_idx
                if num_samples > 0:
                    envelope[current_idx:end_idx] = np.linspace(1, sustain_level, num_samples)
            current_idx = end_idx
        else:
            # If no decay phase, jump directly to sustain level
            if current_idx < len(envelope):
                envelope[current_idx] = sustain_level
        
        # Sustain phase: hold at sustain level
        if sustain_samples > 0 and current_idx < len(envelope):
            end_idx = min(current_idx + sustain_samples, len(envelope))
            if end_idx > current_idx:
                envelope[current_idx:end_idx] = sustain_level
            current_idx = end_idx
        
        # Release phase: sustain level to 0
        if release_samples > 0 and current_idx < len(envelope):
            remaining_samples = len(envelope) - current_idx
            actual_release_samples = min(release_samples, remaining_samples)
            if actual_release_samples > 0:
                envelope[current_idx:current_idx + actual_release_samples] = np.linspace(sustain_level, 0, actual_release_samples)
        
        return envelope
    
# Global synthesizer instance
synth = AudioSynthesizer(duration=2.0)  # Maximum 2 seconds duration

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/synthesize', methods=['POST'])
def synthesize():
    data = request.json
    oscillators = data.get('oscillators', [])
    
    # Generate mixed wave
    mixed_wave = synth.mix_waves(oscillators)
    
    response_data = {
        'success': True,
        'mode': 'standard',
        'duration': synth.duration,
        'timing_info': {
            'total_duration_seconds': synth.duration,
            'total_duration_milliseconds': synth.duration * 1000,
            'sample_rate_hz': synth.sample_rate
        }
    }
    
    return jsonify(response_data)

if __name__ == '__main__':
    # Allow network access from other devices
    # host='0.0.0.0' allows connections from any IP address
    # port=5001 to avoid conflicts with other services
    print("🎵 Starting Enhanced Audio Frequency Mixing Deck Server...")
    print("📡 Network access enabled!")
    print("🌐 Access locally at: http://localhost:5001")
    print("🌐 Access from network at: http://[YOUR_IP]:5001")
    print("💡 Enhanced features: Extended frequency range (5Hz-21kHz), Real-time synthesis!")
    app.run(debug=True, host='0.0.0.0', port=5001)
