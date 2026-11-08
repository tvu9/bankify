"""Extract newly spoken words from successive overlapping Whisper windows.

Keeps bounded, in-memory transcript context; never persists text.
"""
import re


def words(text):
    return re.findall(r"\b[\w']+\b", text.casefold())


class TranscriptDelta:
    def __init__(self):
        self.previous = []
        self.tail = []
        self.silent = False

    def reset(self):
        self.previous = []
        self.tail = []
        self.silent = False

    def mark_silence(self):
        # A new utterance after a quiet interval may legitimately repeat words.
        self.silent = True

    def consume(self, transcript):
        parts = transcript.split()
        normalized = words(transcript)
        if not normalized:
            return ''
        if self.silent:
            self.previous = []
            self.tail = []
            self.silent = False
        if normalized == self.previous or self._contained(normalized):
            return ''
        overlap = 0
        for size in range(min(len(self.previous),len(normalized)), 0, -1):
            if self.previous[-size:] == normalized[:size]:
                overlap = size
                break
        # If a window becomes shorter (no new speech), don't re-log its tail.
        if overlap == len(normalized):
            return ''
        # The normal output has punctuation attached to space-delimited tokens.
        # If tokenization differs, prefer the full text over silently discarding it.
        if len(parts) != len(normalized):
            fresh = transcript.strip() if overlap == 0 else ' '.join(parts[overlap:])
        else:
            fresh = ' '.join(parts[overlap:])
        if not fresh.strip():
            return ''
        old_tail = self.tail
        self.previous = normalized[-160:]
        self.tail = normalized[-4:]
        self._context_before = old_tail
        return fresh

    def _contained(self, normalized):
        if len(normalized) > len(self.previous):
            return False
        return any(self.previous[i:i+len(normalized)] == normalized
                   for i in range(len(self.previous)-len(normalized)+1))

    def context_text(self, novel):
        before = getattr(self, '_context_before', [])
        return ' '.join(before[-3:] + [novel])
