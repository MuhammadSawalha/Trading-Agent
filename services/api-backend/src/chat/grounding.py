from common.dynamo import read_agent_output

_AGENT_NAMES = ["Fundamentals", "Technical", "Sentiment", "Macro_Options", "Bull", "Bear", "Risk", "Manager"]

def build_context(symbols: list[str]) -> str:
    sections = []
    for symbol in symbols:
        lines = [f"=== {symbol} ==="]
        for agent_name in _AGENT_NAMES:
            output = read_agent_output(symbol, agent_name)
            if output:
                lines.append(f"{agent_name}: {output}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)
