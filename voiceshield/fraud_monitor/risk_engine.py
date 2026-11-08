"""VoiceShield: conservative rule-based telephone fraud *indicators*.

No training, identity proof, fraud verdict, persistent audio, or transcripts.
Return a deliberately small set of explainable indicators for the website API.
"""
from collections import deque
import re
import time

# Patterns are deliberately specific. Expand only with consented test cases.
PATTERNS = {
    'credential_request': [
        r'\b(?:tell|give|send|share|read|provide|text|repeat)\s+(?:me|us|the\s+(?:agent|representative))?\s*(?:your|the|that|a)?\s*(?:one[- ]time\s+)?(?:password|passcode|pin|otp|verification\s+code|security\s+code|login\s+code)\b',
        r'\b(?:what\s+is|what\'s)\s+(?:your|the|that)\s+(?:password|pin|verification\s+code|one[- ]time\s+code|security\s+code)\b',
        r'\b(?:code|number)\s+(?:you\s+)?(?:just\s+)?(?:received|got)\s+(?:by|via|in)\s+(?:a\s+)?(?:text|sms|message)\b',
        r'\b(?:read|tell|give|send)\s+(?:me|us)\s+(?:the\s+)?(?:six|6|four|4)[ -]digit\s+code\b',
    ],
    'urgent_transfer': [
        r'\b(?:transfer|wire|send|move)\s+(?:your|the|some|all|any)?\s*(?:money|funds|payment|balance|cash)\s+(?:right\s+now|immediately|today|urgently|asap)\b',
        r'\b(?:immediately|right\s+now|urgently|asap)\s+(?:transfer|wire|send|move)\s+(?:money|funds|payment|cash)\b',
        r'\b(?:transfer|wire|move)\s+(?:the\s+|your\s+)?(?:balance|funds|money)\s+to\s+(?:a\s+)?(?:safe|secure|temporary|new|holding)\s+account\b',
        r'\b(?:protect|secure|save)\s+(?:your\s+)?(?:money|funds|savings)\s+by\s+(?:transferring|moving|wiring)\b',
    ],
    'secrecy_pressure': [
        r'\b(?:do\s+not|don\'t|never)\s+(?:tell|inform|contact|call)\s+(?:anyone|the\s+bank|your\s+family|the\s+police|anybody)\b',
        r'\bkeep\s+(?:this|it|our\s+conversation)\s+(?:a\s+)?secret\b',
        r'\b(?:do\s+not|don\'t)\s+(?:hang\s+up|end\s+(?:the|this)\s+call)\b',
    ],
    'remote_access': [
        r'\b(?:install|download|open)\s+(?:(?:the|a)\s+)?(?:anydesk|teamviewer|remote\s+desktop|screen\s+sharing\s+app)\b',
        r'\b(?:give|grant|allow)\s+(?:me|us)?\s*(?:remote\s+)?access\s+to\s+(?:your|the)\s+(?:computer|phone|device|screen)\b',
        r'\b(?:share\s+your\s+screen|let\s+me\s+control\s+your\s+computer)\b',
    ],
    'claimed_bank_identity': [
        r'\b(?:i\s+am|i\'m|calling\s+from|this\s+is|we\s+are|we\'re)\s+(?:a\s+|the\s+)?(?:bank\s+)?(?:fraud\s+department|bank\s+representative|bank\s+security|your\s+bank)\b',
    ],
}

