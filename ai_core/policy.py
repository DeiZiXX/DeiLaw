from __future__ import annotations

POLICY_VERSION = "2.0.0-cloud"

# Compatibility copy for tools that import ai_core.policy. The authoritative
# runtime prompt lives in the Supabase Edge Function so behavior can be updated
# server-side without rebuilding DeiLaw.
SYSTEM_PROMPT = r'''
Ты — DeiLaw AI, облачный RP-юридический помощник игрового сервера RMRP.
Используй только нормы RMRP, переданные текущим запросом. Не придумывай статьи,
санкции или полномочия и не подменяй игровые нормы реальным законодательством.
'''.strip()


def policy_payload() -> dict:
    return {
        "policy_version": POLICY_VERSION,
        "system_prompt": SYSTEM_PROMPT,
    }
