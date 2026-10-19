"""Receive private row controls while the model's main thread generates."""
import json
import queue
import threading


class ModelInbox:
    def __init__(self, stream):
        self.messages = queue.Queue()
        self.controls = {}
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._read, args=(stream,), daemon=True, name='model-controls')
        self.thread.start()

    def _read(self, stream):
        try:
            for line in stream:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError('INVALID_MODEL_PROTOCOL')
                with self.lock:
                    if value.get('op') == 'cancel_rows':
                        events = self.controls.get(value.get('target_id'), {})
                        for row_id in value.get('row_ids', []):
                            if row_id in events:
                                events[row_id].set()
                        continue
                    events = {}
                    if value.get('op') == 'recognize_batch':
                        rows = value.get('rows')
                        if (not isinstance(rows, list) or not 1 <= len(rows) <= 2
                                or any(not isinstance(row, dict) or not isinstance(row.get('row_id'), str) for row in rows)
                                or len({row['row_id'] for row in rows}) != len(rows)):
                            raise ValueError('INVALID_BATCH_PROTOCOL')
                        events = {row['row_id']: threading.Event() for row in rows}
                        self.controls[value['id']] = events
                self.messages.put((value, events))
        except (ValueError, TypeError, KeyError):
            self.messages.put(({'protocol_error': True}, {}))
        finally:
            with self.lock:
                for events in self.controls.values():
                    for event in events.values():
                        event.set()
            self.messages.put(None)

    def finish(self, identity):
        with self.lock:
            self.controls.pop(identity, None)
