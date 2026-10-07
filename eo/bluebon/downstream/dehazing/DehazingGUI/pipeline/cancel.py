"""파이프라인 취소 신호."""


class CancelledError(Exception):
    """사용자가 처리 중지를 요청했을 때 발생."""


def check(cancel_check):
    """cancel_check() 가 True 면 CancelledError 발생.

    cancel_check 는 callable() -> bool 또는 None.
    """
    if cancel_check is not None and cancel_check():
        raise CancelledError('사용자가 처리를 중지했습니다')
