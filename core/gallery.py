"""An immutable, job-local gallery: editing live registrations cannot change a job."""
import hashlib
import numpy as np
from config import LIVE_MATCH_THRESHOLD, LIVE_MATCH_MARGIN


class GallerySnapshot:
    def __init__(self, rows, threshold=LIVE_MATCH_THRESHOLD, margin=LIVE_MATCH_MARGIN):
        self.threshold, self.margin = float(threshold), float(margin)
        metadata, vectors = [], []
        for pid, name, enabled, vector in rows:
            vector = np.asarray(vector, dtype=np.float32)
            if vector.ndim != 1 or not np.all(np.isfinite(vector)):
                continue
            norm = np.linalg.norm(vector)
            if norm <= 1e-6:
                continue
            metadata.append((int(pid), str(name), bool(enabled)))
            vectors.append(vector / norm)
        self.metadata = tuple(metadata)
        self.matrix = np.stack(vectors) if vectors else np.empty((0, 512), dtype=np.float32)
        self.matrix.setflags(write=False)

    @property
    def watchlist(self):
        people = {}
        for pid, name, enabled in self.metadata:
            if enabled:
                entry = people.setdefault(pid, {'id': pid, 'name': name, 'sample_count': 0})
                entry['sample_count'] += 1
        return list(people.values())

    def audit(self):
        return {'watchlist': self.watchlist, 'gallery_sha256': hashlib.sha256(
            repr(self.metadata).encode('utf-8') + self.matrix.tobytes()).hexdigest(),
            'match_threshold': self.threshold, 'match_margin': self.margin}

    def match(self, embedding):
        if embedding is None or not len(self.metadata):
            return None, 'Unknown', 0.0
        vector = np.asarray(embedding)
        norm = np.linalg.norm(vector)
        if not np.all(np.isfinite(vector)) or norm < 1e-6:
            return None, 'Unknown', 0.0
        people = {}
        for (pid, name, enabled), score in zip(self.metadata, self.matrix @ (vector/norm)):
            if pid not in people or score > people[pid][0]:
                people[pid] = (float(score), name, enabled)
        ranked = sorted(people.items(), key=lambda item: item[1][0], reverse=True)
        pid, (score, name, enabled) = ranked[0]
        second = ranked[1][1][0] if len(ranked) > 1 else -1.0
        if enabled and score >= self.threshold and score-second >= self.margin:
            return pid, name, score
        return None, 'Unknown', score
