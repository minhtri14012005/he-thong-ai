"""Conservative live identity confirmation. Only fresh observations can confirm."""
from collections import deque
import numpy as np
from config import (LIVE_CONFIRM_HITS, LIVE_CONFIRM_WINDOW, LIVE_CONFIRM_SECONDS,
                    LIVE_TRACK_TTL)
from core.tracker import compute_iou


class LiveTracker:
    def __init__(self):
        self.tracks = []
        self.next_id = 1

    def update(self, detections, now):
        self.tracks = [t for t in self.tracks if now - t['seen'] <= LIVE_TRACK_TTL]
        pairs = []
        for ti, track in enumerate(self.tracks):
            for di, det in enumerate(detections):
                overlap = compute_iou(track['bbox'], det['bbox'])
                predicted = np.array(track['bbox']) + track.get('velocity', np.zeros(4)) * min(now-track['seen'], 0.5)
                overlap = max(overlap, compute_iou(predicted, det['bbox']))
                old, new = track.get('embedding'), det.get('embedding')
                similarity = None
                if old is not None and new is not None:
                    similarity = float(np.dot(old, new) / max(1e-8, np.linalg.norm(old) * np.linalg.norm(new)))
                    if similarity < 0.25:
                        continue
                # Identity conflict starts a new track, never inherits old votes.
                if (track.get('candidate_id') is not None and det.get('person_id') is not None
                        and track['candidate_id'] != det['person_id']):
                    continue
                if overlap >= 0.15:
                    pairs.append((overlap + max(0, similarity or 0), ti, di))
        used_t, used_d = set(), set()
        assignments = {}
        for _, ti, di in sorted(pairs, reverse=True):
            if ti not in used_t and di not in used_d:
                assignments[di] = self.tracks[ti]
                used_t.add(ti)
                used_d.add(di)

        results = []
        for di, det in enumerate(detections):
            track = assignments.get(di)
            if track is None:
                track = {'id': self.next_id, 'votes': deque(maxlen=LIVE_CONFIRM_WINDOW),
                         'seen': now, 'first_seen': now}
                self.next_id += 1
                self.tracks.append(track)
            # After any missed observation, all remaining votes still expire by time.
            track['votes'] = deque((v for v in track['votes'] if now - v[0] <= LIVE_CONFIRM_SECONDS),
                                   maxlen=LIVE_CONFIRM_WINDOW)
            person_id = det.get('person_id') if det.get('quality_ok') else None
            track['votes'].append((now, person_id))
            if 'bbox' in track and now > track['seen']:
                velocity = (np.array(det['bbox']) - np.array(track['bbox'])) / (now-track['seen'])
                track['velocity'] = 0.5 * track.get('velocity', velocity) + 0.5 * velocity
            track.update(bbox=det['bbox'], seen=now)
            if det.get('embedding') is not None:
                track['embedding'] = det['embedding']
            if person_id is not None:
                track['candidate_id'] = person_id
            confirmed = person_id is not None and sum(v[1] == person_id for v in track['votes']) >= LIVE_CONFIRM_HITS
            result = {k: v for k, v in det.items() if k != 'embedding'}
            result.update(track_id=track['id'], confirmed=confirmed,
                          first_seen_mono=track['first_seen'],
                          state='confirmed' if confirmed else ('pending' if person_id is not None else 'unknown'))
            # Never emit a confirmed identity on an Unknown or low quality observation.
            if not confirmed:
                result['name'] = 'Unknown'
            track['display'] = result
            results.append(result)
        for track in self.tracks:
            if track['seen'] != now and 'display' in track:
                results.append({**track['display'], 'confirmed': False, 'state': 'lost'})
        return results
