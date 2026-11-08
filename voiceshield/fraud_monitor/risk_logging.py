"""Human-readable ASR fraud-indicator log formatting (no transcript storage)."""


def format_risk_log(result):
    """Show current speech and retained call history as distinct indicators."""
    current = str(result.get('risk_level', 'unresolved')).upper()
    history = str(result.get('call_risk_level', current)).upper()
    current_flags = ','.join(result.get('indicators') or []) or 'none'
    history_flags = ','.join(result.get('call_indicators') or []) or 'none'
    return (f'[SCAM] current={current} call={history} '
            f'current_flags=[{current_flags}] call_flags=[{history_flags}]')
