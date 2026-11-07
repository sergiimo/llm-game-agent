"""Pure save-profile selection and pinned-lineage validation."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SaveCandidate:
    profile_key: str
    path: str
    file_id: str
    digest: str
    save_count: int
    game_time: int
    scene: str
    decoded: dict
    mtime: float = 0.0


@dataclass(frozen=True)
class LogEpoch:
    file_id: str
    first_time: int
    last_time: int
    lines: tuple = ()
    previous_id: str = None
    scene: str = None


class LineageMismatch(ValueError):
    def __init__(self, reason, **details):
        self.reason, self.details = reason, details
        super().__init__(reason)


def _coherent(candidate, log_epoch, tolerance=6 * 3600):
    if candidate.game_time is None or log_epoch.last_time is None:
        return False
    if log_epoch.scene and candidate.scene and log_epoch.scene != candidate.scene:
        return False
    return abs(candidate.game_time - log_epoch.last_time) <= tolerance


def monotonic_log_times(stamps):
    """Normalize the pre-day-change midnight wrap while preserving explicit next-day stamps."""
    out = []
    for raw in stamps:
        value = raw
        if out:
            while value + 12 * 3600 < out[-1]:
                value += 86400
        out.append(value)
    return out


def _continuous(log_epoch, previous_log):
    return bool(previous_log and (
        log_epoch.file_id == previous_log.file_id or
        log_epoch.previous_id == previous_log.file_id or
        log_epoch.first_time is not None and previous_log.last_time is not None and
        log_epoch.first_time >= previous_log.last_time))


def _forward_log_bridge(candidate, log_epoch, previous_log):
    """A pinned stale save is usable when its own uninterrupted log proves forward progression."""
    if (not _continuous(log_epoch, previous_log) or candidate.game_time is None or
            log_epoch.last_time is None or previous_log.last_time is None or
            candidate.game_time > log_epoch.last_time or log_epoch.last_time < previous_log.last_time):
        return False
    if abs(candidate.game_time - log_epoch.last_time) <= 6 * 3600:
        return True
    return any(marker in line for line in log_epoch.lines for marker in
               ('[TRIGGER] AdvanceDay', '[TIME] Day ', '[GAME] ChangeScene '))


def select_profile(candidates, log_epoch):
    """Select one coherent profile, allowing slot rotation only inside that profile."""
    coherent = [candidate for candidate in candidates if _coherent(candidate, log_epoch)]
    profiles = {candidate.profile_key for candidate in coherent}
    if not coherent:
        raise LineageMismatch('no_coherent_profile', log_epoch=log_epoch.file_id)
    if len(profiles) != 1:
        raise LineageMismatch('ambiguous_profiles', profiles=sorted(profiles))
    return max(coherent, key=lambda candidate: (candidate.game_time, candidate.save_count, candidate.file_id))


def validate_pinned(candidate, log_epoch, profile_key, previous=None, previous_log=None):
    """Validate a later slot/log read against a pinned profile and monotonic timeline."""
    if candidate.profile_key != profile_key:
        raise LineageMismatch('profile_changed', pinned=profile_key, observed=candidate.profile_key)
    if not _coherent(candidate, log_epoch) and not _forward_log_bridge(candidate, log_epoch, previous_log):
        raise LineageMismatch('save_log_timeline_conflict', save_time=candidate.game_time,
                              log_time=log_epoch.last_time)
    if previous:
        if candidate.save_count < previous.save_count:
            raise LineageMismatch('save_count_reversed', previous=previous.save_count,
                                  observed=candidate.save_count)
        if candidate.game_time < previous.game_time:
            raise LineageMismatch('game_time_reversed', previous=previous.game_time,
                                  observed=candidate.game_time)
    if previous_log:
        continuous = _continuous(log_epoch, previous_log)
        if not continuous or log_epoch.last_time < previous_log.last_time:
            raise LineageMismatch('log_epoch_conflict', previous=previous_log.file_id,
                                  observed=log_epoch.file_id)
    return candidate
