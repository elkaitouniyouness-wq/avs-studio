import threading

from .config import get_settings

QUEUE = "avs"


class QueueError(Exception):
    pass


def enqueue(func_path: str, *args):
    """Envoie une tâche au worker RQ. Mode inline (INLINE_JOBS=true) réservé au développement/tests."""
    s = get_settings()
    if s.inline_jobs:
        import importlib

        mod, fn = func_path.rsplit(".", 1)
        f = getattr(importlib.import_module(mod), fn)
        t = threading.Thread(target=f, args=args, daemon=True)
        t.start()
        return t
    try:
        import redis
        from rq import Queue, Retry

        q = Queue(QUEUE, connection=redis.from_url(s.redis_url))
        return q.enqueue(func_path, *args, job_timeout=3600, result_ttl=3600)
    except Exception as e:  # noqa: BLE001
        raise QueueError(f"File de tâches indisponible (Redis): {e}") from e