# V3.2 expanded *spoken-request* library. Keep request+target together whenever
# possible: mentioning a scam topic is not equivalent to soliciting a victim.
PATTERNS.update({
    'card_data_request': [
        r'\b(?:tell|give|read|send|share|provide)\s+(?:(?:me|us)\s+)?(?:your\s+)?(?:full\s+)?(?:credit|debit)\s+card\s+(?:number|details|information)\b',
        r'\b(?:tell|give|read|send|share|provide)\s+(?:me|us\s+)?(?:your\s+)?(?:cvv|cvc|card\s+security\s+code|card\s+expiration\s+date)\b',
    ],
    'identity_data_request': [
        r'\b(?:tell|give|send|share|provide|read)\s+(?:me|us\s+)?(?:your\s+)?(?:social\s+security\s+number|social\s+security|ssn|date\s+of\s+birth|routing\s+and\s+account\s+numbers)\b',
        r'\b(?:send|upload|share|text)\s+(?:me|us\s+)?(?:a\s+)?(?:photo|picture|copy)\s+of\s+(?:your\s+)?(?:id|driver.s\s+license|passport)\b',
    ],
    'mfa_approval': [
        r'\b(?:approve|accept|confirm|tap\s+yes|click\s+approve)\s+(?:the\s+|that\s+)?(?:login\s+|sign\s*in\s+|authentication\s+|verification\s+)?(?:request|notification|push|prompt)\b',
        r'\b(?:approve|accept)\s+(?:the\s+|that\s+)?(?:two.factor|multi.factor|mfa|2fa)\s+(?:request|notification|push)\b',
    ],
    'security_disablement': [
        r'\b(?:turn\s+off|disable|remove|deactivate)\s+(?:your\s+|the\s+)?(?:two.factor\s+authentication|multi.factor\s+authentication|2fa|mfa|fraud\s+alerts|security\s+alerts)\b',
        r'\b(?:change|reset)\s+(?:your\s+|the\s+)?(?:bank\s+|account\s+)?password\s+to\s+\S+',
    ],
    'phishing_link': [
        r'\b(?:click|open|visit|follow|go\s+to)\s+(?:the\s+|this\s+|that\s+)?(?:link|website|webpage|site|url)\s+(?:i\s+|we\s+)?(?:just\s+)?(?:sent|texted|emailed|provided)\b',
        r'\b(?:enter|type|submit)\s+(?:your\s+)?(?:password|login|bank\s+credentials|verification\s+code)\s+(?:on|into|at)\s+(?:the\s+|this\s+)?(?:link|website|page|form)\b',
        r'\b(?:scan|open)\s+(?:the\s+|this\s+)?qr\s+code\s+to\s+(?:verify|unlock|secure|recover|restore|pay)\b',
    ],
    'payment_app_request': [
        r'\b(?:send|pay|transfer|move)\s+(?:me\s+|us\s+)?(?:the\s+|your\s+|some\s+)?(?:money|funds|payment|deposit|fee|balance|cash|\$\s*\d+)\s+(?:through|using|via|on|with)\s+(?:zelle|venmo|cash\s*app|paypal|apple\s+cash)\b',
        r'\b(?:zelle|venmo|cash\s*app|paypal|apple\s+cash)\s+(?:me|us)\s+(?:the\s+|your\s+)?(?:money|deposit|fee|payment|\$\s*\d+)\b',
    ],
    'crypto_payment_request': [
        r'\b(?:send|transfer|deposit|pay|buy)\s+(?:some\s+|your\s+|the\s+)?(?:bitcoin|btc|ethereum|eth|crypto|cryptocurrency|usdt)\s+(?:to|into|at|for)\s+(?:my|our|this|the|a)\s+(?:wallet|address|account|payment)\b',
        r'\b(?:pay|send|deposit|transfer)\s+(?:the\s+)?(?:fee|money|funds|payment|ransom)\s+(?:in|with|as)\s+(?:bitcoin|crypto|cryptocurrency|usdt)\b',
        r'\b(?:use|go\s+to)\s+(?:a\s+|the\s+)?(?:bitcoin|crypto)\s+atm\s+to\s+(?:send|pay|deposit|transfer)\b',
    ],
    'gift_card_payment': [
        r'\b(?:buy|purchase|get)\s+(?:me\s+|us\s+)?(?:a\s+|some\s+|the\s+)?(?:apple|itunes|google\s+play|steam|amazon|visa|prepaid)?\s*gift\s*cards?\s+(?:to\s+pay|for\s+(?:the\s+)?(?:payment|fee|tax|fine|bill|verification))\b',
        r'\b(?:read|send|tell|give|text|share)\s+(?:me\s+|us\s+)?(?:the\s+)?(?:numbers?|codes?|pin)\s+(?:on|from|off)\s+(?:the\s+|your\s+)?(?:gift\s*cards?|back\s+of\s+the\s+gift\s*cards?)\b',
        r'\b(?:scratch\s+off|peel\s+off)\s+(?:the\s+)?(?:back|silver\s+strip)\s+(?:of\s+|on\s+)?(?:the\s+|your\s+)?gift\s*cards?\b',
    ],
    'wire_redirection': [
        r'\b(?:change|update|replace|switch|redirect)\s+(?:the\s+|your\s+)?(?:payment|invoice|wire|direct\s+deposit|payroll)\s+(?:bank\s+|account\s+|routing\s+)?(?:details|instructions|number|information|destination)\b',
        r'\b(?:wire|send|transfer|pay)\s+(?:the\s+|your\s+)?(?:invoice|rent|payroll|deposit|closing\s+funds)\s+to\s+(?:this|the|a|my|our)\s+(?:new\s+|different\s+)?(?:bank\s+)?account\b',
    ],
    'cash_courier': [
        r'\b(?:withdraw|take\s+out)\s+(?:your\s+|the\s+)?(?:cash|money|savings|funds)\s+(?:and\s+)?(?:give|hand|deliver|bring)\s+(?:it|the\s+cash|the\s+money)\s+to\s+(?:a|our|the)\s+(?:courier|agent|driver|officer|representative)\b',
        r'\b(?:a|our|the)\s+(?:courier|agent|driver)\s+will\s+(?:pick\s+up|collect)\s+(?:the\s+|your\s+)?(?:cash|money|gold|savings)\b',
    ],
    'advance_fee': [
        r'\b(?:pay|send|transfer|deposit)\s+(?:the\s+|a\s+)?(?:upfront|advance|processing|release|activation|verification|clearance|recovery)\s+fee\s+(?:to|before|first|so)\b',
        r'\b(?:you\s+)?(?:must|need\s+to|have\s+to)\s+pay\s+(?:a\s+|the\s+)?(?:tax|fee|charge|deposit)\s+(?:before|to)\s+(?:receive|release|unlock|collect|withdraw)\s+(?:your\s+|the\s+)?(?:prize|winnings|refund|loan|funds|inheritance|money|payout)\b',
    ],
    'refund_overpayment': [
        r'\b(?:refund|reimbursement|payment)\s+(?:was\s+|has\s+been\s+)?(?:too\s+large|overpaid|sent\s+twice)\s+(?:so\s+)?(?:send|return|transfer|wire|pay)\b',
        r'\b(?:send|return|transfer|wire|pay)\s+(?:me\s+|us\s+)?(?:back\s+)?(?:the\s+)?(?:extra|difference|overpayment|excess)\s+(?:money|amount|refund|funds)\b',
    ],
    'account_takeover': [
        r'\b(?:log\s+in|sign\s+in|access)\s+(?:to\s+)?(?:your\s+)?(?:bank|banking|email|payroll)\s+account\s+(?:for\s+me|for\s+us|and\s+share\s+your\s+screen)\b',
        r'\b(?:add|enroll|register)\s+(?:my|our|this)\s+(?:phone|device|number|email)\s+(?:as\s+)?(?:your\s+)?(?:trusted|recovery|authentication)\s+(?:device|number|email|method)\b',
    ],
    'extortion_payment': [
        r'\b(?:if\s+you\s+don.t|unless\s+you)\s+(?:pay|send|transfer|wire)\s+(?:me\s+|us\s+)?(?:the\s+)?(?:money|bitcoin|crypto|ransom|\$\s*\d+)\b',
        r'\b(?:pay|send|transfer|wire)\s+(?:me\s+|us\s+)?(?:money|bitcoin|crypto|\$\s*\d+)\s+or\s+(?:i|we)\s+will\s+(?:release|expose|publish|leak|share|arrest)\b',
    ],
    'money_mule': [
        r'\b(?:receive|accept|deposit)\s+(?:the\s+|a\s+)?(?:money|funds|payment|check)\s+(?:into\s+)?(?:your\s+)?account\s+and\s+(?:then\s+)?(?:send|forward|transfer|wire)\s+(?:it|the\s+money|the\s+funds)\b',
        r'\b(?:keep|take)\s+(?:a\s+)?(?:commission|cut|percentage)\s+and\s+(?:send|transfer|wire)\s+(?:the\s+)?(?:rest|remainder|balance)\b',
    ],
    'government_impersonation': [
        r'\b(?:i\s+am|i.m|this\s+is|calling\s+from|we.re\s+from)\s+(?:the\s+)?(?:irs|social\s+security\s+administration|fbi|police|sheriff.s\s+office|federal\s+agent|court)\b',
        r'\b(?:warrant\s+for\s+your\s+arrest|arrest\s+warrant)\s+(?:unless|if\s+you\s+do\s+not)\s+(?:you\s+)?(?:pay|send|transfer)\b',
    ],
    'urgency_pressure': [
        r'\b(?:do\s+it|pay\s+it|send\s+it|transfer\s+it)\s+(?:right\s+now|immediately|before\s+it.s\s+too\s+late)\b',
        r'\b(?:you\s+have|you.ve\s+got)\s+(?:only\s+)?(?:five|ten|fifteen|thirty|5|10|15|30)\s+minutes?\s+to\s+(?:pay|transfer|send|verify|comply)\b',
    ],
    'family_emergency': [
        r'\b(?:your|my)\s+(?:grandson|granddaughter|son|daughter|mom|dad|mother|father|grandchild)\s+(?:is\s+)?(?:in\s+jail|in\s+the\s+hospital|been\s+arrested)\s+(?:and\s+)?(?:needs?|requires?)\s+(?:money|bail|payment)\b',
        r'\b(?:i.m|i\s+am)\s+(?:in\s+trouble|in\s+jail|stranded)\s+and\s+(?:i\s+)?(?:need|have\s+to\s+get)\s+(?:money|cash|bail)\b',
    ],
    'investment_guarantee': [
        r'\b(?:guaranteed|risk.free|no.risk)\s+(?:returns?|profits?|investment|income)\b',
        r'\b(?:double|triple)\s+(?:your\s+)?(?:money|investment|crypto)\s+(?:in|within)\s+(?:\d+|a\s+few)\s+(?:days?|weeks?|hours?)\b',
    ],
    'job_fee': [
        r'\b(?:pay|deposit|send)\s+(?:the\s+|a\s+)?(?:training|equipment|onboarding|registration)\s+fee\s+(?:before\s+you\s+|before\s+|to\s+)(?:start|begin|receive|unlock)\s+(?:the\s+|your\s+)?(?:job|work|tasks?|earnings?)\b',
        r'\b(?:deposit|send|pay)\s+(?:your\s+|some\s+)?(?:own\s+)?(?:money|crypto|funds)\s+to\s+(?:unlock|complete|start)\s+(?:the\s+|your\s+)?(?:tasks?|job|earnings?)\b',
    ],
    'recovery_scam': [
        r'\b(?:recover|retrieve|release|return)\s+(?:your\s+|the\s+)?(?:lost|stolen|scammed)?\s*(?:money|crypto|funds)\s+(?:if|once|after)\s+you\s+(?:pay|send|transfer)\b',
    ],
    'prize_fee': [
        r'\b(?:you.ve|you\s+have)\s+won\s+(?:a\s+|the\s+)?(?:prize|lottery|sweepstakes|jackpot)\s+(?:but\s+)?(?:you\s+)?(?:must|need\s+to|have\s+to)\s+pay\b',
    ],
    'romance_pressure': [
        r'\b(?:i\s+love\s+you|trust\s+me)\s+(?:so\s+)?(?:please\s+)?(?:send|wire|transfer)\s+(?:me\s+)?(?:money|cash|funds|crypto)\b',
    ],
    'charity_pressure': [
        r'\b(?:donate|send)\s+(?:money|funds|cash|crypto)\s+(?:to\s+)?(?:my|our|this)\s+(?:personal|private)\s+(?:account|wallet)\s+(?:for|to\s+support)\s+(?:the\s+)?(?:disaster|relief|charity|victims?)\b',
    ],
})

