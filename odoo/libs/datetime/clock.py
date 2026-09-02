import time
from datetime import datetime

__all__ = ["real_cpu_time", "real_datetime_now", "real_time"]

real_time = time.time
real_cpu_time = time.thread_time
real_datetime_now = datetime.now
