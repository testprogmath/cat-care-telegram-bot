"""What a diary text says about the toilet, vomiting, fluids under the skin, broth without pieces
and whether it is a recap of the day."""

import re

_RECAP_RE = re.compile(
    r"если считать|суммарно|в сумме|за день|за сутки|минимум\s+\d+\s*мл|всего\b.{0,30}\bпоступил",
    re.IGNORECASE,
)
_STOOL_RE = re.compile(
    r"покак|\bкака(?:л|ет|ть|ю)|какаш|дефекац|стул|диаре|диарре|понос|\bкал\b", re.IGNORECASE
)
_NO_RESULT_RE = re.compile(
    r"не получил|ничего не|не сделал|безуспеш|ни с чем|без результат|не смогл|не смог\b"
    r"|\bне (?:какал|какает|писал|писает)",
    re.IGNORECASE,
)
_ATTEMPT_RE = re.compile(r"пыта|попыт|пробует|пробовал|тужит|тужил|покопал", re.IGNORECASE)
_DONE_RE = re.compile(r"пописал|покакал|помочил|наделал|какашк|сходил\S* в (?:туалет|лоток|горшок)", re.IGNORECASE)
_MISSED_ENTRY_RE = re.compile(
    r"забыл\w*|не (?:за)?писал\w*|не отметил\w*|пропустил\w*|дописыва\w*|задним числом|vergeten|forgot",
    re.IGNORECASE,
)
_PIECES_RE = re.compile(
    r"кусоч|бульон|подлив|жидкост|смес|\bвс[её]\b|\bвесь\b|\bвсю\b|целиком|полностью|половин|немного|только",
    re.IGNORECASE,
)
_VOMIT_RE = re.compile(r"\bвырвало\b|\bрвот\w*|\bстошнил\w*|\bсрыгну\w*", re.IGNORECASE)
_NO_VOMIT_RE = re.compile(r"без рвоты|не вырвало|не стошнил\w*|рвоты (?:не было|нет)", re.IGNORECASE)
_INFUSION_RE = re.compile(r"ринг|под\s?кож|инфуз|капельн|внутривен|в/в|физраств", re.IGNORECASE)
_BROTH_ONLY_RE = re.compile(
    r"без\s+кусоч|только\s+(?:бульон|соус|подлив)|кусочков\s+не\s+было"
    r"|кусоч\w*\s+(?:\S+\s+)?(?:не\s+(?:ел|ест|съел|стал|трог|тронул)|оставил|оставлен)"
    r"|не\s+(?:ел\w*|трог\w*|тронул\w*)\s+кусоч",
    re.IGNORECASE,
)
_DRANK_BROTH_RE = re.compile(
    r"\b(?:вы|по|с)?(?:пил|лизал|лакал)\w*\s+(?:\S+\s+){0,3}?(?:бульон|соус|подлив)", re.IGNORECASE
)
_PIECES_WORD_RE = re.compile(r"кусоч", re.IGNORECASE)


def mentions_pieces(text: str) -> bool:
    """The message says something about the pieces of a soup or a pouch, or how much of it was eaten."""
    return bool(_PIECES_RE.search(text))


def says_entry_was_missed(text: str) -> bool:
    """The writer says an earlier event went unrecorded: "забыла написать", "не записали"."""
    return bool(_MISSED_ENTRY_RE.search(text))


def is_recap(text: str) -> bool:
    return bool(_RECAP_RE.search(text))


def is_infusion(description: str) -> bool:
    """Fluids put under the skin or into a vein, which the animal did not drink."""
    return bool(_INFUSION_RE.search(description or ""))


def is_broth_only(description: str) -> bool:
    """The broth, sauce or gravy of a pouch was taken and its pieces were left."""
    text = description or ""
    if _BROTH_ONLY_RE.search(text):
        return True
    return bool(_DRANK_BROTH_RE.search(text)) and not _PIECES_WORD_RE.search(text)


def is_stool(description: str) -> bool:
    return bool(_STOOL_RE.search(description or ""))


def is_failed_toilet(description: str) -> bool:
    """An attempt that produced nothing, or a note that the cat has not gone."""
    text = description or ""
    if _NO_RESULT_RE.search(text):
        return True
    return bool(_ATTEMPT_RE.search(text)) and not _DONE_RE.search(text)


def toilet_kind(description: str) -> str:
    if is_failed_toilet(description):
        return "failed"
    return "stool" if is_stool(description) else "urine"


def denies_vomiting(text: str | None) -> bool:
    return bool(_NO_VOMIT_RE.search(text or ""))


def reports_vomiting(text: str | None) -> bool:
    return bool(_VOMIT_RE.search(text or "")) and not denies_vomiting(text)
