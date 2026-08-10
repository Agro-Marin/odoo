import logging
import queue
import threading
import time
from collections.abc import Callable

_logger = logging.getLogger(__name__)

# Global queue instance (singleton per process)
_event_queue_instance: InboundEventQueue | None = None
_queue_lock = threading.RLock()


class InboundEventQueue:
    """Thread-safe async event-processing queue (one instance per Odoo worker)."""

    def __init__(self, worker_count: int = 4, max_queue_size: int = 5000):
        """Initialize the event queue.

        :param worker_count: number of worker threads (default 4)
        :param max_queue_size: maximum queue size (default 5000)
        """
        self.worker_count = worker_count
        self.max_queue_size = max_queue_size
        self._queue = queue.Queue(maxsize=max_queue_size)
        self._workers = []
        self._shutdown_event = threading.Event()
        self._stats = {
            "total_enqueued": 0,
            "total_processed": 0,
            "total_failed": 0,
            "queue_full_count": 0,
        }
        self._stats_lock = threading.Lock()
        self._start_workers()

        _logger.info(
            "InboundEventQueue initialized: %d workers, max %d events",
            worker_count,
            max_queue_size,
        )

    def get_stats(self) -> dict:
        """Get queue statistics."""
        with self._stats_lock:
            return {
                **self._stats,
                "queue_size": self._queue.qsize(),
                "worker_count": self.worker_count,
                "is_shutdown": self._shutdown_event.is_set(),
            }

    def get_health_status(self) -> dict:
        """Get queue health status."""
        workers_alive = sum(1 for w in self._workers if w.is_alive())
        queue_size = self._queue.qsize()
        utilization = (
            (queue_size / self.max_queue_size) * 100 if self.max_queue_size > 0 else 0
        )

        is_healthy = (
            workers_alive == len(self._workers)
            and utilization < 80
            and not self._shutdown_event.is_set()
        )

        return {
            "healthy": is_healthy,
            "queue_size": queue_size,
            "max_queue_size": self.max_queue_size,
            "workers_alive": workers_alive,
            "workers_expected": self.worker_count,
            "utilization_percent": utilization,
            "active": not self._shutdown_event.is_set(),
        }

    def is_healthy(self) -> bool:
        """Check if queue is healthy."""
        return not self._shutdown_event.is_set() and all(
            w.is_alive() for w in self._workers
        )

    def queue(
        self,
        event_id: int,
        handler_callback: Callable[[int], None],
        db_name: str | None = None,
        uid: int | None = None,
    ) -> bool:
        """Add an event to the processing queue.

        :param event_id: ID of the event to process
        :param handler_callback: function to call with the event_id
        :param db_name: database name for ORM-safe execution (recommended)
        :param uid: user ID for the Environment (defaults to SUPERUSER_ID)
        :return: True if queued successfully
        :rtype: bool
        """
        # With db_name the worker creates a dedicated cursor + Environment before
        # calling the handler (handler just receives event_id). Without it (legacy
        # callers) the handler is called directly and manages its own cursor (see
        # api_webhook.models.webhook_subscription).
        if self._shutdown_event.is_set():
            _logger.warning("Queue shutting down - cannot queue event %d", event_id)
            return False

        try:
            self._queue.put(
                (event_id, handler_callback, db_name, uid),
                block=False,
            )

            with self._stats_lock:
                self._stats["total_enqueued"] += 1

            return True

        except queue.Full:
            _logger.error("Event queue full - cannot enqueue event %d", event_id)
            with self._stats_lock:
                self._stats["queue_full_count"] += 1
            return False

    def reset_stats(self):
        """Reset statistics counters."""
        with self._stats_lock:
            self._stats = {
                "total_enqueued": 0,
                "total_processed": 0,
                "total_failed": 0,
                "queue_full_count": 0,
            }

    def shutdown(self, timeout: int = 30):
        """Gracefully shutdown queue."""
        _logger.info("Shutting down InboundEventQueue...")
        self._shutdown_event.set()

        for _ in range(timeout):
            if self._queue.empty():
                break
            time.sleep(1)

        for worker in self._workers:
            worker.join(timeout=5)

        _logger.info("InboundEventQueue shutdown complete")

    def _start_workers(self):
        """Start worker threads."""
        for i in range(self.worker_count):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"CommEventWorker-{i + 1}",
                daemon=True,
            )
            worker.start()
            self._workers.append(worker)

    def _worker_loop(self):
        """Dequeue and process events until shutdown."""
        # When db_name was provided at enqueue time, the handler runs inside a
        # dedicated cursor committed on success / rolled back on failure — no
        # ORM state leaks between events.
        worker_name = threading.current_thread().name

        while not self._shutdown_event.is_set():
            try:
                try:
                    event_id, handler_callback, db_name, uid = self._queue.get(
                        timeout=1.0,
                    )
                except queue.Empty:
                    continue

                try:
                    start_time = time.time()

                    if db_name:
                        self._run_with_cursor(
                            event_id,
                            handler_callback,
                            db_name,
                            uid,
                        )
                    else:
                        handler_callback(event_id)

                    duration = time.time() - start_time

                    _logger.debug(
                        "%s processed event %d in %.2fs",
                        worker_name,
                        event_id,
                        duration,
                    )

                    with self._stats_lock:
                        self._stats["total_processed"] += 1

                except Exception:
                    _logger.exception(
                        "%s error processing event %d",
                        worker_name,
                        event_id,
                    )
                    with self._stats_lock:
                        self._stats["total_failed"] += 1

                finally:
                    self._queue.task_done()

            except Exception:
                _logger.exception("%s unexpected error", worker_name)
                time.sleep(1)

    @staticmethod
    def _run_with_cursor(
        event_id: int,
        handler_callback: Callable[[int], None],
        db_name: str,
        uid: int | None,
    ):
        """Execute the handler inside a dedicated cursor + Environment.

        :param event_id: ID of the event to process
        :param handler_callback: function to call with the event_id
        :param db_name: database name
        :param uid: user ID (defaults to SUPERUSER_ID)
        """
        # Builds a fresh cursor + Environment, reloads the event's channel and
        # delegates to _process_queued_event. If the handler already manages its
        # own cursor (e.g. api_webhook) the outer cursor is harmless. On failure
        # the cursor context manager rolls back automatically.
        from .worker import worker_env

        with worker_env(db_name, uid) as env:
            # Make the env available via the event log for handlers that
            # need ORM access but don't create their own cursor.
            event = env["api.event.log"].browse(event_id)
            if event.exists() and event.channel_id:
                channel = event.channel_id
                if hasattr(channel, "_process_queued_event"):
                    channel._process_queued_event(event)
                    return

            # Fallback: call the raw callback (for handlers that
            # manage their own cursor, like api_webhook).
            handler_callback(event_id)


def get_event_queue(
    worker_count: int = 4, max_queue_size: int = 5000
) -> InboundEventQueue:
    """Get or create the global event-queue instance for this worker process.

    :param worker_count: number of worker threads (only used on first call)
    :param max_queue_size: max queue size (only used on first call)
    :return: the queue instance for this worker process
    :rtype: InboundEventQueue
    """
    global _event_queue_instance  # noqa: PLW0603  -- module-level singleton for the worker process

    with _queue_lock:
        if _event_queue_instance is None:
            _event_queue_instance = InboundEventQueue(
                worker_count=worker_count,
                max_queue_size=max_queue_size,
            )
        return _event_queue_instance


def shutdown_event_queue():
    """Shutdown and clear the global event queue instance."""
    global _event_queue_instance  # noqa: PLW0603  -- module-level singleton for the worker process

    with _queue_lock:
        if _event_queue_instance is not None:
            _event_queue_instance.shutdown()
            _event_queue_instance = None
            _logger.info("Global event queue cleared")