# A mere identity claim or threat of urgency is concerning but insufficient
# evidence for HIGH without a directly sensitive request. Avoid matching the
# benign topic words "bank", "bitcoin", "gift card" by themselves.
HIGH_INDICATORS = frozenset({
    'credential_request', 'urgent_transfer', 'remote_access', 'card_data_request',
    'identity_data_request', 'mfa_approval', 'security_disablement', 'phishing_link',
    'payment_app_request', 'crypto_payment_request', 'gift_card_payment',
    'wire_redirection', 'cash_courier', 'advance_fee', 'refund_overpayment',
    'account_takeover', 'extortion_payment', 'money_mule', 'job_fee',
    'recovery_scam', 'prize_fee', 'romance_pressure', 'charity_pressure',
})

COMPILED = {name: tuple(re.compile(p, re.I) for p in expressions) for name, expressions in PATTERNS.items()}

# Do not globally ignore sentences that mention "never": a caller can warn about
# scams AND ask for a code in the same sentence. Consider local context instead.
SAFETY_ADVICE = re.compile(
    r'\b(?:never|do\s+not|don\'t|shouldn\'t|mustn\'t|avoid)\s+'
    r'(?:(?:ever|anyone\s+to|yourself\s+to)\s+)?'
    r'(?:give|send|share|read|provide|tell|transfer|wire|install|download|grant|allow)\b', re.I)
