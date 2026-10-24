import logging, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from rdp.infra.logging import LogTime, LoggingSettings, configure_logging
from rdp.infra.config import LogConfig
logs = Path(sys.argv[1])
(logs / "web.log.2026-01-01").write_text("old\n")
now = [datetime(2026, 10, 23, 12, tzinfo=timezone.utc)]
tz = timezone(timedelta(hours=8))
lt = LogTime(now=lambda: now[0], timezone=lambda: tz)
real_unlink = Path.unlink
def bad_unlink(self, *a, **k):
    if self.name.startswith("web.log."):
        raise PermissionError(13, "denied", str(self))
    return real_unlink(self, *a, **k)
with patch.object(Path, "unlink", bad_unlink):
    configure_logging(LoggingSettings("web", logs, False, LogConfig()), time_source=lt)
    log = logging.getLogger("probe")
    for i in range(3):
        log.info("第 %d 条", i)
    now[0] += timedelta(days=1)
    for i in range(3, 6):
        log.info("第 %d 条", i)
for h in logging.getLogger().handlers: h.flush()
print(sorted(p.name for p in logs.iterdir()))
print(repr((logs / "web.log").read_text() if (logs/"web.log").exists() else None))
