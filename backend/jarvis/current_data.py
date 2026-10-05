"""Current-data routing uses the owner's current public question, never recalled context."""

import re


def model_status_request(text):
    return bool(
        re.search(r"\b(?:model|provider)\b", text, re.I)
        and re.search(r"\b(?:you|your|jarvis)\b", text, re.I)
        and re.search(r"\b(?:using|selected|running|use|active)\b", text, re.I)
    )


def current_request(text):
    if model_status_request(text):
        return None
    # A temporal word in a personal conversation is not a request for public facts.
    if re.search(
        r"\b(?:i feel|i'm (?:feeling|overwhelmed|tired|sad|happy)|i am (?:feeling|overwhelmed|tired)|tell (?:me|us) a story|recite|motivate me)\b",
        text,
        re.I,
    ):
        return None
    # Private records and action requests retain their own authenticated tools.
    if re.search(
        r"\b(my|our|email|gmail|inbox|calendar|reminder|password|secret|token|api key|address|phone|account|create|save|schedule|book|send|delete|cancel|remember)\b|@|\b\d{6,}\b",
        text,
        re.I,
    ):
        return None
    if re.search(
        r"\b(training|trained|cutoff|knowledge cutoff|your model|your data)\b",
        text,
        re.I,
    ):
        return None
    if re.search(r"\b(news|headlines|current affairs|what.s happening)\b", text, re.I):
        return "news"
    if (
        re.search(
            r"\b(latest|currently|current|recent|today|right now|this week|live data|search (?:the )?web|google search)\b",
            text,
            re.I,
        )
        and re.search(
            r"\b(?:what|who|which|when|where|how|tell|give|report|summarize|check|search|research|look up|find)\b",
            text,
            re.I,
        )
        or re.search(
            r"\bwho is\b.*\b(president|prime minister|chief minister|ceo|governor)\b",
            text,
            re.I,
        )
    ):
        return "web"
    return None


def knowledge_answer(text, settings):
    if model_status_request(text):
        location = (
            "locally through Ollama"
            if settings.provider == "ollama"
            else "through your configured compatible API"
        )
        return f"I'm using {settings.model}, {location}."
    if not (
        re.search(
            r"\b(training|trained|cutoff|knowledge|data|up.?to.?date)\b", text, re.I
        )
        and re.search(r"\b(your|you|up.?to.?date|live|2024|cutoff)\b", text, re.I)
    ):
        return None
    return (
        "My model's training and live information are separate. I don't retrain myself from our chats, "
        "and I shouldn't guess the selected model's training cutoff. I save our conversations locally and recall relevant context. "
        + (
            "For current news I retrieve dated source headlines. "
            if settings.news_enabled
            else "News networking is disabled, so saved headlines may be outdated. "
        )
        + (
            "Google cited search is enabled for broader current public questions. "
            if settings.google_search_enabled
            else "For broader live information, enable Google cited search in Settings using your own Gemini key. "
        )
        + "Current answers need source links and retrieval times; when retrieval fails, I can't verify today's facts."
    )