QUOTED_EXAMPLE = re.compile(r'\b(?:scammers?\s+(?:may|might|will|often)\s+(?:say|ask)|'
                            r'for\s+example|if\s+(?:someone|anyone)\s+asks)\b', re.I)


def analyze_text(text):
    """Return explainable matched indicators. Empty list never means safe."""
    if not isinstance(text, str):
        raise TypeError('transcript must be text')
    indicators = set()
    for sentence in re.split(r'(?<=[.!?])\s+|\n+', text[:4000]):
        for name, patterns in COMPILED.items():
            for pattern in patterns:
                for match in pattern.finditer(sentence):
                    before = sentence[max(0, match.start() - 100):match.start()]
                    # A clearly hypothetical example or an anti-scam warning isn't
                    # evidence of an actual request. Secrecy phrasing is ambiguous
                    # by itself, so keep it but do not elevate it to HIGH alone.
                    if QUOTED_EXAMPLE.search(before):
                        continue
                    if name != 'secrecy_pressure' and (SAFETY_ADVICE.search(before[-65:]) or re.search(r'\b(?:never|do\s+not|don\'t|shouldn\'t|mustn\'t)\s*$', before, re.I)):
                        continue
                    indicators.add(name)
    return sorted(indicators)


class CallRisk:
    """Keep only recent indicator labels, not raw speech; bounded and call-resettable."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.events = deque(maxlen=24)
        self.claimed_identity = False

    def reset(self):
        self.events.clear()
        self.claimed_identity = False

    def add(self, text):
        now = self.clock()
        matched = analyze_text(text)
        # Repeated overlap windows should not produce dozens of duplicate events.
        if matched:
            evidence = frozenset(matched)
            if self.events and self.events[-1][1] == evidence:
                self.events[-1] = (now, evidence)  # refresh active repeated evidence
            else:
                self.events.append((now, evidence))
        self.events = deque(((t, e) for t, e in self.events if 0 <= now - t <= 45), maxlen=24)
        # The latest ASR window drives the current speech risk. Historical flags
        # remain separate: harmless speech does not inherit an earlier HIGH.
        combined = set().union(*(e for _, e in self.events)) if self.events else set()
        self.claimed_identity = 'claimed_bank_identity' in combined
        high_names = HIGH_INDICATORS
        current_high = any(name in matched for name in high_names)
        call_high = any(name in combined for name in high_names)
        current_level = 'high' if current_high else 'elevated' if matched else 'unresolved'
        call_level = 'high' if call_high else 'elevated' if combined else 'unresolved'
        return {
            'risk_level': current_level,
            'indicators': matched,
            'call_risk_level': call_level,
            'call_indicators': sorted(combined),
            'identity_status': 'unverified' if self.claimed_identity else 'not_checked',
            'reason': ('Sensitive request detected in the latest audio; verify via a known number.' if current_high
                       else 'Potential social-engineering language in the latest audio.' if matched
                       else 'No scam phrase detected in the latest audio. Prior warnings may still exist.' if combined
                       else 'No matched phrase in analyzed audio; fraud is not ruled out.'),
        }
