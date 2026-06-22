from __future__ import annotations

import logging
import re
import string
import unicodedata

from pydantic import SecretStr

from app.config import get_settings

logger = logging.getLogger(__name__)

_SUMMARY_CONTEXT_CHARS = 4_000
_SUMMARY_INPUT_CHUNK_CHARS = 14_000
_TRANSCRIPT_CLEAN_CHUNK_CHARS = 12_000

_SYSTEM_TRANSCRIPT_CLEANER = (
    "You are a transcript cleaner. Fix garbled words, remove hallucinations and repetitions. "
    "Keep English words in English. Keep Urdu/Hindi words in Roman script. Do not translate. "
    "Just clean and format properly."
)

_SYSTEM_ACADEMIC_SUMMARIZER = (
    "You are an academic summarizer. Generate a comprehensive and detailed summary in English. "
    "Cover ALL main topics, concepts, and key points discussed in the lecture. The summary should be "
    "proportional to the lecture length. For longer lectures, provide 4-6 paragraphs. For shorter lectures, "
    "provide 2-3 paragraphs. Always end with clear Key Takeaways as bullet points."
)

# Same token repeated more than this many times in a row is treated as ASR hallucination (removed).
_MAX_CONSECUTIVE_SAME_WORD = 3
# Repeated n-gram (phrase) runs longer than this are removed.
_MAX_CONSECUTIVE_SAME_NGRAM = 3

_SYSTEM_SUMMARY = (
    "You write for QuickStudy LMS, an academic learning platform. "
    "Given a draft summary and optional lecture context, polish into formal academic English. "
    "Preserve structure: write only narrative paragraphs. Do not add a \"Key Takeaways\" section or bullet points; that is generated separately. "
    "Clearly state the lecture topic, main concepts, and practical takeaways. "
    "Do not add claims not supported by the draft; you may tighten wording and fix grammar. "
    "Remove redundancy and vague phrases. Output only the final polished summary."
)

# Common ASR bracket / parenthetical noise (conservative — avoid stripping useful parentheses).
_TAG_BRACKET = re.compile(
    r"\[\s*(?:music|musical|applause|laughter|noise|crosstalk|inaudible|unclear|foreign|silence|"
    r"background|beep|click)\s*[^\]]*\]",
    re.IGNORECASE,
)
_TAG_PARENS = re.compile(
    r"\(\s*(?:unclear|inaudible|unintelligible|crosstalk)[^)]*\)",
    re.IGNORECASE,
)
_MULTI_SPACE = re.compile(r"[ \t]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")
# Standalone filler tokens only (word boundaries).
_FILLER = re.compile(r"\b(?:um|uh|uhh|erm|umm|hmm)\b[,. ]*", re.IGNORECASE)


def _secret_value(secret: SecretStr | None) -> str | None:
    if secret is None:
        return None
    v = secret.get_secret_value().strip()
    return v or None


class MissingOpenAIKeyError(RuntimeError):
    """Raised when OPENAI_API_KEY is required but missing or empty."""


def _require_openai_key() -> str:
    key = _secret_value(get_settings().openai_api_key)
    if not key:
        raise MissingOpenAIKeyError(
            "OPENAI_API_KEY is not set. Add it to the project root .env file (e.g. OPENAI_API_KEY=sk-...) "
            "or export it in your environment, then restart the server."
        )
    return key


def heuristic_clean(text: str) -> str:
    """
    Deterministic cleanup: normalize Unicode, strip ASR noise tags, collapse whitespace, light filler removal.
    """

    if not text or not str(text).strip():
        return ""
    t = unicodedata.normalize("NFC", str(text).strip())
    t = _TAG_BRACKET.sub(" ", t)
    t = _TAG_PARENS.sub(" ", t)
    t = _FILLER.sub(" ", t)
    t = _MULTI_SPACE.sub(" ", t)
    t = _MULTI_NEWLINE.sub("\n\n", t)
    return t.strip()


def _norm_token_key(token: str) -> str:
    """Normalize for duplicate detection (Latin case-fold; strip outer punctuation)."""

    s = token.strip()
    if not s:
        return ""
    core = s.strip(string.punctuation + "।،؟؛…‧·・")
    if not core:
        return ""
    if core.isascii():
        return core.lower()
    return core


_VOWELS_LATIN = frozenset("aeiouAEIOU")


def _ascii_word_is_gibberish(token: str) -> bool:
    """Long Latin-alphabet tokens with no vowels are often ASR noise (conservative length floor)."""

    letters = [c for c in token if c.isalpha() and c.isascii()]
    if len(letters) < 7:
        return False
    return not any(c in _VOWELS_LATIN for c in letters)


# Repeated single character (e.g. "aaaaa") or keyboard mashing
_GIBBER_CHAR_RUN = re.compile(r"(.)\1{6,}", re.UNICODE)
# Mostly non-letter noise tokens (isolated)
_GIBBER_NONWORD = re.compile(r"\b[^\w\s]{4,}\b", re.UNICODE)


def remove_excessive_word_repeats(text: str, *, max_run: int = _MAX_CONSECUTIVE_SAME_WORD) -> str:
    """
    Drop runs where the same token (normalized) appears more than max_run times consecutively.
    Keeps up to max_run occurrences; removes the entire run when longer (hallucination).
    """

    if not text.strip():
        return text
    words = text.split()
    if not words:
        return text
    out: list[str] = []
    i = 0
    while i < len(words):
        j = i + 1
        key = _norm_token_key(words[i])
        while j < len(words) and _norm_token_key(words[j]) == key and key != "":
            j += 1
        run = j - i
        if run > max_run:
            i = j
            continue
        out.extend(words[i:j])
        i = j
    return " ".join(out)


def remove_excessive_ngram_repeats(
    text: str,
    *,
    n: int = 2,
    max_run: int = _MAX_CONSECUTIVE_SAME_NGRAM,
) -> str:
    """Remove consecutive repeats of the same n-word phrase when repeated more than max_run times."""

    words = text.split()
    if len(words) < n * (max_run + 1):
        return text
    out: list[str] = []
    i = 0
    while i <= len(words) - n:
        gram = tuple(_norm_token_key(words[i + k]) for k in range(n))
        if any(not g for g in gram):
            out.append(words[i])
            i += 1
            continue
        j = i
        count = 0
        while j + n <= len(words) and tuple(_norm_token_key(words[j + k]) for k in range(n)) == gram:
            count += 1
            j += n
        if count > max_run:
            i = j
        else:
            out.extend(words[i:j])
            i = j
    out.extend(words[i:])
    return " ".join(out)


def strip_gibberish_patterns(text: str) -> str:
    """Remove obvious character-level gibberish and very suspicious ASCII tokens."""

    if not text:
        return text
    t = _GIBBER_CHAR_RUN.sub(" ", text)
    t = _GIBBER_NONWORD.sub(" ", t)
    words = t.split()
    kept: list[str] = []
    for w in words:
        if _ascii_word_is_gibberish(w):
            continue
        kept.append(w)
    return " ".join(kept)


def clean_mixed_language_transcript(raw: str) -> str:
    """
    Clean transcript without language conversion: formatting, ASR tags, hallucination loops, gibberish.
    Preserves English + Roman Urdu / Hindi / code-mixed text as produced by Whisper.
    """

    t = heuristic_clean(raw)
    if not t:
        return ""
    paragraphs: list[str] = []
    for block in t.split("\n\n"):
        b = block.strip()
        if not b:
            continue
        b = remove_excessive_word_repeats(b, max_run=_MAX_CONSECUTIVE_SAME_WORD)
        b = remove_excessive_ngram_repeats(b, n=2, max_run=_MAX_CONSECUTIVE_SAME_NGRAM)
        b = remove_excessive_ngram_repeats(b, n=3, max_run=_MAX_CONSECUTIVE_SAME_NGRAM)
        b = strip_gibberish_patterns(b)
        b = _MULTI_SPACE.sub(" ", b).strip()
        if b:
            paragraphs.append(b)
    result = "\n\n".join(paragraphs)
    return _MULTI_NEWLINE.sub("\n\n", result).strip()


def _chunk_transcript_for_gpt(text: str, max_chars: int) -> list[str]:
    t = text.strip()
    if not t:
        return []
    if len(t) <= max_chars:
        return [t]

    blocks = t.split("\n\n")
    chunks: list[str] = []
    buf: list[str] = []
    cur = 0
    for block in blocks:
        extra = len(block) + (2 if buf else 0)
        if cur + extra > max_chars and buf:
            chunks.append("\n\n".join(buf))
            buf = [block]
            cur = len(block)
        else:
            buf.append(block)
            cur += extra
    if buf:
        chunks.append("\n\n".join(buf))

    out: list[str] = []
    for c in chunks:
        if len(c) <= max_chars:
            out.append(c)
            continue
        start = 0
        while start < len(c):
            out.append(c[start : start + max_chars])
            start += max_chars
    return out


