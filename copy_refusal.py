"""FIX-P2-09-06: typed refusals of the protected copy (no imports).

``CopyRefusal`` is a ``ValueError`` with a ``kind``. Code that already does
``except ValueError`` keeps working, and the message text stays exactly the
one raised before. The copy screen (``real_copy_flow._reason``) reads the
``kind`` to pick its short reason instead of searching pieces of the text;
an error without a known ``kind`` still goes through the old text search.

This module imports nothing from the project, so the executor and the
modules it calls (selective_recovery, multi_source_recheck) can all import
it without an import cycle.
"""
from __future__ import annotations

KIND_CONFIRM = 'confirmacao'   # the person's confirmation is missing or stale
KIND_DISKS = 'discos'          # destinations not proven on another disk
KIND_UNIDADE = 'unidade'       # destination missing, not a folder, or on C:
KIND_RAIZ = 'raiz'             # source or destination is a drive root
KIND_LINK = 'link'             # a link or junction in the path
KIND_SOBREPOR = 'sobrepor'     # destination inside the source or vice versa
KIND_MUDOU = 'mudou'           # something changed since the preview

KINDS = (KIND_CONFIRM, KIND_DISKS, KIND_UNIDADE, KIND_RAIZ, KIND_LINK,
         KIND_SOBREPOR, KIND_MUDOU)


class CopyRefusal(ValueError):
    """A refusal of a check, with a ``kind`` (one of ``KINDS``)."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind
