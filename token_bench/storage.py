"""게시와 worker가 공유하는 플랫폼별 배타적 파일 잠금."""

import contextlib
import sys
from pathlib import Path

class FileLockError(RuntimeError):
    """같은 상태 저장소에 이미 다른 worker가 상주하고 있을 때 발생한다."""


# 파일 잠금 API가 POSIX(fcntl)와 Windows(msvcrt)로 갈린다. import 시점에
# 플랫폼별 모듈을 고르기만 하고, 잠그고 푸는 동작은 아래 두 함수로 감싸서
# worker_lock 본문은 플랫폼을 몰라도 되게 한다.
if sys.platform == "win32":
    import msvcrt

    def _lock_exclusive_nonblocking(fp) -> None:
        fp.seek(0)
        msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(fp) -> None:
        with contextlib.suppress(OSError):
            fp.seek(0)
            msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock_exclusive_nonblocking(fp) -> None:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fp) -> None:
        with contextlib.suppress(OSError):
            fcntl.flock(fp.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def file_lock(lock_path: Path):
    """구독 실행 worker가 같은 상태 저장소에 하나만 상주하도록 강제한다."""

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # msvcrt.locking은 파일에 바이트가 하나 이상 있어야 잠글 수 있다.
    if not lock_path.exists() or lock_path.stat().st_size == 0:
        lock_path.write_bytes(b"0")
    fp = open(lock_path, "r+b")
    try:
        try:
            _lock_exclusive_nonblocking(fp)
        except OSError as exc:
            raise FileLockError(
                f"이미 다른 프로세스가 '{lock_path}' 잠금을 사용 중이다."
            ) from exc
        yield
    finally:
        _unlock(fp)
        fp.close()