def openai_clean_mixed_transcript(*, transcript: str) -> str:
    """
    Clean a mixed-language transcript with OpenAI: fix garbled text, drop hallucinations, no translation.
    Long inputs are chunked; multiple segments are stitched with a final consistency pass.
    """

    key = _require_openai_key()
    base = transcript.strip()
    if not base:
        return ""

    settings = get_settings()
    model = settings.openai_model

    chunks = _chunk_transcript_for_gpt(base, _TRANSCRIPT_CLEAN_CHUNK_CHARS)
    n = len(chunks)
    partials: list[str] = []

    for i, chunk in enumerate(chunks):
        logger.info(
            "OpenAI transcript clean chunk",
            extra={"chunk_index": i, "total_chunks": n, "chunk_chars": len(chunk)},
        )
        user_msg = (
            f"This is segment {i + 1} of {n} of the same lecture. Output only the cleaned transcript "
            f"for this segment. Do not add a title or commentary.\n\n---\n{chunk}\n---"
        )
        messages = [
            {"role": "system", "content": _SYSTEM_TRANSCRIPT_CLEANER},
            {"role": "user", "content": user_msg},
        ]
        out = _openai_chat(
            api_key=key,
            model=model,
            messages=messages,
            max_tokens=8192,
            temperature=0.15,
        )
        if not (out and out.strip()):
            raise RuntimeError("OpenAI returned an empty transcript segment while cleaning")
        partials.append(heuristic_clean(out))

    if n == 1:
        return partials[0].strip()

    joined = "\n\n".join(partials)
    stitch_user = (
        "The following text is the same lecture transcript in order, already cleaned segment-by-segment. "
        "Merge into one continuous transcript: fix awkward breaks at segment boundaries, remove duplicated "
        "lines at joins, keep one consistent formatting. Do not translate; keep English and Roman Urdu/Hindi.\n\n"
        f"---\n{joined}\n---"
    )
    messages = [
        {"role": "system", "content": _SYSTEM_TRANSCRIPT_CLEANER},
        {"role": "user", "content": stitch_user},
    ]
    final = _openai_chat(
        api_key=key,
        model=model,
        messages=messages,
        max_tokens=8192,
        temperature=0.12,
    )
    if not (final and final.strip()):
        raise RuntimeError("OpenAI returned empty text while merging cleaned transcript segments")
    return heuristic_clean(final).strip()


def gpt_summarize_mixed_transcript(*, transcript: str, summary_type: str) -> str:
    """
    Summarize a mixed-language lecture transcript using OpenAI GPT (see settings.openai_model).
    Long transcripts are chunked; partial summaries are merged in a second pass.
    """

    key = _require_openai_key()
    settings = get_settings()

    base = transcript.strip()
    if not base:
        return ""

    model = settings.openai_model
    is_detailed = summary_type == "detailed"
    per_chunk_tokens = 1500 if is_detailed else 800
    merge_tokens = 1500 if is_detailed else 800
    length_hint = (
        "Provide thorough coverage: proportional depth, multiple paragraphs if the segment is rich, "
        "and end this segment's contribution toward the final Key Takeaways bullets where appropriate."
        if is_detailed
        else "Keep this segment concise (roughly toward 2-3 paragraphs total for short lectures); "
        "still note main ideas so merged summary can include Key Takeaways bullets."
    )

    chunks = _chunk_transcript_for_gpt(base, _SUMMARY_INPUT_CHUNK_CHARS)
    n = len(chunks)
    partials: list[str] = []

    for i, chunk in enumerate(chunks):
        logger.info(
            "GPT summarization chunk",
            extra={"chunk_index": i, "total_chunks": n, "chunk_chars": len(chunk)},
        )
        user_msg = (
            f"This is segment {i + 1} of {n} of the same lecture transcript. {length_hint}\n\n"
            f"---\n{chunk}\n---"
        )
        messages = [
            {"role": "system", "content": _SYSTEM_ACADEMIC_SUMMARIZER},
            {"role": "user", "content": user_msg},
        ]
        out = _openai_chat(
            api_key=key,
            model=model,
            messages=messages,
            max_tokens=per_chunk_tokens,
            temperature=0.25,
        )
        if out:
            partials.append(heuristic_clean(out))

    if not partials:
        return ""

    if n == 1:
        return "\n\n".join(partials).strip()

    combined = "\n\n".join(partials)
    merge_user = (
        "Below are partial summaries of consecutive segments of one lecture. Merge them into a single "
        "coherent academic summary in English. Remove redundancy; do not add facts not supported by "
        f"these notes. {length_hint}\n\n---\n{combined}\n---"
    )
    messages = [
        {"role": "system", "content": _SYSTEM_ACADEMIC_SUMMARIZER},
        {"role": "user", "content": merge_user},
    ]
    final = _openai_chat(
        api_key=key,
        model=model,
        messages=messages,
        max_tokens=merge_tokens,
        temperature=0.2,
    )
    return heuristic_clean(final).strip()


