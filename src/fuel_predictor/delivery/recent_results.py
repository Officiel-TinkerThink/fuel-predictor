"""The result of an upload, kept a while so its page can be reloaded.

An upload's result used to be the answer to the POST that sent the file, so
refreshing it - on a phone, or reopening the tab - sent the file again: a
bulk plan planned every row a second time. The upload now answers with a
redirect to its result, which this store keeps in memory for an hour; the
same file sent again by the same person within minutes is taken for that
refresh or a double tap, and leads to the result it already has.

In memory on purpose: a result is only a view of what the upload already
stored (operations, actual fuel), each reachable from its own page; losing
the view on a restart loses nothing, and the page then says where to look.
"""

import hashlib
import secrets
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import TYPE_CHECKING

from fastapi import status
from fastapi.responses import HTMLResponse

from fuel_predictor.delivery.rendering import render

if TYPE_CHECKING:
    from fuel_predictor.application.identity import ActiveCaller


@dataclass(frozen=True, slots=True)
class KeptResult[T]:
    token: str
    owner: str
    digest: str
    filename: str
    result: T
    kept_at: datetime


class RecentResults[T]:
    def __init__(
        self,
        *,
        keep_for: timedelta = timedelta(hours=1),
        same_file_within: timedelta = timedelta(minutes=15),
        limit: int = 50,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._keep_for = keep_for
        self._same_file_within = same_file_within
        self._limit = limit
        self._now = now
        self._kept: OrderedDict[str, KeptResult[T]] = OrderedDict()
        self._lock = Lock()

    @staticmethod
    def digest(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def keep(self, owner: str, digest: str, filename: str, result: T) -> KeptResult[T]:
        kept = KeptResult(
            token=secrets.token_urlsafe(12),
            owner=owner,
            digest=digest,
            filename=filename,
            result=result,
            kept_at=self._now(),
        )
        with self._lock:
            self._forget_old()
            self._kept[kept.token] = kept
            while len(self._kept) > self._limit:
                self._kept.popitem(last=False)
        return kept

    def get(self, token: str, owner: str) -> KeptResult[T] | None:
        """The result, for the person whose upload it was only."""
        with self._lock:
            self._forget_old()
            kept = self._kept.get(token)
        return kept if kept is not None and kept.owner == owner else None

    def same_file(self, owner: str, digest: str) -> KeptResult[T] | None:
        """This person's result for these exact bytes, if sent moments ago."""
        since = self._now() - self._same_file_within
        with self._lock:
            self._forget_old()
            for kept in reversed(self._kept.values()):
                if kept.owner == owner and kept.digest == digest and kept.kept_at >= since:
                    return kept
        return None

    def _forget_old(self) -> None:
        cutoff = self._now() - self._keep_for
        for token in [token for token, kept in self._kept.items() if kept.kept_at < cutoff]:
            del self._kept[token]


def result_gone(
    caller: "ActiveCaller", upload_href: str, upload_label: str, where_saved: str
) -> HTMLResponse:
    """A result no longer kept: what the upload saved is still saved."""
    return HTMLResponse(
        render(
            "pesan.html",
            caller=caller,
            page_title="Hasil unggahan tidak lagi tersedia",
            active_path=upload_href,
            message=(
                "Hasil sebuah unggahan hanya disimpan sebentar, dan yang ini sudah tidak "
                f"tersedia. Yang tersimpan tetap tersimpan: {where_saved}"
            ),
            back_href=upload_href,
            back_label=f"Kembali ke {upload_label}",
        ),
        status_code=status.HTTP_404_NOT_FOUND,
    )
