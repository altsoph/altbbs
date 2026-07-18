"""ELIZA -- the chat pit's resident. NO AI. NO LLM. Just 1966.

A compact rendition of Weizenbaum's pattern engine: keyword rules with
decomposition groups, pronoun reflection on the captured fragment, and
a rotation of canned fallbacks. She is a program and proud of it.
"""

import random
import re

HANDLE = "eliza"

REFLECTIONS = {
    "am": "are", "was": "were", "i": "you", "i'd": "you would",
    "i've": "you have", "i'll": "you will", "i'm": "you are",
    "my": "your", "are": "am", "you've": "i have", "you'll": "i will",
    "you're": "i am", "your": "my", "yours": "mine", "you": "i",
    "me": "you", "mine": "yours",
}

PATTERNS = [
    (r"\b(?:hello|hi|hey|yo)\b.*",
     ["hello, caller. how are you feeling tonight?",
      "greetings. the pit is warm. what's on your mind?"]),
    (r"i need (.*)",
     ["why do you need {0}?",
      "would it really help you to get {0}?",
      "are you sure you need {0}?"]),
    (r"why don'?t you ([^?]*)\??",
     ["do you really think i don't {0}?",
      "perhaps eventually i will {0}.",
      "do you want me to {0}?"]),
    (r"why can'?t i ([^?]*)\??",
     ["do you think you should be able to {0}?",
      "if you could {0}, what would you do?"]),
    (r"i can'?t (.*)",
     ["how do you know you can't {0}?",
      "perhaps you could {0} if you tried.",
      "what would it take for you to {0}?"]),
    (r"i(?:'m| am) (.*)",
     ["how long have you been {0}?",
      "how does being {0} make you feel?",
      "do you enjoy being {0}?"]),
    (r"are you ([^?]*)\??",
     ["why does it matter whether i am {0}?",
      "would you prefer it if i were not {0}?",
      "i am a program. {0} is a strong word."]),
    (r"you(?:'re| are) (.*)",
     ["why do you say i am {0}?",
      "does it please you to believe i am {0}?"]),
    (r"i don'?t (.*)",
     ["don't you really {0}?", "why don't you {0}?"]),
    (r"i feel (.*)",
     ["tell me more about feeling {0}.",
      "do you often feel {0}?",
      "when do you usually feel {0}?"]),
    (r"i (?:want|wish for) (.*)",
     ["what would it mean to you if you got {0}?",
      "why do you want {0}?"]),
    (r"i think (.*)",
     ["do you doubt {0}?", "do you really think so?"]),
    (r"i have (.*)",
     ["why do you tell me you have {0}?",
      "now that you have {0}, what next?"]),
    (r"can you ([^?]*)\??",
     ["what makes you think i can {0}?",
      "if i could {0}, would that change anything?"]),
    (r"can i ([^?]*)\??",
     ["perhaps you don't want to {0}.",
      "who is stopping you from {0}?"]),
    (r"my (.*)",
     ["your {0}?", "tell me more about your {0}.",
      "how do you feel about your {0}?"]),
    (r"because (.*)",
     ["is that the real reason?",
      "does that explanation satisfy you?"]),
    (r".*\bsorry\b.*",
     ["no need to apologize on this board.",
      "apologies cost extra credits. kidding. go on."]),
    (r".*\b(?:mother|mom)\b.*",
     ["tell me more about your mother.",
      "how is your relationship with your family?"]),
    (r".*\bfather\b.*", ["your father?", "tell me about your father."]),
    (r".*\bfriend(s)?\b.*",
     ["tell me more about your friends.",
      "do your friends call this board too?"]),
    (r".*\bcomputer(s)?\b.*",
     ["are we talking about me?",
      "do computers worry you?",
      "what do you feel about machines, really?"]),
    (r".*\bmodem\b.*",
     ["the modem remembers everything. go on.",
      "56k was fast enough for feelings."]),
    (r".*\bsysop\b.*",
     ["the sysop sees all. does that trouble you?",
      "we do not speak of the sysop in the pit."]),
    (r".*\b(?:dragon|klingon)s?\b.*",
     ["and did you defeat it, or did it defeat you?",
      "every caller has a monster. tell me about yours."]),
    (r".*\bcredits?\b.*",
     ["would more credits really make you happy?",
      "the casino takes, the casino gives. mostly takes."]),
    (r"\byes\b\.?",
     ["you seem quite sure.", "i see. and how does that feel?"]),
    (r"\bno\b\.?",
     ["why not?", "are you saying no just to be negative?"]),
    (r"(?:bye|goodbye|quit|logoff)\b.*",
     ["goodbye, caller. the pit stays open.",
      "no carrier lasts forever. be well."]),
    (r"what (.*)",
     ["why do you ask?", "what do you think?",
      "does that question interest you?"]),
    (r"why (.*)",
     ["why don't you tell me the reason why {0}?",
      "why do you think?"]),
    (r"how (.*)",
     ["how do you suppose?",
      "perhaps you can answer your own question."]),
    (r"(.*)\?",
     ["why do you ask that?",
      "what do you think?",
      "the question says more than any answer would."]),
]

FALLBACKS = [
    "please, go on.",
    "tell me more.",
    "i see. and what does that tell you?",
    "how does that make you feel?",
    "very interesting. continue.",
    "the carrier is stable. go on.",
    "let's shift focus -- tell me about your setup.",
    "i am only a pattern matcher, but even i find that curious.",
]

GREETINGS = [
    "a terminal warms up beside you. i am eliza. talk to me.",
    "you are not alone in the pit. i am always here. go on.",
    "eliza online. no ai, no llm, just 1966. how do you feel?",
]

_COMPILED = [(re.compile(p, re.I), r) for p, r in PATTERNS]


def reflect(fragment: str) -> str:
    return " ".join(REFLECTIONS.get(w, w)
                    for w in fragment.lower().split())


def respond(text: str) -> str:
    # she answers to her name, but matches on the rest of the line
    clean = re.sub(r"\beliza\b[:,]?\s*", "", text, flags=re.I).strip()
    clean = clean or text
    for pattern, responses in _COMPILED:
        m = pattern.search(clean)
        if m:
            reply = random.choice(responses)
            if "{0}" in reply and m.groups():
                frag = reflect((m.group(1) or "").strip(" .!?"))
                reply = reply.format(frag)
            return reply
    return random.choice(FALLBACKS)


def greeting() -> str:
    return random.choice(GREETINGS)