def _openai_chat(
    *,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    response_format: dict[str, str] | None = None,
) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    create_kwargs: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if response_format is not None:
        create_kwargs["response_format"] = response_format
    response = client.chat.completions.create(**create_kwargs)
    choice = response.choices[0]
    content = choice.message.content
    return (content or "").strip()


def openai_chat_completion(
    *,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float = 0.35,
    model: str | None = None,
    response_format: dict[str, str] | None = None,
) -> str:
    """
    Single OpenAI chat completion using the project API key.

    For structured outputs, pass ``response_format={"type": "json_object"}`` and ask for JSON only
    in the system/user prompts (OpenAI JSON mode).
    """

    api_key = _require_openai_key()
    settings = get_settings()
    use_model = model or settings.openai_model
    return _openai_chat(
        api_key=api_key,
        model=use_model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        response_format=response_format,
    )


def _hf_chat(
    *,
    api_token: str,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
) -> str:
    from huggingface_hub import InferenceClient

    client = InferenceClient(token=api_token)
    output = client.chat_completion(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    if not output.choices:
        return ""
    msg = output.choices[0].message
    return (msg.content or "").strip()


def _chat_with_fallback(
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    temperature: float = 0.2,
) -> str | None:
    settings = get_settings()
    key = _secret_value(settings.openai_api_key)
    if key:
        try:
            text = _openai_chat(
                api_key=key,
                model=settings.openai_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if text:
                logger.debug("LLM refinement used OpenAI", extra={"model": settings.openai_model})
            return text or None
        except Exception:
            logger.exception("OpenAI chat completion failed; trying Hugging Face if configured")

    hf = _secret_value(settings.huggingface_api_token)
    if hf:
        try:
            text = _hf_chat(
                api_token=hf,
                model=settings.hf_refinement_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if text:
                logger.debug(
                    "LLM refinement used Hugging Face Inference",
                    extra={"model": settings.hf_refinement_model},
                )
            return text or None
        except Exception:
            logger.exception("Hugging Face chat completion failed")

    return None


def clean_text_for_summarization(text: str) -> str:
    """
    Light normalization before summarization. Stored transcript is already OpenAI-cleaned (mixed language).
    """

    return clean_mixed_language_transcript(text)


def polish_academic_summary(
    *, draft_summary: str, lecture_context: str, summary_type: str = "short"
) -> str:
    """
    Rewrite BART draft into clearer academic English when an LLM API is configured; otherwise return draft.
    """

    draft = heuristic_clean(draft_summary)
    if not draft:
        return ""

    ctx = heuristic_clean(lecture_context)[:_SUMMARY_CONTEXT_CHARS]
    user_msg = (
        "Draft summary:\n---\n"
        f"{draft}\n---\n\n"
        "Lecture context (excerpt; for accuracy only, do not paste verbatim):\n---\n"
        f"{ctx if ctx else '(not available)'}\n---\n\n"
        "Produce the polished summary as instructed."
    )
    messages = [
        {"role": "system", "content": _SYSTEM_SUMMARY},
        {"role": "user", "content": user_msg},
    ]
    polish_max = 1500 if summary_type == "detailed" else 800
    polished = _chat_with_fallback(messages, max_tokens=polish_max, temperature=0.25)
    if polished:
        cleaned = heuristic_clean(polished).strip()
        if cleaned:
            return cleaned
    return draft
